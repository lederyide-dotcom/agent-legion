"""執行設定。熔斷數值的放寬須先問 David（spec「必須停下來問我」）。"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_dsn() -> str:
    user = os.environ.get("LEGION_DB_USER", "legion")
    pw = os.environ.get("LEGION_DB_PASSWORD", "legion_local_only")
    name = os.environ.get("LEGION_DB_NAME", "legion")
    port = os.environ.get("LEGION_DB_PORT", "55432")
    return f"postgresql://{user}:{pw}@127.0.0.1:{port}/{name}"


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else default


class Settings(BaseModel):
    dsn: str = Field(default_factory=_default_dsn)
    schema_name: str = "legion"
    vault: Path = Field(default_factory=lambda: _env_path("LEGION_VAULT", PROJECT_ROOT / "vault"))
    data_dir: Path = Field(default_factory=lambda: _env_path("LEGION_DATA_DIR", PROJECT_ROOT / "02_data"))
    output_dir: Path = Field(default_factory=lambda: _env_path("LEGION_OUTPUT_DIR", PROJECT_ROOT / "01_output"))
    worktrees_dir: Path = Field(default_factory=lambda: _env_path("LEGION_WORKTREES", PROJECT_ROOT / ".worktrees"))
    task_prefix: str = "T"

    # 熔斷
    task_budget_usd: float = 2.0
    daily_budget_usd: float = 5.0
    max_retries: int = 3
    call_timeout_s: int = 900
    followup_cap: int = 2
    followup_max_depth: int = 2
    # 回灌想法是否直接寫進 INBOX（下一輪自動領取）。真實 backend 由 CLI 預設關閉，改寫到 AI/inbox_hold/ 等 David 放行。
    followup_auto_ingest: bool = True
    install_cap: int = 10
    ledger_include_mock: bool = False  # 持久花費帳本預設不記 mock 呼叫（demo 不污染帳本）；測試會打開

    # 角色與 backend
    agent_backend: str = "mock"  # mock | claude
    reviewer_backend: str = "claude"  # claude | codex（未安裝時退回 claude 全新 session）
    claude_model: str | None = None
    commander_preamble: str = ""  # 指揮官前置指令（例如 /poteto-mode），本輪預設空白

    # 紀錄文件
    render_mermaid: bool = Field(default_factory=lambda: os.environ.get("LEGION_RENDER_MERMAID", "1") != "0")
    mermaid_cli: Path = PROJECT_ROOT / "tools" / "mermaid" / "node_modules" / ".bin" / "mmdc.cmd"
    mermaid_puppeteer_cfg: Path = PROJECT_ROOT / "tools" / "mermaid" / "puppeteer.json"
    soffice: Path = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")

    @property
    def ai_dir(self) -> Path:
        return self.vault / "AI"

    @property
    def inbox_dir(self) -> Path:
        return self.vault / "INBOX"

    @property
    def stop_file(self) -> Path:
        return self.vault / "STOP"

    @property
    def install_ledger(self) -> Path:
        return self.data_dir / "install_ledger.csv"

    @property
    def cost_ledger(self) -> Path:
        return self.data_dir / "cost_ledger.csv"

    def record_dir(self, task_id: str) -> Path:
        return self.ai_dir / "records" / task_id
