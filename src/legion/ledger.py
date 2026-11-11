"""持久花費帳本：每次 agent 呼叫（含失敗、逾時）追加一列到 02_data/cost_ledger.csv。

DB 可能被重建（事故 2），帳本是 append-only 的 CSV，不隨 DB 消失；每日預算取「DB 當日花費」與
「帳本當日花費」較大者，避免低估。帳本依 schema 分開計算，demo／測試的 mock 花費不會算進正式預算。
"""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

FIELDS = ["time", "schema", "task", "role", "backend", "model", "session_id", "status", "cost_usd", "note"]


def append_cost(path: Path, *, schema: str, task: str, role: str, backend: str, model: str | None,
                session_id: str, status: str, cost_usd: float, note: str = "",
                when: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "time": (when or datetime.now().astimezone()).isoformat(timespec="seconds"),
            "schema": schema, "task": task, "role": role, "backend": backend, "model": model or "",
            "session_id": session_id, "status": status, "cost_usd": f"{cost_usd:.6f}", "note": note,
        })


def total_on(path: Path, day: date, schema: str) -> float:
    """帳本中某 schema 在本地日期 day 的花費合計。壞列略過（帳本可能被手動編輯）。"""
    if not path.exists():
        return 0.0
    total = 0.0
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("schema") != schema:
                continue
            try:
                when = datetime.fromisoformat(r["time"])
                cost = float(r["cost_usd"])
            except (KeyError, TypeError, ValueError):
                continue
            local = when.astimezone() if when.tzinfo else when
            if local.date() == day:
                total += cost
    return total
