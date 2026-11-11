"""風險分級（程式判定）。agent 只能提議，最終風險 = max(規則判定, agent 提議)，不能降級。"""
from __future__ import annotations

import re
import shlex
from pathlib import Path, PureWindowsPath
from typing import Any

from .models import InstallRequest, Risk, max_risk

# 驗收指令白名單：VERIFY 由 runner 親自執行，因此只放行測試與 git 唯讀類指令
ACCEPT_CMD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(python|py(\s+-3(\.\d+)?)?)\s+-m\s+pytest(\s|$)"),
    re.compile(r"^pytest(\s|$)"),
    re.compile(r"^git\s+(status|diff|log|rev-parse|show)(\s|$)"),
    re.compile(r"^(python|py(\s+-3(\.\d+)?)?)\s+-m\s+legion\.checks(\s|$)"),
)
_SHELL_META = re.compile(r"[&|;<>`]|\$\(")
_ENV_RE = re.compile(r"(^|[\\/\s'\"])\.env(\b|$)|\.env\.", re.IGNORECASE)

HIGH_ACTIONS = {"delete", "network_write", "message"}
MID_ACTIONS = {"merge"}


_PYTEST_FLAGS = {"-q", "-qq", "-x", "-v", "-s", "-rA", "--tb=short", "--tb=no", "--tb=line", "--no-header"}
_PYTEST_VALUE_FLAGS = {"-k", "-m", "--maxfail"}
_GIT_SUBS = {"status", "diff", "log", "rev-parse", "show"}
_GIT_FLAGS = {
    "--porcelain", "--short", "-s", "--stat", "--name-only", "--name-status", "--oneline", "--cached", "--staged",
    "--exit-code", "--quiet", "--untracked-files=all", "--untracked-files=no", "--no-color", "--shortstat",
    "--verify", "--abbrev-ref", "--show-toplevel", "-n",
}
_SAFE_REL = re.compile(r"^[\w.\-/:~^\[\]]+$")


def _safe_rel_path(tok: str) -> bool:
    return (bool(_SAFE_REL.match(tok)) and not tok.startswith(("/", "~")) and ".." not in tok
            and not re.match(r"^[A-Za-z]:", tok))


def accept_cmd_allowed(cmd: str) -> bool:
    """驗收指令由 runner 親自執行，因此逐 token 檢查：只允許白名單旗標與 worktree 內的相對路徑。"""
    c = cmd.strip().replace("\\", "/")
    if _SHELL_META.search(c) or not any(p.match(c) for p in ACCEPT_CMD_PATTERNS):
        return False
    try:
        argv = shlex.split(c, posix=True)
    except ValueError:
        return False
    if argv[0] == "py":
        argv = argv[2:] if len(argv) > 1 and argv[1].startswith("-3") else argv[1:]
        argv = ["python", *argv]
    if argv[0] in {"python", "python3"} and argv[1:3] == ["-m", "pytest"]:
        rest = argv[3:]
    elif argv[0] == "pytest":
        rest = argv[1:]
    elif argv[0] == "git":
        if len(argv) < 2 or argv[1] not in _GIT_SUBS:
            return False
        for i, tok in enumerate(argv[2:], start=2):
            if tok.startswith("-"):
                if tok not in _GIT_FLAGS and not re.fullmatch(r"-\d{1,3}", tok):
                    return False
            elif argv[i - 1] == "-n":
                if not tok.isdigit():
                    return False
            elif tok != "--" and not _safe_rel_path(tok):
                return False
        return True
    elif argv[0] in {"python", "python3"} and argv[1:3] == ["-m", "legion.checks"]:
        rest = argv[3:]
        if len(rest) < 2 or rest[0] != "report":
            return False
        path = rest[1]
        if "/AI/reports/" not in path or not path.endswith("-report.md") or ".." in path:
            return False
        it = iter(rest[2:])
        for tok in it:
            if tok == "--verify-refs":  # 無參數旗標：只讀核對行號
                continue
            val = next(it, None)
            if val is None:
                return False
            if tok == "--min-refs":
                if not val.isdigit():
                    return False
            elif tok not in {"--section", "--min-chars"}:
                return False
        return True
    else:
        return False
    it = iter(rest)
    for tok in it:
        if tok in _PYTEST_FLAGS:
            continue
        if tok in _PYTEST_VALUE_FLAGS:
            val = next(it, None)
            if val is None or val.startswith("-"):
                return False
            continue
        if tok == "-p":
            if next(it, None) != "no:cacheprovider":
                return False
            continue
        if tok.startswith("-") or not _safe_rel_path(tok):
            return False
    return True


