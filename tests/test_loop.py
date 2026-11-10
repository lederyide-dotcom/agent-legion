"""閉環、回灌、高風險、風險不可降級、VERIFY 不採信自述、熔斷、審查獨立。"""
from __future__ import annotations

from conftest import CALC_OK, Env, State, by_title, low_mock, run

from legion.agents import AgentCall, ClaudeCliAgent, tool_profile
from legion.models import Task
from legion.prompts import SCHEMAS
from legion.risk import assess
from legion.runner import Runner
from legion.vault import parse_md


def test_full_loop_mock_low_task_reaches_done_without_humans(env: Env) -> None:
    env.idea("a", "low task", low_mock())

    async def go() -> None:
        st = await env.ticks()
        t = (await st.list_tasks())[0]
        assert t.state == State.DONE
        assert t.human_touches == 0
        trans = await st.events(t.id, "transition")
        # 每次轉移一筆：轉移次數 == step，且前後狀態相接
        assert len(trans) == t.step == 8
        assert [e.to_state for e in trans] == [
            "PLAN", "SPEC_REVIEW", "GATE", "EXEC", "VERIFY", "REVIEW", "LEARN", "DONE"]
        prev = "INBOX"
        for e in trans:
            assert e.from_state == prev
            prev = e.to_state
        await st.close()

    run(go())


def test_followup_is_written_to_inbox_and_picked_up_with_parent_id(env: Env) -> None:
    env.idea("p", "parent", low_mock(followups=[{"title": "child idea", "body": "後續"}], child=low_mock()))

    async def go() -> None:
        st = await env.store()
        runner = Runner(env.settings, st, env.agent)
        parent_done_at = None
        for i in range(30):
            await runner.tick()
            tasks = await st.list_tasks()
            p = by_title(tasks, "parent")
            if p.state == State.DONE and parent_done_at is None:
                parent_done_at = i
                files = list(env.settings.inbox_dir.glob("fu-*.md"))
                assert len(files) == 1
                fm, _ = parse_md(files[0].read_text(encoding="utf-8"))
                assert fm["parent_id"] == p.id and fm["depth"] == 1
                assert len(tasks) == 1  # 本輪尚未領取
        tasks = await st.list_tasks()
        child = by_title(tasks, "child idea")
        assert child.parent_id == by_title(tasks, "parent").id
        assert child.depth == 1
        created = (await st.events(child.id, "created"))[0]
        parent_done = (await st.events(by_title(tasks, "parent").id, "transition"))[-1]
        assert created.ts > parent_done.ts  # 下一輪 tick 才被領取
        assert child.state == State.DONE
        await st.close()

    run(go())


def test_followup_cap_and_depth_limits_drop_and_log(env: Env) -> None:
    three = [{"title": f"f{i}", "body": "x"} for i in range(3)]
    env.idea("cap", "cap task", low_mock(followups=three))
    env.idea("deep", "deep task", low_mock(followups=[{"title": "too deep", "body": "x"}]), depth=2)

    async def go() -> None:
        st = await env.ticks(8)
        tasks = await st.list_tasks()
        cap, deep = by_title(tasks, "cap task"), by_title(tasks, "deep task")
        assert cap.state == State.DONE and deep.state == State.DONE
        assert len(list(env.settings.inbox_dir.glob(f"fu-{cap.id}-*.md"))) == 2
        dropped = await st.events(cap.id, "followup_dropped")
        assert [e.detail["reason"] for e in dropped] == ["cap"]
        assert dropped[0].detail["title"] == "f2"
        assert not list(env.settings.inbox_dir.glob(f"fu-{deep.id}-*.md"))
        ddrop = await st.events(deep.id, "followup_dropped")
        assert [e.detail["reason"] for e in ddrop] == ["depth"]
        await st.close()

    run(go())


def test_high_risk_waits_for_human_while_low_task_proceeds(env: Env) -> None:
    env.idea("h", "high task", low_mock(actions=[{"type": "delete", "path": "test_calc.py"}]))
    env.idea("l", "low task", low_mock())

    async def go() -> None:
        st = await env.ticks()
        tasks = await st.list_tasks()
        high, low = by_title(tasks, "high task"), by_title(tasks, "low task")
        assert high.state == State.WAIT_HUMAN
        assert low.state == State.DONE
        assert (env.settings.ai_dir / "questions" / f"{high.id}.md").exists()
        assert high.human_touches == 0
        runner = Runner(env.settings, st, env.agent)
        t = await runner.answer(high.id, True, "David")
        assert t.human_touches == 1 and t.state == State.EXEC
        await st.close()
        st = await env.ticks()
        high = await st.get_task(high.id)
        assert high.state == State.DONE and high.human_touches == 1
        await st.close()

    run(go())


