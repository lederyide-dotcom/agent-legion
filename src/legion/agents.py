"""AgentBackend：ClaudeCliAgent（claude -p）與 MockAgent（零成本測試）。

工具權限依角色固定（程式決定，agent 不能自行擴權）：
- 唯讀角色（planner、spec_reviewer、reviewer、scribe）：--tools Read,Glob,Grep，從工具層移除 Bash／Edit／Write。
- executor：可編輯與執行白名單 Bash；安裝類、push、merge、.env 一律 deny。
  註：官方文件明言 Bash deny 規則不是安全邊界，硬邊界由 runner 的 VERIFY 親自執行與 worktree 外 git 狀態比對承擔。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .models import AgentResult, Task

READONLY_ROLES = frozenset({"planner", "spec_reviewer", "reviewer", "scribe"})
REVIEWER_ROLES = frozenset({"spec_reviewer", "reviewer"})
ALL_ROLES = READONLY_ROLES | {"executor"}

ENV_DENY = [
    "Read(**/.env)", "Read(**/.env.*)", "Bash(*.env*)",
    # 相對規則以 cwd 解析；cwd 是別的 repo 時也要擋到任何位置的 .env（審查建議，絕對路徑寫法）
    "Read(//**/.env)", "Read(//**/.env.*)",
    # 金鑰與憑證（spec：讀取須先問）
    "Read(//**/.ssh/**)", "Read(//**/*.pem)", "Read(//**/*.key)", "Read(//**/*.pfx)", "Read(//**/id_rsa*)",
    "Read(//**/id_ed25519*)", "Read(//**/.credentials.json)", "Read(~/.claude/**)", "Read(~/.aws/**)",
    "Bash(*.ssh*)", "Bash(*.pem*)", "Bash(*credentials*)",
]
# executor 不得改寫會改變 agent 行為的設定（hook、權限、MCP）
CONFIG_DENY = ["Edit(.claude/**)", "Edit(**/.claude/**)", "Edit(**/.mcp.json)"]
INSTALL_DENY = [
    "Bash(pip *)", "Bash(pip3 *)", "Bash(* -m pip *)", "Bash(uv *)", "Bash(npm *)", "Bash(npx *)", "Bash(pnpm *)",
    "Bash(yarn *)", "Bash(winget *)", "Bash(choco *)", "Bash(scoop *)", "Bash(curl *)", "Bash(wget *)",
    "Bash(Invoke-WebRequest *)", "Bash(iwr *)", "Bash(docker *)", "Bash(claude *)",
]
GIT_DENY = [
    "Bash(git push *)", "Bash(git merge *)", "Bash(git rebase *)", "Bash(git reset *)", "Bash(git worktree *)",
    "Bash(git checkout *)", "Bash(git switch *)", "Bash(git branch *)", "Bash(git remote *)", "Bash(rm *)",
]
EXEC_BASH_ALLOW = [
    "Bash(git status *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git show *)", "Bash(git add *)",
    "Bash(git commit *)", "Bash(python -m pytest *)", "Bash(pytest *)", "Bash(ls *)", "Bash(cat *)",
]

INSTALL_CMD_RE = re.compile(
    r"\b(pip|pip3|uv|npm|npx|pnpm|yarn|winget|choco|scoop|curl|wget|docker|apt|brew)\b|install", re.IGNORECASE
)


class ToolProfile(BaseModel):
    tools: list[str]
    allow: list[str]
    deny: list[str]
    permission_mode: str


def tool_profile(role: str, kind: str = "write") -> ToolProfile:
    """依角色與任務類型決定工具。唯讀任務的 executor 也只給唯讀工具（報告經由 report_md 回傳）。"""
    if role in READONLY_ROLES or (role == "executor" and kind == "readonly"):
        return ToolProfile(
            tools=["Read", "Glob", "Grep"],
            allow=["Read", "Glob", "Grep"],
            deny=[*ENV_DENY, "Edit", "Write", "Bash", "WebFetch", "WebSearch"],
            permission_mode="dontAsk",
        )
    if role == "executor":
        return ToolProfile(
            tools=["Read", "Glob", "Grep", "Edit", "Write", "Bash"],
            allow=["Read", "Glob", "Grep", "Edit", "Write", *EXEC_BASH_ALLOW],
            deny=[*ENV_DENY, *CONFIG_DENY, *INSTALL_DENY, *GIT_DENY, "WebFetch", "WebSearch"],
            permission_mode="acceptEdits",
        )
    raise ValueError(f"未知角色：{role}")


class AgentCall(BaseModel):
    role: str
    prompt: str
    cwd: Path
    schema_: dict[str, Any] = Field(alias="schema")
    task: Task
    attempt: int = 0
    timeout_s: int = 900
    budget_usd: float = 1.0
    add_dirs: list[Path] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class AgentFailure(Exception):
    """agent 呼叫失敗；cost_usd 為已花掉（或保守估計）的金額，runner 會照記入帳，避免預算低估。"""

    def __init__(self, msg: str, cost_usd: float = 0.0, session_id: str | None = None,
                 duration_s: float = 0.0) -> None:
        super().__init__(msg)
        self.cost_usd = cost_usd
        self.session_id = session_id
        self.duration_s = duration_s


class AgentTimeout(AgentFailure):
    pass


class AgentError(AgentFailure):
    pass


def _kill_tree(pid: int) -> None:
    """逾時時連同子孫行程一起結束（Bash 工具開的 shell 可能握著 stdout 管線）。"""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30)
    else:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass


class AgentBackend(Protocol):
    name: str

    async def run(self, call: AgentCall) -> AgentResult: ...


# ---------------------------------------------------------------- Claude CLI
class ClaudeCliAgent:
    """呼叫 `claude -p --output-format json`。每次呼叫都是全新 session（不用 --continue／--resume）。"""

    name = "claude"

    def __init__(self, model: str | None = None, exe: str = "claude") -> None:
        self.model = model
        self.exe = exe

    def build_cmd(self, call: AgentCall, settings_path: Path) -> list[str]:
        prof = tool_profile(call.role, call.task.kind)
        cmd = [
            self.exe, "-p", "--output-format", "json",
            "--json-schema", json.dumps(call.schema_, ensure_ascii=False),
            "--tools", ",".join(prof.tools),
            "--allowedTools", ",".join(prof.allow),
            "--permission-mode", prof.permission_mode,
            "--permission-prompts", "none",
            "--setting-sources", "project",
            "--strict-mcp-config",
            "--settings", str(settings_path),
            "--max-budget-usd", f"{call.budget_usd:.2f}",
        ]
        if self.model:
            cmd += ["--model", self.model]
        for d in call.add_dirs:
            cmd += ["--add-dir", str(d)]
        return cmd

    async def run(self, call: AgentCall) -> AgentResult:
        prof = tool_profile(call.role, call.task.kind)
        with tempfile.TemporaryDirectory(prefix="legion-") as td:
            settings_path = Path(td) / "settings.json"
            settings_path.write_text(
                json.dumps({"permissions": {"allow": prof.allow, "deny": prof.deny}}), encoding="utf-8"
            )
            cmd = self.build_cmd(call, settings_path)
            env = dict(os.environ)
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            t0 = time.monotonic()

            def go() -> tuple[int, str, str]:
                flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                p = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding="utf-8", errors="replace", cwd=call.cwd, env=env, creationflags=flags,
                )
                try:
                    so, se = p.communicate(call.prompt, timeout=call.timeout_s)
                except subprocess.TimeoutExpired:
                    _kill_tree(p.pid)
                    try:
                        p.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        pass
                    raise
                return p.returncode, so, se

            try:
                code, stdout, stderr = await asyncio.to_thread(go)
            except subprocess.TimeoutExpired as exc:
                # 實際花費未知，以本次呼叫上限（--max-budget-usd）保守入帳
                raise AgentTimeout(f"{call.role} 超過 {call.timeout_s} 秒", cost_usd=call.budget_usd,
                                   duration_s=float(call.timeout_s)) from exc
        dur = time.monotonic() - t0
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise AgentError(f"claude 輸出不是 JSON（exit {code}）：{stderr[-400:]}", duration_s=dur) from exc
        cost = float(data.get("total_cost_usd") or 0.0)
        sid = str(data.get("session_id") or "") or None
        if data.get("is_error") or data.get("subtype") != "success":
            raise AgentError(f"claude 回報錯誤：subtype={data.get('subtype')} result={str(data.get('result'))[:300]}",
                             cost_usd=cost, session_id=sid, duration_s=dur)
        out = data.get("structured_output")
        if not isinstance(out, dict):  # structured_output 可能不存在，退回解析 result
            try:
                out = json.loads(data.get("result") or "")
            except json.JSONDecodeError as exc:
                raise AgentError("沒有 structured_output，result 也不是 JSON", cost_usd=cost, session_id=sid,
                                 duration_s=dur) from exc
            if not isinstance(out, dict):
                raise AgentError("result 不是 JSON 物件", cost_usd=cost, session_id=sid, duration_s=dur)
        out["_permission_denials"] = data.get("permission_denials") or []
        return AgentResult(
            output=out,
            session_id=str(data["session_id"]),
            cost_usd=float(data.get("total_cost_usd") or 0.0),
            duration_s=dur,
            model=self.model or next(iter(data.get("modelUsage") or {}), None),
            backend=self.name,
        )


def reviewer_backend(setting: str, fallback: AgentBackend) -> tuple[AgentBackend, str | None]:
    """審查者 backend。codex 的非互動唯讀呼叫語法尚未驗證，本輪一律退回 Claude 全新 session。"""
    if setting == "codex":
        if shutil.which("codex") is None:
            return fallback, "codex 未安裝，審查者退回 Claude 全新 session"
        return fallback, "codex 呼叫方式未驗證，審查者退回 Claude 全新 session"
    return fallback, None


# ---------------------------------------------------------------- Mock
class MockAgent:
    """零成本測試用。行為由任務 meta.mock 劇本決定；每次呼叫產生新的 session_id。

    劇本欄位（皆可省略）：
      risk_proposed, actions, accept_cmds, installs(PLAN 宣告), cost
      spec_review: ["revise", "pass"]（依序取用，用完取最後一個）
      exec: [{"write_files": {...}, "claim": "passed", "install_requests": [...]}]
      review: ["fail", "pass"]
      followups: [{"title":..., "body":...}]
      timeout_roles: ["executor"]
      tamper_evidence: true（模擬書記官改證據，用來測 runner 會擋）
    """

    name = "mock"

    def __init__(self, cost: float = 0.01) -> None:
        self.cost = cost
        self.calls: list[tuple[str, str, str]] = []  # (task_id, role, session_id)
        self.prompts: list[tuple[str, str, str]] = []  # (task_id, role, prompt)：測試用來檢查提示內容

    @staticmethod
    def _pick(seq: list[Any], i: int, default: Any) -> Any:
        if not seq:
            return default
        return seq[min(i, len(seq) - 1)]

    async def run(self, call: AgentCall) -> AgentResult:
        sc: dict[str, Any] = call.task.meta.get("mock", {})
        if call.role in sc.get("timeout_roles", []):
            raise AgentTimeout(f"mock：{call.role} 逾時", cost_usd=call.budget_usd)
        if call.role in sc.get("error_roles", []):
            raise AgentError(f"mock：{call.role} 回報錯誤", cost_usd=0.02, session_id=f"mock-{uuid.uuid4()}")
        if call.role in sc.get("crash_roles", []):
            raise RuntimeError(f"mock：{call.role} 非預期例外")
        sid = f"mock-{uuid.uuid4()}"
        self.calls.append((call.task.id, call.role, sid))
        self.prompts.append((call.task.id, call.role, call.prompt))
        cost = float(sc.get("cost", self.cost))
        task = call.task
        out: dict[str, Any]
        if call.role == "planner":
            out = {
                "spec_md": f"# {task.title}\n\n## 目標\n{task.body or task.title}\n\n## 驗收\n"
                + "\n".join(f"- `{c}`" for c in sc.get("accept_cmds", ["python -m pytest -q"])),
                "risk_proposed": sc.get("risk_proposed", "low"),
                "accept_cmds": sc.get("accept_cmds", ["python -m pytest -q"]),
                "actions": sc.get("actions", [{"type": "write", "path": "feature.py"}]),
                "installs": sc.get("installs", []),
                "rationale": "mock 規劃",
            }
        elif call.role == "spec_reviewer":
            v = self._pick(sc.get("spec_review", []), call.attempt, "pass")
            default_findings = [] if v == "pass" else ["mock：驗收指令不足"]
            out = {"verdict": v, "findings": self._pick(sc.get("spec_findings", []), call.attempt, default_findings)}
        elif call.role == "executor":
            beh: dict[str, Any] = self._pick(sc.get("exec", []), call.attempt, {})
            for rel, content in beh.get("write_files", {}).items():
                p = call.cwd / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            for rel in beh.get("delete_files", []):  # 模擬 agent 未在 PLAN 宣告就刪檔
                (call.cwd / rel).unlink()
            out = {
                "summary": beh.get("summary", "mock 執行完成"),
                "claim": beh.get("claim", "passed"),
                "changed_files": list(beh.get("write_files", {}).keys()),
                "install_requests": beh.get("install_requests", []),
                "report_md": beh.get("report_md", ""),
            }
        elif call.role == "reviewer":
            v = self._pick(sc.get("review", []), call.attempt, "pass")
            out = {"verdict": v, "findings": [] if v == "pass" else ["mock：交付不符規格"]}
        elif call.role == "scribe":
            ev_ids: list[str] = call.task.meta.get("_evidence_ids", [])
            cite = "、".join(ev_ids[-2:]) if ev_ids else "E-001"
            vruns = call.task.meta.get("verify_runs", [])
            last_cmds = {r["cmd"]: r["txt"] for r in (vruns[-1]["cmds"] if vruns else [])}
            revs = call.task.meta.get("reviews", {})

            def rcite(stage: str) -> str:
                items = revs.get(stage, [])
                return items[-1]["ev"] if items else cite
            if sc.get("tamper_evidence"):
                for f in (call.add_dirs[0] / "evidence").glob("*.txt") if call.add_dirs else []:
                    f.chmod(0o666)
                    f.write_text("被竄改", encoding="utf-8")
            crit = call.task.accept_cmds
            out = {
                "design_notes": f"本任務依規格在 worktree 內完成變更，驗證結果見（{cite}）。",
                "verification_notes": [
                    {"criterion": c, "conclusion": f"runner 親自執行此指令，exit 0（{last_cmds.get(c, cite)}）。"}
                    for c in crit
                ],
                "review_notes": [
                    {"stage": "spec_review", "conclusion": f"規格審查通過（{rcite('spec_review')}）。"},
                    {"stage": "review", "conclusion": f"交付審查通過（{rcite('review')}）。"},
                ],
                "issues_lessons": "mock 任務未遇到問題。",
                "lessons_md": f"# 教訓：{task.title}\n\n- mock 閉環順利完成。\n",
                "handoff_md": f"# 交接：{task.title}\n\n- 無待辦。\n",
                "followups": sc.get("followups", []),
            }
        else:
            raise AgentError(f"mock 不支援角色 {call.role}")
        return AgentResult(output=out, session_id=sid, cost_usd=cost, duration_s=0.01, model="mock", backend="mock")
