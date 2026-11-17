"""派工成效：各角色 × 模型的呼叫次數、花費、失敗數，以及執行者模型的「一次過」與「升級」比例。

資料來自 DB 的 agent_runs 與 tasks（純函式，測試不需要 DB）。只回答「派給誰、花多少、做得好不好」，
不改任何派工設定；要調整模型請用 LEGION_MODEL_<角色>。
"""
from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel

from .models import AgentRun, State, Task


class RoleModelUsage(BaseModel):
    role: str
    model: str
    calls: int
    failed: int
    cost_usd: float
    avg_cost_usd: float
    avg_s: float


class ExecutorOutcome(BaseModel):
    model: str          # 這個任務第一次執行用的模型
    tasks: int          # 已結束（DONE 或 HALT）的任務數
    first_pass: int     # 只執行 1 次就 DONE
    retried: int        # 有重做（第 2 次起的執行；含逾時或 CLI 錯誤後重跑，不一定換了模型）
    done: int

    @property
    def first_pass_rate(self) -> float:
        return self.first_pass / self.tasks if self.tasks else 0.0


def _model(run: AgentRun) -> str:
    return run.model or "(CLI 預設)"


def usage_by_role_model(runs: list[AgentRun], backend: str | None = "claude") -> list[RoleModelUsage]:
    """backend=None 表示不篩選（含 mock）。依花費由高到低排序。"""
    agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for r in runs:
        if backend is not None and r.backend != backend:
            continue
        a = agg[(r.role, _model(r))]
        a[0] += 1
        a[1] += r.status != "completed"
        a[2] += r.cost_usd
        a[3] += r.duration_s
    out = [RoleModelUsage(role=role, model=model, calls=int(n), failed=int(f), cost_usd=round(c, 4),
                          avg_cost_usd=round(c / n, 4), avg_s=round(s / n, 1))
           for (role, model), (n, f, c, s) in agg.items()]
    return sorted(out, key=lambda u: (-u.cost_usd, u.role, u.model))


def executor_outcomes(runs: list[AgentRun], tasks: list[Task], backend: str | None = "claude") -> list[ExecutorOutcome]:
    """只看已結束的任務；依第一次執行的模型分組。"""
    finished = {t.id: t for t in tasks if t.state in (State.DONE, State.HALT)}
    by_task: dict[str, list[AgentRun]] = defaultdict(list)
    for r in runs:
        if r.role == "executor" and r.task_id in finished and (backend is None or r.backend == backend):
            by_task[r.task_id].append(r)
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for tid, rs in by_task.items():
        rs.sort(key=lambda r: r.step)  # 穩定排序：同 step 保持 DB id 順序
        done = finished[tid].state == State.DONE
        a = agg[_model(rs[0])]
        a[0] += 1
        a[1] += done and len(rs) == 1
        a[2] += len(rs) > 1
        a[3] += done
    return [ExecutorOutcome(model=m, tasks=n, first_pass=fp, retried=esc, done=d)
            for m, (n, fp, esc, d) in sorted(agg.items())]


def render(usage: list[RoleModelUsage], outcomes: list[ExecutorOutcome], labels: dict[str, str]) -> str:
    if not usage:
        return "還沒有真實呼叫紀錄（mock 不算；加 --all 可一起看）。"
    total = sum(u.cost_usd for u in usage) or 1.0
    lines = ["角色\t模型\t次數\t失敗\t花費\t每次\t平均秒數\t佔比"]
    for u in usage:
        lines.append(f"{labels.get(u.role, u.role)}\t{u.model}\t{u.calls}\t{u.failed}\t${u.cost_usd:.4f}\t"
                     f"${u.avg_cost_usd:.4f}\t{u.avg_s}\t{u.cost_usd / total:.0%}")
    lines.append(f"合計\t\t{sum(u.calls for u in usage)}\t{sum(u.failed for u in usage)}\t"
                 f"${sum(u.cost_usd for u in usage):.4f}")
    if outcomes:
        lines += ["", "執行者（依第一次執行的模型；只算已結束任務）", "模型\t任務\t一次過\t一次過比例\t有重做\t最後 DONE"]
        for o in outcomes:
            lines.append(f"{o.model}\t{o.tasks}\t{o.first_pass}\t{o.first_pass_rate:.0%}\t{o.retried}\t{o.done}")
        lines.append("（一次過＝只執行 1 次就 DONE；分母含所有 HALT，包括預算熔斷與人工取消）")
    models = {u.model for u in usage}
    aliases = sorted(a for a in ("opus", "sonnet", "haiku") if a in models
                     and any(m.startswith(f"claude-{a}-") for m in models))
    if aliases:
        lines.append(f"（{'、'.join(aliases)} 是舊紀錄存的別名，和 claude-{aliases[0]}-… 可能是同一個模型，分列是因為紀錄方式不同）")
    if "(CLI 預設)" in models:
        lines.append("（(CLI 預設)＝沒有指定模型，或舊版失敗紀錄沒有記下模型）")
    return "\n".join(lines)
