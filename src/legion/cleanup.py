"""清理已併入的 legion 分支與 worktree：預設只列清單，加 --apply 才刪。

安全規則（任何一條不符就保留，並寫明原因）：
- 只處理已結束的可寫任務：DONE，或沒有 return_state（不能續跑）的 HALT
- 目標 repo 的 HEAD 必須停在一般分支上（不是游離 HEAD、不是 legion/*），且沒有 rebase／merge 等進行中
- 分支必須存在，而且是目標 repo HEAD 的祖先（已併入）
- worktree 必須在 settings.worktrees_dir/<任務編號>、登記在目標 repo、停在 legion/<id> 分支上、沒有進行中的操作
- worktree 不能有未提交或被忽略的檔案（快取資料夾除外）
- 還有未結束任務或待領取想法以它為 base_branch 的分支不刪
- 刪除時用 `git worktree remove`（不加 --force）與 `git branch -d`（不用 -D），git 自己會再擋一次
- --apply 期間持有 runner 的鎖，避免和 tick 同時動同一個任務
- worktree 資料夾若沒有登記在任何 repo（孤兒），只列出、不刪
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Store
from .models import State, Task

# 這些被忽略的資料夾只是快取，可以跟 worktree 一起刪
DISPOSABLE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
IN_PROGRESS_MARKERS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")
_BASE_RE = re.compile(r"base_branch:\s*['\"]?(legion/[A-Za-z0-9_-]+)")


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:
        return subprocess.CompletedProcess(["git", *args], -1, "", f"{type(e).__name__}: {e}")


def _norm(p: str | Path) -> str:
    return os.path.normcase(str(Path(p).resolve()))


def _registered_worktrees(repo: str) -> set[str]:
    out = _git(repo, "worktree", "list", "--porcelain")
    if out.returncode != 0:
        return set()
    return {_norm(ln[len("worktree "):]) for ln in out.stdout.splitlines() if ln.startswith("worktree ")}


def _in_progress(cwd: str) -> str | None:
    gd = _git(cwd, "rev-parse", "--absolute-git-dir")
    if gd.returncode != 0:
        return "無法讀取 git 目錄"
    hit = [m for m in IN_PROGRESS_MARKERS if (Path(gd.stdout.strip()) / m).exists()]
    return f"有進行中的操作（{', '.join(hit)}）" if hit else None


def _repo_head_problem(repo: str) -> str | None:
    ref = _git(repo, "symbolic-ref", "-q", "HEAD")
    if ref.returncode != 0:
        return "目標 repo 的 HEAD 是游離狀態"
    if ref.stdout.strip().startswith("refs/heads/legion/"):
        return f"目標 repo 停在 {ref.stdout.strip()}，不是主分支"
    return _in_progress(repo)


def _worktree_problem(wt: Path, branch: str) -> str | None:
    ref = _git(str(wt), "symbolic-ref", "-q", "HEAD")
    if ref.returncode != 0:
        return "worktree 是游離 HEAD，可能有不在分支上的 commit"
    if ref.stdout.strip() != f"refs/heads/{branch}":
        return f"worktree 停在 {ref.stdout.strip()}，不是 {branch}"
    prog = _in_progress(str(wt))
    if prog:
        return prog
    st = _git(str(wt), "status", "--porcelain", "--ignored")
    if st.returncode != 0:
        return "無法讀取 worktree 狀態"
    dirty, ignored = [], []
    for ln in st.stdout.splitlines():
        path = ln[3:].strip().strip('"')
        if ln.startswith("!!"):
            if not any(part in DISPOSABLE_DIRS for part in Path(path).parts):
                ignored.append(path)
        elif ln.strip():
            dirty.append(path)
    if dirty:
        return "worktree 有未提交的變更"
    if ignored:
        return f"worktree 有被忽略的檔案（{', '.join(ignored[:3])}）"
    return None


def _protected_bases(settings: Settings, tasks: list[Task]) -> set[str]:
    """還要被接續的分支：未結束任務的 base_branch，以及 INBOX／inbox_hold 想法檔裡寫的 base_branch。"""
    out = {str(t.meta.get("base_branch")) for t in tasks if t.meta.get("base_branch") and not _finished(t)}
    for d in (settings.inbox_dir, settings.ai_dir / "inbox_hold"):
        if d.exists():
            for f in d.glob("*.md"):
                try:
                    out |= set(_BASE_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
                except OSError:
                    continue
    return out


def _finished(t: Task) -> bool:
    return t.state == State.DONE or (t.state == State.HALT and t.return_state is None)


def _row(t: Task, branch: str, wt: Path | None, wt_exists: bool, branch_exists: bool) -> dict[str, Any]:
    return {"id": t.id, "state": t.state.value, "title": t.title, "repo": t.repo, "branch": branch,
            "branch_exists": branch_exists, "worktree": str(wt) if wt and wt_exists else None}


def _check(settings: Settings, t: Task, registered: set[str], head_problem: dict[str, str | None],
           protected: set[str]) -> dict[str, Any] | None:
    """回傳一列（含 reason 與 removable），已經乾淨就回 None。"""
    repo = str(t.repo)
    branch = f"legion/{t.id}"
    wt = Path(t.worktree) if t.worktree else None
    wt_exists = bool(wt and wt.exists())
    branch_exists = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    if not wt_exists and not branch_exists:
        return None
    row = _row(t, branch, wt, wt_exists, branch_exists)

    def keep(reason: str) -> dict[str, Any]:
        return {**row, "removable": False, "reason": reason}

    if not _finished(t):
        return keep(f"任務還沒結束（{t.state.value}）" if t.state != State.HALT else "HALT 但可以續跑（有 return_state）")
    if head_problem.get(repo):
        return keep(str(head_problem[repo]))
    if not branch_exists:
        return keep("分支已不存在但 worktree 還在，無法確認裡面的 commit 是否已併入")
    if branch in protected:
        return keep("還有任務或想法檔要從這個分支接續（base_branch）")
    if wt_exists and wt is not None:
        if _norm(wt) != _norm(settings.worktrees_dir / t.id):
            return keep(f"worktree 不在 legion 的工作區（{settings.worktrees_dir.name}/{t.id}），不碰")
        if _norm(wt) not in registered:
            return keep("worktree 沒有登記在目標 repo，不確定歸屬")
        problem = _worktree_problem(wt, branch)
        if problem:
            return keep(problem)
    if _git(repo, "merge-base", "--is-ancestor", branch, "HEAD").returncode != 0:
        return keep("分支還沒併入目標 repo 的 HEAD")
    return {**row, "removable": True, "reason": "已併入 HEAD、worktree 乾淨"}


def plan(settings: Settings, tasks: list[Task]) -> dict[str, Any]:
    repos = {str(t.repo) for t in tasks if t.repo and Path(t.repo).exists()}
    registered: set[str] = set()
    for repo in repos:
        registered |= _registered_worktrees(repo)
    head_problem = {repo: _repo_head_problem(repo) for repo in repos}
    protected = _protected_bases(settings, tasks)
    remove: list[dict[str, Any]] = []
    keep: list[dict[str, Any]] = []
    for t in sorted(tasks, key=lambda x: x.id):
        if t.kind != "write" or not t.repo or str(t.repo) not in repos:
            continue
        r = _check(settings, t, registered, head_problem, protected)
        if r is not None:
            (remove if r.pop("removable") else keep).append(r)
    known = {_norm(r["worktree"]) for r in remove + keep if r["worktree"]}
    orphans = []
    if settings.worktrees_dir.exists():
        for d in sorted(settings.worktrees_dir.iterdir()):
            if d.is_dir() and _norm(d) not in registered and _norm(d) not in known:
                orphans.append({"path": str(d), "reason": "沒有登記在任何 repo 的 worktree 清單；只列出，不刪"})
    return {"remove": remove, "keep": keep, "orphans": orphans}


async def run_cleanup(settings: Settings, store: Store, apply: bool = False) -> dict[str, Any]:
    if not apply:
        return {**plan(settings, await store.list_tasks()), "applied": False}
    if not await store.try_lock():
        return {"remove": [], "keep": [], "orphans": [], "applied": False,
                "error": "另一個 tick 正在執行，稍後再清理"}
    try:
        # 拿到鎖之後才重新計算清單，避免用到過期的狀態
        p = {**plan(settings, await store.list_tasks()), "applied": True}
        done = []
        for r in p["remove"]:
            res: dict[str, Any] = {"id": r["id"], "worktree_removed": None, "branch_deleted": None, "errors": []}
            if r["worktree"]:
                out = _git(r["repo"], "worktree", "remove", r["worktree"])
                res["worktree_removed"] = out.returncode == 0
                if out.returncode != 0:
                    res["errors"].append(out.stderr.strip()[-300:])
                else:
                    await store.update_task(r["id"], worktree=None)
            if r["branch_exists"] and not res["errors"]:
                out = _git(r["repo"], "branch", "-d", r["branch"])
                res["branch_deleted"] = out.returncode == 0
                if out.returncode != 0:
                    res["errors"].append(out.stderr.strip()[-300:])
            await store.add_event(r["id"], "cleanup", {k: v for k, v in res.items() if k != "id"})
            done.append(res)
        p["results"] = done
        return p
    finally:
        await store.unlock()
