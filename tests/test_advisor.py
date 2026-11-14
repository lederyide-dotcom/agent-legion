"""軍師：任務因同一錯誤或重試上限要停下時，請示軍師提出至少 3 個錦囊，交人決定；人閒置則由指揮官＋軍師決議。"""
from __future__ import annotations

from datetime import timedelta

from conftest import CALC_OK, Env, State, low_mock, run

from legion.db import utcnow
from legion.runner import Runner

# 第一次執行沒改程式（同一錯誤反覆出現 → same_error），採用錦囊後第二輪才正確
SPIN_THEN_FIX = low_mock(exec=[{"claim": "passed", "write_files": {}}, {"claim": "passed", "write_files": {}},
                               {"claim": "passed", "write_files": {}},
                               {"claim": "passed", "write_files": {"calc.py": CALC_OK}}])


def _on(env: Env, **kw: object):  # type: ignore[no-untyped-def]
    return env.settings.model_copy(update={"advisor_enabled": True, **kw})


def test_stuck_task_consults_advisor_instead_of_halting(env: Env) -> None:
    env.idea("a", "stuck", SPIN_THEN_FIX)

    async def go() -> None:
        st = await env.ticks(settings=_on(env, advisor_idle_minutes=60))
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN and "軍師錦囊" in (t.wait_reason or ""), (t.state, t.halt_reason)
            adv = t.meta["advisor"]
            assert len(adv["options"]) >= 3 and adv["recommended"] == "A"
            assert adv["reason"].startswith("same_error_x3")
            q = (env.settings.ai_dir / "questions" / f"{t.id}.md").read_text(encoding="utf-8")
            assert "⭐ A." in q and "legion choose" in q and "60 分鐘內沒有決定" in q
            used = [(role, m, e) for tid, role, m, e in env.agent.models if tid == t.id and role == "advisor"]
            assert used == [("advisor", "opus", "high")]
        finally:
            await st.close()

    run(go())


def test_human_choice_applies_option_and_task_finishes(env: Env) -> None:
    env.idea("h", "stuck", SPIN_THEN_FIX)
    s = _on(env, advisor_idle_minutes=60)

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            runner = Runner(s, st, env.agent)
            t = await runner.choose(t.id, "A", "approver")
            assert t.state == State.EXEC and t.human_touches == 1 and t.retries == 0
            assert t.meta.get("advisor_guidance")
            for _ in range(20):
                await runner.tick()
            t = await st.get_task(t.id)
            assert t.state == State.DONE, (t.state, t.halt_reason)
            # 指引會帶進執行者的提示
            exec_prompts = [p for tid, role, p in env.agent.prompts if tid == t.id and role == "executor"]
            assert "軍師的錦囊" in exec_prompts[-1]
        finally:
            await st.close()

    run(go())


def test_idle_human_lets_commander_and_advisor_decide(env: Env) -> None:
    env.idea("i", "stuck", SPIN_THEN_FIX)
    s = _on(env, advisor_idle_minutes=0)  # 測試中把閒置門檻設為 0：下一輪 tick 就自動決議

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.DONE, (t.state, t.halt_reason, t.wait_reason)
            assert t.human_touches == 0  # 自動決議不計人工介入
            hist = t.meta["advisor_history"]
            assert hist[0]["auto"] is True and hist[0]["decision"] == "A"
            assert any("自動決議" in str(e.detail.get("message", "")) for e in await st.all_events("advisor_decision"))
        finally:
            await st.close()

    run(go())


def test_auto_decision_waits_before_idle_time(env: Env) -> None:
    env.idea("w", "stuck", SPIN_THEN_FIX)
    s = _on(env, advisor_idle_minutes=15)

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            runner = Runner(s, st, env.agent)
            await runner.tick()
            assert (await st.get_task(t.id)).state == State.WAIT_HUMAN  # 未滿 15 分鐘，不動
            meta = dict(t.meta)  # 把請示時間往前推 16 分鐘，模擬人閒置
            meta["advisor"] = {**meta["advisor"], "asked_at": (utcnow() - timedelta(minutes=16)).isoformat()}
            await st.update_task(t.id, meta=meta)
            summary = await runner.tick()
            assert summary["auto_decided"] == [t.id]
        finally:
            await st.close()

    run(go())


