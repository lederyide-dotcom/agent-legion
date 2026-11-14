"""改檔檢查（scripts/check_text_files.py）：CRLF 與語法錯誤要擋下，.bat／.ps1 的 CRLF 放行；repo 設定要在。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from legion.config import PROJECT_ROOT

ROOT = Path(PROJECT_ROOT)
_spec = importlib.util.spec_from_file_location("check_text_files", ROOT / "scripts" / "check_text_files.py")
assert _spec and _spec.loader
ctf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctf)


def test_crlf_and_broken_python_are_reported(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    (tmp_path / "b.py").write_bytes(b'print("a\n")\n')  # 經 Bash 傳送時 \n 變成真換行的典型事故
    (tmp_path / "ok.py").write_bytes(b"z = 'a\\nb'\n")
    (tmp_path / "run.ps1").write_bytes(b"Write-Host hi\r\n")
    (tmp_path / "start.bat").write_bytes(b"@echo off\r\n")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0")
    problems = ctf.check([str(tmp_path / n) for n in ("a.py", "b.py", "ok.py", "run.ps1", "start.bat", "pic.png")])
    joined = "\n".join(problems)
    assert len(problems) == 2, problems
    assert "a.py" in joined and "CRLF" in joined
    assert "b.py:1" in joined and "語法錯誤" in joined


def test_main_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_bytes("# 標題\n內容\n".encode("utf-8"))
    bad = tmp_path / "bad.md"
    bad.write_bytes("# 標題\r\n".encode("utf-8"))
    assert ctf.main([str(good)]) == 0
    assert ctf.main([str(bad)]) == 2


def test_chinese_and_space_filenames_are_checked() -> None:
    """git 預設把中文路徑跳脫成找不到的字串；審查抓到過中文檔被靜靜略過，這裡用真的未追蹤檔驗。"""
    probe = ROOT / "zz_測試 檔名.md"
    probe.write_bytes("# 中文檔名\r\n".encode("utf-8"))
    try:
        assert "zz_測試 檔名.md" in ctf.changed_files()
        assert any("zz_測試 檔名.md" in p and "CRLF" in p for p in ctf.check(ctf.changed_files()))
    finally:
        probe.unlink()


def test_hook_checks_only_the_touched_file(tmp_path: Path) -> None:
    inside = ROOT / "README.md"
    assert ctf.hook_files('{"tool_input": {"file_path": "%s"}}' % str(inside).replace("\\", "/")) == ["README.md"]
    assert ctf.hook_files('{"tool_input": {"file_path": "%s"}}' % str(tmp_path / "x.py").replace("\\", "/")) == []
    assert ctf.hook_files('{"tool_input": {"command": "ls"}}') is None  # Bash：改看工作目錄變動
    assert ctf.hook_files("不是 JSON") is None


def test_repo_enforces_lf_and_hooks_exist() -> None:
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attrs and "*.bat text eol=crlf" in attrs and "*.ps1 text eol=crlf" in attrs
    hook = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "check_text_files.py --staged" in hook and "main(['docs', '--check'])" in hook
    assert "--git-common-dir" in hook  # worktree 裡沒有 .venv 時退回主 worktree（legion 自動提交不能被擋）
    settings = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert "check_text_files.py --hook" in settings and "PostToolUse" in settings
    # repo 裡的 .py 都是 LF 且能編譯
    py = [str(p) for p in [*ROOT.glob("src/legion/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py")]]
    assert ctf.check(py) == []
