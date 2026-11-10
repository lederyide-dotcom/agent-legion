"""紀錄文件檢查（可單獨執行）：章節、證據可追溯、圖號圖說、敘述不得無憑據。

用法：python -m legion.checks record <record.md> [--criteria-json '[...]'] [--csv 02_data/record_check.csv]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
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
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"), "record": r.path, "ok": r.ok,
            "chapters_ok": r.chapters_ok, "n_evidence": r.n_evidence, "n_images": r.n_images,
            "unknown_evidence": ";".join(r.unknown_evidence), "missing_files": ";".join(r.missing_files),
            "hash_mismatch": ";".join(r.hash_mismatch), "uncaptioned_images": ";".join(r.uncaptioned_images),
            "uncited_paragraphs": " || ".join(r.uncited_paragraphs),
        })


def check_report(path: Path, sections: list[str], min_chars: int) -> int:
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
    args = ap.parse_args(argv)
    if args.cmd == "report":
        return check_report(args.path, args.section, args.min_chars)
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
