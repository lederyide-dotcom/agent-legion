"""紀錄文件檢查（可單獨執行）：章節、證據可追溯、圖號圖說、敘述不得無憑據。

用法：python -m legion.checks record <record.md> [--criteria-json '[...]'] [--csv 02_data/record_check.csv]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .record import CHAPTERS

EV_RE = re.compile(r"\bE-\d{3}\b")
IMG_RE = re.compile(r"^!\[[^\]]*\]\(([^)]+)\)\s*$")
CAPTION_RE = re.compile(r"^\*圖 (\d+)：.+（E-\d{3}）\*$")


class RecordCheck(BaseModel):
    path: str
    chapters_ok: bool
    missing_chapters: list[str] = Field(default_factory=list)
    missing_criteria: list[str] = Field(default_factory=list)
    unknown_evidence: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    hash_mismatch: list[str] = Field(default_factory=list)
    uncaptioned_images: list[str] = Field(default_factory=list)
    uncited_paragraphs: list[str] = Field(default_factory=list)
    n_evidence: int = 0
    n_images: int = 0

    @property
    def ok(self) -> bool:
        return (self.chapters_ok and not self.missing_criteria and not self.unknown_evidence
                and not self.missing_files and not self.hash_mismatch and not self.uncaptioned_images
                and not self.uncited_paragraphs)


def _sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cur: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf)
            cur, buf = line[3:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf)
    return out


def parse_ledger(text: str) -> dict[str, tuple[str, str]]:
    """附錄證據清冊 → {E-id: (相對路徑, sha256)}"""
    sec = _sections(text).get(CHAPTERS[7], "")
    out: dict[str, tuple[str, str]] = {}
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and EV_RE.fullmatch(cells[0]):
            out[cells[0]] = (cells[1], cells[2])
    return out


def narrative_violations(text: str) -> list[str]:
    """第 5、6 章每個結論段落（以空行分隔的區塊，排除標題、圖、圖說、程式碼）至少要引用一個證據編號。"""
    secs = _sections(text)
    bad: list[str] = []
    for ch in (CHAPTERS[4], CHAPTERS[5]):
        body = secs.get(ch, "")
        in_code = False
        blocks: list[list[str]] = [[]]
        for line in body.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if not line.strip():
                blocks.append([])
                continue
            blocks[-1].append(line)
        for b in blocks:
            content = [ln for ln in b if not ln.startswith("#") and not IMG_RE.match(ln.strip())
                       and not CAPTION_RE.match(ln.strip())]
            if not content:
                continue
            joined = " ".join(content).strip()
            if joined in {"（尚未執行驗證）", "（尚未進行）"}:
                continue
            if not EV_RE.search(joined):
                bad.append(f"[{ch}] {joined[:120]}")
    return bad


def check_record(path: Path, criteria: list[str] | None = None) -> RecordCheck:
    text = path.read_text(encoding="utf-8")
    secs = _sections(text)
    missing = [c for c in CHAPTERS if c not in secs]
    ledger = parse_ledger(text)
    rdir = path.parent
    referenced = set(EV_RE.findall(text))
    unknown = sorted(referenced - set(ledger))
    missing_files, mismatch = [], []
    for eid, (rel, sha) in ledger.items():
        f = rdir / rel
        if not f.exists():
            missing_files.append(f"{eid}:{rel}")
            continue
        if hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            mismatch.append(f"{eid}:{rel}")
    lines = text.splitlines()
    uncaptioned, n_img, expect = [], 0, 1
    for i, line in enumerate(lines):
        m = IMG_RE.match(line.strip())
        if not m:
            continue
        n_img += 1
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        cm = CAPTION_RE.match(nxt)
        if not cm or int(cm.group(1)) != expect:
            uncaptioned.append(m.group(1))
        expect += 1
        if not (rdir / m.group(1)).exists():
            missing_files.append(f"image:{m.group(1)}")
    miss_crit: list[str] = []
    ch5 = secs.get(CHAPTERS[4], "")
    for i, c in enumerate(criteria or [], start=1):
        if f"### 5.{i} 驗收標準 {i}：`{c}`" not in ch5:
            miss_crit.append(c)
    return RecordCheck(
        path=str(path), chapters_ok=not missing, missing_chapters=missing, missing_criteria=miss_crit,
        unknown_evidence=unknown, missing_files=missing_files, hash_mismatch=mismatch,
        uncaptioned_images=uncaptioned, uncited_paragraphs=narrative_violations(text),
        n_evidence=len(ledger), n_images=n_img,
    )


CSV_FIELDS = ["time", "record", "ok", "chapters_ok", "n_evidence", "n_images", "unknown_evidence",
              "missing_files", "hash_mismatch", "uncaptioned_images", "uncited_paragraphs"]


def append_csv(out: Path, r: RecordCheck) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    new = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"), "record": r.path, "ok": r.ok,
            "chapters_ok": r.chapters_ok, "n_evidence": r.n_evidence, "n_images": r.n_images,
            "unknown_evidence": ";".join(r.unknown_evidence), "missing_files": ";".join(r.missing_files),
            "hash_mismatch": ";".join(r.hash_mismatch), "uncaptioned_images": ";".join(r.uncaptioned_images),
            "uncited_paragraphs": " || ".join(r.uncited_paragraphs),
        })


def _git_ls_files(root: Path) -> list[str]:
    try:
        # -z：中文檔名不會被引號轉義
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True,
                             encoding="utf-8", timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [p for p in out.stdout.split("\0") if p] if out.returncode == 0 else []


# 路徑只認 ASCII 字元：中文緊貼檔名（「定義於telegram_bot.py:12」）時不會把中文吃進路徑
_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_/\\.-])((?:[A-Za-z]:[\\/])?[A-Za-z0-9_.\-/\\]+"
    r"\.(?:py|pyi|sh|ya?ml|md|json|bat|ps1|txt|toml|cfg|ini|jsx?|tsx?|csv|sql|html|css))"
    r"[:：](\d+)(?:\s*[-–~]\s*(\d+))?")


def verify_refs(text: str, root: Path) -> tuple[int, list[str]]:
    """檢查報告中每個 `檔名:行號`（含 `檔名:起-迄`）：檔案存在、位於 root 內、行號在範圍內。

    回傳 (引用數, 問題清單)。取代「交付審查者抽查行號」：LLM 抽查不可靠，改由程式逐一核對。
    """
    root = root.resolve()
    problems: list[str] = []
    n = 0
    line_counts: dict[Path, int] = {}
    tracked: list[str] | None = None
    for m in _REF_RE.finditer(text):
        n += 1
        raw, start, end = m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))
        p = Path(raw.replace("\\", "/"))
        full = (p if p.is_absolute() else root / p).resolve()
        ref = m.group(0)
        if not full.is_file() and not p.is_absolute() and "/" not in raw.replace("\\", "/"):
            # 只寫檔名（例如 spec.md:21）：以 git 追蹤檔中唯一同名者為準；不用 rglob（目標 repo 可能有百萬檔）
            if tracked is None:
                tracked = _git_ls_files(root)
            same = [t for t in tracked if t.rsplit("/", 1)[-1] == raw]
            if len(same) == 1:
                full = (root / same[0]).resolve()
            elif len(same) > 1:
                problems.append(f"{ref}：只寫檔名且有 {len(same)} 個同名檔，無法判定")
                continue
        try:
            full.relative_to(root)
        except ValueError:
            problems.append(f"{ref}：在目標 repo（{root}）之外")
            continue
        if not full.is_file():
            problems.append(f"{ref}：檔案不存在")
            continue
        if full not in line_counts:
            try:
                # 只以 \n 切行（splitlines 會把 \x0c、  也當換行而多算）
                line_counts[full] = len(full.read_text(encoding="utf-8", errors="replace").rstrip("\n").split("\n"))
            except OSError as exc:
                problems.append(f"{ref}：無法讀取（{exc!r}）")
                continue
        total = line_counts[full]
        if start < 1 or end < start or end > total:
            problems.append(f"{ref}：行號超出範圍（檔案共 {total} 行）")
    return n, problems


def check_report(path: Path, sections: list[str], min_chars: int, verify: bool = False,
                 root: Path | None = None, min_refs: int = 0) -> int:
    if not path.exists():
        print(f"NG 報告不存在：{path}")
        return 1
    text = path.read_text(encoding="utf-8")
    heads = [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]
    missing = [s for s in sections if not any(s in h for h in heads)]
    print(f"報告 {path}：{len(text)} 字元、{len(heads)} 個標題")
    for s in sections:
        print(f"  章節「{s}」：{'有' if s not in missing else '缺'}")
    if len(text) < min_chars:
        print(f"NG 報告過短（< {min_chars} 字元）")
        return 1
    if missing:
        print(f"NG 缺少章節：{missing}")
        return 1
    if verify:
        base = root or Path.cwd()
        n, problems = verify_refs(text, base)
        print(f"  行號引用：{n} 筆，問題 {len(problems)} 筆（以 {base.resolve()} 為準）")
        for prob in problems[:50]:
            print(f"    - {prob}")
        if problems:
            print("NG 報告引用的檔案或行號不存在")
            return 1
        if n < min_refs:
            print(f"NG 行號引用少於 {min_refs} 筆")
            return 1
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="legion.checks")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("record")
    rp.add_argument("paths", nargs="+", type=Path)
    rp.add_argument("--criteria-json", default=None)
    rp.add_argument("--criterion", action="append", default=None, help="驗收標準原文，可重複")
    rp.add_argument("--csv", type=Path, default=None)
    rpt = sub.add_parser("report", help="檢查唯讀任務的報告存在、夠長、含必要章節")
    rpt.add_argument("path", type=Path)
    rpt.add_argument("--section", action="append", default=[])
    rpt.add_argument("--min-chars", type=int, default=800)
    rpt.add_argument("--verify-refs", action="store_true", help="逐一核對報告中的 檔名:行號（以目前目錄或 --root 為準）")
    rpt.add_argument("--root", type=Path, default=None)
    rpt.add_argument("--min-refs", type=int, default=0)
    args = ap.parse_args(argv)
    if args.cmd == "report":
        return check_report(args.path, args.section, args.min_chars, args.verify_refs, args.root, args.min_refs)
    crit = json.loads(args.criteria_json) if args.criteria_json else args.criterion
    all_ok = True
    for p in args.paths:
        r = check_record(p, crit)
        if args.csv:
            append_csv(args.csv, r)
        print(f"{'OK ' if r.ok else 'NG '} {p}  證據 {r.n_evidence}、圖 {r.n_images}")
        for name in ("missing_chapters", "missing_criteria", "unknown_evidence", "missing_files", "hash_mismatch",
                     "uncaptioned_images", "uncited_paragraphs"):
            for item in getattr(r, name):
                print(f"   {name}: {item}")
        all_ok &= r.ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
