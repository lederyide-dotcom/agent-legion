"""風險分級（程式判定）。agent 只能提議，最終風險 = max(規則判定, agent 提議)，不能降級。"""
from __future__ import annotations

import re
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


def accept_cmd_allowed(cmd: str) -> bool:
    c = cmd.strip()
    if _SHELL_META.search(c):
        return False
    return any(p.match(c) for p in ACCEPT_CMD_PATTERNS)


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


def install_levels(reqs: list[InstallRequest]) -> list[str]:
    from .installs import classify

    return [classify(r).level for r in reqs]
