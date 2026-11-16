"""Obsidian Vault：骨架、任務筆記匯出、儀表.base、流程.md／流程.canvas（定義在 diagrams.py）、週報。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from . import diagrams
from .config import PROJECT_ROOT, Settings
from .db import Store
from .models import Task

AI_SUBDIRS = ("tasks", "specs", "handoffs", "lessons", "questions", "reports", "records")

BASE_YAML = diagrams.base_yaml()


_ROLE_LABEL = {"planner": "指揮官（規劃）", "spec_reviewer": "規格審查者", "executor": "指揮官（執行）",
               "reviewer": "交付審查者", "scribe": "書記官", "advisor": "軍師（卡住時才請示）",
               "strategist": "參謀（戰役中決定下一步）"}
# 模型顯示名稱、官方單價（USD／每百萬 token，輸入／輸出；2026-11-12 查詢官方定價頁）、畫布顏色
_MODEL_INFO: dict[str, tuple[str, str, str]] = {
    "fable": ("Fable 5.2", "$8／$40", "1"), "claude-fable-5-2": ("Fable 5.2", "$8／$40", "1"),
    "opus": ("Opus 5.5", "$4／$20", "6"), "claude-opus-5-5": ("Opus 5.5", "$4／$20", "6"),
    "sonnet": ("Sonnet 5.5", "$2／$10", "5"), "claude-sonnet-5-5": ("Sonnet 5.5", "$2／$10", "5"),
    "haiku": ("Haiku 5.5", "$0.10／$0.50", "4"), "claude-haiku-5-5": ("Haiku 5.5", "$0.10／$0.50", "4"),
}


def _model_name(model: str | None) -> str:
    return _MODEL_INFO.get((model or "").lower(), (model or "CLI 預設", "", ""))[0]


def _fmt(model: str | None, effort: str | None) -> str:
    return f"{_model_name(model)} / {effort}" if effort else _model_name(model)


def _role_assignment(settings: Settings, role: str) -> tuple[str, str | None, str | None, str | None]:
    """(第 1 次模型, effort, 重做時模型, effort)；重做時與第 1 次相同則後兩者為 None。"""
    m, e = settings.model_for(role, 0, False)
    m2, e2 = settings.model_for(role, 1, True)
    if (m2, e2) == (m, e):
        return m or "", e, None, None
    return m or "", e, m2, e2


def canvas_json(settings: Settings | None = None) -> dict[str, Any]:
    """閉環流程畫布（定義在 diagrams.py）。傳入 settings 時，在 Claude 角色節點上標註實際分配的模型。"""
    if settings is None:
        return diagrams.canvas_json()
    models: dict[str, list[str]] = {}
    for n in diagrams.NODES:
        if n.role:
            m, e, m2, e2 = _role_assignment(settings, n.role)
            models[n.role] = [f"模型：{_fmt(m, e)}"] + ([f"重做時：{_fmt(m2, e2)}"] if m2 else [])
    return diagrams.canvas_json(models)


def models_canvas_json(settings: Settings) -> dict[str, Any]:
    """角色 → 模型 關係畫布：依 runner 實際設定（含環境變數覆寫）產生。紅線＝失敗後升級。"""
    lanes = [("PLAN", "planner"), ("SPEC_REVIEW", "spec_reviewer"), ("GATE", None), ("EXEC", "executor"),
             ("VERIFY", None), ("REVIEW", "reviewer"), ("LEARN", "scribe"), ("ADVISOR", "advisor"), ("MISSION", "strategist")]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    model_nodes: dict[str, str] = {}
    pending: list[tuple[str, str, str, str]] = []  # (角色節點, 模型, 標籤, 種類)
    escalations: dict[tuple[str, str], list[str]] = {}  # (第 1 次模型, 升級模型) → 說明
    for i, (state, role) in enumerate(lanes):
        nid = f"r-{state.lower()}"
        if role is None:
            text = f"{state}\nrunner 程式判斷\n不用模型"
            nodes.append({"id": nid, "type": "text", "text": text, "x": 0, "y": i * 170, "width": 300, "height": 120,
                          "color": "3"})
            continue
        m, e, m2, e2 = _role_assignment(settings, role)
        color = _MODEL_INFO.get(m.lower(), ("", "", "0"))[2]
        nodes.append({"id": nid, "type": "text", "text": f"{state}\n{_ROLE_LABEL[role]}", "x": 0, "y": i * 170,
                      "width": 300, "height": 120, "color": color})
        pending.append((nid, m, f"第 1 次｜{e or '預設'}", ""))
        if m2:
            # 升級畫成「模型 → 模型」一條紅線（不從角色直接連，避免與第 1 次的連線交叉、標籤重疊）
            who = "審查者隨之升級" if role == "reviewer" else f"{_ROLE_LABEL[role]}重做時"
            escalations.setdefault((m.lower(), m2.lower()), []).append(f"{who}｜{e2 or '預設'}")
            pending.append(("", m2, "", "esc"))  # 只為確保升級目標模型有節點
    # 模型節點放在「第 1 次用它的角色」那幾列的中間，讓第 1 次的連線接近水平；升級線（紅）改從底部接入，避免標籤重疊
    row_y = {n["id"]: n["y"] for n in nodes}
    first_rows: dict[str, list[int]] = {}
    for nid, model, _, kind in pending:
        if not kind:
            first_rows.setdefault(model.lower(), []).append(row_y[nid])
    for _, model, _, _ in pending:
        key = model.lower()
        if key not in model_nodes:
            name, price, color = _MODEL_INFO.get(key, (model, "", "0"))
            mid = f"m-{len(model_nodes)}"
            model_nodes[key] = mid
            ys = first_rows.get(key) or [0]
            text = f"## {name}" + (f"\n官方單價 {price}\n（每百萬 token 輸入／輸出）" if price else "")
            nodes.append({"id": mid, "type": "text", "text": text, "x": 1000, "y": sum(ys) // len(ys) - 20,
                          "width": 300, "height": 160, "color": color})
    # 兩個模型的「平均列」可能剛好相同（例如 Opus 用在頭尾、Sonnet 用在中間）→ 依序往下推開，避免疊在一起
    placed = sorted((n for n in nodes if n["id"].startswith("m-")), key=lambda n: n["y"])
    for prev, cur in zip(placed, placed[1:]):
        cur["y"] = max(cur["y"], prev["y"] + prev["height"] + 40)
    for nid, model, label, kind in pending:
        if kind:
            continue
        edges.append({"id": f"e-{len(edges):02d}", "fromNode": nid, "fromSide": "right",
                      "toNode": model_nodes[model.lower()], "toSide": "left", "toEnd": "arrow", "label": label})
    node_y = {n["id"]: n["y"] for n in nodes}
    for (src, dst), whys in escalations.items():
        a, b = model_nodes[src], model_nodes[dst]
        up = node_y[b] < node_y[a]
        edges.append({"id": f"e-{len(edges):02d}", "fromNode": a, "fromSide": "top" if up else "bottom",
                      "toNode": b, "toSide": "bottom" if up else "top", "toEnd": "arrow", "color": "1",
                      "label": "失敗後升級\n" + "\n".join(whys)})
    legend = ("**怎麼看**\n- 左：閉環中的角色，依流程由上而下\n- 右：模型與官方單價（2026-11-12 查詢）\n"
              "- 灰線：第 1 次呼叫用的模型；紅線：驗收或審查失敗後，改用的模型\n"
              "- 節點顏色＝第 1 次用的模型；黃色＝runner 程式，不用模型\n"
              "- 依 runner 實際設定自動產生，改環境變數後下次 tick 會更新")
    nodes.append({"id": "legend", "type": "text", "text": legend, "x": 1420, "y": 0, "width": 380, "height": 260})
    return {"nodes": nodes, "edges": edges}


def init_vault(settings: Settings) -> None:
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    for sub in AI_SUBDIRS:
        (settings.ai_dir / sub).mkdir(parents=True, exist_ok=True)
    keep = [settings.inbox_dir / ".gitkeep"] + [settings.ai_dir / s / ".gitkeep" for s in AI_SUBDIRS]
    for k in keep:
        if not k.exists():
            k.write_text("", encoding="utf-8", newline="\n")
    (settings.ai_dir / "儀表.base").write_text(BASE_YAML, encoding="utf-8", newline="\n")
    (settings.ai_dir / "流程.md").write_text(diagrams.flow_markdown(), encoding="utf-8", newline="\n")
    (settings.ai_dir / "儀表.md").write_text(diagrams.dashboard_note(), encoding="utf-8", newline="\n")
    # 動態 SVG：vault 裡還沒有時，先放 repo 的版本（legion docs 產生），Obsidian 的嵌入才不會破圖
    img = settings.vault / diagrams.VAULT_IMG
    img.mkdir(parents=True, exist_ok=True)
    for rel in (diagrams.FLOW_SVG, diagrams.DASHBOARD_SVG):
        src, dst = PROJECT_ROOT / rel, img / Path(rel).name
        if src.exists() and not dst.exists():
            dst.write_bytes(src.read_bytes())
    (settings.ai_dir / "流程.canvas").write_text(
        json.dumps(canvas_json(settings), ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    (settings.ai_dir / "模型分配.canvas").write_text(
        json.dumps(models_canvas_json(settings), ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    readme = settings.vault / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Agent Legion Vault\n\n"
            "- `INBOX/`：一個 .md 一個想法（可選 frontmatter：title、kind、repo、subdir）。\n"
            "- `STOP`：**建立這個檔案（內容不限）即全系統停止**，所有進行中任務進入 HALT。\n"
            "- `AI/`：agent 與 runner 可寫區；`AI/儀表.base` 是儀表，`AI/流程.md` 是閉環流程圖（與 GitHub README 同一張），`AI/流程.canvas` 是可拖曳並標註模型的版本。\n",
            encoding="utf-8", newline="\n",
        )


# ---------------------------------------------------------------- INBOX
def parse_md(text: str) -> tuple[dict[str, Any], str]:
    # 只認「獨立一行的 ---」當分隔：內文或欄位值裡的 --- 不會把 frontmatter 切壞
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", text, re.DOTALL)
    if m:
        fm = yaml.safe_load(m.group(1)) or {}
        if isinstance(fm, dict):
            return fm, m.group(2).lstrip("\n")
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


def existing_ids(settings: Settings, prefix: str) -> set[str]:
    ids = {p.stem for p in (settings.ai_dir / "tasks").glob(f"{prefix}-*.md")}
    ids |= {p.name for p in (settings.ai_dir / "records").glob(f"{prefix}-*") if p.is_dir()}
    return ids


_SELF_REF = re.compile(
    # legion 專有名稱與檔案
    r"legion|src/legion|(?:risk|prompts|agents|checks|runner|ledger|installs)\.py|agent_runs|"
    r"spec_review|max_retries|followup_cap|inbox_hold|"
    # 熔斷與預算（spec：放寬須先問使用者）
    r"熔斷|(?:每日|單日|任務)?預算(?:上限|門檻)|daily_budget|task_budget|"
    # 風險規則與權限
    r"風險(?:規則|分級|門檻|下限)|risk_floor|權限|deny\s*清單|allowedTools|\.claude/|settings\.json|\.mcp\.json|"
    # 驗收流程本身（不是目標 repo 的驗收）
    r"驗收流程|驗收指令白名單",
    re.IGNORECASE)


def is_self_referential(text: str) -> bool:
    """後續想法是否在談 legion 自己（規則、角色、熔斷等）。這類想法不得掛在目標 repo 上自動執行。"""
    return bool(_SELF_REF.search(text))


def write_followup(settings: Settings, parent: Task, n: int, title: str, body: str, hold: bool = False,
                   mission: dict[str, Any] | None = None, base_branch: str | None = None,
                   kind: str | None = None) -> Path:
    """hold=True 時寫到 AI/inbox_hold/，不會被 tick 領取；使用者把檔案移回 INBOX 才算放行。

    涉及 legion 本身的想法（事故 4：T-0009～T-0013 內容在改 legion 卻掛在目標 repo 上）：
    repo 改指 legion 專案、kind 改 readonly（只提案不改）、風險下限 mid。
    mission／base_branch 只由 runner 在戰役接續時傳入：子任務帶著戰役設定，並從上一個任務的分支接著做。
    """
    folder = settings.ai_dir / "inbox_hold" if hold else settings.inbox_dir
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"fu-{parent.id}-{n}.md"
    fm: dict[str, Any] = {
        "title": title, "parent_id": parent.id, "depth": parent.depth + 1,
        "kind": kind if kind in {"readonly", "write"} else parent.kind,
        "repo": parent.repo, "subdir": parent.subdir,
    }
    if parent.meta.get("allowed_paths"):
        fm["allowed_paths"] = list(parent.meta["allowed_paths"])  # 改動範圍沿用上層任務，不因回灌而放寬
    if mission:
        fm["mission"] = mission
    if base_branch:
        fm["base_branch"] = base_branch
    if is_self_referential(f"{title}\n{body}"):
        fm.update(kind="readonly", repo=str(PROJECT_ROOT), subdir=None, risk_floor="mid", self_ref=True)
        for k in ("allowed_paths", "mission", "base_branch"):
            fm.pop(k, None)
        body = f"（runner：此後續想法涉及 legion 本身，改為對 legion 的唯讀提案；實作須使用者另行決定）\n\n{body}"
    child = parent.meta.get("mock", {}).get("child")
    if child is not None:
        fm["mock"] = child
    path.write_text(f"---\n{yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)}---\n{body}\n", encoding="utf-8", newline="\n")
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
        lines += ["", f"> [!question] 等待使用者：{task.wait_reason}（見 [[questions/{task.id}]]）"]
    if task.halt_reason:
        lines += ["", f"> [!danger] HALT：{task.halt_reason}"]
    lines += ["", task.body]
    path = settings.ai_dir / "tasks" / f"{task.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def write_question(settings: Settings, task: Task, reason: str, details: list[str]) -> Path:
    path = settings.ai_dir / "questions" / f"{task.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- {d}" for d in details) or "- （無）"
    path.write_text(
        f"---\ntask: {task.id}\nreason: {reason}\nasked: {datetime.now().astimezone().isoformat(timespec='seconds')}\n---\n"
        f"# 需要使用者決定：{task.id} {task.title}\n\n原因：{reason}\n\n## 細節\n{body}\n\n"
        f"## 怎麼回答（在專案根目錄執行）\n```\n.venv\\Scripts\\python.exe -m legion answer {task.id} approve\n"
        f".venv\\Scripts\\python.exe -m legion answer {task.id} reject\n```\n",
        encoding="utf-8", newline="\n",
    )
    return path


_OUTCOME_LABEL = {"continue": "進行中（已排入下一個任務）", "complete": "✅ 目標達成", "caps": "⏹ 達到上限，停止接續",
                  "paused": "⏸ 暫停，等使用者"}


def write_mission_note(settings: Settings, mission: dict[str, Any], tasks: list[Task]) -> Path:
    """戰役進度筆記（AI/missions/<名稱>.md）：目標、上限、每個任務的狀態與花費、成果所在分支。"""
    safe_name = re.sub(r"[^\w.-]+", "_", str(mission["name"]))
    path = settings.ai_dir / "missions" / f"{safe_name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tasks = sorted(tasks, key=lambda t: t.id)
    spent = sum(t.cost_usd for t in tasks)
    last = tasks[-1] if tasks else None
    outcome = (last.meta.get("mission_outcome") if last else None) or ""
    if last and last.state.value == "HALT" and (last.halt_reason or "").startswith("operator_cancel") \
            and last.return_state is None:
        status = f"⏹ {last.id} 已取消，戰役結束"
    elif last and last.state.value in {"HALT", "WAIT_HUMAN"}:
        status = f"⏸ {last.id} 停在 {last.state.value}，等使用者處理"
    elif outcome and last and last.state.value == "DONE":
        status = _OUTCOME_LABEL.get(outcome, outcome)
    else:
        status = "進行中"
    writes = [t for t in tasks if t.kind == "write" and t.state.value == "DONE"]
    rows = [f"| [[tasks/{t.id}]] | {t.title} | {t.kind} | {t.state.value} | ${t.cost_usd:.4f} |" for t in tasks]
    branch = (f"\n成果在目標 repo 的分支 `legion/{writes[-1].id}`（包含前面所有任務的變更）。確認後自行 merge，"
              "legion 不會動主分支。\n") if writes else ""
    path.write_text(
        f"---\nmission: {mission['name']}\nstatus: {status}\ntasks: {len(tasks)}\ncost_usd: {round(spent, 4)}\n---\n"
        f"# 戰役：{mission['name']}\n\n- 狀態：**{status}**\n"
        f"- 任務：{len(tasks)}／{mission['max_tasks']}　花費：${spent:.4f}／${float(mission['budget_usd']):.2f}\n"
        f"{branch}\n## 目標\n{mission['goal']}\n\n## 任務\n| 編號 | 標題 | 類型 | 狀態 | 花費 |\n|---|---|---|---|---|\n"
        + "\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    return path


_KIND_LABEL = {"revise_spec": "回到規劃重寫規格", "retry_with_guidance": "依指引重新執行", "split_task": "拆成小任務",
               "abandon": "放棄這個任務", "needs_human": "需要你處理"}


def write_advisor_question(settings: Settings, task: Task, adv: dict[str, Any]) -> Path:
    """軍師的錦囊寫成問題檔，讓使用者在 Obsidian 裡選；也說明閒置多久後會自動決議。"""
    path = settings.ai_dir / "questions" / f"{task.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for o in adv["options"]:
        star = "⭐ " if str(o.get("id")) == adv["recommended"] else ""
        rows.append(f"### {star}{o.get('id')}. {o.get('title')}\n"
                    f"- 種類：{_KIND_LABEL.get(str(o.get('kind')), o.get('kind'))}　風險：{o.get('risk')}　"
                    f"預估花費：${float(o.get('est_cost_usd') or 0):.2f}\n"
                    f"- 做法：{o.get('plan')}\n- 理由：{o.get('rationale')}\n")
    minutes = settings.advisor_idle_minutes
    path.write_text(
        f"---\ntask: {task.id}\nreason: 軍師錦囊待決定\nasked: {adv['asked_at']}\n---\n"
        f"# 軍師錦囊：{task.id} {task.title}\n\n卡住原因：{adv['reason']}\n\n"
        f"任務風險：{task.risk or '未判定'}" + ("（high 風險任務不會自動決議，一定等你）" if task.risk == "high" else "") +
        f"\n\n## 軍師診斷\n{adv['diagnosis']}\n\n"
        f"## 錦囊（⭐ 為軍師推薦）\n" + "\n".join(rows) +
        f"\n## 怎麼決定\n```\n.venv\\Scripts\\python.exe -m legion choose {task.id} <選項編號>\n"
        f".venv\\Scripts\\python.exe -m legion answer {task.id} approve   # 採用推薦\n"
        f".venv\\Scripts\\python.exe -m legion answer {task.id} reject    # 停止任務\n```\n\n"
        f"> [!info] {minutes:g} 分鐘內沒有決定，指揮官＋軍師會自動決議：優先採用推薦，"
        f"但只限「不需要你處理、風險不是 high、預估花費在剩餘預算內」的錦囊；都不符合就繼續等你。\n",
        encoding="utf-8", newline="\n",
    )
    return path


def write_clarify_question(settings: Settings, task: Task, questions: list[dict[str, Any]]) -> Path:
    """需求釐清寫成問題檔：每題列選項（⭐ 為預設），附回答方式與閒置後採用預設的說明。"""
    path = settings.ai_dir / "questions" / f"{task.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for q in questions:
        opts = "\n".join(f"- {'⭐ ' if o == q['default'] else ''}{'ABCD'[i]}. {o}" for i, o in enumerate(q["options"]))
        why = f"\n  （為什麼問：{q['why']}）" if q.get("why") else ""
        blocks.append(f"### {q['id']}. {q['question']}{why}\n{opts}\n")
    example = " ".join(f"{q['id']}={'ABCD'[q['options'].index(q['default'])]}" for q in questions)
    minutes = settings.clarify_idle_minutes
    path.write_text(
        f"---\ntask: {task.id}\nreason: 需求釐清待回答\nasked: {task.meta.get('clarify', {}).get('asked_at', '')}\n---\n"
        f"# 需求釐清：{task.id} {task.title}\n\n規劃者覺得想法還有不清楚的地方，先問你 {len(questions)} 題。"
        "⭐ 是預設答案，規格已照預設寫好。\n\n" + "\n".join(blocks) +
        f"\n## 怎麼回答\n```\n.venv\\Scripts\\python.exe -m legion clarify {task.id} --defaults   # 全部採用預設\n"
        f".venv\\Scripts\\python.exe -m legion clarify {task.id} {example}   # 逐題指定（沒寫的題目採用預設）\n```\n\n"
        f"> [!info] {minutes:g} 分鐘內沒有回答，就採用預設答案繼續（之後仍有規格審查與守門）。"
        "有任何答案不是預設，規劃者會照你的答案重寫規格。\n",
        encoding="utf-8", newline="\n",
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
    path.write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    return path
