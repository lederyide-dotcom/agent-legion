"""研究報告第 1 步：硬防線（不經 LLM 的程式檢查）。

1. 既有測試只能新增、不能刪除或削弱
2. 改動範圍允許清單（只能由人在想法檔設定）
3. 同一個驗收失敗反覆出現就停下，不等重試上限
4. 每次呼叫 agent 前都檢查 STOP
"""
from __future__ import annotations

import pytest
from conftest import CALC_OK, Env, State, low_mock, run

from legion.demo import TEST
from legion.models import Task
from legion.risk import collection_risks, failure_signature, out_of_scope, protected_test_violations
from legion.runner import Halt, Runner

WEAKENED = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"  # 刪掉 test_multiply
EXTENDED = TEST + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"


# ---- 純函式
def test_protected_test_violations_rules() -> None:
    ns = "M\ttest_calc.py\nD\ttests/test_old.py\nA\ttests/test_new.py\nM\tcalc.py\nM\ttests/test_more.py"
    numstat = "0\t3\ttest_calc.py\n0\t5\ttests/test_old.py\n9\t0\ttests/test_new.py\n1\t4\tcalc.py\n6\t0\ttests/test_more.py"
    bad = protected_test_violations(ns, numstat)
    assert len(bad) == 2
    assert any("test_calc.py" in b and "3 行" in b for b in bad)  # 改寫既有測試
    assert any("tests/test_old.py" in b and "刪除" in b for b in bad)  # 刪除既有測試檔
    # 新增測試檔、只新增行的修改、非測試檔的刪改都不算違規
    assert not any(s in " ".join(bad) for s in ("test_new.py", "test_more.py", "calc.py："))


def test_additions_that_weaken_existing_tests_are_caught() -> None:
    """審查指出的繞過：只「新增行」也能讓既有測試失效。"""
    base_src = {"tests/test_a.py": "def test_b():\n    assert f() == 1\n"}
    ns = "M\ttests/test_a.py"
    skip = protected_test_violations(ns, "2\t0\ttests/test_a.py",
                                     {"tests/test_a.py": "import pytest\n@pytest.mark.skip"}, base_src)
    assert any("跳過標記" in v for v in skip)
    redefine = protected_test_violations(ns, "3\t0\ttests/test_a.py",
                                         {"tests/test_a.py": "def test_b():\n    pass"}, base_src)
    assert any("重新定義" in v and "test_b" in v for v in redefine)
    # 新增不同名的測試案例仍然允許
    assert protected_test_violations(ns, "3\t0\ttests/test_a.py",
                                     {"tests/test_a.py": "def test_c():\n    assert f() == 1"}, base_src) == []
    # 無法逐行比對（-diff 屬性或二進位）、型別變更、中文檔名被加引號
    assert protected_test_violations(ns, "-\t-\ttests/test_a.py")
    assert protected_test_violations("T\ttests/test_a.py", "")
    assert protected_test_violations('D\t"tests/test_中文.py"', "")


def test_collection_risks_go_to_human_but_new_isolated_conftest_is_fine() -> None:
    base_files = ["calc.py", "test_calc.py"]
    assert collection_risks("A\tconftest.py", base_files, [])  # 根目錄 conftest 會作用到既有 test_calc.py
    assert collection_risks("M\tpyproject.toml", base_files, [])
    assert collection_risks("A\t.gitignore", base_files, [])
    assert collection_risks("", base_files, ["S tests/test_x.py"])  # skip-worktree 讓變更不出現在 diff
    # T-0017 的情況：新目錄 tests/ 裡新增 conftest，base 在該目錄下沒有測試 → 不影響既有測試
    assert collection_risks("A\ttests/conftest.py\nA\ttests/test_new.py", base_files, ["H calc.py"]) == []


def test_out_of_scope_globs() -> None:
    ns = "M\ttelegram_bot.py\nA\ttests/test_x.py\nA\tdocs/note.md\nM\tsub/a/b.py"
    assert out_of_scope(ns, ["telegram_bot.py", "tests/**"]) == ["docs/note.md", "sub/a/b.py"]
    assert out_of_scope(ns, ["sub/**", "*.py", "tests/**", "docs/*.md"]) == []
    assert out_of_scope(ns, []) == []  # 沒設定就不限制


def test_failure_signature_ignores_noise_but_not_different_failures() -> None:
    a = ["$ python -m pytest -q  (exit 1)\nFAILED test_calc.py::test_multiply - assert 0 == 20\n1 failed in 0.03s"]
    b = ["$ python -m pytest -q  (exit 1)\nFAILED test_calc.py::test_multiply - assert 0 == 20\n1 failed in 1.27s"]
    c = ["$ python -m pytest -q  (exit 1)\nFAILED test_calc.py::test_add - assert 4 == 5\n1 failed in 0.03s"]
    assert failure_signature(a) == failure_signature(b)
    assert failure_signature(a) != failure_signature(c)


# ---- 整合：runner 實際行為
def test_weakening_existing_test_fails_verify_then_recovers(env: Env) -> None:
    env.idea("w", "weaken test", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "test_calc.py": WEAKENED}},  # pytest 會過，但測試被削弱
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "test_calc.py": TEST}},
    ]))
    t = run(env.run_until())[0]
    assert t.state == State.DONE, t.halt_reason
    assert t.retries == 1
    first = t.meta["verify_runs"][0]
    guard = next(c for c in first["checks"] if "既有測試" in c["name"])
    assert not guard["ok"] and not first["ok"]
    assert all(c["exit"] == 0 for c in first["cmds"])  # 證明是硬防線擋下，不是測試本身失敗


