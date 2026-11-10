"""開發紀錄文件 record.md：每次狀態變更就重新產生（即時累積），8 個固定章節。

敘述與證據分離：第 5、6 章的事實區塊全部由 runner 依證據產生並引用 E-xxx；書記官的敘述只放在標明的「結論」行，
且同樣必須引用證據編號（由 checks.narrative_violations 檢查）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .config import Settings
from .db import Store
from .models import DOC_DRAFT, AgentRun, Evidence, State, Task, TaskEvent

CHAPTERS = [
    "1. 文件資訊", "2. 目標與範圍", "3. 執行歷程", "4. 設計與變更說明", "5. 驗證證據", "6. 審查紀錄",
    "7. 問題與教訓", "8. 附錄：證據清冊",
]
ROLE_OF_STATE = {
    "INBOX": "Runner", "PLAN": "指揮官（planner）", "SPEC_REVIEW": "規格審查者", "GATE": "Runner",
    "EXEC": "指揮官（executor）", "VERIFY": "Runner", "REVIEW": "交付審查者", "LEARN": "書記官",
    "WAIT_HUMAN": "David", "HALT": "Runner", "DONE": "—",
}
VERSION = "0.4"


class _Fig:
    def __init__(self) -> None:
        self.n = 0

    def img(self, ev: Evidence, alt: str) -> list[str]:
        self.n += 1
        return [f"![圖 {self.n}]({ev.path})", f"*圖 {self.n}：{alt}（{ev.id}）*"]


def _fmt(ts: datetime | None) -> str:
    return ts.astimezone().strftime("%Y-%m-%d %H:%M:%S") if ts else "—"


def mermaid_flow(events: list[TaskEvent]) -> str:
    seen: dict[tuple[str, str], int] = {}
    for e in events:
        if e.kind == "transition" and e.from_state and e.to_state:
            seen[(e.from_state, e.to_state)] = seen.get((e.from_state, e.to_state), 0) + 1
    lines = ["flowchart LR"]
    for (a, b), n in seen.items():
        label = f"|{n} 次|" if n > 1 else ""
        lines.append(f"    {a}([{a}]) -->{label} {b}([{b}])")
    if len(lines) == 1:
        lines.append("    INBOX([INBOX])")
    return "\n".join(lines) + "\n"


def _timeline(events: list[TaskEvent], runs: list[AgentRun]) -> list[str]:
    trans = [e for e in events if e.kind == "transition"]
    rows = ["| # | 狀態 | 開始 | 結束 | 負責角色 | 模型 | agent 耗時（秒） |", "|---|---|---|---|---|---|---|"]
    created = next((e for e in events if e.kind == "created"), None)
    starts: list[tuple[str, datetime]] = []
    if created:
        starts.append(("INBOX", created.ts))
    for e in trans:
        if e.to_state:
            starts.append((e.to_state, e.ts))
    for i, (st, ts) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else None
        step = i  # transition 次數＝進入該狀態時的 step
        rs = [r for r in runs if r.state == st and r.step == step]
        model = "、".join(sorted({r.model or r.backend for r in rs})) or "—"
        dur = f"{sum(r.duration_s for r in rs):.1f}" if rs else "—"
        rows.append(f"| {i + 1} | {st} | {_fmt(ts)} | {_fmt(end)} | {ROLE_OF_STATE.get(st, '')} | {model} | {dur} |")
    return rows


async def render_record(settings: Settings, store: Store, task: Task) -> Path:
    events = await store.events(task.id)
    runs = await store.runs(task.id)
    evs = await store.evidence(task.id)
    by_id = {e.id: e for e in evs}
    meta = task.meta
    fig = _Fig()
    approved = task.doc_status != DOC_DRAFT

    fm = {
        "id": task.id, "title": task.title, "doc_status": task.doc_status, "version": VERSION,
        "state": task.state.value, "risk": task.risk, "cost_usd": round(task.cost_usd, 6),
        "human_touches": task.human_touches,
        "approved_by": task.doc_approved_by,
        "approved_at": task.doc_approved_at.isoformat() if task.doc_approved_at else None,
    }
    md: list[str] = ["---", yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip(), "---", ""]
    if approved:
        md += [f"> [!success] {task.doc_status}（核可人：{task.doc_approved_by}，時間：{_fmt(task.doc_approved_at)}）", ""]
    else:
        md += [f"> [!warning] {DOC_DRAFT}", ""]
    md += [f"# 開發紀錄：{task.title}（{task.id}）", ""]

    # 1
    created = events[0].ts if events else None
    md += [f"## {CHAPTERS[0]}", "", "| 欄位 | 內容 |", "|---|---|",
           f"| 編號 | {task.id} |", f"| 任務 | {task.title} |", f"| 日期 | {_fmt(created)} |",
           f"| 版本 | {VERSION}（step {task.step}） |", f"| 狀態 | {task.state.value} |",
           f"| 文件狀態 | {task.doc_status} |", f"| 風險等級 | {task.risk or '未判定'} |",
           f"| 成本（USD，用戶端估算） | {task.cost_usd:.4f} |", f"| 人工介入次數 | {task.human_touches} |",
           f"| 上層任務 | {task.parent_id or '—'}（深度 {task.depth}） |", ""]
    # 2
    spec_md = str(task.plan.get("spec_md", "")).strip()
    md += [f"## {CHAPTERS[1]}", "", "以下引自規格 `specs/" + task.id + ".md`：", ""]
    md += [("> " + ln) if ln else ">" for ln in (spec_md or "（尚未規劃）").splitlines()] + [""]
    if task.risk_reasons:
        md += ["風險判定理由（程式判定）：", "", *[f"- {r}" for r in task.risk_reasons], ""]
    # 3
    md += [f"## {CHAPTERS[2]}", "", *_timeline(events, runs), ""]
    # 4
    md += [f"## {CHAPTERS[3]}", ""]
    mm = by_id.get(meta.get("mermaid_ev", ""))
    md += ["### 4.1 流程圖（Mermaid）", "", "```mermaid", mermaid_flow(events).rstrip(), "```", ""]
    mimg = by_id.get(meta.get("mermaid_img_ev", ""))
    if mimg:
        md += [*fig.img(mimg, "本任務實際經過的狀態流程（Mermaid 轉圖）"), ""]
    if mm:
        md += [f"Mermaid 原始碼：[{mm.id}]({mm.path})", ""]
    scribe: dict[str, Any] = meta.get("scribe", {})
    if scribe.get("design_notes"):
        md += ["### 4.2 設計說明", "", str(scribe["design_notes"]).strip(), ""]
    ds = by_id.get(meta.get("diffstat_ev", ""))
    md += ["### 4.3 變更檔案與 diff 統計", ""]
    if ds:
        text = (settings.record_dir(task.id) / ds.path).read_text(encoding="utf-8")
        md += ["```text", text.rstrip() or "（無變更）", "```", f"來源：[{ds.id}]({ds.path})", ""]
    else:
        md += ["（尚無）", ""]
    chart = by_id.get(meta.get("runs_chart_ev", ""))
    csv_ev = by_id.get(meta.get("runs_csv_ev", ""))
    if chart:
        md += ["### 4.4 成本與耗時", "", *fig.img(chart, "各次 agent 呼叫的成本與耗時"), ""]
        if csv_ev:
            md += [f"資料來源：[{csv_ev.id}]({csv_ev.path})", ""]
    # 5
    md += [f"## {CHAPTERS[4]}", ""]
    verify_runs: list[dict[str, Any]] = meta.get("verify_runs", [])
    last = verify_runs[-1] if verify_runs else None
    notes = {n.get("criterion"): n.get("conclusion") for n in scribe.get("verification_notes", [])}
    for i, cmd in enumerate(task.accept_cmds, start=1):
        md += [f"### 5.{i} 驗收標準 {i}：`{cmd}`", ""]
        res = next((r for r in (last or {}).get("cmds", []) if r["cmd"] == cmd), None)
        if res is None:
            md += ["（尚未執行驗證）", ""]
            continue
        txt, img = by_id.get(res["txt"]), by_id.get(res.get("img", ""))
        ok = "通過" if res["exit"] == 0 else "未通過"
        md += [f"- 指令：`{cmd}`", f"- 結果：exit {res['exit']}，{ok}（{res['txt']}）",
               f"- 原始檔：[{res['txt']}]({txt.path if txt else ''})", ""]
        if img:
            md += [*fig.img(img, f"驗收標準 {i} 的終端輸出"), ""]
        if cmd in notes:
            md += [f"**結論**：{notes[cmd]}", ""]
    extra = (last or {}).get("checks", [])
    if extra:
        md += [f"### 5.{len(task.accept_cmds) + 1} Runner 附加檢查", ""]
        for c in extra:
            md += [f"- {c['name']}：{'通過' if c['ok'] else '未通過'}（{c['txt']}）"]
        md += [""]
    if len(verify_runs) > 1:
        md += [f"### 5.{len(task.accept_cmds) + 2} 先前的驗證嘗試", ""]
        for j, vr in enumerate(verify_runs[:-1], start=1):
            ids = "、".join(r["txt"] for r in vr.get("cmds", []))
            md += [f"- 第 {j} 次：{'通過' if vr.get('ok') else '未通過，退回 EXEC'}（{ids}）"]
        md += [""]
    # 6
    md += [f"## {CHAPTERS[5]}", ""]
    rnotes = {n.get("stage"): n.get("conclusion") for n in scribe.get("review_notes", [])}
    reviews: dict[str, list[dict[str, Any]]] = meta.get("reviews", {})
    for k, (stage, name) in enumerate((("spec_review", "規格審查"), ("review", "交付審查")), start=1):
        md += [f"### 6.{k} {name}", ""]
        items = reviews.get(stage, [])
        if not items:
            md += ["（尚未進行）", ""]
            continue
        for j, rv in enumerate(items, start=1):
            findings = "；".join(rv.get("findings") or []) or "無"
            action = "放行" if rv["verdict"] == "pass" else ("退回 PLAN" if stage == "spec_review" else "退回 EXEC")
            md += [f"- 第 {j} 次結論：{rv['verdict']}（{rv['ev']}）", f"- 發現：{findings}（{rv['ev']}）",
                   f"- 處置：{action}（{rv['ev']}）", ""]
        if stage in rnotes:
            md += [f"**結論**：{rnotes[stage]}", ""]
    # 7
    md += [f"## {CHAPTERS[6]}", ""]
    if scribe.get("issues_lessons"):
        md += [str(scribe["issues_lessons"]).strip(), ""]
    md += [f"- 重試次數：{task.retries}", f"- HALT 原因：{task.halt_reason or '無'}"]
    for e in events:
        if e.kind in {"followup_dropped", "notify", "narrative_uncited", "install"}:
            md.append(f"- {e.kind}：{e.detail.get('message', e.detail)}")
    md += [""]
    # 8
    md += [f"## {CHAPTERS[7]}", "", "| 證據編號 | 檔名 | SHA-256 | 產生時間 | 產生者 |", "|---|---|---|---|---|"]
    for e in evs:
        md.append(f"| {e.id} | {e.path} | {e.sha256} | {_fmt(e.created_at)} | {e.producer} |")
    md.append("")

    path = settings.record_dir(task.id) / "record.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(md), encoding="utf-8")
    return path


def is_closed(task: Task) -> bool:
    return task.state == State.DONE