def _outside(path: str, worktree: Path | None) -> bool:
    p = PureWindowsPath(path)
    if p.is_absolute() or p.drive or path.startswith(("/", "\\")):
        if worktree is None:
            return True
        try:
            Path(path).resolve().relative_to(worktree.resolve())
            return False
        except ValueError:
            return True
    return ".." in p.parts


def assess(
    proposed: Risk | None,
    actions: list[dict[str, Any]],
    accept_cmds: list[str],
    kind: str,
    worktree: Path | None,
    install_levels: list[str] | None = None,
) -> tuple[Risk, list[str]]:
    """回傳 (最終風險, 理由)。"""
    reasons: list[str] = []
    rule: Risk = "low"

    def bump(level: Risk, why: str) -> None:
        nonlocal rule
        rule = max_risk(rule, level)
        reasons.append(f"{level}: {why}")

    for a in actions:
        typ = str(a.get("type", "")).lower()
        path = str(a.get("path", "") or "")
        if typ in HIGH_ACTIONS:
            bump("high", f"動作 {typ}")
        if typ == "install":
            bump("high", "安裝須經安裝分級器（PLAN 階段提出即視為高風險）")
        if path and _ENV_RE.search(path):
            bump("high", f"涉及 .env：{path}")
        if typ in {"write", "edit", "delete", "create"}:
            if kind == "readonly":
                bump("high", f"唯讀任務要求寫入：{path}")
            if path and _outside(path, worktree):
                bump("high", f"寫入 worktree 以外：{path}")
            name = Path(path).name.lower()
            if name == "claude.md":
                bump("mid", "修改 CLAUDE.md")
            if "skill" in path.lower().replace("\\", "/").split("/")[:-1] or name == "skill.md":
                bump("mid", "修改 skill")
        if typ in MID_ACTIONS:
            bump("mid", f"動作 {typ}（會合併到主分支）")
        if typ in {"edit_claude_md"}:
            bump("mid", "修改 CLAUDE.md")
        if typ in {"edit_skill"}:
            bump("mid", "修改 skill")
    for cmd in accept_cmds:
        if _ENV_RE.search(cmd):
            bump("high", f"驗收指令涉及 .env：{cmd}")
        elif not accept_cmd_allowed(cmd):
            bump("high", f"驗收指令不在白名單：{cmd}")
    for lvl in install_levels or []:
        if lvl == "ask":
            bump("high", "安裝落在「必須問」等級")
    final = max_risk(rule, proposed)
    if proposed is not None and final != proposed:
        reasons.append(f"agent 提議 {proposed}，依規則改為 {final}（不可降級）")
    return final, reasons


def assess_diff(name_status: str) -> tuple[Risk, list[str]]:
    """依 EXEC 實際產生的變更（git diff --name-status）重新判定風險，不依賴 agent 自報。"""
    rule: Risk = "low"
    reasons: list[str] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code, paths = parts[0], parts[1:]
        for p in paths:
            low = p.lower()
            name = low.rsplit("/", 1)[-1]
            if code.startswith("D"):
                rule = max_risk(rule, "high")
                reasons.append(f"high: 實際變更含刪除：{p}")
            if _ENV_RE.search(p):
                rule = max_risk(rule, "high")
                reasons.append(f"high: 實際變更涉及 .env：{p}")
            if low.startswith(".claude/") or "/.claude/" in low or name == ".mcp.json":
                rule = max_risk(rule, "high")
                reasons.append(f"high: 實際變更修改 agent 設定：{p}")
            if name == "claude.md":
                rule = max_risk(rule, "mid")
                reasons.append(f"mid: 實際變更修改 CLAUDE.md：{p}")
            if name == "skill.md" or "/skills/" in f"/{low}":
                rule = max_risk(rule, "mid")
                reasons.append(f"mid: 實際變更修改 skill：{p}")
    return rule, reasons


def install_levels(reqs: list[InstallRequest]) -> list[str]:
    from .installs import classify

    return [classify(r).level for r in reqs]
