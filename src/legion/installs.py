"""安全安裝政策：分級器、安裝清冊。等級由 runner 程式判定，agent 不能自行認定安全。"""
from __future__ import annotations

import asyncio
import csv
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .models import InstallDecision, InstallRequest

LEDGER_FIELDS = [
    "time", "task", "tool", "version", "source", "level", "install_cmd", "uninstall_cmd", "license",
]

# 可判定為開放原始碼的授權（SPDX 或常見寫法）
OPEN_LICENSES = {
    "mit", "mit-cmu", "bsd", "bsd-2-clause", "bsd-3-clause", "apache-2.0", "apache 2.0", "isc", "mpl-2.0",
    "lgpl-2.1", "lgpl-3.0", "gpl-2.0", "gpl-3.0", "agpl-3.0", "psf-2.0", "python-2.0", "unlicense", "zlib",
    "0bsd", "postgresql", "cc0-1.0",
}
_REMOTE_SCRIPT = re.compile(
    r"(curl|wget|iwr|invoke-webrequest|irm|invoke-restmethod)[^|]*\|\s*(sh|bash|iex|invoke-expression|pwsh|powershell)"
    r"|\biex\b|invoke-expression|bash\s+<\(|sh\s+-c\s+\"?\$\(curl",
    re.IGNORECASE,
)
_UNPINNED = re.compile(r"^(|\*|latest|any|x)$|[*^~><]", re.IGNORECASE)
_ADMIN_HINT = re.compile(
    r"(?:^|\s)(?:sudo|runas|--global|-g|/machine|--scope[\s=]+machine|--location)(?=\s|$)"
    r"|\bsetx\s+/m\b|\breg\s+add\b|\bnetsh\b|\bsc\s+create\b|\bStart-Process\b.*-Verb\s+RunAs",
    re.IGNORECASE,
)

AUTO_SOURCES = {
    "pip": {"pypi"},
    "uv": {"pypi"},
    "npm": {"npm"},
    "docker": {"dockerhub-official", "dockerhub-verified"},
}


def classify(req: InstallRequest) -> InstallDecision:
    reasons: list[str] = []
    ask = False

    def need_ask(why: str) -> None:
        nonlocal ask
        ask = True
        reasons.append(why)

    if req.manager in {"mcp", "plugin", "skill", "hook"}:
        need_ask(f"{req.manager} 會改變 agent 自己的行為與權限")
    if req.manager in {"script", "other"}:
        need_ask(f"安裝方式 {req.manager} 不在官方管道")
    if _REMOTE_SCRIPT.search(req.command):
        need_ask("直接執行遠端腳本")
    if req.requires_admin or req.scope == "system" or _ADMIN_HINT.search(req.command):
        need_ask("需要管理員權限或修改系統／全域設定")
    if req.version is None or _UNPINNED.search(req.version.strip()):
        need_ask("未鎖定版本")
    lic = (req.license or "").strip().lower()
    if not lic or lic not in OPEN_LICENSES:
        need_ask(f"授權條款非開放原始碼或無法判定：{req.license!r}")
    if req.name_source not in {"official_docs", "lockfile"}:
        need_ask("套件名稱未出自官方文件或既有 lockfile（防仿冒套件）")

    level = "ask"
    if not ask:
        if req.manager in AUTO_SOURCES:
            if req.source.lower() in AUTO_SOURCES[req.manager] and req.scope in {"venv", "project"}:
                level = "auto"
                reasons.append(f"專案層級 {req.manager}，來源 {req.source}")
            else:
                reasons.append(f"{req.manager} 的範圍 {req.scope} 或來源 {req.source!r} 不符自動條件")
        elif req.manager == "winget" and req.source.lower() == "winget" and req.scope == "user":
            level = "auto_notify"
            reasons.append("winget 官方來源、使用者層級")
        elif req.manager == "official-release" and req.scope == "user":
            level = "auto_notify"
            reasons.append("工具官方發行頁、使用者層級")
        else:
            reasons.append("不符合任何自動條件")
    return InstallDecision(level=level, reasons=reasons)  # type: ignore[arg-type]


def uninstall_command(req: InstallRequest) -> str:
    if req.uninstall_command:
        return req.uninstall_command
    if req.manager in {"pip", "uv"}:
        return f"python -m pip uninstall -y {req.tool}"
    if req.manager == "npm":
        return f"npm uninstall {req.tool}"
    if req.manager == "docker":
        return f"docker image rm {req.tool}:{req.version}"
    if req.manager == "winget":
        return f"winget uninstall --id {req.tool} --exact"
    raise ValueError(f"無法為 {req.manager} 產生移除指令，需人工處理")


def append_ledger(path: Path, task_id: str, req: InstallRequest, level: str) -> dict[str, str]:
    row = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task": task_id,
        "tool": req.tool,
        "version": req.version or "",
        "source": req.source,
        "level": {"auto": "自動", "auto_notify": "自動＋通知", "ask": "必須問"}[level],
        "install_cmd": req.command,
        "uninstall_cmd": uninstall_command(req),
        "license": req.license or "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


class Installer(Protocol):
    async def install(self, req: InstallRequest, cwd: Path) -> None: ...


class RecordingInstaller:
    """測試與 mock 用：不實際安裝，只記錄。"""

    def __init__(self) -> None:
        self.done: list[InstallRequest] = []

    async def install(self, req: InstallRequest, cwd: Path) -> None:
        self.done.append(req)


class ShellInstaller:
    """真實安裝：只會被 runner 對 auto／auto_notify 等級呼叫，且只在 EXEC 狀態。"""

    async def install(self, req: InstallRequest, cwd: Path) -> None:
        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(req.command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=900)

        proc = await asyncio.to_thread(run)
        if proc.returncode != 0:
            raise RuntimeError(f"安裝失敗（exit {proc.returncode}）：{proc.stderr[-500:]}")
