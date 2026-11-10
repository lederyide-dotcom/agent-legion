"""各角色的 prompt 與 JSON Schema（結構化輸出）。"""
from __future__ import annotations

import json
from typing import Any

from .models import Task

_S = {"type": "string"}
_SL = {"type": "array", "items": {"type": "string"}}

SCHEMAS: dict[str, dict[str, Any]] = {
    "planner": {
        "type": "object",
        "properties": {
            "spec_md": _S,
            "risk_proposed": {"type": "string", "enum": ["low", "mid", "high"]},
            "accept_cmds": _SL,
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"type": _S, "path": _S},
                    "required": ["type"],
                },
            },
            "installs": {"type": "array", "items": {"type": "object"}},
            "rationale": _S,
        },
        "required": ["spec_md", "risk_proposed", "accept_cmds", "actions", "rationale"],
    },
    "spec_reviewer": {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": ["pass", "revise"]}, "findings": _SL},
        "required": ["verdict", "findings"],
    },
    "executor": {
        "type": "object",
        "properties": {
            "summary": _S,
            "claim": _S,
            "changed_files": _SL,
            "install_requests": {"type": "array", "items": {"type": "object"}},
            "report_md": _S,
        },
        "required": ["summary", "claim", "changed_files"],
    },
    "reviewer": {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": ["pass", "fail"]}, "findings": _SL},
        "required": ["verdict", "findings"],
    },
    "scribe": {
        "type": "object",
        "properties": {
            "design_notes": _S,
            "verification_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"criterion": _S, "conclusion": _S},
                    "required": ["criterion", "conclusion"],
                },
            },
            "review_notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"stage": _S, "conclusion": _S},
                    "required": ["stage", "conclusion"],
                },
            },
            "issues_lessons": _S,
            "lessons_md": _S,
            "handoff_md": _S,
            "followups": {
                "type": "array",
                "items": {"type": "object", "properties": {"title": _S, "body": _S}, "required": ["title", "body"]},
            },
        },
        "required": [
            "design_notes", "verification_notes", "review_notes", "issues_lessons", "lessons_md", "handoff_md",
            "followups",
        ],
    },
}

RULES_BLOCK = """\
規則（由 runner 以程式強制，違反會被擋或升級風險）：
- 驗收指令只能是：`python -m pytest ...`、`pytest ...`、`git status|diff|log|rev-parse|show ...`，不得含 & | ; > < 等 shell 符號。
- 風險只能提議，程式會依規則判定並取較高者。
- 不得讀取 .env、金鑰、憑證；不得安裝任何東西（需要時在 install_requests 提出，由 runner 判級）。
- 不得 push、merge、刪除檔案、對外網路寫入或發訊。
"""


def planner_prompt(task: Task, preamble: str, workdir_desc: str) -> str:
    return f"""{preamble}
你是指揮官，負責規劃。任務編號 {task.id}，類型 {task.kind}（readonly＝只能讀；write＝只能改工作目錄內）。
工作目錄：{workdir_desc}

## 想法
{task.title}

{task.body}

請先閱讀工作目錄了解現況，產出：
- spec_md：精簡規格（目標、範圍、驗收標準）。
- accept_cmds：1～3 條可在工作目錄自動執行、exit 0 代表通過的驗收指令。
- actions：預計動作清單，每項 {{type: read|write|delete|install|merge|network_write|message, path}}，path 用相對路徑。
- risk_proposed：你的風險提議。
{RULES_BLOCK}"""


def spec_review_prompt(task: Task, spec_md: str, accept_cmds: list[str]) -> str:
    return f"""你是規格審查者（全新 session、唯讀）。審查下面的任務規格是否可執行、驗收指令是否足以驗證目標。
只回 verdict（pass／revise）與 findings。

任務：{task.title}
類型：{task.kind}

## 規格
{spec_md}

## 驗收指令
{json.dumps(accept_cmds, ensure_ascii=False)}
{RULES_BLOCK}"""


def executor_prompt(task: Task, preamble: str, spec_md: str, last_failure: str | None) -> str:
    extra = f"\n## 上一輪驗證失敗（runner 親自執行的輸出）\n```\n{last_failure}\n```\n" if last_failure else ""
    if task.kind == "readonly":
        mode = ("本任務唯讀：不得修改任何檔案。把完整報告（Markdown，至少 800 字）放在 report_md，"
                "必須有標題含「架構」與「測試缺口」的章節；每個判斷附上檔案路徑作為依據。")
    else:
        mode = "只能修改目前工作目錄內的檔案；完成後可用 git add／git commit 在此 worktree 內提交。"
    return f"""{preamble}
你是指揮官，負責執行任務 {task.id}。{mode}
完成後 runner 會親自執行驗收指令，你的自述不會被採信。

## 規格
{spec_md}

## 驗收指令
{json.dumps(task.accept_cmds, ensure_ascii=False)}
{extra}
{RULES_BLOCK}
回報 summary、claim、changed_files（相對路徑）。"""


def reviewer_prompt(task: Task, spec_md: str, diff: str, evidence_digest: str) -> str:
    return f"""你是交付審查者（全新 session、唯讀）。對照規格，檢查變更與 runner 產生的證據，判斷是否可交付。
只回 verdict（pass／fail）與 findings。

## 規格
{spec_md}

## 變更（git diff）
```diff
{diff[:20000]}
```

## 證據摘要（runner 產生，編號 E-xxx）
{evidence_digest[:12000]}
"""


def scribe_prompt(task: Task, spec_md: str, evidence_digest: str, reviews: dict[str, Any]) -> str:
    crit = json.dumps(task.accept_cmds, ensure_ascii=False)
    return f"""你是書記官（全新 session、唯讀）。你只寫敘述，不得產生或改寫證據。
每一個結論都必須在句中引用證據編號（例如「測試全數通過（E-003）」）；沒有證據支持的話不要下結論。

任務 {task.id}：{task.title}（深度 {task.depth}）
## 規格
{spec_md}

## 驗收標準（verification_notes 必須每條各一項，criterion 原文照抄）
{crit}

## 證據摘要
{evidence_digest[:15000]}

## 審查結果
{json.dumps(reviews, ensure_ascii=False)[:6000]}

產出：design_notes、verification_notes、review_notes（stage 為 spec_review 與 review）、issues_lessons、
lessons_md、handoff_md、followups（最多 2 個值得做的後續想法；沒有就空陣列）。"""
