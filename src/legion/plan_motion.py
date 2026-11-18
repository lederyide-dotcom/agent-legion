"""計畫動態圖：從 03_docs/inbox.md 產生 plan.svg，GitHub README、Obsidian AI/計畫.md、手機文件庫共用同一張。

和 motion.py 的流程圖一樣只用 SVG 內的 CSS 動畫（GitHub 與 Obsidian 都不執行腳本），跟隨亮暗配色與「減少動態」。
獨立成一個模組：指紋只算本檔，改計畫圖版面不會讓需要瀏覽器才能重產的流程圖跟著過期。
內容只取決於 inbox.md（不放產生時間），所以同一份 inbox 一定產生同一張圖，可直接比對位元組檢查是否過期。
"""
from __future__ import annotations

import hashlib
import re
from html import escape
from pathlib import Path

from pydantic import BaseModel

from . import diagrams
from .config import Settings
from .inbox import DEFAULT_INBOX, InboxData, load_inbox
from .motion import FONT, _write

PLAN_W = 460          # 窄版：手機 375px（左右留 16px）時縮放約 0.75，項目字約 12px
PLAN_LIST_MAX = 4     # 「等你決定」「進行中／待做」各列幾筆
PLAN_RECENT = 6       # 「最近完成」列幾筆
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MD_MARK = re.compile(r"\*\*|`|\[\[|\]\]")
_KINDS = {"待掌舵": "pending", "已決定": "decided", "可自主做": "auto"}


class PlanItem(BaseModel):
    id: str
    title: str
    lane: str          # wait（David 決定或處理）／todo（進行中、延後或 Claude 待做）／done
    blocked: bool = False
    date: str = ""     # 完成日期（狀態欄寫的 YYYY-MM-DD；沒寫就空字串）
    order: int = 0     # 在 inbox.md 裡的先後


class PlanData(BaseModel):
    source: str
    sha256: str
    items: list[PlanItem]

    def lane(self, name: str) -> list[PlanItem]:
        return [i for i in self.items if i.lane == name]

    def recent(self) -> list[PlanItem]:
        """最近完成：有日期的依日期新到舊、同日依 inbox 中較後者優先；沒寫日期的不列（不猜）。"""
        dated = [i for i in self.lane("done") if i.date]
        return sorted(dated, key=lambda i: (i.date, i.order), reverse=True)[:PLAN_RECENT]


def _lane(kind: str, status: str) -> str:
    """分道規則：
    - 待掌舵：一律 wait。
    - 已決定：✅ 或「結案」→ done；⏳／⛔ → wait（等 David 處理）；其他（例如「再試 1～2 個」「延後」）→ todo。
    - 可自主做：✅ → done；其他 → todo。
    """
    if kind == "pending":
        return "wait"
    if "✅" in status or (kind == "decided" and "結案" in status):
        return "done"
    if kind == "decided" and ("⏳" in status or "⛔" in status):
        return "wait"
    return "todo"


def plan_data(inbox: InboxData) -> PlanData:
    """把 parse_inbox() 的結果分成三道（見 _lane）。只讀「待掌舵」「已決定」「可自主做」三節（以標題關鍵字辨識），
    分流建議表不算計畫項目。缺節、欄位不夠或找不到狀態欄一律報錯，不默默分錯道。"""
    items: list[PlanItem] = []
    order = 0
    seen: set[str] = set()
    for sec in inbox.sections:
        kind = next((v for k, v in _KINDS.items() if k in sec.title), None)
        if kind is None:
            continue
        seen.add(kind)
        if len(sec.headers) < 2:
            raise ValueError(f"「{sec.title}」至少要有編號與標題兩欄")
        status_key = next((k for k in ("狀態", "執行結果") if k in sec.headers), None)
        if kind != "pending" and status_key is None:
            raise ValueError(f"「{sec.title}」找不到「狀態」或「執行結果」欄")
        id_key, title_key = sec.headers[0], sec.headers[1]
        for row in sec.rows:
            order += 1
            status = row[status_key] if status_key else ""
            lane = _lane(kind, status)
            m = _DATE.search(status) if lane == "done" else None
            items.append(PlanItem(id=row[id_key].strip(), title=_MD_MARK.sub("", row[title_key]).strip(), lane=lane,
                                  blocked="⛔" in status, date=m.group(0) if m else "", order=order))
    missing = [k for k, v in _KINDS.items() if v not in seen]
    if missing:
        raise ValueError(f"inbox 缺少計畫用的節（標題需含：{'、'.join(missing)}）")
    return PlanData(source=inbox.source, sha256=inbox.sha256, items=items)


