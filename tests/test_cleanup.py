"""legion cleanup：預設只列不刪；--apply 只刪已併入 HEAD 且 worktree 乾淨的分支與 worktree。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import Env, State, low_mock, run

from legion.cleanup import run_cleanup
from legion.db import Store
from legion.models import Task


def _commit(wt: str, msg: str) -> None:
    # 訊息要不同：兩個 mock 任務改出一樣的內容，同一秒提交會得到同一個 commit
    subprocess.run(["git", "-C", wt, "add", "-A"], check=True)
    subprocess.run(["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", msg],
                   check=True)


def _branch_exists(repo: Path, branch: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                          capture_output=True, check=False).returncode == 0


def test_cleanup_dry_run_then_apply_only_merged_clean(env: Env) -> None:
    env.idea("a", "加 multiply", low_mock())
    env.idea("c", "另一個完成但沒合併", low_mock())
    env.idea("b", "刪測試", low_mock(actions=[{"type": "delete", "path": "test_calc.py"}]))  # high → 等人

    async def go() -> None:
        st = await env.ticks()
        try:
            tasks = {t.title: t for t in await st.list_tasks()}
            a, c, b = tasks["加 multiply"], tasks["另一個完成但沒合併"], tasks["刪測試"]
            assert a.state == c.state == State.DONE and b.state == State.WAIT_HUMAN
            orphan = env.settings.worktrees_dir / "X-9999"
            orphan.mkdir(parents=True)

            # 1. mock 執行者沒 commit：worktree 有變更 → 全部保留
            p = await run_cleanup(env.settings, st)
            assert p["remove"] == [] and p["applied"] is False
            reasons = {r["id"]: r["reason"] for r in p["keep"]}
            assert "未提交" in reasons[a.id] and "未提交" in reasons[c.id]
            assert b.id not in {r["id"] for r in p["remove"]}
            assert [o["path"] for o in p["orphans"]] == [str(orphan)]

            # 2. 兩個都提交，只有 a 併入 HEAD → 只列 a；dry-run 不動任何東西
            _commit(a.worktree or "", "a")
            _commit(c.worktree or "", "c")
            subprocess.run(["git", "-C", str(env.repo), "merge", "-q", "--ff-only", f"legion/{a.id}"], check=True)
            p = await run_cleanup(env.settings, st)
            assert [r["id"] for r in p["remove"]] == [a.id]
            assert "還沒併入" in {r["id"]: r["reason"] for r in p["keep"]}[c.id]
            assert Path(a.worktree or "").exists() and _branch_exists(env.repo, f"legion/{a.id}")

            # 3. --apply：只刪 a；c、b、孤兒資料夾都還在；留下 cleanup 事件
            p = await run_cleanup(env.settings, st, apply=True)
            assert p["results"] == [{"id": a.id, "worktree_removed": True, "branch_deleted": True, "errors": []}]
            assert not Path(a.worktree or "").exists() and not _branch_exists(env.repo, f"legion/{a.id}")
            assert Path(c.worktree or "").exists() and _branch_exists(env.repo, f"legion/{c.id}")
            assert orphan.exists()
            assert [e.kind for e in await st.events(a.id, "cleanup")] == ["cleanup"]

            # 4. 再跑一次：a 已乾淨，不再出現
            p = await run_cleanup(env.settings, st)
            assert a.id not in {r["id"] for r in p["remove"] + p["keep"]}
        finally:
            await st.close()

    run(go())


def _g(cwd: str | Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


async def _merged_done(env: Env) -> tuple[Store, Task]:
    """一個已完成、已提交、已 ff 併入目標 repo 的任務：正常情況下應該可以清。"""
    env.idea("a", "加 multiply", low_mock())
    st = await env.ticks()
    t = (await st.list_tasks())[0]
    assert t.state == State.DONE and t.worktree
    _commit(t.worktree, "a")
    _g(env.repo, "merge", "-q", "--ff-only", f"legion/{t.id}")
    p = await run_cleanup(env.settings, st)
    assert [r["id"] for r in p["remove"]] == [t.id]  # 對照組：沒動手腳時可清
    return st, t


def _kept_reason(p: dict[str, Any], tid: str) -> str:
    assert tid not in {r["id"] for r in p["remove"]}
    return {r["id"]: r["reason"] for r in p["keep"]}[tid]


def _setup_detached_worktree_commit(env: Env, t: Task) -> None:
    # 在 worktree 游離 HEAD 上 commit：分支還停在已併入的地方，但有不在任何分支上的 commit
    _g(t.worktree or "", "checkout", "-q", "--detach")
    (Path(t.worktree or "") / "extra.py").write_text("x = 1\n", encoding="utf-8")
    _commit(t.worktree or "", "detached")


def _setup_branch_deleted(env: Env, t: Task) -> None:
    _g(t.worktree or "", "checkout", "-q", "--detach")
    _g(env.repo, "branch", "-D", f"legion/{t.id}")


def _setup_repo_detached(env: Env, t: Task) -> None:
    _g(env.repo, "checkout", "-q", "--detach")


def _setup_ignored_file(env: Env, t: Task) -> None:
    common = Path(_g(t.worktree or "", "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    (common / "info").mkdir(exist_ok=True)
    (common / "info" / "exclude").write_text("out/\n__pycache__/\n", encoding="utf-8")
    (Path(t.worktree or "") / "out").mkdir()
    (Path(t.worktree or "") / "out" / "result.csv").write_text("a,b\n", encoding="utf-8")


def _setup_other_branch(env: Env, t: Task) -> None:
    _g(t.worktree or "", "checkout", "-q", "-b", "my-feature")


CASES = {
    "detached_worktree": (_setup_detached_worktree_commit, "游離 HEAD"),
    "branch_deleted": (_setup_branch_deleted, "分支已不存在"),
    "repo_detached": (_setup_repo_detached, "目標 repo 的 HEAD 是游離狀態"),
    "ignored_file": (_setup_ignored_file, "被忽略的檔案"),
    "other_branch": (_setup_other_branch, "不是 legion/"),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_cleanup_keeps_work_that_could_be_lost(env: Env, case: str) -> None:
    setup, expect = CASES[case]

    async def go() -> None:
        st, t = await _merged_done(env)
        try:
            setup(env, t)
            p = await run_cleanup(env.settings, st, apply=True)
            assert expect in _kept_reason(p, t.id)
            assert p["results"] == []
            assert Path(t.worktree or "").exists()
        finally:
            await st.close()

    run(go())


def test_cleanup_ignores_cache_dirs_only(env: Env) -> None:
    async def go() -> None:
        st, t = await _merged_done(env)
        try:
            common = Path(_g(t.worktree or "", "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
            (common / "info").mkdir(exist_ok=True)
            (common / "info" / "exclude").write_text("__pycache__/\n", encoding="utf-8")
            (Path(t.worktree or "") / "__pycache__").mkdir()
            (Path(t.worktree or "") / "__pycache__" / "calc.pyc").write_bytes(b"\0")
            p = await run_cleanup(env.settings, st)
            assert [r["id"] for r in p["remove"]] == [t.id]
        finally:
            await st.close()

    run(go())


def test_cleanup_keeps_resumable_halt_and_outside_worktree_and_base_branch(env: Env) -> None:
    async def go() -> None:
        st, t = await _merged_done(env)
        try:
            # 可續跑的 HALT
            t = await st.transition(t, State.HALT, {"test": "stop"}, return_state=State.EXEC)
            assert "可以續跑" in _kept_reason(await run_cleanup(env.settings, st), t.id)
            t = await st.transition(t, State.DONE, {"test": "back"}, return_state=None)
            # 想法檔要從這個分支接續
            hold = env.settings.ai_dir / "inbox_hold"
            hold.mkdir(parents=True, exist_ok=True)
            idea = hold / "next.md"
            idea.write_text(f"---\nmission:\n  name: m\nbase_branch: legion/{t.id}\n---\n", encoding="utf-8")
            assert "base_branch" in _kept_reason(await run_cleanup(env.settings, st), t.id)
            idea.unlink()
            # 資料庫指到 legion 工作區以外的 worktree
            outside = env.settings.worktrees_dir.parent / "user-feature"
            _g(env.repo, "worktree", "add", "-q", "-b", "user-feature", str(outside))
            await st.update_task(t.id, worktree=str(outside))
            assert "不在 legion 的工作區" in _kept_reason(await run_cleanup(env.settings, st, apply=True), t.id)
            assert outside.exists()
        finally:
            await st.close()

    run(go())


def test_cleanup_apply_clears_task_worktree_field(env: Env) -> None:
    async def go() -> None:
        st, t = await _merged_done(env)
        try:
            p = await run_cleanup(env.settings, st, apply=True)
            assert p["results"][0]["errors"] == []
            assert (await st.get_task(t.id)).worktree is None
        finally:
            await st.close()

    run(go())


def test_cleanup_never_touches_unfinished_task_even_if_branch_merged(env: Env) -> None:
    env.idea("b", "刪測試", low_mock(actions=[{"type": "delete", "path": "test_calc.py"}]))

    async def go() -> None:
        st = await env.ticks()
        try:
            b = (await st.list_tasks())[0]
            assert b.state == State.WAIT_HUMAN
            p = await run_cleanup(env.settings, st, apply=True)
            assert b.id not in {r["id"] for r in p["remove"]}
            assert p["results"] == []
            if b.worktree:
                assert Path(b.worktree).exists()
                assert "還沒結束" in {r["id"]: r["reason"] for r in p["keep"]}[b.id]
        finally:
            await st.close()

    run(go())