def test_auto_decision_never_picks_unsafe_options(env: Env) -> None:
    only_unsafe = {"diagnosis": "需要人", "recommended": "A", "options": [
        {"id": "A", "kind": "needs_human", "title": "提高預算", "plan": "x", "est_cost_usd": 0, "risk": "low",
         "rationale": "r"},
        {"id": "B", "kind": "retry_with_guidance", "title": "高風險重做", "plan": "x", "est_cost_usd": 0.1,
         "risk": "high", "rationale": "r"},
        {"id": "C", "kind": "revise_spec", "title": "太貴", "plan": "x", "est_cost_usd": 99, "risk": "low",
         "rationale": "r"}]}
    env.idea("u", "stuck", {**SPIN_THEN_FIX, "advice": [only_unsafe]})
    s = _on(env, advisor_idle_minutes=0)

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN  # 沒有安全、非 high 風險、預算內的錦囊 → 繼續等人
            assert await st.all_events("advisor_auto_skipped")
        finally:
            await st.close()

    run(go())


def test_bad_advice_or_consult_limit_falls_back_to_halt(env: Env) -> None:
    two_only = {"diagnosis": "d", "recommended": "A", "options": [
        {"id": "A", "kind": "abandon", "title": "放棄", "plan": "x", "est_cost_usd": 0, "risk": "low", "rationale": "r"},
        {"id": "B", "kind": "abandon", "title": "放棄2", "plan": "x", "est_cost_usd": 0, "risk": "low",
         "rationale": "r"}]}
    env.idea("b", "stuck", {**SPIN_THEN_FIX, "advice": [two_only]})

    async def go() -> None:
        st = await env.ticks(settings=_on(env))
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.HALT and t.halt_reason.startswith("same_error_x3")  # 錦囊不足 3 個 → 照原本停下
            assert await st.all_events("advisor_failed")
        finally:
            await st.close()

    run(go())


def test_consults_are_capped_per_task(env: Env) -> None:
    # 每次採用錦囊後仍然失敗：最多請示 2 次，第 3 次直接停下，不會無限循環
    env.idea("c", "never fixes", low_mock(exec=[{"claim": "passed", "write_files": {}}]))

    async def go() -> None:
        st = await env.ticks(n=80, settings=_on(env, advisor_idle_minutes=0))
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.HALT and t.meta["advisor_consults"] == 2
            assert len(t.meta["advisor_history"]) == 2
            assert (t.halt_reason or "").startswith("same_error_x3")  # 第 3 次不再請示，照熔斷停下
        finally:
            await st.close()

    run(go())


# ---- 審查後補強（🔴1：不得跳過 GATE；🔴2：舊錦囊不得搶別的等待）
def _transitions(events: list) -> list[str]:  # type: ignore[type-arg]
    return [f"{e.from_state}->{e.to_state}" for e in events if e.kind == "transition"]


def test_stuck_in_spec_review_never_jumps_to_exec(env: Env) -> None:
    # 規格審查一直退回 → 重試上限 → 軍師推薦「依指引重做」：必須改走規劃，不得直接執行
    env.idea("s", "spec stuck", low_mock(spec_review=["revise"]))

    async def go() -> None:
        st = await env.ticks(n=60, settings=_on(env, advisor_idle_minutes=0))
        try:
            t = (await st.list_tasks())[0]
            assert all("EXEC" not in tr for tr in _transitions(await st.events(t.id))), _transitions(await st.events(t.id))
            assert t.meta["advisor_history"][0]["applied_kind"] == "revise_spec"
        finally:
            await st.close()

    run(go())


def test_high_risk_task_is_never_auto_decided(env: Env) -> None:
    env.idea("h", "high stuck", low_mock(risk_proposed="high", spec_review=["revise"]))

    async def go() -> None:
        st = await env.ticks(n=60, settings=_on(env, advisor_idle_minutes=0))
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN and t.risk == "high"
            assert await st.all_events("advisor_auto_skipped")
            assert not await st.all_events("advisor_decision")
        finally:
            await st.close()

    run(go())


