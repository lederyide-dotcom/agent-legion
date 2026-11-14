"""cancel 也能收尾「停下但還能續跑」的任務：改成不再續跑，舊原因保留，晨報與 cleanup 視為已結束。"""
from __future__ import annotations

import pytest
from conftest import Env, State, low_mock, run

from legion.brief import collect
from legion.cleanup import plan
from legion.runner import Runner


def test_cancel_resumable_halt_makes_it_final(env: Env) -> None:
    env.idea("a", "加 multiply", low_mock())

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            t = await st.transition(t, State.HALT, {"test": "stop"}, return_state=State.EXEC,
                                    halt_reason="agent_error: budget")
            r = Runner(env.settings, st, env.agent)
            out = await r.cancel(t.id, "tester", "已被別的任務取代")
            assert out.state == State.HALT and out.return_state is None
            assert out.halt_reason and out.halt_reason.startswith("operator_cancel: 已被別的任務取代")
            assert "agent_error: budget" in out.halt_reason
            assert out.human_touches == t.human_touches + 1
            assert [e.kind for e in await st.events(t.id, "cancel_halted")] == ["cancel_halted"]
            with pytest.raises(ValueError):
                await r.resume(t.id, "tester")
            with pytest.raises(ValueError):  # 已經不能續跑的 HALT 再 cancel 一次 → 拒絕
                await r.cancel(t.id, "tester", "again")
            assert collect(env.settings, await st.list_tasks())["recent_halts"] == []
            # cleanup 視為已結束（分支沒併入仍會保留，理由不再是「可以續跑」）
            reason = {r["id"]: r["reason"] for r in plan(env.settings, await st.list_tasks())["keep"]}.get(t.id, "")
            assert "可以續跑" not in reason
        finally:
            await st.close()

    run(go())


def test_cancel_halted_refuses_if_task_was_resumed_meanwhile(env: Env) -> None:
    env.idea("a", "加 multiply", low_mock())

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            t = await st.transition(t, State.HALT, {"test": "stop"}, return_state=State.EXEC)
            stale = t
            # 另一個終端機先 resume：狀態與 step 都變了
            await st.transition(t, State.EXEC, {"test": "resumed"}, halt_reason=None)

            class StaleStore:
                """讓 cancel 讀到 resume 之前的舊狀態，模擬兩邊同時操作。"""

                def __getattr__(self, name: str) -> object:
                    return getattr(st, name)

                async def get_task(self, task_id: str) -> object:
                    return stale

            r = Runner(env.settings, StaleStore(), env.agent)  # type: ignore[arg-type]
            with pytest.raises(RuntimeError):
                await r.cancel(t.id, "tester", "晚了一步")
            now = await st.get_task(t.id)
            assert now.state == State.EXEC and not (now.halt_reason or "").startswith("operator_cancel")
            assert now.human_touches == t.human_touches
        finally:
            await st.close()

    run(go())
