"""Obsidian Vault：骨架、任務筆記匯出、儀表.base、流程.canvas、週報。"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .config import Settings
from .db import Store
from .models import Task

AI_SUBDIRS = ("tasks", "specs", "handoffs", "lessons", "questions", "reports", "records")

BASE_YAML = """\
filters:
  and:
    - 'file.inFolder("AI/tasks")'
    - 'file.ext == "md"'
formulas:
  cost_label: 'if(cost_usd, "$" + cost_usd.toFixed(4), "")'
properties:
  state:
    displayName: "狀態"
  risk:
    displayName: "風險"
  cost_usd:
    displayName: "成本 USD"
  human_touches:
    displayName: "人工介入"
  verdict:
    displayName: "審查結論"
  formula.cost_label:
    displayName: "成本"
views:
  - type: table
    name: "依狀態"
    groupBy:
      property: state
      direction: ASC
    order:
      - file.name
      - title
      - state
      - risk
      - formula.cost_label
      - human_touches
      - verdict
    summaries:
      cost_usd: Sum
      human_touches: Sum
  - type: table
    name: "依風險"
    groupBy:
      property: risk
      direction: DESC
    order:
      - file.name
      - title
      - risk
      - state
      - cost_usd
    summaries:
      cost_usd: Sum
  - type: table
    name: "等待 David"
    filters:
      or:
        - 'state == "WAIT_HUMAN"'
        - 'state == "HALT"'
    order:
      - file.name
      - title
      - state
      - wait_reason
      - halt_reason
