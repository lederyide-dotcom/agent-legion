"""需求釐清：規劃者對模糊想法提問 → 停下等人；採用預設沿用規格、非預設答案重新規劃、閒置採用預設。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import Env, State, low_mock, run

from legion.db import utcnow
from legion.runner import CLARIFY_WAIT, Runner

QUESTIONS = [
    {"question": "multiply 要支援浮點數嗎？", "options": ["只要整數", "整數與浮點數"], "default": "整數與浮點數",
     "why": "影響測試案例"},
    {"question": "要不要補 docstring？", "options": ["要", "不用"], "default": "不用"},
    {"question": "格式壞掉的題目", "options": ["只有一個"], "default": "只有一個"},  # 選項不足 → 丟掉
]


def _roles(env: Env, tid: str, role: str) -> int:
    return sum(1 for t, r, *_ in env.agent.models if t == tid and r == role)


async def _asked(env: Env, **kw: object):  # type: ignore[no-untyped-def]
    env.idea("c", "幫 calc 加乘法", low_mock(questions=QUESTIONS))
    st = await env.ticks(settings=env.settings.model_copy(update={"clarify_idle_minutes": 60.0, **kw}))
    return st, (await st.list_tasks())[0]


def test_vague_idea_stops_to_ask_before_executing(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            assert t.state == State.WAIT_HUMAN and t.wait_reason == CLARIFY_WAIT
            assert [q["id"] for q in t.meta["clarify"]["questions"]] == ["1", "2"]  # 壞題被丟掉
            assert _roles(env, t.id, "executor") == 0 and _roles(env, t.id, "spec_reviewer") == 0
            note = (env.settings.ai_dir / "questions" / f"{t.id}.md").read_text(encoding="utf-8")
            assert "⭐ B. 整數與浮點數" in note and f"legion clarify {t.id} --defaults" in note and "1=B 2=B" in note
            assert "需求釐清" in env.agent.prompts[0][2]  # 第一次規劃有告訴規劃者可以提問
        finally:
            await st.close()

    run(go())


def test_defaults_reuse_the_spec_without_replanning(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            await Runner(env.settings, st, env.agent).answer(t.id, True, "david")  # approve＝全部預設
        finally:
            await st.close()
        t = (await (await env.ticks()).list_tasks())[0]
        assert t.state == State.DONE, (t.state, t.halt_reason)
        assert _roles(env, t.id, "planner") == 1 and t.human_touches == 1
        assert all(a["default"] for a in t.meta["clarify_answers"])

    run(go())


def test_non_default_answer_replans_with_answers_and_never_asks_again(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            t = await Runner(env.settings, st, env.agent).clarify(t.id, {"1": "a"}, "david")  # 代號不分大小寫
            assert t.state == State.PLAN
        finally:
            await st.close()
        t = (await (await env.ticks()).list_tasks())[0]
        assert t.state == State.DONE, (t.state, t.halt_reason, t.wait_reason)
        assert _roles(env, t.id, "planner") == 2
        second = [p for tid, role, p in env.agent.prompts if tid == t.id and role == "planner"][1]
        assert "只要整數" in second and "不要再提問" in second and "需求釐清（選填 questions）" not in second

    run(go())


def test_idle_user_gets_defaults_automatically(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            meta = dict(t.meta)
            meta["clarify"] = {**meta["clarify"], "asked_at": (utcnow() - timedelta(minutes=61)).isoformat()}
            await st.update_task(t.id, meta=meta)
            s = env.settings.model_copy(update={"clarify_idle_minutes": 60.0})
            summary = await Runner(s, st, env.agent).tick()
            assert summary["auto_clarified"] == [t.id]
            t = await st.get_task(t.id)
            # 同一輪 tick 採用預設後會繼續往下走（規格審查 → 守門）；不重新規劃、不算人工介入
            assert t.state not in (State.WAIT_HUMAN, State.PLAN, State.HALT), t.state
            assert t.human_touches == 0 and t.meta["clarify"]["auto"] is True
            assert _roles(env, t.id, "planner") == 1
        finally:
            await st.close()

    run(go())


def test_not_yet_idle_keeps_waiting(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            summary = await Runner(env.settings.model_copy(update={"clarify_idle_minutes": 60.0}), st,
                                   env.agent).tick()
            assert summary["auto_clarified"] == []
            assert (await st.get_task(t.id)).state == State.WAIT_HUMAN
        finally:
            await st.close()

    run(go())


def test_clarify_can_be_turned_off(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env, clarify_enabled=False)
        try:
            assert t.state == State.DONE and "clarify" not in t.meta
            assert "需求釐清" not in env.agent.prompts[0][2]
        finally:
            await st.close()

    run(go())


def test_untrusted_questions_are_cleaned() -> None:
    raw = [
        {"question": "整數選項", "options": 5, "default": "x"},                       # options 不是 list
        {"question": "字串選項", "options": "ab", "default": "a"},                     # 不能被拆成 a、b
        {"question": None, "options": ["a", "b"], "default": "a"},                     # 題目不是字串
        {"question": "換行\n### 假標題\n---", "options": ["甲\n- 假清單", "乙"], "default": "乙", "why": "x" * 999},
        {"question": "長選項", "options": ["好" * 500, "短"], "default": "短"},
        "不是 dict",
    ]
    out = Runner._clean_questions(raw)
    assert [q["question"] for q in out] == ["換行 ### 假標題 ---", "長選項"]
    assert "\n" not in out[0]["options"][0] and out[0]["options"][0] == "甲 - 假清單"
    assert len(out[0]["why"]) == 200 and len(out[1]["options"][0]) == 80


def test_no_questions_after_spec_review_sends_it_back(env: Env) -> None:
    env.idea("r", "規格會被退回一次", low_mock(spec_review=["revise", "pass"]))
    t = run(env.run_until())[0]
    assert t.state == State.DONE
    prompts_ = [p for tid, role, p in env.agent.prompts if tid == t.id and role == "planner"]
    assert len(prompts_) == 2
    assert "需求釐清（選填 questions）" in prompts_[0] and "需求釐清（選填 questions）" not in prompts_[1]


def test_resume_restarts_the_idle_clock(env: Env) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            r = Runner(env.settings.model_copy(update={"clarify_idle_minutes": 60.0}), st, env.agent)
            await r.cancel(t.id, "david", "先暫停")  # 進行中的任務第一次 cancel → 可續跑的 HALT
            meta = dict((await st.get_task(t.id)).meta)
            meta["clarify"] = {**meta["clarify"], "asked_at": (utcnow() - timedelta(minutes=600)).isoformat()}
            await st.update_task(t.id, meta=meta)
            t = await r.resume(t.id, "david")
            assert t.state == State.WAIT_HUMAN and t.wait_reason == CLARIFY_WAIT
            assert (await r.tick())["auto_clarified"] == []  # 計時重新起算：不會一續跑就自動採用預設
        finally:
            await st.close()

    run(go())


def test_cli_answer_parsing() -> None:
    from legion.cli import parse_clarify_args
    from legion.runner import UserError

    assert parse_clarify_args([], True) is None
    assert parse_clarify_args(["1=B", " 2 = 整數 "], False) == {"1": "B", "2": "整數"}
    for answers, defaults in ([], False), (["1=A"], True), (["1"], False), (["1=A", "1=B"], False), (["=A"], False):
        with pytest.raises(UserError):
            parse_clarify_args(answers, defaults)


@pytest.mark.parametrize("answers", [{"9": "A"}, {"1": "Z"}, {"1": "不存在的選項"}])
def test_bad_answers_are_rejected_and_state_unchanged(env: Env, answers: dict[str, str]) -> None:
    async def go() -> None:
        st, t = await _asked(env)
        try:
            with pytest.raises(ValueError):
                await Runner(env.settings, st, env.agent).clarify(t.id, answers, "david")
            t2 = await st.get_task(t.id)
            assert t2.state == State.WAIT_HUMAN and t2.wait_reason == CLARIFY_WAIT and t2.human_touches == 0
        finally:
            await st.close()

    run(go())
