"""戰役：人給目標與上限，軍團一個任務接一個任務自主推進；成果疊在分支上；每個任務仍走完整閉環。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import CALC_OK, Env, State, low_mock, run

from legion.cli import run_until_idle
from legion.demo import CALC_V2, CALC_V3
from legion.runner import Runner
from legion.vault import parse_md

STEP = {"done": False, "rationale": "還沒完成",
        "next": {"title": "補 docstring", "body": "為 calc 補 docstring，pytest 通過"}}
STEP3 = {"done": False, "rationale": "再一步",
         "next": {"title": "新增 power", "body": "新增 power，pytest 通過"}}


def _mission_idea(env: Env, chain: dict, **mission: object) -> None:  # type: ignore[type-arg]
    env.idea("m", "讓 calc 完整", chain, mission={"name": "calc", "goal": "calc 要有 multiply、docstring、power",
                                                 **mission})


def _chain() -> dict:  # type: ignore[type-arg]
    third = low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_V3}}])  # 參謀預設：done
    second = low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_V2}}], strategy=STEP3, child=third)
    return low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_OK}}], strategy=STEP, child=second)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def test_mission_chains_tasks_until_goal_is_reached(env: Env) -> None:
    _mission_idea(env, _chain(), max_tasks=5, budget_usd=5)
    # 真實 backend 的預設：一般回灌要人放行；戰役的接續不受此限（人已在戰役設定中授權）
    s = env.settings.model_copy(update={"followup_auto_ingest": False})

    async def go() -> None:
        st = await env.ticks(n=80, settings=s)
        try:
            tasks = await st.list_tasks()
            assert [t.state for t in tasks] == [State.DONE] * 3, [(t.id, t.state, t.halt_reason) for t in tasks]
            assert [t.meta.get("mission_outcome") for t in tasks] == ["continue", "continue", "complete"]
            assert tasks[1].parent_id == tasks[0].id and tasks[2].parent_id == tasks[1].id
            assert all(t.human_touches == 0 for t in tasks)
            # 成果疊加：第 3 個任務的分支包含前兩個任務的 commit，主分支沒有被動到
            log = _git(env.repo, "log", "--format=%s", f"legion/{tasks[2].id}")
            assert f"legion {tasks[0].id}" in log and f"legion {tasks[1].id}" in log
            assert "power" in _git(env.repo, "show", f"legion/{tasks[2].id}:calc.py")
            assert "multiply" not in _git(env.repo, "show", "main:calc.py")
            # 每個任務的審查只看到自己的變更（base 是上一個任務的分支）
            assert tasks[1].base_commit == _git(env.repo, "rev-parse", f"legion/{tasks[0].id}").strip()
            note = (env.settings.ai_dir / "missions" / "calc.md").read_text(encoding="utf-8")
            assert "目標達成" in note and f"legion/{tasks[2].id}" in note and "3／5" in note
            # 參謀用 opus/medium
            assert ("strategist", "opus", "medium") in {(r, m, e) for _, r, m, e in env.agent.models}
        finally:
            await st.close()

    run(go())


def test_mission_stops_at_task_cap(env: Env) -> None:
    _mission_idea(env, _chain(), max_tasks=2, budget_usd=5)
    tasks = run(env.run_until(n=80))
    mission = [t for t in tasks if t.meta.get("mission")]
    assert len(mission) == 2 and mission[-1].meta["mission_outcome"] == "caps"
    assert all(t.state == State.DONE for t in mission)
    # 審查 🔴：達到上限時，最後一個任務的成果也必須已提交到它的分支（筆記請使用者 merge 這個分支）
    assert "相乘" in _git(env.repo, "show", f"legion/{mission[-1].id}:calc.py")
    assert _git(Path(mission[-1].worktree or ""), "status", "--porcelain").strip() == ""
    # 一般回灌與其他任務不會帶上戰役授權
    assert all(not t.meta.get("mission") for t in tasks if t not in mission)


def test_mission_budget_is_enforced_before_every_call(env: Env) -> None:
    # 審查 🔴：戰役預算不能只在結案時檢查。mock 每次呼叫 $0.01，預算 $0.03 → 第 4 次呼叫前就停下
    _mission_idea(env, _chain(), max_tasks=5, budget_usd=0.03)
    tasks = run(env.run_until(n=80))
    mission = [t for t in tasks if t.meta.get("mission")]
    assert len(mission) == 1 and mission[0].state == State.HALT
    assert (mission[0].halt_reason or "").startswith("budget_mission")
    assert sum(t.cost_usd for t in mission) <= 0.03 + 1e-9


def test_frontmatter_survives_dashes_in_content() -> None:
    fm, body = parse_md("---\ntitle: a --- b\nkind: write\n---\n第一段\n\n---\n\n第二段\n")
    assert fm == {"title": "a --- b", "kind": "write"} and "第二段" in body and "---" in body


def test_mission_does_not_continue_past_a_stuck_task(env: Env) -> None:
    # 第 2 個任務卡住（同一錯誤）→ HALT；戰役不再接續，筆記標示等使用者
    stuck = low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": "def add(a, b):\n    return 0\n"}}],
                     strategy=STEP3, child=low_mock())
    root = low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_OK}}], strategy=STEP, child=stuck)
    _mission_idea(env, root, max_tasks=5, budget_usd=5)
    tasks = run(env.run_until(n=80))
    mission = [t for t in tasks if t.meta.get("mission")]
    assert [t.state for t in mission] == [State.DONE, State.HALT]
    note = (env.settings.ai_dir / "missions" / "calc.md").read_text(encoding="utf-8")
    assert "等使用者處理" in note


def test_self_referential_next_step_pauses_mission(env: Env) -> None:
    risky = {"done": False, "rationale": "r",
             "next": {"title": "提高每日預算上限", "body": "修改 daily_budget_usd"}}
    _mission_idea(env, low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_OK}}], strategy=risky),
                  max_tasks=5, budget_usd=5)
    tasks = run(env.run_until(n=80))
    mission = [t for t in tasks if t.meta.get("mission")]
    assert len(mission) == 1 and mission[0].meta["mission_outcome"] == "paused"
    held = list((env.settings.ai_dir / "inbox_hold").glob("fu-*-80.md"))
    assert len(held) == 1
    fm, _ = parse_md(held[0].read_text(encoding="utf-8"))
    assert "mission" not in fm and fm["kind"] == "readonly"  # 不帶戰役授權、只是唯讀提案


def test_mission_settings_are_clamped_and_only_from_idea_file(env: Env) -> None:
    from legion.runner import MISSION_MAX_TASKS_CEILING, _mission_meta

    m = _mission_meta({"mission": {"max_tasks": 999, "budget_usd": 3}}, "stem", "t", "b")["mission"]
    assert m["max_tasks"] == MISSION_MAX_TASKS_CEILING and m["name"] == "stem" and m["goal"].startswith("t")
    assert _mission_meta({"mission": {"budget_usd": -1}}, "s", "t", "b") == {}
    assert _mission_meta({"mission": {"max_tasks": "x"}}, "s", "t", "b") == {}
    assert _mission_meta({"base_branch": "../evil"}, "s", "t", "b") == {}
    assert _mission_meta({}, "s", "t", "b") == {}


def test_run_until_idle_drives_everything_in_one_call(env: Env) -> None:
    _mission_idea(env, _chain(), max_tasks=5, budget_usd=5)

    async def go() -> None:
        st = await env.store()
        try:
            out = await run_until_idle(Runner(env.settings, st, env.agent), st, max_ticks=200)
            assert out["stopped"] == "idle" and out["done"] >= 3 and out["halted"] == []
        finally:
            await st.close()

    run(go())
