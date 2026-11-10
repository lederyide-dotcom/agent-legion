"""資料結構（Pydantic）。狀態清單與 Task 欄位的定義變更須先問 David。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class State(str, Enum):
    INBOX = "INBOX"
    PLAN = "PLAN"
    SPEC_REVIEW = "SPEC_REVIEW"
    GATE = "GATE"
    EXEC = "EXEC"
    VERIFY = "VERIFY"
    REVIEW = "REVIEW"
    LEARN = "LEARN"
    DONE = "DONE"
    WAIT_HUMAN = "WAIT_HUMAN"
    HALT = "HALT"


TERMINAL_STATES = frozenset({State.DONE, State.HALT})
PAUSED_STATES = frozenset({State.WAIT_HUMAN})

Risk = Literal["low", "mid", "high"]
RISK_ORDER: dict[str, int] = {"low": 0, "mid": 1, "high": 2}

TaskKind = Literal["readonly", "write"]

DOC_DRAFT = "草稿（AI 產生，未經核可）"
DOC_APPROVED = "已核可"


def max_risk(*risks: str | None) -> Risk:
    """取最高風險；None 視為 low。"""
    best: Risk = "low"
    for r in risks:
        if r is not None and RISK_ORDER[r] > RISK_ORDER[best]:
            best = r  # type: ignore[assignment]
    return best


class Task(BaseModel):
    id: str
    title: str
    body: str = ""
    kind: TaskKind = "write"
    state: State = State.INBOX
    risk: Risk | None = None
    risk_proposed: Risk | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    verdict: str | None = None
    human_touches: int = 0
    parent_id: str | None = None
    depth: int = 0
    retries: int = 0
    step: int = 0
    halt_reason: str | None = None
    return_state: State | None = None  # WAIT_HUMAN／HALT 之後要回到的狀態
    wait_reason: str | None = None
    accept_cmds: list[str] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    repo: str | None = None  # 目標 repo（實戰 A／B、mock 測試 repo）
    subdir: str | None = None  # 在 repo／worktree 內的工作子目錄（例如 sandbox_repo）
    worktree: str | None = None
    base_commit: str | None = None
    install_count: int = 0
    source_path: str | None = None
    source_sha: str | None = None
    doc_status: str = DOC_DRAFT
    doc_approved_by: str | None = None
    doc_approved_at: datetime | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskEvent(BaseModel):
    id: int
    task_id: str
    ts: datetime
    kind: str
    from_state: str | None = None
    to_state: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentRun(BaseModel):
    task_id: str
    state: str
    step: int
    role: str
    backend: str
    model: str | None = None
    session_id: str
    cost_usd: float
    duration_s: float
    status: str = "completed"
    output: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Evidence(BaseModel):
    id: str  # E-001
    task_id: str
    step: int
    label: str
    kind: Literal["text", "image", "csv", "mermaid", "json"]
    path: str  # 相對於 records/<id>/
    sha256: str
    producer: str
    caption: str = ""
    created_at: datetime | None = None


class AgentResult(BaseModel):
    output: dict[str, Any]
    session_id: str
    cost_usd: float
    duration_s: float
    model: str | None = None
    backend: str


class InstallRequest(BaseModel):
    """EXEC 階段 agent 提出的安裝請求；等級由 runner 判定，agent 不能自行認定。"""

    tool: str
    version: str | None = None
    manager: Literal[
        "pip", "uv", "npm", "docker", "winget", "official-release", "script", "mcp", "plugin", "skill", "hook",
        "other",
    ]
    scope: Literal["venv", "project", "user", "system"] = "project"
    source: str = ""  # pypi / npm / dockerhub-official / dockerhub-verified / winget / official-release / 其他
    requires_admin: bool = False
    license: str | None = None
    name_source: Literal["official_docs", "lockfile", "unknown"] = "unknown"
    command: str = ""
    uninstall_command: str | None = None


InstallLevel = Literal["auto", "auto_notify", "ask"]


class InstallDecision(BaseModel):
    level: InstallLevel
    reasons: list[str]