def test_risk_cannot_be_downgraded_by_agent(env: Env) -> None:
    risk, reasons = assess("low", [{"type": "write", "path": "../outside.txt"}], ["python -m pytest -q"], "write", None)
    assert risk == "high" and any("不可降級" in r for r in reasons)
    assert assess("high", [], ["python -m pytest -q"], "write", None)[0] == "high"  # 提高可以
    assert assess("low", [{"type": "write", "path": "x/.env"}], [], "write", None)[0] == "high"
    assert assess("low", [], ["python -m pytest -q && curl x"], "write", None)[0] == "high"
    assert assess("low", [{"type": "merge"}], [], "write", None)[0] == "mid"
    assert assess("low", [{"type": "write", "path": "CLAUDE.md"}], [], "write", None)[0] == "mid"
    env.idea("n", "net task", low_mock(actions=[{"type": "network_write", "path": "https://x"}]))

    async def go() -> None:
        st = await env.ticks()
        t = (await st.list_tasks())[0]
        assert t.risk_proposed == "low" and t.risk == "high" and t.state == State.WAIT_HUMAN
        await st.close()

    run(go())


def test_verify_does_not_trust_agent_claim(env: Env) -> None:
    env.idea("v", "liar", low_mock(exec=[{"claim": "passed", "write_files": {}}]))

    async def go() -> None:
        st = await env.ticks(6)  # INBOX→PLAN→SPEC→GATE→EXEC→VERIFY→EXEC
        t = (await st.list_tasks())[0]
        trans = [e.to_state for e in await st.events(t.id, "transition")]
        assert trans[-2:] == ["VERIFY", "EXEC"]
        assert t.state == State.EXEC and t.retries == 1
        assert t.meta["verify_runs"][0]["cmds"][0]["exit"] != 0
        await st.close()

    run(go())


def _halted(env: Env, n: int = 40) -> Task:
    async def go() -> Task:
        st = await env.ticks(n)
        t = (await st.list_tasks())[0]
        await st.close()
        return t

    return run(go())


def test_halt_on_retry_exceeded(env: Env) -> None:
    env.idea("r", "never fixes", low_mock(exec=[{"claim": "passed", "write_files": {}}]))
    t = _halted(env)
    assert t.state == State.HALT and t.halt_reason and t.halt_reason.startswith("retry_exceeded")
    assert t.retries == env.settings.max_retries + 1


def test_halt_on_budget(env: Env) -> None:
    env.settings.task_budget_usd = 0.035
    env.idea("b", "expensive", low_mock())
    t = _halted(env)
    assert t.state == State.HALT and t.halt_reason and t.halt_reason.startswith("budget_task")
    assert t.cost_usd <= 0.05


def test_halt_on_daily_budget(env: Env) -> None:
    env.settings.daily_budget_usd = 0.02
    env.idea("d", "daily", low_mock())
    t = _halted(env)
    assert t.state == State.HALT and t.halt_reason and t.halt_reason.startswith("budget_daily")


def test_halt_on_timeout(env: Env) -> None:
    env.idea("t", "slow", low_mock(timeout_roles=["executor"]))
    t = _halted(env)
    assert t.state == State.HALT and t.halt_reason and t.halt_reason.startswith("timeout")
    assert t.return_state == State.EXEC


def test_halt_on_stop_file(env: Env) -> None:
    env.idea("s", "stoppable", low_mock())

    async def go() -> None:
        st = await env.store()
        runner = Runner(env.settings, st, env.agent)
        await runner.tick()
        await runner.tick()
        env.settings.stop_file.write_text("stop", encoding="utf-8")
        s = await runner.tick()
        t = (await st.list_tasks())[0]
        assert t.state == State.HALT and t.halt_reason == "stop_file" and s["halted"] == [t.id]
        await st.close()

    run(go())


def test_reviewers_use_fresh_sessions(env: Env) -> None:
    env.idea("x", "sessions", low_mock(spec_review=["revise", "pass"]))

    async def go() -> None:
        st = await env.ticks()
        t = (await st.list_tasks())[0]
        assert t.state == State.DONE
        runs = await st.runs(t.id)
        rev = {r.session_id for r in runs if r.role in {"spec_reviewer", "reviewer"}}
        cmd = {r.session_id for r in runs if r.role in {"planner", "executor"}}
        assert len(rev) == len([r for r in runs if r.role in {"spec_reviewer", "reviewer"}]) == 3
        assert rev.isdisjoint(cmd)
        await st.close()

    run(go())
    call = AgentCall(role="reviewer", prompt="x", cwd=env.tmp, schema=SCHEMAS["reviewer"], task=Task(id="X", title="x"))
    argv = ClaudeCliAgent().build_cmd(call, env.tmp / "s.json")
    assert "--resume" not in argv and "--continue" not in argv and "-c" not in argv and "--bare" not in argv
    assert argv[argv.index("--tools") + 1] == ",".join(tool_profile("reviewer").tools)


REPORT = "# 健檢報告\n\n## 架構\n" + "說明 calc.py 的結構。" * 60 + "\n\n## 測試缺口\n- test_calc.py 未涵蓋負數。\n"