"""

_FLOW = [
    ("INBOX", "INBOX\nDavid 丟想法", 0, 0, "6"),
    ("PLAN", "PLAN\n指揮官規劃", 260, 0, "5"),
    ("SPEC_REVIEW", "SPEC_REVIEW\n規格審查者（全新 session）", 520, 0, "5"),
    ("GATE", "GATE\nRunner 依風險分級", 780, 0, "3"),
    ("EXEC", "EXEC\n指揮官在 worktree 執行", 780, 200, "5"),
    ("VERIFY", "VERIFY\nRunner 親自執行驗收指令", 520, 200, "3"),
    ("REVIEW", "REVIEW\n交付審查者（全新 session）", 260, 200, "5"),
    ("LEARN", "LEARN\n書記官：教訓、交接、回灌", 0, 200, "5"),
    ("DONE", "DONE", 0, 400, "4"),
    ("WAIT_HUMAN", "WAIT_HUMAN\n寫 questions/ 等 David", 1040, 0, "1"),
    ("HALT", "HALT\n超預算／超重試／逾時／STOP", 1040, 200, "1"),
]
_EDGES = [
    ("INBOX", "PLAN", ""), ("PLAN", "SPEC_REVIEW", ""), ("SPEC_REVIEW", "GATE", "pass"),
    ("SPEC_REVIEW", "PLAN", "revise"), ("GATE", "EXEC", "low／mid"), ("GATE", "WAIT_HUMAN", "high"),
    ("WAIT_HUMAN", "EXEC", "David 核准"), ("EXEC", "VERIFY", ""), ("VERIFY", "REVIEW", "通過"),
    ("VERIFY", "EXEC", "失敗（重試≤3）"), ("REVIEW", "LEARN", "pass"), ("REVIEW", "EXEC", "fail"),
    ("LEARN", "DONE", ""), ("LEARN", "INBOX", "回灌≤2、深度≤2"), ("EXEC", "HALT", "熔斷"),
]


def canvas_json() -> dict[str, Any]:
    nodes = [
        {"id": f"n-{sid.lower()}", "type": "text", "text": text, "x": x, "y": y, "width": 220, "height": 90,
         "color": color}
        for sid, text, x, y, color in _FLOW
    ]
    edges = []
    for i, (a, b, label) in enumerate(_EDGES):
        e: dict[str, Any] = {"id": f"e-{i:02d}", "fromNode": f"n-{a.lower()}", "toNode": f"n-{b.lower()}",
                             "toEnd": "arrow"}
        if label:
            e["label"] = label
        edges.append(e)
    return {"nodes": nodes, "edges": edges}


def init_vault(settings: Settings) -> None:
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    for sub in AI_SUBDIRS:
        (settings.ai_dir / sub).mkdir(parents=True, exist_ok=True)
    keep = [settings.inbox_dir / ".gitkeep"] + [settings.ai_dir / s / ".gitkeep" for s in AI_SUBDIRS]
    for k in keep:
        if not k.exists():
            k.write_text("", encoding="utf-8")
    (settings.ai_dir / "儀表.base").write_text(BASE_YAML, encoding="utf-8")
    (settings.ai_dir / "流程.canvas").write_text(
        json.dumps(canvas_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    readme = settings.vault / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Agent Legion Vault\n\n"
            "- `INBOX/`：一個 .md 一個想法（可選 frontmatter：title、kind、repo、subdir）。\n"
            "- `STOP`：**建立這個檔案（內容不限）即全系統停止**，所有進行中任務進入 HALT。\n"
            "- `AI/`：agent 與 runner 可寫區；`AI/儀表.base` 是儀表，`AI/流程.canvas` 是閉環流程圖。\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------- INBOX
def parse_md(text: str) -> tuple[dict[str, Any], str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            fm = yaml.safe_load(parts[1]) or {}
            if isinstance(fm, dict):
                return fm, parts[2].lstrip("\n")
    return {}, text


def inbox_files(settings: Settings) -> tuple[list[tuple[Path, str, dict[str, Any], str]], list[str]]:
    """回傳 (可領取的想法, 壞檔清單)。壞檔逐檔隔離，不讓一個檔案卡住整個系統。"""
    out = []
    bad: list[str] = []
    for p in sorted(settings.inbox_dir.glob("*.md")):
        try:
            raw = p.read_bytes()
            sha = hashlib.sha256(raw + p.name.encode("utf-8")).hexdigest()
            fm, body = parse_md(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            bad.append(f"{p.name}: {exc!r}"[:300])
            continue
        out.append((p, sha, fm, body))
    return out, bad


def write_followup(settings: Settings, parent: Task, n: int, title: str, body: str) -> Path:
    path = settings.inbox_dir / f"fu-{parent.id}-{n}.md"
    fm = {
        "title": title, "parent_id": parent.id, "depth": parent.depth + 1, "kind": parent.kind,
        "repo": parent.repo, "subdir": parent.subdir,
    }
    child = parent.meta.get("mock", {}).get("child")
    if child is not None:
        fm["mock"] = child
    path.write_text(f"---\n{yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)}---\n{body}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- 任務筆記
def task_frontmatter(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "state": task.state.value,
        "risk": task.risk,
        "cost_usd": round(task.cost_usd, 6),
        "verdict": task.verdict,
        "human_touches": task.human_touches,
        "parent_id": task.parent_id,
        "depth": task.depth,
        "retries": task.retries,
        "halt_reason": task.halt_reason,
        "wait_reason": task.wait_reason,
        "updated": task.updated_at.isoformat() if task.updated_at else None,
    }


def export_task(settings: Settings, task: Task) -> Path:
    fm = task_frontmatter(task)
    lines = [
        "---", yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip(), "---",
        f"# {task.id} {task.title}", "",
        f"- 狀態：**{task.state.value}**　風險：{task.risk or '未判定'}　成本：${task.cost_usd:.4f}",
        f"- 規格：[[specs/{task.id}]]　紀錄文件：[[records/{task.id}/record]]",
    ]
    if task.risk_reasons:
        lines += ["", "## 風險判定理由", *[f"- {r}" for r in task.risk_reasons]]
    if task.wait_reason:
        lines += ["", f"> [!question] 等待 David：{task.wait_reason}（見 [[questions/{task.id}]]）"]
    if task.halt_reason:
        lines += ["", f"> [!danger] HALT：{task.halt_reason}"]
    lines += ["", task.body]
    path = settings.ai_dir / "tasks" / f"{task.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_question(settings: Settings, task: Task, reason: str, details: list[str]) -> Path:
    path = settings.ai_dir / "questions" / f"{task.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {d}" for d in details) or "- （無）"
    path.write_text(
        f"---\ntask: {task.id}\nreason: {reason}\nasked: {datetime.now().astimezone().isoformat(timespec='seconds')}\n---\n"
        f"# 需要 David 決定：{task.id} {task.title}\n\n原因：{reason}\n\n## 細節\n{body}\n\n"
        f"## 怎麼回答\n```\nlegion answer {task.id} approve\nlegion answer {task.id} reject\n```\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------- 週報
async def weekly_report(settings: Settings, store: Store, day: date | None = None) -> Path:
    import csv

    day = day or date.today()
    tasks = await store.list_tasks()
    notify = await store.all_events("notify")
    rows = [
        f"| {t.id} | {t.title} | {t.state.value} | {t.risk or ''} | {t.cost_usd:.4f} | {t.human_touches} |"
        for t in tasks
    ]
    installs: list[str] = []
    if settings.install_ledger.exists():
        with settings.install_ledger.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("level") == "自動＋通知":
                    installs.append(f"- {r['time']} {r['task']} {r['tool']} {r['version']}（移除：`{r['uninstall_cmd']}`）")
    total = sum(t.cost_usd for t in tasks)
    md = [
        f"# 週報 {day.isoformat()}", "",
        f"- 任務數：{len(tasks)}　總成本（用戶端估算）：${total:.4f}",
        f"- 人工介入合計：{sum(t.human_touches for t in tasks)}", "",
        "## 任務", "| 編號 | 標題 | 狀態 | 風險 | 成本 | 人工介入 |", "|---|---|---|---|---|---|", *rows, "",
        "## mid 風險通知", *([f"- {e.ts:%Y-%m-%d %H:%M} {e.task_id}：{e.detail.get('message', '')}" for e in notify]
                           or ["- （無）"]), "",
        "## 自動＋通知等級的安裝（可事後移除）", *(installs or ["- （無）"]),
    ]
    path = settings.ai_dir / "reports" / f"weekly-{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return path
