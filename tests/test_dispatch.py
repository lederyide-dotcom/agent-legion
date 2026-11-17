"""派工成效報表：各角色 × 模型的次數與花費；執行者一次過／重做比例（純函式，不需要 DB）。"""
from __future__ import annotations

import pytest
from conftest import Env, State, low_mock, run

from legion.dispatch import executor_outcomes, render, usage_by_role_model
from legion.models import AgentRun, Task


def _run(tid: str, role: str, model: str | None, cost: float, step: int = 0, status: str = "completed",
         backend: str = "claude") -> AgentRun:
    return AgentRun(task_id=tid, state="X", step=step, role=role, backend=backend, model=model, session_id="s",
                    cost_usd=cost, duration_s=10.0, status=status)


def _task(tid: str, state: State) -> Task:
    return Task(id=tid, title=tid, state=state, doc_status="draft")


RUNS = [
    _run("T1", "planner", "opus", 0.10), _run("T1", "executor", "sonnet", 0.20),
    _run("T2", "planner", "opus", 0.12), _run("T2", "executor", "sonnet", 0.30),
    _run("T2", "executor", "opus", 0.50, step=1),                        # 重做升級
    _run("T3", "executor", "sonnet", 0.05, status="timeout"),            # 失敗、任務 HALT
    _run("T4", "executor", "sonnet", 0.07),                              # 任務還在跑：不算結果
    _run("T1", "scribe", "mock", 0.0, backend="mock"),                   # mock：預設不算
]
TASKS = [_task("T1", State.DONE), _task("T2", State.DONE), _task("T3", State.HALT), _task("T4", State.EXEC)]


def test_usage_groups_by_role_and_model_and_skips_mock() -> None:
    u = {(x.role, x.model): x for x in usage_by_role_model(RUNS)}
    assert ("scribe", "mock") not in u
    assert u[("executor", "sonnet")].calls == 4 and u[("executor", "sonnet")].failed == 1
    assert u[("executor", "sonnet")].cost_usd == 0.62 and u[("executor", "sonnet")].avg_cost_usd == 0.155
    assert u[("planner", "opus")].calls == 2
    assert usage_by_role_model(RUNS)[0].model == "sonnet"  # 花費最高的排第一
    assert ("scribe", "mock") in {(x.role, x.model) for x in usage_by_role_model(RUNS, backend=None)}


def test_executor_outcomes_first_pass_and_escalation() -> None:
    (o,) = executor_outcomes(RUNS, TASKS)
    assert (o.model, o.tasks, o.first_pass, o.retried, o.done) == ("sonnet", 3, 1, 1, 2)
    assert round(o.first_pass_rate, 2) == 0.33


def test_render_has_totals_labels_and_empty_message() -> None:
    text = render(usage_by_role_model(RUNS), executor_outcomes(RUNS, TASKS), {"executor": "執行者"})
    assert "執行者\tsonnet\t4\t1\t$0.6200" in text and "合計" in text and "一次過比例" in text
    assert "還沒有真實呼叫紀錄" in render([], [], {})


def test_render_explains_aliases() -> None:
    runs = [_run("T1", "executor", "sonnet", 0.1), _run("T2", "executor", "claude-sonnet-5-5", 0.1),
            _run("T3", "reviewer", None, 0.1)]
    text = render(usage_by_role_model(runs), [], {})
    assert "sonnet 是舊紀錄存的別名" in text and "(CLI 預設)＝" in text


def test_failed_call_records_requested_model(env: Env) -> None:
    """審查抓到：逾時／錯誤的呼叫原本 model 是 None，失敗數全算到 (CLI 預設)。"""
    env.idea("f", "執行會逾時", low_mock(timeout_roles=["executor"]))
    t = run(env.run_until())[0]

    async def go() -> None:
        st = await env.store()
        try:
            failed = [r for r in await st.runs(t.id) if r.status != "completed"]
            assert failed and all(r.model for r in failed), [(r.role, r.model) for r in failed]
        finally:
            await st.close()

    run(go())


def test_cli_usage_reads_db(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    from legion.cli import main

    env.idea("d", "派工報表", low_mock())
    run(env.run_until())
    assert main(["--schema", env.settings.schema_name, "models", "--all"]) == 0
    out = capsys.readouterr().out
    assert "派工成效" in out and "合計" in out and "執行者（依第一次執行的模型" in out
