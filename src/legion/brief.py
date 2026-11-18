"""每日晨報：用程式彙整「等你處理的事」，產生一份晨報檔與一行摘要（給手機推播）。

不呼叫任何 agent、不花額度；結果只取自 DB、花費帳本與 git，可重現、可測試。
"""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import ATTRIBUTION, ledger
from .cleanup import plan as cleanup_plan
from .config import Settings
from .db import Store, utcnow
from .models import State, Task


def _branch_pending_merge(repo: str, branch: str) -> bool:
    """分支存在、且還沒併入該 repo 目前的 HEAD。"""
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=30, check=False)

    if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode != 0:
        return False
    return git("merge-base", "--is-ancestor", branch, "HEAD").returncode != 0


def _worktree_dirty(worktree: str | None) -> bool:
    if not worktree or not Path(worktree).exists():
        return False
    out = subprocess.run(["git", "-C", worktree, "status", "--porcelain"], capture_output=True, text=True,
                         timeout=30, check=False)
    return out.returncode == 0 and bool(out.stdout.strip())


def collect(settings: Settings, tasks: list[Task], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    now = utcnow()
    waiting = [{"id": t.id, "title": t.title, "reason": t.wait_reason or ""} for t in tasks if t.state == State.WAIT_HUMAN]
    recent_halts = [
        {"id": t.id, "title": t.title, "reason": (t.halt_reason or "")[:120]}
        for t in tasks
        if t.state == State.HALT and not (t.halt_reason or "").startswith("operator_cancel")
        and t.updated_at is not None and now - t.updated_at <= timedelta(hours=36)
    ]
    # 待 merge：完成的可寫任務，分支還沒併入目標 repo；同一戰役只列最後一個（它包含前面的變更）
    done_writes = [t for t in tasks if t.state == State.DONE and t.kind == "write" and t.repo]
    last_in_mission: dict[str, Task] = {}
    singles: list[Task] = []
    for t in done_writes:
        name = (t.meta.get("mission") or {}).get("name")
        if name:
            if name not in last_in_mission or t.id > last_in_mission[name].id:
                last_in_mission[name] = t
        else:
            singles.append(t)
    pending = []
    for t in [*singles, *last_in_mission.values()]:
        if _branch_pending_merge(str(t.repo), f"legion/{t.id}"):
            pending.append({"id": t.id, "branch": f"legion/{t.id}", "title": t.title, "note": ""})
        elif _worktree_dirty(t.worktree):
            # agent 沒有自己 commit：成果只在 worktree，分支上看不到，不列出就會被漏掉
            pending.append({"id": t.id, "branch": f"legion/{t.id}", "title": t.title,
                            "note": f"成果未提交，在 worktree：{Path(t.worktree or '').name}"})
    missions: dict[str, dict[str, Any]] = {}
    for t in tasks:
        m = t.meta.get("mission")
        if m:
            row = missions.setdefault(m["name"], {"tasks": 0, "spent": 0.0, "budget": m["budget_usd"], "last": t})
            row["tasks"] += 1
            row["spent"] += t.cost_usd
            if t.id > row["last"].id:
                row["last"] = t
    mission_rows = [{"name": k, "tasks": v["tasks"], "spent": round(v["spent"], 4), "budget": v["budget"],
                     "last": v["last"].id, "state": v["last"].state.value,
                     "outcome": v["last"].meta.get("mission_outcome") or ""} for k, v in sorted(missions.items())]
    # 可清理：已併入且乾淨的分支與 worktree（只列出；刪除要人跑 legion cleanup --apply）
    cleanable = [r["id"] for r in cleanup_plan(settings, tasks)["remove"]]
    cost_today = ledger.total_on(settings.cost_ledger, today, settings.schema_name)
    cost_yday = ledger.total_on(settings.cost_ledger, today - timedelta(days=1), settings.schema_name)
    return {"date": today.isoformat(), "waiting": waiting, "recent_halts": recent_halts, "pending_merge": pending,
            "missions": mission_rows, "cleanable": cleanable, "cost_today": round(cost_today, 4), "cost_yesterday": round(cost_yday, 4),
            "daily_budget": settings.daily_budget_usd}


def headline(b: dict[str, Any]) -> str:
    """一行摘要（≤ 180 字），先講要你動手的事。"""
    parts = []
    if b["waiting"]:
        ids = "、".join(w["id"] for w in b["waiting"][:3])
        parts.append(f"{len(b['waiting'])} 件等你處理（{ids}）")
    if b["recent_halts"]:
        parts.append(f"{len(b['recent_halts'])} 件停下（{'、'.join(h['id'] for h in b['recent_halts'][:3])}）")
    if b["pending_merge"]:
        parts.append(f"{len(b['pending_merge'])} 個分支待 merge")
    if b.get("cleanable"):
        parts.append(f"{len(b['cleanable'])} 項可清理")
    todo = "；".join(parts) if parts else "無待辦"
    text = f"legion 晨報：{todo}；昨日花費 ${b['cost_yesterday']:.2f}"
    return text[:180]


def render(b: dict[str, Any]) -> str:
    lines = [f"# legion 晨報 {b['date']}", "", f"**{headline(b)}**", ""]
    lines += ["## 等你處理", *([f"- {w['id']} {w['title']}：{w['reason']}（見 [[questions/{w['id']}]]）"
                                for w in b["waiting"]] or ["- （無）"]), ""]
    lines += ["## 最近 36 小時停下的任務", *([f"- {h['id']} {h['title']}：{h['reason']}" for h in b["recent_halts"]]
                                       or ["- （無）"]), ""]
    lines += ["## 待 merge 的分支（檢查後自行 merge）",
              *([f"- `{p['branch']}`：{p['title']}" + (f"（{p['note']}）" if p.get("note") else "")
                 for p in b["pending_merge"]] or ["- （無）"]), ""]
    lines += ["## 可清理（已併入且乾淨；同意後跑 `legion cleanup --apply`）",
              *([f"- `legion/{i}` 與它的 worktree" for i in b.get("cleanable", [])] or ["- （無）"]), ""]
    lines += ["## 戰役", *([f"- {m['name']}：{m['tasks']} 個任務、${m['spent']:.2f}／${float(m['budget']):.2f}，"
                          f"最後 {m['last']}（{m['state']}{'，' + m['outcome'] if m['outcome'] else ''}）"
                          for m in b["missions"]] or ["- （無）"]), ""]
    lines += ["## 花費", f"- 昨日 ${b['cost_yesterday']:.4f}　今日至今 ${b['cost_today']:.4f}　每日上限 ${b['daily_budget']:.2f}",
              "", f"_產生時間 {datetime.now().astimezone().isoformat(timespec='seconds')}；資料來源：DB、花費帳本、git_",
              "", f"_由 {ATTRIBUTION} 產生_"]
    return "\n".join(lines) + "\n"


async def build(settings: Settings, store: Store, today: date | None = None) -> tuple[dict[str, Any], Path]:
    b = collect(settings, await store.list_tasks(), today)
    path = settings.ai_dir / "reports" / f"brief-{b['date']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(b), encoding="utf-8", newline="\n")
    from .motion import write_dashboard  # 晨報順便更新 Obsidian 儀表.md 上方的 KPI 卡（附屬功能，失敗不影響晨報）

    try:
        await write_dashboard(settings, store, brief=b)
    except OSError as e:
        b["dashboard_error"] = str(e)
    from .plan_motion import write_plan  # 計畫動態圖也跟著 inbox 重產（附屬功能，失敗不影響晨報；錯誤由 CLI 印出）

    try:
        write_plan(settings)
    except (OSError, ValueError) as e:
        b["plan_error"] = str(e)
    b["headline"] = headline(b)
    b["file"] = str(path)
    return b, path
