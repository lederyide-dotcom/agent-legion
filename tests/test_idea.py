"""想法入口 legion idea：一句話寫成 INBOX 想法檔；目標 repo 依 --repo、LEGION_DEFAULT_REPO、目前 git repo 推斷。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from conftest import Env, State, run

from legion.cli import main
from legion.intake import resolve_repo, write_idea
from legion.vault import parse_md


def test_idea_file_is_ingested(env: Env) -> None:
    p = write_idea(env.settings, "幫 calc 加上乘法 multiply，附測試", env.repo, now=datetime(2026, 11, 16, 9, 0, 0))
    assert p.name == "idea-20261116-090000.md"
    fm, body = parse_md(p.read_text(encoding="utf-8"))
    assert fm == {"title": "幫 calc 加上乘法 multiply，附測試", "kind": "write", "repo": env.repo.as_posix()}
    assert body.strip() == "幫 calc 加上乘法 multiply，附測試"
    # 同一秒兩個想法不會互相覆蓋
    assert write_idea(env.settings, "第二個", env.repo, now=datetime(2026, 11, 16, 9, 0, 0)).name.endswith("-2.md")

    async def go() -> None:
        st = await env.ticks(n=1)
        try:
            titles = {t.title for t in await st.list_tasks()}
            assert "幫 calc 加上乘法 multiply，附測試" in titles
            assert all(t.repo == env.repo.as_posix() for t in await st.list_tasks() if t.state != State.HALT)
        finally:
            await st.close()

    run(go())


def test_long_text_gets_short_title(env: Env) -> None:
    p = write_idea(env.settings, "很長" * 40 + "\n第二行細節", env.repo)
    fm, body = parse_md(p.read_text(encoding="utf-8"))
    assert len(fm["title"]) == 40 and fm["title"].endswith("…") and "第二行細節" in body


def test_repo_resolution_order(env: Env, tmp_path: Path) -> None:
    other = tmp_path / "not-a-repo"
    other.mkdir()
    s = env.settings
    assert resolve_repo(str(env.repo), s, other) == env.repo.resolve()
    assert resolve_repo(None, s.model_copy(update={"default_repo": str(env.repo)}), other) == env.repo.resolve()
    assert resolve_repo(None, s, env.repo / "sub" if (env.repo / "sub").exists() else env.repo) == env.repo.resolve()
    assert resolve_repo(None, s, other) is None
    with pytest.raises(ValueError):
        resolve_repo(str(other), s, env.repo)


def test_legion_itself_needs_explicit_repo_and_gets_risk_floor(env: Env) -> None:
    """在 legion 資料夾裡忘了加 --repo，不能默默變成「改 legion 自己」的任務（審查抓到的安全缺口）。"""
    from legion.config import PROJECT_ROOT

    root = Path(PROJECT_ROOT)
    with pytest.raises(ValueError, match="--repo"):
        resolve_repo(None, env.settings, root / "src")
    explicit = resolve_repo(str(root), env.settings, env.repo)
    assert explicit == root.resolve()
    fm, _ = parse_md(write_idea(env.settings, "改 legion 的 README", explicit).read_text(encoding="utf-8"))
    assert fm["risk_floor"] == "mid"
    fm2, _ = parse_md(write_idea(env.settings, "改別的專案", env.repo).read_text(encoding="utf-8"))
    assert "risk_floor" not in fm2


def test_repo_subfolder_keeps_subdir(env: Env) -> None:
    """--repo 指到 repo 裡的子資料夾：repo 取根目錄，subdir 記下子資料夾（不默默放大成整個 repo）。"""
    import subprocess

    from legion.intake import subdir_for

    sub = env.repo / "pkg"
    sub.mkdir(exist_ok=True)
    (sub / "a.py").write_bytes(b"x = 1\n")
    top = resolve_repo(str(sub), env.settings, env.repo)
    assert top == env.repo.resolve()
    with pytest.raises(ValueError, match="還沒進 git"):  # 沒進 git：worktree 看不到，提早報錯
        subdir_for(str(sub), env.settings, top)
    for cmd in (["add", "pkg"], ["commit", "-qm", "pkg"]):
        subprocess.run(["git", *cmd], cwd=env.repo, check=True, capture_output=True)
    assert subdir_for(str(sub), env.settings, top) == "pkg"
    assert subdir_for(str(env.repo), env.settings, top) is None
    assert subdir_for(None, env.settings, top) is None
    s2 = env.settings.model_copy(update={"default_repo": str(sub)})  # 預設 repo 指子資料夾也一樣
    assert resolve_repo(None, s2, Path.cwd()) == top and subdir_for(None, s2, top) == "pkg"
    fm, _ = parse_md(write_idea(env.settings, "只改 pkg", top, subdir="pkg").read_text(encoding="utf-8"))
    assert fm["subdir"] == "pkg"


def test_cli_reports_missing_repo(env: Env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("LEGION_VAULT", str(env.settings.vault))
    monkeypatch.delenv("LEGION_DEFAULT_REPO", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert main(["idea", "沒有 repo 的想法"]) == 1
    assert "--repo" in capsys.readouterr().err
    assert main(["idea", "有 repo 的想法", "--repo", str(env.repo)]) == 0
    assert len(list(env.settings.inbox_dir.glob("idea-*.md"))) == 1
