"""驗收輔助：檢查 mock demo 的紀錄文件與匯出結果，寫入 02_data/record_check.csv、export_check.csv、image_check.csv。

用法：.venv\\Scripts\\python.exe scripts\\verify_artifacts.py
前提：已跑過 `python -m legion demo --mock`（schema demo）。
"""
from __future__ import annotations

import asyncio
import csv
import sys
from datetime import datetime

from legion.checks import append_csv, check_record
from legion.config import Settings
from legion.db import Store
from legion.evidence import image_stats
from legion.export import append_export_check, export
from legion.models import State


async def main() -> int:
    s = Settings(schema_name="demo")
    st = await Store.connect(s.dsn, s.schema_name)
    tasks = [t for t in await st.list_tasks() if t.state == State.DONE]
    await st.close()
    if not tasks:
        print("沒有已結案的 demo 任務，請先跑 python -m legion demo --mock")
        return 1
    ok = True
    img_rows = []
    for t in tasks:
        rec = s.record_dir(t.id) / "record.md"
        r = check_record(rec, t.accept_cmds)
        append_csv(s.data_dir / "record_check.csv", r)
        print(f"record {t.id}: {'OK' if r.ok else 'NG'}  證據 {r.n_evidence}、圖 {r.n_images}")
        ok &= r.ok
        for ln in rec.read_text(encoding="utf-8").splitlines():
            if ln.startswith("!["):
                rel = ln.split("(", 1)[1].rstrip(")")
                w, h, sd = image_stats(rec.parent / rel)
                kind = "mermaid" if "mermaid" in rel else ("chart" if "chart" in rel else "terminal")
                good = w >= 200 and h >= 80 and sd > 5
                ok &= good
                img_rows.append({"time": datetime.now().astimezone().isoformat(timespec="seconds"), "task": t.id,
                                 "file": rel, "kind": kind, "width": w, "height": h, "stddev": f"{sd:.1f}",
                                 "ok": good})
    out = s.data_dir / "image_check.csv"
    new = not out.exists()
    with out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(img_rows[0]), lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(img_rows)
    kinds = {r["kind"] for r in img_rows if r["task"] == tasks[0].id}
    print(f"{tasks[0].id} 圖種類：{sorted(kinds)}")
    ok &= kinds >= {"mermaid", "chart", "terminal"}
    first = tasks[0]
    n_img = sum(1 for ln in (s.record_dir(first.id) / "record.md").read_text(encoding="utf-8").splitlines()
                if ln.startswith("!["))
    for fmt in ("docx", "pdf"):
        p = await export(s, first.id, fmt)
        row = append_export_check(s.data_dir / "export_check.csv", first.id, p, n_img)
        print(f"export {fmt}: {row}")
        ok &= bool(row["ok"])
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(asyncio.run(main()))