def test_stale_advice_does_not_hijack_other_waits(env: Env) -> None:
    # 任務因 diff 高風險（刪檔）在等核准；即使 meta 殘留未決的舊錦囊，也不得被自動決議或被 approve 導去採用
    env.idea("d", "deletes", low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_OK},
                                             "delete_files": [".gitignore"]}]))
    s = _on(env, advisor_idle_minutes=0)

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN and "high" in (t.wait_reason or "")
            stale = {"reason": "same_error_x3", "options": [
                {"id": x, "kind": "abandon", "title": "放棄", "plan": "", "est_cost_usd": 0.0, "risk": "low",
                 "rationale": ""} for x in "ABC"], "recommended": "A", "decided": False,
                "asked_at": (utcnow() - timedelta(hours=1)).isoformat(), "return_state": "VERIFY"}
            await st.update_task(t.id, meta={**t.meta, "advisor": stale})
            runner = Runner(s, st, env.agent)
            summary = await runner.tick()
            assert summary["auto_decided"] == [] and (await st.get_task(t.id)).state == State.WAIT_HUMAN
            t2 = await runner.answer(t.id, True, "approver")  # 核准的是 diff，不是錦囊
            assert t2.state == State.VERIFY and not await st.all_events("advisor_decision")
        finally:
            await st.close()

    run(go())


def test_reject_voids_advice_so_resume_is_not_auto_decided(env: Env) -> None:
    env.idea("r", "stuck", SPIN_THEN_FIX)
    s = _on(env, advisor_idle_minutes=60)

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            runner = Runner(s.model_copy(update={"advisor_idle_minutes": 0}), st, env.agent)
            t = await runner.answer(t.id, False, "approver", "不要")
            assert t.state == State.HALT and t.meta["advisor"]["void"] is True
            await runner.resume(t.id, "approver")
            summary = await runner.tick()
            assert summary["auto_decided"] == []
            assert not await st.all_events("advisor_decision")
        finally:
            await st.close()

    run(go())


def test_abandon_then_resume_returns_to_where_it_was(env: Env) -> None:
    abandon_first = {"diagnosis": "d", "recommended": "A", "options": [
        {"id": "A", "kind": "abandon", "title": "放棄", "plan": "x", "est_cost_usd": 0, "risk": "low", "rationale": "r"},
        {"id": "B", "kind": "revise_spec", "title": "重寫", "plan": "x", "est_cost_usd": 0.1, "risk": "low",
         "rationale": "r"},
        {"id": "C", "kind": "needs_human", "title": "人", "plan": "x", "est_cost_usd": 0, "risk": "low",
         "rationale": "r"}]}
    env.idea("x", "stuck", {**SPIN_THEN_FIX, "advice": [abandon_first]})
    s = _on(env, advisor_idle_minutes=60)

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            runner = Runner(s, st, env.agent)
            t = await runner.choose(t.id, "A", "approver")
            assert t.state == State.HALT and (t.halt_reason or "").startswith("advisor_abandon")
            t = await runner.resume(t.id, "approver")
            assert t.state == State.VERIFY  # 回到卡住的地方，而不是卡在 WAIT_HUMAN
        finally:
            await st.close()

    run(go())


def test_untrusted_advice_fields_are_sanitized(env: Env) -> None:
    from legion.runner import Runner as R

    bad = R._clean_option({"id": "A", "kind": "retry_with_guidance", "title": "t", "plan": "p",
                           "est_cost_usd": "約0.1", "rationale": "r"})
    assert bad is not None and bad["kind"] == "needs_human" and bad["risk"] == "high"  # 花費不明、風險缺漏
    neg = R._clean_option({"id": "B", "kind": "drop_tests", "title": "t", "plan": "p", "est_cost_usd": -5,
                           "risk": "low", "rationale": "r"})
    assert neg is not None and neg["kind"] == "needs_human"  # 未知種類、負花費 → 不可自動採用


def test_replan_that_drops_failing_acceptance_cmds_needs_human(env: Env) -> None:
    # 依錦囊重新規劃時，新規格拿掉了原本失敗的驗收指令（換成較寬鬆的 git status）→ 判 high，在 GATE 停下等人
    env.idea("p", "loosen", low_mock(accept_cmds=["git status --porcelain"]))

    async def go() -> None:
        st = await env.store()
        try:
            runner = Runner(env.settings, st, env.agent)
            await runner.tick()  # 領取並進入 PLAN
            t = (await st.list_tasks())[0]
            await st.update_task(t.id, meta={**t.meta, "advisor_required_cmds": ["python -m pytest -q"]})
            for _ in range(5):
                await runner.tick()
            t = await st.get_task(t.id)
            assert t.state == State.WAIT_HUMAN and t.risk == "high"
            assert any("拿掉了原本的驗收指令" in r for r in t.risk_reasons)
        finally:
            await st.close()

    run(go())
