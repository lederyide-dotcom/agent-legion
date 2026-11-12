"""一次性：把 2026-11-11 已發生的真實花費回填到 02_data/cost_ledger.csv（標明來源）。"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime

import yaml

from legion.cli import _windows_loop
from legion.config import Settings
from legion.db import Store
from legion.ledger import append_cost, total_on


async def main() -> None:
    s = Settings()
    path = s.cost_ledger
    if path.exists():
        print("帳本已存在，不重複回填：", path)
        sys.exit(1)
    # 1) DB 重建前的任務：只剩 vault 筆記的任務總額
    for tid in ("T-0001", "T-0002", "T-0003", "T-0004", "T-0005"):
        note = s.ai_dir / "tasks" / f"{tid}.md"
        fm = yaml.safe_load(note.read_text(encoding="utf-8").split("---", 2)[1])
        upd = datetime.fromisoformat(str(fm["updated"])) if fm.get("updated") else None
        append_cost(path, schema="legion", task=tid, role="(task total)", backend="claude", model="sonnet",
                    session_id="(backfill)", status="backfill", cost_usd=float(fm["cost_usd"] or 0),
                    note="回填：vault/AI/tasks 筆記的任務總額（DB 已重建，無逐次紀錄）", when=upd)
    # 2) DB 現存的逐次紀錄
    st = await Store.connect(s.dsn, "legion")
    try:
        for t in await st.list_tasks():
            for r in await st.runs(t.id):
                append_cost(path, schema="legion", task=t.id, role=r.role, backend=r.backend, model=r.model,
                            session_id=r.session_id, status=r.status, cost_usd=r.cost_usd,
                            note="回填：DB agent_runs", when=r.started_at)
    finally:
        await st.close()
    today = datetime.now().astimezone().date()
    print("回填完成；帳本今日合計（schema legion）：", round(total_on(path, today, "legion"), 4))


if __name__ == "__main__":
    _windows_loop()
    asyncio.run(main())
