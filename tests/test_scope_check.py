"""A9：可寫任務的變更範圍由 runner 提供證據（相對起點 commit、含未追蹤新檔），規劃者不必自己寫範圍指令。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import CALC_OK, Env, State, low_mock, run

from legion.db import Store
from legion.models import Task
from legion.prompts import planner_prompt, spec_review_prompt
from legion.runner import Runner


def _scope(env: Env, t: Task, run_idx: int = -1) -> tuple[dict, str]:
    check = next(c for c in t.meta["verify_runs"][run_idx]["checks"] if c["name"].startswith("變更範圍"))
    return check, check["txt"]


async def _evidence_text(env: Env, st: Store, t: Task, ev_id: str) -> str:
    ev = next(e for e in await st.evidence(t.id) if e.id == ev_id)
    return (env.settings.record_dir(t.id) / ev.path).read_text(encoding="utf-8")


def test_scope_check_lists_changes_including_new_files(env: Env) -> None:
    env.idea("s", "加 multiply 與新模組", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "helpers.py": "Y = 2\n"}}]),
        allowed_paths=["calc.py", "helpers.py", "test_*.py"])

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.DONE, t.halt_reason
            check, ev_id = _scope(env, t)
            assert check["ok"]
            text = await _evidence_text(env, st, t, ev_id)
            assert "M\tcalc.py" in text and "A\thelpers.py" in text  # 未追蹤新檔也算
            assert f"base: {t.base_commit}" in text
            assert "allowed: calc.py, helpers.py, test_*.py" in text and "result: OK" in text
        finally:
            await st.close()

    run(go())


def test_scope_check_marks_human_approved_out_of_scope(env: Env) -> None:
    env.idea("o", "超出範圍但經核准", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "extra.py": "X = 1\n"}}]),
        allowed_paths=["calc.py", "test_*.py"])

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN  # diff gate 先擋
            runner = Runner(env.settings, st, env.agent)
            await runner.answer(t.id, True, "approver")
            for _ in range(15):
                await runner.tick()
                t = await st.get_task(t.id)
                if t.state in (State.DONE, State.HALT, State.WAIT_HUMAN):
                    break
            assert t.state == State.DONE, (t.state, t.halt_reason)
            check, ev_id = _scope(env, t)
            assert check["ok"]
            text = await _evidence_text(env, st, t, ev_id)
            assert "out of scope: extra.py" in text and "result: OUT_OF_SCOPE_APPROVED" in text
        finally:
            await st.close()

    run(go())


def test_planner_and_spec_reviewer_are_told_runner_checks_scope() -> None:
    w = Task(id="T-1", title="t", body="b", kind="write", meta={"allowed_paths": ["src/**"]})
    r = Task(id="T-2", title="t", body="b", kind="readonly")
    p = planner_prompt(w, "", "wd")
    assert "範圍檢查（runner 固定機制" in p and "`src/**`" in p and "git status --short" in p
    assert "範圍檢查（runner 固定機制" not in planner_prompt(r, "", "wd")
    s = spec_review_prompt(w, "spec", ["python -m pytest -q"])
    assert "不算缺漏" in s and "範圍檢查（runner 固定機制" in s and "仍屬「必修」" in s
    assert "不算缺漏" not in spec_review_prompt(r, "spec", ["python -m pytest -q"])
    assert "不算缺漏" not in p  # 審查用的說明只給審查者


ARTIFACT_TEST = (
    "import pathlib\nimport time\n\n\n"
    "def test_writes_artifact():\n"
    "    pathlib.Path('artifact.log').write_text(str(time.time()), encoding='utf-8')\n"
)


def test_artifact_from_accept_cmds_waits_for_human_then_passes_by_path(env: Env) -> None:
    """驗收指令每次產生內容不同的範圍外檔案：停下等核准（不耗重試），核准路徑後即可完成，不會卡死。"""
    env.idea("x", "測試會寫出 log", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "test_art.py": ARTIFACT_TEST}}]),
        allowed_paths=["calc.py", "test_*.py"])

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN and t.retries == 0, (t.state, t.halt_reason)
            assert any("artifact.log" in r for r in t.risk_reasons)
            runner = Runner(env.settings, st, env.agent)
            await runner.answer(t.id, True, "approver")
            for _ in range(15):
                await runner.tick()
                t = await st.get_task(t.id)
                if t.state in (State.DONE, State.HALT, State.WAIT_HUMAN):
                    break
            assert t.state == State.DONE and t.retries == 0, (t.state, t.halt_reason)
            assert t.meta["approved_oos_paths"] == ["artifact.log"]
            check, ev_id = _scope(env, t)
            text = await _evidence_text(env, st, t, ev_id)
            assert check["ok"] and text.startswith("result: OUT_OF_SCOPE_APPROVED")
        finally:
            await st.close()

    run(go())


def test_scope_check_counts_committed_changes(env: Env) -> None:
    """agent 自己 commit 之後，範圍證據仍列出相對起點 commit 的變更（A9 的主要動機）。"""
    env.idea("c", "加 multiply", low_mock(), allowed_paths=["calc.py", "test_*.py"])

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.DONE and t.worktree
            wt = Path(t.worktree)
            subprocess.run(["git", "-C", str(wt), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(wt), "-c", "user.name=t", "-c", "user.email=t@localhost",
                            "commit", "-qm", "agent commit"], check=True)
            assert subprocess.run(["git", "-C", str(wt), "status", "--short"], capture_output=True, text=True,
                                  check=True).stdout == ""  # 舊做法的 git status --short 會是空的
            r = await Runner(env.settings, st, env.agent)._scope_check(t, wt, 99)
            text = await _evidence_text(env, st, t, r["txt"])
            assert r["ok"] and "M\tcalc.py" in text
        finally:
            await st.close()

    run(go())
