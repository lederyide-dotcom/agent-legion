"""可中斷續跑：在各狀態中途用 os._exit 真的殺掉 runner 行程，重跑 `legion tick` 後從原狀態繼續，不重複扣預算。"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import Env, State, low_mock, run

BASELINE_COST = 0.05  # 5 次 agent 呼叫 × 0.01


def _tick(env: Env, crash: str | None) -> int:
    e = dict(os.environ)
    e.update(LEGION_VAULT=str(env.settings.vault), LEGION_DATA_DIR=str(env.settings.data_dir),
             LEGION_WORKTREES=str(env.settings.worktrees_dir), LEGION_RENDER_MERMAID="0")
    if crash:
        e["LEGION_CRASH_AT"] = crash
    else:
        e.pop("LEGION_CRASH_AT", None)
    p = subprocess.run([sys.executable, "-m", "legion", "--schema", env.schema, "tick", "--backend", "mock"],
                       env=e, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if p.returncode not in (0, 17):
        raise AssertionError(p.stderr[-2000:])
    return p.returncode


@pytest.mark.parametrize("crash", [
    "PLAN:after_agent", "SPEC_REVIEW:before_agent", "EXEC:after_agent", "VERIFY:after_transition",
    "REVIEW:after_agent", "LEARN:after_agent",
])
def test_kill_mid_state_then_resume(env: Env, crash: str) -> None:
    async def init() -> None:
        st = await env.store()  # 建表
        await st.close()

    run(init())
    env.idea("k", "killable", low_mock())
    state_name = crash.split(":")[0]
    killed_in = None
    for _ in range(15):
        code = _tick(env, crash)
        if code == 17:
            async def snap() -> tuple[State, float]:
                st = await env.store()
                t = (await st.list_tasks())[0]
                await st.close()
                return t.state, t.cost_usd

            killed_in = run(snap())
            break
    assert killed_in is not None, "沒有觸發中斷點"
    state_at_kill, cost_at_kill = killed_in
    # before/after_agent：仍停在原狀態；after_transition：剛轉入該狀態即被殺
    assert state_at_kill.value == state_name
    for _ in range(15):
        _tick(env, None)

    async def final() -> None:
        st = await env.store()
        t = (await st.list_tasks())[0]
        runs = await st.runs(t.id)
        assert t.state == State.DONE
        assert abs(t.cost_usd - BASELINE_COST) < 1e-9, f"重複扣預算：{t.cost_usd}"
        keys = [(r.state, r.step, r.role) for r in runs]
        assert len(keys) == len(set(keys)) == 5
        trans = await st.events(t.id, "transition")
        assert len(trans) == t.step == 8
        await st.close()

    run(final())
    assert cost_at_kill <= BASELINE_COST
