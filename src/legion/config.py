"""執行設定。熔斷數值的放寬須先問使用者（spec「必須停下來問我」）。

所有路徑都相對於專案根目錄，或由環境變數覆寫（見 .env.example），程式內不寫死個人環境的絕對路徑。
"""
from __future__ import annotations

import os
import shutil
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


# 角色 → (模型, effort)。依研究報告的角色配置：規劃與規格審查用強模型；執行先用 Sonnet、失敗才升級；
# 書記官用最便宜的 Haiku。effort 為 None 表示不指定（Haiku 是否支援 effort 未確認，因此不傳）。
DEFAULT_ROLE_MODELS: dict[str, tuple[str, str | None]] = {
    "planner": ("opus", "medium"),
    "spec_reviewer": ("opus", "medium"),
    "executor": ("sonnet", None),
    "reviewer": ("sonnet", "high"),
    "scribe": ("claude-haiku-5-5", None),
    # 軍師：只在任務卡住時請示，提出至少 3 個錦囊（Pro 方案的 Fable 需另購 credits，故預設 Opus／high）
    "advisor": ("opus", "high"),
    # 參謀：戰役中每個任務結案時，對照目標決定下一步或宣告完成
    "strategist": ("opus", "medium"),
}
# 執行者驗收或審查失敗後重做時改用；交付審查也隨之升到同一個模型（審查者不低於執行者）
DEFAULT_ESCALATION: tuple[str, str | None] = ("opus", "high")
EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def _env_effort(name: str, default: str | None) -> str | None:
    v = os.environ.get(name)
    if v is None:
        return default
    v = v.strip().lower()
    return None if v in {"", "none", "default"} else (v if v in EFFORTS else default)


def _role_models() -> dict[str, tuple[str, str | None]]:
    """預設表，可用環境變數逐角色覆寫：LEGION_MODEL_PLANNER=sonnet、LEGION_EFFORT_PLANNER=high（none＝不指定）。"""
    out: dict[str, tuple[str, str | None]] = {}
    for role, (model, effort) in DEFAULT_ROLE_MODELS.items():
        key = role.upper()
        out[role] = (os.environ.get(f"LEGION_MODEL_{key}") or model, _env_effort(f"LEGION_EFFORT_{key}", effort))
    return out


def _escalation() -> tuple[str, str | None] | None:
    model = os.environ.get("LEGION_ESCALATE_MODEL", DEFAULT_ESCALATION[0])
    if model.strip().lower() in {"", "none", "off"}:
        return None  # 關閉升級
    return model, _env_effort("LEGION_ESCALATE_EFFORT", DEFAULT_ESCALATION[1])


def _first_existing(env: str, which: str, candidates: list[str]) -> Path:
    """環境變數 → PATH 上的執行檔 → 常見安裝位置；都找不到時回傳第一個候選（呼叫端會給出清楚的錯誤）。"""
    if os.environ.get(env):
        return Path(os.environ[env])
    found = shutil.which(which)
    if found:
        return Path(found)
    expanded = [Path(os.path.expandvars(c)) for c in candidates]
    return next((p for p in expanded if p.exists()), expanded[0])


def _default_soffice() -> Path:
    return _first_existing("LEGION_SOFFICE", "soffice", [
        r"%ProgramFiles%\LibreOffice\program\soffice.exe", "/usr/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice"])


def _default_browser() -> Path:
    """Mermaid 轉圖（puppeteer）用的 Chromium 系瀏覽器。"""
    return _first_existing("LEGION_BROWSER", "msedge", [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        "/usr/bin/chromium", "/usr/bin/google-chrome"])


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
    daily_budget_usd: float = 2.0  # spec v0.5：單日超過 $2 必須先問使用者
    max_retries: int = 3
    same_error_limit: int = 3  # 同一個驗收失敗特徵出現幾次就 HALT（不等重試上限）
    # 軍師：任務因同一錯誤或重試上限要停下時，先請示軍師提出錦囊，交給人決定
    advisor_enabled: bool = Field(default_factory=lambda: os.environ.get("LEGION_ADVISOR", "1") != "0")
    advisor_idle_minutes: float = Field(
        default_factory=lambda: float(os.environ.get("LEGION_ADVISOR_IDLE_MINUTES", "15")))  # 人閒置多久就自動決議
    advisor_budget_usd: float = Field(default=0.5, gt=0)  # 每次請示的上限（仍計入單任務與每日預算）
    advisor_max_consults: int = 2  # 每個任務最多請示幾次，避免「失敗→請示→自動重試」無限循環
    call_timeout_s: int = 900
    followup_cap: int = 2
    followup_max_depth: int = 2
    # 回灌想法是否直接寫進 INBOX（下一輪自動領取）。真實 backend 由 CLI 預設關閉，改寫到 AI/inbox_hold/ 等使用者放行。
    followup_auto_ingest: bool = True
    install_cap: int = 10
    report_min_refs: int = 3  # 唯讀報告至少要有幾筆可核對的 檔名:行號（零引用不得通過）
    ledger_include_mock: bool = False  # 持久花費帳本預設不記 mock 呼叫（demo 不污染帳本）；測試會打開

    # 角色與 backend
    agent_backend: str = "mock"  # mock | claude
    reviewer_backend: str = "claude"  # claude | codex（未安裝時退回 claude 全新 session）
    claude_model: str | None = None  # 有值時「所有角色」統一用這個模型（tick --model 的總開關），否則依角色表
    role_models: dict[str, tuple[str, str | None]] = Field(default_factory=_role_models)
    escalation: tuple[str, str | None] | None = Field(default_factory=_escalation)
    commander_preamble: str = ""  # 指揮官前置指令（例如 /poteto-mode），本輪預設空白

    # 紀錄文件
    render_mermaid: bool = Field(default_factory=lambda: os.environ.get("LEGION_RENDER_MERMAID", "1") != "0")
    mermaid_cli: Path = PROJECT_ROOT / "tools" / "mermaid" / "node_modules" / ".bin" / "mmdc.cmd"
    browser: Path = Field(default_factory=_default_browser)
    soffice: Path = Field(default_factory=_default_soffice)

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
    def prompt_dir(self) -> Path:
        """提示全文的本機存放處（.legion_tmp 已在 .gitignore）。"""
        return self.worktrees_dir.parent / ".legion_tmp" / "prompts"

    @property
    def cost_ledger(self) -> Path:
        return self.data_dir / "cost_ledger.csv"

    def model_for(self, role: str, attempt: int, escalated: bool) -> tuple[str | None, str | None]:
        """指揮官（runner）替這次呼叫選模型與 effort。

        - tick --model 指定時：全部角色統一用它（不升級），維持舊行為
        - 執行者第 2 次起（驗收或審查失敗後重做）改用升級模型
        - 執行者升級過的任務，交付審查也用升級模型（審查者不低於執行者）
        """
        if self.claude_model:
            return self.claude_model, None
        model, effort = self.role_models.get(role, (None, None))
        if self.escalation and ((role == "executor" and attempt >= 1) or (role == "reviewer" and escalated)):
            esc_model, esc_effort = self.escalation
            return esc_model, (esc_effort if role == "executor" else effort)
        return model, effort

    def record_dir(self, task_id: str) -> Path:
        return self.ai_dir / "records" / task_id
