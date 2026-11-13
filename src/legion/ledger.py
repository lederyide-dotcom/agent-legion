"""持久花費帳本：每次 agent 呼叫（含失敗、逾時）追加一列到 02_data/cost_ledger.csv。

DB 可能被重建（事故 2），帳本是 append-only 的 CSV，不隨 DB 消失；每日預算取「DB 當日花費」與
「帳本當日花費」較大者，避免低估。真實花費跨 schema 加總；mock 花費只算本 schema，不會算進正式預算。
"""
from __future__ import annotations

import csv
import os
from datetime import date, datetime
from pathlib import Path

# effort 放最後一欄：舊帳本（無 effort 欄）第一次寫入時補欄，既有列 effort 留空（＝當時未記錄，不是「未指定」）。
# effort 記的是 runner 傳給 CLI 的 --effort 值；空字串表示沒有傳（用 CLI 預設）。CLI 是否確實套用無法從輸出確認。
FIELDS = ["time", "schema", "task", "role", "backend", "model", "session_id", "status", "cost_usd", "note",
          "effort"]


def _ensure_header(path: Path) -> list[str]:
    """回傳這個帳本該用的欄位順序。舊帳本缺欄時補到最後並把舊列補空值；未知欄位（人工加的）照留不刪。

    改寫時先寫暫存檔再 os.replace，中途崩潰不會留下半個檔案。這裡不能 raise：它在 agent 呼叫之後執行，
    一旦失敗，這次已發生的花費就沒入帳。
    """
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        missing = [k for k in FIELDS if k not in header]
        if not missing:
            return header
        rows = list(reader)
    header += missing
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
    return header


def append_cost(path: Path, *, schema: str, task: str, role: str, backend: str, model: str | None,
                session_id: str, status: str, cost_usd: float, note: str = "",
                when: datetime | None = None, effort: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    header = FIELDS if new else _ensure_header(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, restval="")
        if new:
            w.writeheader()
        w.writerow({
            "time": (when or datetime.now().astimezone()).isoformat(timespec="seconds"),
            "schema": schema, "task": task, "role": role, "backend": backend, "model": model or "",
            "session_id": session_id, "status": status, "cost_usd": f"{cost_usd:.6f}", "note": note,
            "effort": effort or "",
        })


def total_on(path: Path, day: date, schema: str, real_account: bool = True) -> float:
    """本地日期 day 的花費合計。壞列略過（帳本可能被手動編輯）。

    real_account=True（真實 backend）：真實花費是整個帳號共用的額度，非 mock 列跨 schema 加總，mock 列只算本 schema。
    real_account=False（mock backend，例如 demo）：只算本 schema；不花錢的 mock 不受真實額度限制。
    """
    if not path.exists():
        return 0.0
    total = 0.0
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            same = r.get("schema") == schema
            if not same and (not real_account or r.get("backend") == "mock"):
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