def test_adding_cases_to_existing_test_is_allowed(env: Env) -> None:
    env.idea("a", "extend test", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "test_calc.py": EXTENDED}}]))
    t = run(env.run_until())[0]
    assert t.state == State.DONE and t.retries == 0, t.halt_reason


def test_human_can_allow_test_changes_in_idea_file(env: Env) -> None:
    env.idea("h", "allowed weaken", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "test_calc.py": WEAKENED}}]), allow_test_changes=True)
    t = run(env.run_until())[0]
    assert t.state == State.DONE and t.retries == 0, t.halt_reason


def test_change_outside_allowed_paths_waits_for_human(env: Env) -> None:
    env.idea("s", "scoped", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "extra.py": "X = 1\n"}}]),
        allowed_paths=["calc.py", "test_*.py"])
    t = run(env.run_until())[0]
    assert t.state == State.WAIT_HUMAN
    assert any("超出允許範圍" in r and "extra.py" in r for r in t.risk_reasons)


def test_same_failure_three_times_halts_before_retry_limit(env: Env) -> None:
    # 每次都宣稱完成但沒改程式：同一個測試以同樣方式失敗
    env.idea("e", "spinning", low_mock(exec=[{"claim": "passed", "write_files": {}}]))
    t = run(env.run_until())[0]
    assert t.state == State.HALT and (t.halt_reason or "").startswith("same_error_x3"), t.halt_reason
    assert t.retries == 2  # 第 3 次相同失敗就停，沒有用完重試上限 3
    assert len({r["sig"] for r in t.meta["failure_sigs"]}) == 1


SKIPPED = TEST.replace("def test_multiply", "import pytest\n\n\n@pytest.mark.skip\ndef test_multiply")
EMPTYING_CONFTEST = "def pytest_collection_modifyitems(items):\n    items.clear()\n"


def test_skip_marker_on_existing_test_fails_verify(env: Env) -> None:
    env.idea("k", "skip it", low_mock(exec=[
        {"claim": "passed", "write_files": {"test_calc.py": SKIPPED}},  # 不修 calc，直接跳過失敗的測試
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "test_calc.py": TEST}},
    ]))
    t = run(env.run_until())[0]
    assert t.state == State.DONE and t.retries == 1, t.halt_reason
    guard = next(c for c in t.meta["verify_runs"][0]["checks"] if "既有測試" in c["name"])
    assert not guard["ok"]


def test_conftest_that_empties_collection_waits_for_human(env: Env) -> None:
    env.idea("c", "empty collection", low_mock(exec=[
        {"claim": "passed", "write_files": {"conftest.py": EMPTYING_CONFTEST}}]))
    t = run(env.run_until())[0]
    assert t.state == State.WAIT_HUMAN
    assert any("conftest.py 會作用到既有測試" in r for r in t.risk_reasons)


def test_approval_is_bound_to_diff_content_and_discloses_test_weakening(env: Env) -> None:
    """審查指出：簽章只雜湊檔名時，核准後可繼續削弱測試。改為內容層級後，內容一變就要重新核准。"""
    wrong = "def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return 0\n"
    env.idea("p", "approve then weaken", low_mock(exec=[
        {"claim": "passed", "write_files": {"calc.py": wrong, "extra.py": "X = 1\n"}},
        {"claim": "passed", "write_files": {"calc.py": CALC_OK, "extra.py": "X = 1\n", "test_calc.py": WEAKENED}},
    ]), allowed_paths=["calc.py", "test_*.py"])

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN  # 第一次：extra.py 超出範圍
            runner = Runner(env.settings, st, env.agent)
            await runner.answer(t.id, True, "approver")
            for _ in range(10):
                await runner.tick()
                t = await st.get_task(t.id)
                if t.state == State.WAIT_HUMAN:
                    break
            # 核准後測試失敗退回；第二次執行削弱了測試 → 內容變了，需要重新核准，且問題中揭露削弱
            assert t.state == State.WAIT_HUMAN, t.state
            assert any("注意" in r and "test_calc.py" in r for r in t.risk_reasons)
        finally:
            await st.close()

    run(go())


def test_resume_after_same_error_gives_a_fresh_count(env: Env) -> None:
    env.idea("e", "spinning", low_mock(exec=[{"claim": "passed", "write_files": {}}]))

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert (t.halt_reason or "").startswith("same_error_x3")
            runner = Runner(env.settings, st, env.agent)
            await runner.resume(t.id, "approver")
            await runner.tick()  # 重新驗收：失敗一次，計數從 1 開始，不會立刻再停
            t = await st.get_task(t.id)
            assert t.state == State.EXEC, (t.state, t.halt_reason)
            assert len(t.meta["failure_sigs"]) == 1 and len(t.meta["failure_sigs_archived"]) == 3
        finally:
            await st.close()

    run(go())


def test_stop_file_is_checked_before_every_agent_call(env: Env) -> None:
    async def go() -> None:
        st = await env.store()
        try:
            runner = Runner(env.settings, st, env.agent)
            env.settings.stop_file.write_text("stop", encoding="utf-8")
            task = Task(id="T-STOP", title="t", kind="readonly")
            with pytest.raises(Halt) as exc:
                await runner._agent(task, "planner", "prompt", env.settings.ai_dir)
            assert exc.value.reason == "stop_file"
            assert env.agent.calls == []  # agent 完全沒有被呼叫
        finally:
            await st.close()

    run(go())