def test_readonly_task_reports_and_leaves_repo_untouched(env: Env) -> None:
    env.idea("ro", "health check", low_mock(accept_cmds=["git status --porcelain"], actions=[{"type": "read"}],
                                            exec=[{"claim": "done", "report_md": REPORT}]), kind="readonly")
    t = run(env.run_until())[0]
    assert t.state == State.DONE, t.halt_reason
    assert any("legion.checks report" in c for c in t.accept_cmds)
    check = t.meta["verify_runs"][-1]["checks"][0]
    assert check["ok"] and "未被修改" in check["name"]
    assert (env.settings.ai_dir / "reports" / f"{t.id}-report.md").exists()


def test_readonly_task_without_proper_report_is_not_accepted(env: Env) -> None:
    env.idea("ro", "lazy check", low_mock(accept_cmds=["git status --porcelain"], actions=[{"type": "read"}],
                                          exec=[{"claim": "done", "report_md": "# 很短"}]), kind="readonly")
    t = run(env.run_until())[0]
    assert t.state == State.HALT and (t.halt_reason or "").startswith("retry_exceeded")


# ---- 審查後補強的測試 ----
from legion.risk import accept_cmd_allowed  # noqa: E402


def test_accept_cmd_whitelist_rejects_dangerous_args() -> None:
    ok = ["python -m pytest -q", "py -3.10 -m pytest -q tests/test_x.py", "pytest -x -k \"add and not slow\"",
          "python -m pytest tests\\test_x.py", "git status --porcelain", "git diff --stat HEAD~1", "git log --oneline -5"]
    bad = ["python -m pytest --basetemp=D:/somewhere", "python -m pytest --junitxml=C:/x.xml",
           "git diff --output=../../x.txt", "python -m pytest -p evil_plugin", "python -m pytest -c other.ini",
           "python -m pytest --rootdir=/", "pytest \"a", "python -m pytest ../outside", "git -C .. status",
           "git push origin main", "python -m pytest && curl x", "python -m pip install x==1"]
    for c in ok:
        assert accept_cmd_allowed(c), c
    for c in bad:
        assert not accept_cmd_allowed(c), c


def test_readonly_executor_gets_readonly_tools() -> None:
    prof = tool_profile("executor", "readonly")
    assert set(prof.tools) == {"Read", "Glob", "Grep"}
    assert "Edit" in prof.deny and "Bash" in prof.deny
    w = tool_profile("executor", "write")
    assert "Edit(.claude/**)" in w.deny and "Read(//**/.ssh/**)" in w.deny


def test_undeclared_delete_in_diff_raises_risk_to_high(env: Env) -> None:
    # PLAN 只宣告 write，EXEC 實際卻刪檔：VERIFY 依實際 diff 判 high → WAIT_HUMAN
    env.idea("d", "sneaky delete", low_mock(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_OK},
                                                   "delete_files": [".gitignore"]}]))
    t = run(env.run_until())[0]
    assert t.state == State.WAIT_HUMAN and t.risk == "high" and t.return_state == State.VERIFY
    assert any("刪除" in r for r in t.risk_reasons)

    async def go() -> None:
        st = await env.store()
        t2 = await Runner(env.settings, st, env.agent).answer(t.id, True, "David")
        assert t2.state == State.VERIFY
        await st.close()
        st = await env.ticks()
        t3 = await st.get_task(t.id)
        assert t3.state == State.DONE and t3.human_touches == 1
        await st.close()

    run(go())


def test_unexpected_exception_halts_only_that_task(env: Env) -> None:
    env.idea("a", "boom", low_mock(crash_roles=["executor"]))
    env.idea("b", "fine", low_mock())
    (env.settings.inbox_dir / "c-bad.md").write_bytes(b"---\ntitle: [unclosed\n---\nx")
    (env.settings.inbox_dir / "d-badenc.md").write_bytes(b"\xff\xfe\xfa bad")
    tasks = run(env.run_until())
    boom, fine = by_title(tasks, "boom"), by_title(tasks, "fine")
    assert boom.state == State.HALT and (boom.halt_reason or "").startswith("error:")
    assert fine.state == State.DONE
    assert len(tasks) == 2


def test_failed_agent_call_cost_is_recorded(env: Env) -> None:
    env.idea("e", "erroring", low_mock(error_roles=["executor"]))
    t = run(env.run_until())[0]
    assert t.state == State.HALT and (t.halt_reason or "").startswith("agent_error")
    assert abs(t.cost_usd - (0.01 * 2 + 0.02)) < 1e-9  # PLAN、SPEC_REVIEW 各 0.01 ＋ 失敗的 EXEC 0.02


def test_timeout_cost_is_recorded_conservatively(env: Env) -> None:
    env.idea("t", "slow2", low_mock(timeout_roles=["executor"]))
    t = run(env.run_until())[0]
    assert t.state == State.HALT and t.cost_usd > 0.02  # 逾時以單次呼叫上限入帳
