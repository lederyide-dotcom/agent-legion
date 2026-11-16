"""評測基準：9 道固定題目全部符合預期；結果存檔、寫 metrics、儀表看得到趨勢。"""
from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

from legion.bench import CASES, history, run_bench, save
from legion.config import Settings
from legion.models import State
from legion.motion import dashboard_svg


def test_bench_all_cases_match_expectations(tmp_path: Path) -> None:
    res = asyncio.run(run_bench(Settings(), tmp=tmp_path / "bench"))
    bad = {r["key"]: r["problems"] for r in res["rows"] if not r["ok"]}
    assert not bad, bad
    assert res["passed"] == res["cases"] == len(CASES) == 9 and res["match_rate"] == 1.0
    # 涵蓋三種結局：完成、停下等人、（軍師）等人選錦囊
    assert {c.state for c in CASES} == {State.DONE, State.WAIT_HUMAN}
    assert any(c.key == "advisor" for c in CASES)
    # 守門與範圍檢查要分得出是哪一道擋下的（審查做過變異測試：只看最終狀態會放過回歸）
    by_key = {c.key: c for c in CASES}
    assert by_key["high-risk"].execs == 0 and by_key["high-risk"].wait_reason
    assert by_key["out-of-scope"].reason_contains and by_key["out-of-scope"].wait_reason


def test_save_writes_json_metrics_and_history(tmp_path: Path) -> None:
    res = {"at": "2026-11-15T01:00:00+08:00", "commit": "abc1234", "cases": 8, "passed": 7, "match_rate": 0.875,
           "agent_calls": 40, "wall_s": 20.0, "rows": []}
    path = save(res, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["passed"] == 7
    rows = list(csv.reader((tmp_path / "metrics.csv").open(encoding="utf-8")))
    assert rows[0] == ["date", "commit", "metric", "value", "command"]
    assert [r[2] for r in rows[1:]] == ["bench.mock.match_rate", "bench.mock.agent_calls", "bench.mock.wall_s"]
    save({**res, "at": "2026-11-15T02:00:00+08:00", "passed": 8}, tmp_path)
    h = history(tmp_path)
    assert [x["passed"] for x in h] == [7, 8]


def test_dashboard_shows_bench_trend() -> None:
    st = {"generated_at": "now", "counts": {"running": 0, "waiting": 0, "halt": 0, "done": 1}, "total": 1,
          "cost_today": 0.0, "daily_budget": 2.0, "cost_7d": 0.0, "cost_all": 0.0, "waiting_ids": [], "last_halt": "",
          "bench": [{"at": "a", "passed": 7, "cases": 8, "commit": "x"}, {"at": "b", "passed": 8, "cases": 8, "commit": "y"}]}
    svg = dashboard_svg(st)
    assert svg.count('class="bad"') == 1 and svg.count('class="ok"') == 1 and "最新 8/8 符合預期" in svg
    assert "尚未執行" in dashboard_svg({**st, "bench": []})
