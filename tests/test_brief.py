"""每日晨報：只用程式彙整等你處理的事，內容必須和實際狀態一致。"""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta

from conftest import CALC_OK, Env, State, low_mock, run

from legion.brief import build, headline
from legion.ledger import append_cost


def test_brief_matches_actual_state(env: Env) -> None:
    env.idea("a", "加 multiply", low_mock())  # 完成 → 分支待 merge
    env.idea("b", "刪測試", low_mock(actions=[{"type": "delete", "path": "test_calc.py"}]))  # high → 等人
    yday = datetime.now().astimezone() - timedelta(days=1)
    append_cost(env.settings.cost_ledger, schema=env.settings.schema_name, task="X", role="planner",
                backend="claude", model="opus", session_id="s", status="completed", cost_usd=0.42, when=yday)

    async def go() -> None:
        st = await env.ticks()
        try:
            tasks = {t.title: t for t in await st.list_tasks()}
            done, wait = tasks["加 multiply"], tasks["刪測試"]
            assert done.state == State.DONE and wait.state == State.WAIT_HUMAN
            b, path = await build(env.settings, st)
            assert [w["id"] for w in b["waiting"]] == [wait.id]
            assert [p["branch"] for p in b["pending_merge"]] == [f"legion/{done.id}"]
            assert b["cost_yesterday"] == 0.42
            assert f"1 件等你處理（{wait.id}）" in b["headline"] and "1 個分支待 merge" in b["headline"]
            assert path.exists() and wait.id in path.read_text(encoding="utf-8")
            assert "成果未提交" in b["pending_merge"][0]["note"]  # mock 執行者沒有自己 commit
            # 提交並 merge 之後，就不再列為待 merge
            wt = done.worktree or ""
            subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
            subprocess.run(["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", "x"],
                           check=True)
            b_committed, _ = await build(env.settings, st)
            assert b_committed["pending_merge"][0]["note"] == ""  # 已提交、尚未 merge
            subprocess.run(["git", "-C", str(env.repo), "merge", "-q", "--ff-only", f"legion/{done.id}"], check=True)
            b2, _ = await build(env.settings, st)
            assert b2["pending_merge"] == []
        finally:
            await st.close()

    run(go())


def test_headline_is_short_and_says_no_todo_when_clear() -> None:
    clear = {"waiting": [], "recent_halts": [], "pending_merge": [], "cost_yesterday": 0.0}
    assert headline(clear) == "legion 晨報：無待辦；昨日花費 $0.00"
    busy = {"waiting": [{"id": f"T-{i:04d}"} for i in range(9)], "recent_halts": [{"id": "T-0100"}],
            "pending_merge": [{"id": "T-1"}], "cost_yesterday": 1.234}
    h = headline(busy)
    assert len(h) <= 180 and h.startswith("legion 晨報：9 件等你處理") and "$1.23" in h


def test_brief_never_lists_cancelled_tasks_as_halted(env: Env) -> None:
    env.idea("c", "取消", low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_OK}}]))

    async def go() -> None:
        st = await env.store()
        try:
            from legion.runner import Runner

            r = Runner(env.settings, st, env.agent)
            await r.tick()
            t = (await st.list_tasks())[0]
            await r.cancel(t.id, "approver", "不要了")
            b, _ = await build(env.settings, st, date.today())
            assert b["recent_halts"] == []
        finally:
            await st.close()

    run(go())
