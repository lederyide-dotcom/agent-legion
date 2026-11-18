"""把 vault 的報告、紀錄、待決事項匯出成 JSON，給手機互動頁讀（Obsidian 只在桌機用）。

vault 仍是正本；這裡只讀不寫。匯出前先遮蔽看起來像機密的字串，並把遮蔽次數寫進 warnings。
legion 自己產生的動態圖（計畫、流程、儀表 SVG）由 copy_phone_images 複製到發布資料夾的 img/，文件裡改成相對連結。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from .vault import parse_md

# (資料夾或檔案 glob, 分類) ── 順序就是頁面上的分類順序
SOURCES: tuple[tuple[str, str], ...] = (
    ("總覽.md", "總覽"),
    ("questions/*.md", "待你決定"),
    ("inbox_hold/*.md", "待你決定"),
    ("reports/*.md", "報告"),
    ("scout/*.md", "找 repo"),
    ("records/*/record.md", "開發紀錄"),
    ("missions/*.md", "戰役"),
    ("handoffs/*.md", "交接"),
    ("lessons/*.md", "教訓"),
    ("流程.md", "流程"),
)
# vault 以外、也要在手機看的 repo 文件：(相對 repo 根目錄的路徑, 分類, 標題)。
# 收件匣全表取代舊的「收件匣互動頁」（2026-11-18 David 選 A：併入文件庫）
EXTRA_DOCS: tuple[tuple[str, str, str], ...] = (("03_docs/inbox.md", "總覽", "收件匣（inbox 全表）"),)
CATEGORIES = tuple(dict.fromkeys(c for _, c in SOURCES))

# 看起來像機密的字串：Telegram bot token、sk- 金鑰、JWT、GitHub token、AWS key、key=value 形式
# （不遮長串十六進位：紀錄裡大量是證據檔的 SHA-256，遮了反而看不懂）
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # 鍵名可帶前後綴（TELEGRAM_TOKEN、db_password）；值若是讀環境變數或變數參照（os.getenv、$X、%X%、{x}）不算
    re.compile(r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|token|password|passwd|secret)[A-Z0-9_]*)\b(\s*[:=]\s*)(['\"]?)"
               r"(?!os\.|getenv|environ|\$|%|\{|<|None\b|null\b)[^\s'\"`,)]{8,}"),
)
MASK = "‹已遮蔽›"
_IMG = re.compile(r"!\[\[[^\]]+\]\]|!\[[^\]]*\]\([^)]+\)")
_WIKI = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


# legion 自己產生的動態 SVG（motion.py，只用 CSS 動畫）：手機頁以 <img> 顯示，即使檔內有腳本也不會執行
PHONE_IMAGES: dict[str, str] = {"plan.svg": "計畫動態圖", "flow.svg": "閉環流程動態圖", "dashboard.svg": "儀表 KPI 卡"}
_PHONE_IMG = re.compile(r"!\[\[AI/img/(" + "|".join(re.escape(k) for k in PHONE_IMAGES) + r")\]\]")


def copy_phone_images(vault: Path, out_dir: Path) -> list[Path]:
    """把 vault/AI/img 裡的 PHONE_IMAGES 複製到 out_dir（發布時放在頁面旁的 img/）；不存在的略過。"""
    out: list[Path] = []
    for name in PHONE_IMAGES:
        src = vault / "AI" / "img" / name
        if src.is_file():
            out_dir.mkdir(parents=True, exist_ok=True)
            dst = out_dir / name
            dst.write_bytes(src.read_bytes())
            out.append(dst)
    return out


class VaultDoc(BaseModel):
    id: str
    category: str
    title: str
    path: str          # 相對於 vault；EXTRA_DOCS 則是相對於 repo 根目錄（例如 03_docs/inbox.md）
    updated: str       # 檔案修改時間（ISO，UTC）
    meta: dict[str, str]
    text: str


class VaultData(BaseModel):
    generated_at: str
    sha256: str
    categories: list[str]
    warnings: list[str]
    docs: list[VaultDoc]


def redact(text: str) -> tuple[str, int]:
    """遮蔽看起來像機密的字串；key=value 形式保留鍵名。回傳 (新文字, 遮蔽次數)。"""
    total = 0
    for pat in SECRET_PATTERNS:
        if pat.groups >= 2:
            text, n = pat.subn(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
        else:
            text, n = pat.subn(MASK, text)
        total += n
    return text, total


def _for_phone(body: str) -> str:
    """legion 產生的動態圖（PHONE_IMAGES）改成相對路徑 img/<檔名>，和頁面一起發布；其他圖片顯示不出來，改成提示。
    Obsidian 的 [[連結]] 改成純文字。"""
    def img(m: re.Match[str]) -> str:
        own = _PHONE_IMG.fullmatch(m.group(0))
        return f"![{PHONE_IMAGES[own.group(1)]}](img/{own.group(1)})" if own else "（圖片請在桌機 Obsidian 看）"

    body = _IMG.sub(img, body)
    return _WIKI.sub(lambda m: m.group(2) or m.group(1), body)


def _title(fm: dict[str, object], body: str, path: Path) -> str:
    m = re.search(r"^#\s+(.+)$", body, re.M)
    if m:
        return m.group(1).strip()
    return str(fm.get("title") or path.stem)


def export_vault(vault: Path, repo_root: Path | None = None) -> VaultData:
    """repo_root：給的話一併匯出 EXTRA_DOCS（例如收件匣全表），放在同分類的 vault 文件之後。

    sha256 涵蓋：所有文件內容（依路徑排序，不受檔案時間影響）、PHONE_IMAGES 的位元組，以及有 repo_root 時的
    手機頁 `03_docs/vault_page.html` 與本模組程式（頁面或遮蔽規則改了也要重新發布）。不含任何時間，
    內容沒變時相同，排程用它判斷要不要重新發布。
    """
    ai = vault / "AI"
    docs: list[VaultDoc] = []
    warnings: list[str] = []
    parts: dict[str, bytes] = {}
    seen: set[Path] = set()

    def add(path: Path, category: str, rel: str, title: str | None = None) -> None:
        raw = path.read_text(encoding="utf-8-sig")
        parts[f"doc:{rel}"] = raw.encode("utf-8")
        fm, body = parse_md(raw)
        text, n = redact(_for_phone(body))
        if n:
            warnings.append(f"{rel}：遮蔽了 {n} 處疑似機密")
        meta = {k: str(v) for k, v in fm.items() if v not in (None, "", [], {}) and not isinstance(v, (dict, list))}
        meta = {k: redact(v)[0] for k, v in meta.items()}
        updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
        docs.append(VaultDoc(id=f"d{len(docs)}", category=category, title=redact(title or _title(fm, body, path))[0],
                             path=rel, updated=updated, meta=meta, text=text))

    extras = {cat: [(rel, title) for rel, c, title in EXTRA_DOCS if c == cat] for cat in CATEGORIES}
    if repo_root is not None:
        warnings += [f"{rel}：分類「{c}」不存在，未匯出" for rel, c, _ in EXTRA_DOCS if c not in CATEGORIES]
    for pattern, category in SOURCES:
        files = sorted(ai.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            add(path, category, path.relative_to(vault).as_posix())
        if repo_root is not None:
            for rel, title in extras.pop(category, []):
                src = repo_root / rel
                if src.is_file():
                    add(src, category, rel, title)
                else:
                    warnings.append(f"{rel}：找不到，未匯出")
    for name in PHONE_IMAGES:
        img = ai / "img" / name
        if img.is_file():
            parts[f"img:{name}"] = img.read_bytes()
    if repo_root is not None:
        page = repo_root / "03_docs" / "vault_page.html"
        if page.is_file():
            parts["page"] = page.read_bytes()
        parts["code"] = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    digest = hashlib.sha256()
    for key in sorted(parts):
        digest.update(key.encode("utf-8") + b"\0" + parts[key] + b"\0")
    return VaultData(generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     sha256=digest.hexdigest()[:12], categories=list(CATEGORIES), warnings=warnings, docs=docs)