def _char_w(ch: str) -> float:
    # 全形（CJK、全形標點）與 emoji 約 1em，其餘約 0.56em；組合字元與變體選擇符不佔寬
    o = ord(ch)
    if o in (0x200D, 0xFE0F) or 0x0300 <= o <= 0x036F:
        return 0.0
    return 1.0 if o > 0x2E7F or 0x2300 <= o <= 0x27BF else 0.56


def _fit(text: str, px: float, fs: float) -> str:
    """依字寬估計截斷，超過加「…」。SVG 當圖片顯示時不能靠 CSS 省略號。"""
    used = 0.0
    for i, ch in enumerate(text):
        used += fs * _char_w(ch)
        if used > px:
            cut = text[:max(i - 1, 0)]
            return cut.rstrip("‍️") + "…"
    return text


def plan_fingerprint() -> str:
    """計畫圖的程式指紋：只算本模組（版面、CSS）；與 inbox sha 一起嵌入 SVG。"""
    return hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def plan_svg(p: PlanData) -> str:
    """三格數字＋完成進度條＋等你決定／進行中清單＋最近完成時間軸。
    靜止時就完整；動態只有：等你決定的格子外框呼吸、清單前的提醒點閃、最近完成依序「滑入 ✅」、進度條流光。"""
    W, pad, fs = PLAN_W, 16, 16
    wait, todo, done = p.lane("wait"), p.lane("todo"), p.lane("done")
    total = len(p.items)
    parts: list[str] = []
    y = 38
    parts.append(f'<text x="{pad}" y="{y}" font-size="20" font-weight="700">agent-legion 計畫</text>'
                 f'<text class="muted" x="{W - pad}" y="{y}" font-size="12" text-anchor="end">'
                 f'inbox sha {escape(p.sha256)}</text>')
    y += 16
    tiles = [("等你決定", len(wait), "wait"), ("進行中／待做", len(todo), "run"), ("完成", len(done), "done")]
    tw = (W - 2 * pad - 2 * 10) / 3
    for i, (label, value, kind) in enumerate(tiles):
        x = pad + i * (tw + 10)
        pulse = " pulse" if kind == "wait" and value else ""
        parts.append(f'<g class="tile{pulse}"><rect class="tbg {kind}" x="{x:.1f}" y="{y}" width="{tw:.1f}" height="76" rx="12"/>'
                     f'<text class="num {kind}" x="{x + 12:.1f}" y="{y + 42}" font-size="32">{value}</text>'
                     f'<text class="lbl" x="{x + 12:.1f}" y="{y + 64}" font-size="14">{escape(label)}</text></g>')
    y += 76 + 26
    ratio = len(done) / total if total else 0.0
    bar_w = W - 2 * pad
    fill_w = max(bar_w * ratio, 4)
    parts.append(f'<text x="{pad}" y="{y}" font-size="14">完成 {len(done)}／{total}（{ratio * 100:.0f}%）</text>')
    y += 10
    parts.append(f'<rect class="track" x="{pad}" y="{y}" width="{bar_w}" height="10" rx="5"/>'
                 f'<rect class="bar" x="{pad}" y="{y}" width="{fill_w:.1f}" height="10" rx="5"/>'
                 f'<clipPath id="lp-barclip"><rect x="{pad}" y="{y}" width="{fill_w:.1f}" height="10" rx="5"/></clipPath>'
                 f'<g clip-path="url(#lp-barclip)"><rect class="sheen" x="{pad}" y="{y}" width="80" height="10" '
                 f'fill="url(#lp-sheen)"/></g>')
    y += 10 + 32

    def section(head: str, rows: list[PlanItem], kind: str, empty: str) -> None:
        nonlocal y
        more = f"（另 {len(rows) - PLAN_LIST_MAX} 項）" if len(rows) > PLAN_LIST_MAX else ""
        parts.append(f'<text x="{pad}" y="{y}" font-size="16" font-weight="700">{escape(head)}{escape(more)}</text>')
        y += 28
        if not rows:
            parts.append(f'<text class="muted" x="{pad + 16}" y="{y}" font-size="{fs}">{escape(empty)}</text>')
            y += 28
        for it in rows[:PLAN_LIST_MAX]:
            mark = "⛔ " if it.blocked else ""
            label = _fit(f"{mark}{it.id}　{it.title}", W - 2 * pad - 18, fs)
            parts.append(f'<circle class="dot {kind}" cx="{pad + 5}" cy="{y - 5}" r="4.5"/>'
                         f'<text x="{pad + 18}" y="{y}" font-size="{fs}">{escape(label)}</text>')
            y += 28
        y += 12

    section("等你決定／處理", wait, "wait", "沒有")
    section("進行中／待做", todo, "run", "沒有：可自主做的都完成了")

    recent = p.recent()
    parts.append(f'<text x="{pad}" y="{y}" font-size="16" font-weight="700">最近完成</text>')
    y += 4
    line_top = y
    rows_svg: list[str] = []
    for i, it in enumerate(recent):
        ry = y + 24 + i * 30
        label = _fit(f"{it.id}　{it.title}", W - 2 * pad - 116, fs)
        rows_svg.append(f'<g class="rc rc{i}"><circle class="ok" cx="{pad + 8}" cy="{ry - 5}" r="6"/>'
                        f'<path class="tick" d="M{pad + 5} {ry - 5}l2.2 2.2l3.8-4.2" fill="none" stroke-width="1.8"/>'
                        f'<text class="muted" x="{pad + 22}" y="{ry}" font-size="13">{escape(it.date)}</text>'
                        f'<text x="{pad + 106}" y="{ry}" font-size="{fs}">{escape(label)}</text></g>')
    if recent:
        y_end = y + 24 + (len(recent) - 1) * 30
        parts.append(f'<line class="flowline" x1="{pad + 8}" y1="{line_top}" x2="{pad + 8}" y2="{y_end - 5}"/>')
        parts.extend(rows_svg)
        y = y_end + 16
    else:
        parts.append(f'<text class="muted" x="{pad + 16}" y="{y + 24}" font-size="{fs}">還沒有寫日期的完成項目</text>')
        y += 40
    undated = sum(1 for i in done if not i.date)
    if undated:
        parts.append(f'<text class="muted" x="{pad}" y="{y + 6}" font-size="13">另有 {undated} 項完成但 inbox 未記日期，'
                     '不列入時間軸</text>')
        y += 22
    parts.append(f'<text class="muted" x="{pad}" y="{y + 8}" font-size="12">來源 {escape(p.source)}</text>')
    y += 24
    H = y + 6

    step = 0.7
    cycle = max(len(recent), 1) * step + 4.0
    # backwards：延遲期間就先套用第一個關鍵影格，避免第一輪「先完整、瞬間變暗、再滑入」的閃爍
    rc_rules = "".join(f".rc{i}{{animation:lp-in {cycle:.1f}s ease-out {i * step:.1f}s infinite backwards}}"
                       for i in range(len(recent)))
    in_end = round(1.0 / cycle * 100, 2)
    css = f"""
:root{{--bg:#ffffff;--line:#d9e0e7;--fg:#1b2430;--muted:#5d6b7a;--run:#2f5f8a;--wait:#a5620f;--done:#2e7d4f;
--run-s:#e3edf6;--wait-s:#fbefdc;--done-s:#e2f2e8;--track:#eef1f4;--bar:#2e7d4f}}
@media (prefers-color-scheme: dark){{:root{{--bg:#1a2129;--line:#2c3743;--fg:#e4e9ee;--muted:#93a1af;--run:#7fb0dc;
--wait:#e2a656;--done:#6cc690;--run-s:#1f3245;--wait-s:#3a2c17;--done-s:#1c3326;--track:#2c3743;--bar:#6cc690}}}}
text{{font-family:{FONT};fill:var(--fg)}}
.card{{fill:var(--bg);stroke:var(--line)}}
.muted,.lbl{{fill:var(--muted)}}
.num{{font-weight:700;font-variant-numeric:tabular-nums}}
.num.run{{fill:var(--run)}}.num.wait{{fill:var(--wait)}}.num.done{{fill:var(--done)}}
.tbg.run{{fill:var(--run-s)}}.tbg.wait{{fill:var(--wait-s)}}.tbg.done{{fill:var(--done-s)}}
.tbg{{stroke:transparent;stroke-width:3}}
.track{{fill:var(--track)}}.bar{{fill:var(--bar)}}
.dot.wait{{fill:var(--wait)}}.dot.run{{fill:var(--run)}}
.ok{{fill:var(--done)}}.tick{{stroke:var(--bg)}}
.flowline{{stroke:var(--done);stroke-width:2;stroke-dasharray:4 5;opacity:.6}}
/* 靜止時就完整：所有數字與項目一開始就在；動畫只做提醒與「流入完成」的方向感 */
.pulse .tbg{{animation:lp-pulse 2s ease-in-out 1s infinite}}
@keyframes lp-pulse{{0%,100%{{stroke:transparent}}50%{{stroke:var(--wait)}}}}
.dot.wait{{animation:lp-blink 1.6s ease-in-out infinite}}
@keyframes lp-blink{{50%{{opacity:.3}}}}
.flowline{{animation:lp-flow 1.2s linear infinite}}
@keyframes lp-flow{{to{{stroke-dashoffset:-18}}}}
@keyframes lp-in{{0%{{transform:translateX(-14px);opacity:.35}}{in_end}%,100%{{transform:none;opacity:1}}}}
{rc_rules}
.sheen{{animation:lp-sheen 2.8s ease-in-out infinite}}
@keyframes lp-sheen{{from{{transform:translateX(-80px)}}to{{transform:translateX({fill_w:.0f}px)}}}}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important}}.sheen{{display:none}}}}
"""
    wait_ids = "、".join(i.id for i in wait) or "沒有"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">'
        f'<title>agent-legion 計畫</title><desc>共 {total} 項：等你決定 {len(wait)}（{escape(wait_ids)}）、'
        f'進行中／待做 {len(todo)}、完成 {len(done)}。最近完成：{escape("、".join(f"{i.date} {i.id}" for i in recent))}。'
        f'來源 {escape(p.source)}（sha {escape(p.sha256)}）</desc>'
        f'<metadata>legion-plan:{escape(p.sha256)}:{plan_fingerprint()}</metadata>'
        f"<style>{css}</style>"
        f'<defs><linearGradient id="lp-sheen"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>'
        f'</linearGradient></defs>'
        f'<rect class="card" x="1" y="1" width="{W - 2}" height="{H - 2}" rx="16"/>'
        + "".join(parts) + "</svg>")


def write_plan(settings: Settings, project_root: Path | None = None, inbox_path: Path | None = None) -> Path:
    """依 inbox.md 產生計畫動態圖，寫到 vault（與 project_root 下的 03_docs/img，若有給）。"""
    svg = plan_svg(plan_data(load_inbox(inbox_path or DEFAULT_INBOX)))
    out = settings.ai_dir / diagrams.VAULT_IMG.split("/", 1)[1] / "plan.svg"
    _write(svg, [out] + ([project_root / diagrams.PLAN_SVG] if project_root else []))
    return out


def plan_is_fresh(svg_path: Path, inbox_path: Path | None = None) -> bool:
    """已產生的計畫圖是否與目前 inbox.md＋本模組一致（內容是 inbox 的純函數，所以直接比位元組）。"""
    if not svg_path.exists():
        return False
    want = plan_svg(plan_data(load_inbox(inbox_path or DEFAULT_INBOX)))
    return svg_path.read_bytes() == want.encode("utf-8")
