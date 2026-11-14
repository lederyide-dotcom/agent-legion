"""cost_ledger 記錄每次呼叫的 effort：可對照角色表驗證；舊帳本（無 effort 欄）自動補欄、既有列不變。"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from conftest import Env, State, low_mock, run

from legion.ledger import FIELDS, append_cost, total_on

OLD_HEADER = "time,schema,task,role,backend,model,session_id,status,cost_usd,note\n"
OLD_ROW = "2026-11-10T17:45:43+00:00,legion,T-0001,(task total),claude,sonnet,(backfill),backfill,0.220523,回填\n"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_old_ledger_migrates_header_and_keeps_rows(tmp_path: Path) -> None:
    led = tmp_path / "cost_ledger.csv"
    led.write_text(OLD_HEADER + OLD_ROW, encoding="utf-8")
    append_cost(led, schema="legion", task="T-9", role="planner", backend="claude", model="opus",
                session_id="s", status="completed", cost_usd=0.1, effort="medium")
    rows = _rows(led)
    assert led.read_text(encoding="utf-8").splitlines()[0] == ",".join(FIELDS)
    assert len(rows) == 2
    assert rows[0]["task"] == "T-0001" and rows[0]["cost_usd"] == "0.220523" and rows[0]["effort"] == ""
    assert rows[1]["effort"] == "medium"
    assert not (tmp_path / "cost_ledger.csv.tmp").exists()
    # 第二次寫入不再改寫（表頭已一致），total_on 照常加總
    append_cost(led, schema="legion", task="T-9", role="scribe", backend="claude", model="haiku",
                session_id="s2", status="completed", cost_usd=0.2)
    assert [r["effort"] for r in _rows(led)] == ["", "medium", ""]
    assert abs(total_on(led, date.today(), "legion") - 0.3) < 1e-9


def test_unknown_columns_are_kept_and_never_raise(tmp_path: Path) -> None:
    """人工加的欄位照留；補欄不 raise（在 agent 呼叫之後執行，失敗會讓花費漏記）。"""
    led = tmp_path / "cost_ledger.csv"
    led.write_text(OLD_HEADER.rstrip("\n") + ",mystery\n" + OLD_ROW.rstrip("\n") + ",keep-me\n", encoding="utf-8")
    append_cost(led, schema="legion", task="T-1", role="planner", backend="claude", model=None,
                session_id="s", status="completed", cost_usd=0.1, effort="high")
    rows = _rows(led)
    assert rows[0]["mystery"] == "keep-me" and rows[0]["effort"] == ""
    assert rows[1]["mystery"] == "" and rows[1]["effort"] == "high"
    assert abs(total_on(led, date.today(), "legion") - 0.1) < 1e-9


def test_runner_ledger_effort_matches_role_table(env: Env) -> None:
    s = env.settings.model_copy(update={"ledger_include_mock": True})
    env.idea("a", "effort rows", low_mock())

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            assert (await st.list_tasks())[0].state == State.DONE
        finally:
            await st.close()

    run(go())
    rows = _rows(s.cost_ledger)
    assert rows, "應有帳本列"
    calls = {(t, r): (m, e) for t, r, m, e in env.agent.models}
    for r in rows:
        model, effort = calls[(r["task"], r["role"])]
        assert r["effort"] == (effort or ""), r
        assert r["effort"] == (s.model_for(r["role"], 0, False)[1] or ""), r
    assert {r["role"]: r["effort"] for r in rows}["planner"] == "medium"


def test_failed_call_records_requested_model_and_effort(env: Env) -> None:
    s = env.settings.model_copy(update={"ledger_include_mock": True})
    env.idea("a", "planner error", low_mock(error_roles=["planner"]))

    async def go() -> None:
        st = await env.ticks(settings=s)
        await st.close()

    run(go())
    err = [r for r in _rows(s.cost_ledger) if r["status"] == "error"]
    assert err and all(r["role"] == "planner" for r in err)
    assert all(r["model"] == "opus" and r["effort"] == "medium" for r in err)
