"""Runner：`legion tick` 執行一輪，每個任務前進一步；可重入、可中斷續跑。

判斷交給 LLM（怎麼拆、怎麼做），邊界交給程式（能不能做、花多少、何時停）。
- 狀態轉移與 task_events 在同一交易；agent_run 與成本在同一交易，續跑時重用已完成的 run，不重複扣預算。
- VERIFY 由 runner 親自執行驗收指令，不採信 agent 自述。
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import ledger, prompts, vault
from .agents import REVIEWER_ROLES, AgentBackend, AgentCall, AgentError, AgentFailure, AgentTimeout
from .checks import narrative_violations
from .config import Settings
from .db import Store, utcnow
from .evidence import EvidenceStore, render_mermaid, render_runs_chart, render_terminal, snapshot_hashes
from .installs import Installer, RecordingInstaller, append_ledger, canonical_argv, classify
from .models import (
    DOC_APPROVED,
    PAUSED_STATES,
    RISK_ORDER,
    TERMINAL_STATES,
    AgentRun,
    InstallRequest,
    State,
    Task,
    max_risk,
)
from .record import mermaid_flow, render_record
from .risk import (
    added_lines_by_file,
    assess,
    assess_diff,
    collection_risks,
    failure_signature,
    is_test_path,
    out_of_scope,
    protected_test_violations,
)

_GITQ = ["-c", "core.quotepath=false"]  # 中文檔名不加引號，路徑比對才準確


class Halt(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _crash_point(state: str, point: str) -> None:
    """測試用：環境變數 LEGION_CRASH_AT=STATE:point 時直接殺掉行程（模擬中途被中斷）。"""
    if os.environ.get("LEGION_CRASH_AT") == f"{state}:{point}":
        os._exit(17)


async def git(args: list[str], cwd: Path, check: bool = True) -> str:
    def go() -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=300)

    proc = await asyncio.to_thread(go)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{proc.stderr.strip()[-400:]}")
    return proc.stdout


def normalize_cmd(cmd: str) -> list[str]:
    """把驗收指令轉成 argv：python／py -3.x／pytest 一律換成目前 venv 的 python，pytest 關閉快取避免寫檔。"""
    argv = shlex.split(cmd.replace("\\", "/"), posix=True)
    if not argv:
        raise ValueError("空的驗收指令")
    if argv[0] == "py":
        argv = argv[2:] if len(argv) > 1 and argv[1].startswith("-3") else argv[1:]
        argv = [sys.executable, *argv]
    elif argv[0] in {"python", "python3"}:
        argv = [sys.executable, *argv[1:]]
    elif argv[0] == "pytest":
        argv = [sys.executable, "-m", "pytest", *argv[1:]]
    if len(argv) >= 3 and argv[1:3] == ["-m", "pytest"] and "no:cacheprovider" not in argv:
        argv += ["-p", "no:cacheprovider"]
    return argv


async def run_cmd(cmd: str, cwd: Path, timeout: int) -> tuple[int, str]:
    argv = normalize_cmd(cmd)
    # 只傳必要的環境變數：驗收指令會跑 agent 寫的測試，輸出會成為證據並進 git，避免機密外洩
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE",
            "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "NUMBER_OF_PROCESSORS",
            "PROCESSOR_ARCHITECTURE", "OS", "USERNAME", "LANG", "PYTHONIOENCODING", "PYTHONUTF8"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def go() -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)

    try:
        proc = await asyncio.to_thread(go)
    except subprocess.TimeoutExpired:
        return 124, f"（逾時 {timeout} 秒）"
    return proc.returncode, (proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")).strip()


class Runner:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        agent: AgentBackend,
        reviewer_agent: AgentBackend | None = None,
        installer: Installer | None = None,
    ) -> None:
        self.s = settings
        self.store = store
        self.agent = agent
        self.reviewer = reviewer_agent or agent
        self.installer = installer or RecordingInstaller()
        self.ev = EvidenceStore(store, settings)
        self.bad_inbox: list[str] = []

    # ------------------------------------------------------------ tick
    async def tick(self) -> dict[str, Any]:
        summary: dict[str, Any] = {"locked": False, "ingested": [], "advanced": {}, "halted": []}
        if not await self.store.try_lock():
            summary["skipped"] = "另一個 tick 正在執行"
            return summary
        summary["locked"] = True
        try:
            if self.s.stop_file.exists():
                summary["halted"] = await self._halt_all("stop_file")
                return summary
            summary["ingested"] = await self.ingest_inbox()
            if self.bad_inbox:
                summary["bad_inbox"] = self.bad_inbox
            active = [t for t in await self.store.list_tasks()
                      if t.state not in TERMINAL_STATES and t.state not in PAUSED_STATES]
            for task in active:
                if self.s.stop_file.exists():
                    summary["halted"] += await self._halt_all("stop_file")
                    break
                before = task.state.value
                try:
                    task = await self.step(task)
                except Halt as h:
                    task = await self._halt(await self.store.get_task(task.id), h.reason)
                except AgentTimeout as exc:
                    task = await self._halt(await self.store.get_task(task.id), f"timeout: {exc}")
                except AgentError as exc:
                    task = await self._halt(await self.store.get_task(task.id), f"agent_error: {exc}")
                except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                    raise
                except Exception as exc:  # noqa: BLE001 — 單張任務出錯不得卡住整個系統：轉 HALT 並保留錯誤
                    task = await self._halt(await self.store.get_task(task.id), f"error: {exc!r}"[:500])
                summary["advanced"][task.id] = f"{before}→{task.state.value}"
        finally:
            await self.store.unlock()
        return summary

    async def _halt_all(self, reason: str) -> list[str]:
        out = []
        for t in await self.store.list_tasks():
            if t.state not in TERMINAL_STATES:
                await self._halt(t, reason)
                out.append(t.id)
        return out

    async def _halt(self, task: Task, reason: str) -> Task:
        if task.state == State.HALT:
            return task
        t = await self.store.transition(task, State.HALT, {"reason": reason}, halt_reason=reason,
                                        return_state=task.state)
        await self._after_change(t)
        return t

    async def _go(self, task: Task, to: State, detail: dict[str, Any] | None = None, **fields: Any) -> Task:
        t = await self.store.transition(task, to, detail, **fields)
        _crash_point(to.value, "after_transition")
        await self._after_change(t)
        return t

    async def _after_change(self, task: Task) -> None:
        vault.export_task(self.s, task)
        await render_record(self.s, self.store, task)

    # ------------------------------------------------------------ INBOX
    async def ingest_inbox(self) -> list[str]:
        created = []
        files, bad = vault.inbox_files(self.s)
        self.bad_inbox = bad  # 壞檔逐檔隔離：略過並回報，不影響其他想法與任務
        for path, sha, fm, body in files:
            if await self.store.has_source(sha):
                continue
            if "mock" in fm and getattr(self.agent, "name", "") != "mock":
                # 帶 mock 劇本的想法檔只給 MockAgent；真實 backend 一律跳過，避免 demo 檔被真實 agent 領取花錢
                continue
            title = str(fm.get("title") or next((ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()),
                                                path.stem))
            try:
                kind = fm.get("kind", "write")
                if kind not in {"readonly", "write"}:
                    raise ValueError(f"kind 必須是 readonly 或 write：{kind!r}")
                task = Task(
                    id="pending", title=title, body=body.strip(), kind=kind,
                    parent_id=fm.get("parent_id"), depth=int(fm.get("depth", 0)), repo=fm.get("repo"),
                    subdir=fm.get("subdir"), source_path=str(path), source_sha=sha,
                    meta={**({"mock": fm["mock"]} if "mock" in fm else {}),
                          **({"risk_floor": fm["risk_floor"]} if fm.get("risk_floor") in RISK_ORDER else {}),
                          # 以下兩個欄位只能由人寫在想法檔：agent 無法替自己放寬
                          **({"allow_test_changes": True} if fm.get("allow_test_changes") is True else {}),
                          **({"allowed_paths": [str(p) for p in fm["allowed_paths"]]}
                             if isinstance(fm.get("allowed_paths"), list) else {})},
                )
            except (ValueError, TypeError, ValidationError) as exc:
                self.bad_inbox.append(f"{path.name}: {exc}")
                continue
            tid = await self.store.next_task_id(self.s.task_prefix, vault.existing_ids(self.s, self.s.task_prefix))
            task = await self.store.insert_task(task.model_copy(update={"id": tid}))
            # 領取後封存：避免 DB 重建後被重複領取（重複花費）
            done_dir = self.s.ai_dir / "inbox_done"
            done_dir.mkdir(parents=True, exist_ok=True)
            archived = done_dir / f"{tid}__{path.name}"
            path.replace(archived)
            task = await self.store.update_task(tid, source_path=str(archived))
            await self._after_change(task)
            created.append(tid)
        return created

    # ------------------------------------------------------------ dispatch
    async def step(self, task: Task) -> Task:
        handler = {
            State.INBOX: self._inbox, State.PLAN: self._plan, State.SPEC_REVIEW: self._spec_review,
            State.GATE: self._gate, State.EXEC: self._exec, State.VERIFY: self._verify,
            State.REVIEW: self._review, State.LEARN: self._learn,
        }[task.state]
        return await handler(task)

    async def _inbox(self, task: Task) -> Task:
        return await self._go(task, State.PLAN)

    # ------------------------------------------------------------ agent 呼叫（可重入）
    async def _check_budget(self, task: Task) -> float:
        if task.cost_usd >= self.s.task_budget_usd:
            raise Halt(f"budget_task: {task.cost_usd:.4f} ≥ {self.s.task_budget_usd}")
        # DB 可能重建過：取 DB 與持久帳本的較大者，避免每日預算低估
        today = max(await self.store.cost_on(date.today()),
                    ledger.total_on(self.s.cost_ledger, date.today(), self.s.schema_name,
                                    real_account=getattr(self.agent, "name", "") != "mock"))
        if today >= self.s.daily_budget_usd:
            raise Halt(f"budget_daily: {today:.4f} ≥ {self.s.daily_budget_usd}")
        return min(self.s.task_budget_usd - task.cost_usd, self.s.daily_budget_usd - today)

    def _ledger(self, task: Task, role: str, backend: str, model: str | None, session_id: str, status: str,
                cost: float) -> None:
        if backend == "mock" and not self.s.ledger_include_mock:
            return
        ledger.append_cost(self.s.cost_ledger, schema=self.s.schema_name, task=task.id, role=role, backend=backend,
                           model=model, session_id=session_id, status=status, cost_usd=cost)

    async def _save_prompt(self, task: Task, role: str, prompt: str) -> None:
        """提示存證：全文存在本機 .legion_tmp/prompts/（gitignore，不進 vault、不推上 GitHub），
        vault 證據只留 SHA-256、長度與本機路徑。提示可能含目標 repo 的完整 diff 或程式碼，不能 commit。"""
        sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        local = self.s.prompt_dir / task.id / f"step{task.step:03d}_{role}.md"
        local.parent.mkdir(parents=True, exist_ok=True)
        if not local.exists():  # 續跑時保留第一版，與證據雜湊一致
            local.write_text(prompt, encoding="utf-8")
        digest = (f"role: {role}\nstep: {task.step}\nsha256: {sha}\nchars: {len(prompt)}\n"
                  f"local_copy: {local}\n（全文不進 git；以 sha256 對照本機副本）\n")
        await self.ev.add_text(task, task.step, f"prompt_{role}", digest, f"{role} 提示雜湊（全文存本機）",
                               producer="runner", kind="text", ext="txt")

    async def _agent(self, task: Task, role: str, prompt: str, cwd: Path, add_dirs: list[Path] | None = None,
                     save_prompt: bool = True) -> dict[str, Any]:
        existing = await self.store.find_run(task.id, task.state.value, task.step, role)
        if existing is not None:  # 續跑：上次已完成並已扣款，直接重用
            return existing.output
        if self.s.stop_file.exists():  # 每次呼叫 agent 前都檢查，不只在 tick 開頭
            raise Halt("stop_file")
        remaining = await self._check_budget(task)
        if save_prompt:
            await self._save_prompt(task, role, prompt)
        _crash_point(task.state.value, "before_agent")
        backend = self.reviewer if role in REVIEWER_ROLES else self.agent
        attempt = len([r for r in await self.store.runs(task.id) if r.role == role])
        call = AgentCall(role=role, prompt=prompt, cwd=cwd, schema=prompts.SCHEMAS[role], task=task,
                         attempt=attempt, timeout_s=self.s.call_timeout_s, budget_usd=max(remaining, 0.01),
                         add_dirs=add_dirs or [])
        started = utcnow()
        try:
            res = await backend.run(call)
        except AgentFailure as exc:
            # 失敗或逾時也要把花費入帳，避免預算熔斷低估。帳本先寫：崩潰時寧可多記，不可漏記
            self._ledger(task, role, backend.name, None, exc.session_id or "(none)",
                         "timeout" if isinstance(exc, AgentTimeout) else "error", exc.cost_usd)
            await self.store.record_run(AgentRun(
                task_id=task.id, state=task.state.value, step=task.step, role=role, backend=backend.name,
                session_id=exc.session_id or "(none)", cost_usd=exc.cost_usd, duration_s=exc.duration_s,
                status="timeout" if isinstance(exc, AgentTimeout) else "error", output={"error": str(exc)[:500]},
                started_at=started,
            ))
            raise
        self._ledger(task, role, res.backend, res.model, res.session_id, "completed", res.cost_usd)
        await self.store.record_run(AgentRun(
            task_id=task.id, state=task.state.value, step=task.step, role=role, backend=res.backend,
            model=res.model, session_id=res.session_id, cost_usd=res.cost_usd, duration_s=res.duration_s,
            output=res.output, started_at=started,
        ))
        _crash_point(task.state.value, "after_agent")
        fresh = await self.store.get_task(task.id)
        if fresh.cost_usd > self.s.task_budget_usd:
            raise Halt(f"budget_task: {fresh.cost_usd:.4f} > {self.s.task_budget_usd}")
        return res.output

    # ------------------------------------------------------------ 路徑
    def _worktree_path(self, task: Task) -> Path:
        return self.s.worktrees_dir / task.id

    def _workdir(self, task: Task) -> Path:
        if task.repo is None:
            raise Halt("no_repo: 任務沒有指定 repo")
        base = Path(task.worktree) if (task.kind == "write" and task.worktree) else Path(task.repo)
        return base / task.subdir if task.subdir else base

    async def _ensure_worktree(self, task: Task) -> Task:
        if task.kind != "write" or task.worktree:
            return task
        if task.repo is None:
            raise Halt("no_repo: 任務沒有指定 repo")
        wt = self._worktree_path(task)
        repo = Path(task.repo)
        if not wt.exists():
            self.s.worktrees_dir.mkdir(parents=True, exist_ok=True)
            branch = f"legion/{task.id}"
            exists = (await git(["branch", "--list", branch], repo)).strip()
            args = ["worktree", "add", str(wt), branch] if exists else ["worktree", "add", "-b", branch, str(wt), "HEAD"]
            await git(args, repo)
        base = (await git(["rev-parse", "HEAD"], wt)).strip()
        return await self.store.update_task(task.id, worktree=str(wt), base_commit=base)

    def _allowed_prefixes(self, repo: Path) -> list[str]:
        """repo 內允許 runner 自己寫入的區域（vault/AI、install ledger），比對 worktree 外變更時排除。"""
        out = []
        # cost_ledger 與 vault/.obsidian（Obsidian 開啟時會寫入）也排除，避免 legion 自身任務被誤判為修改
        for p, is_dir in ((self.s.ai_dir, True), (self.s.inbox_dir, True), (self.s.install_ledger, False),
                          (self.s.cost_ledger, False), (self.s.vault / ".obsidian", True)):
            try:
                rel = p.resolve().relative_to(repo.resolve()).as_posix()
                out.append(rel + "/" if is_dir else rel)
            except ValueError:
                continue
        return out

    async def _repo_state(self, repo: Path) -> dict[str, str]:
        head = (await git(["rev-parse", "HEAD"], repo)).strip()
        status = await git(["status", "--porcelain", "--untracked-files=all"], repo)
        allowed = self._allowed_prefixes(repo)
        lines = [ln for ln in status.splitlines()
                 if not any(ln[3:].strip('"').startswith(a) for a in allowed)]
        return {"head": head, "status": "\n".join(sorted(lines))}

    def _report_path(self, task: Task) -> str:
        return (self.s.ai_dir / "reports" / f"{task.id}-report.md").resolve().as_posix()

    # ------------------------------------------------------------ PLAN
    async def _plan(self, task: Task) -> Task:
        wd = self._workdir(task) if task.repo else self.s.ai_dir
        desc = f"{wd}（{task.kind}）"
        prev = (task.meta.get("reviews", {}).get("spec_review") or [{}])[-1]
        prior = ([str(f) for f in prev.get("findings", []) or []]
                 if prev and prev.get("verdict") != "pass" else [])  # 與 _spec_review 一致：非 pass 即退回
        out = await self._agent(task, "planner", prompts.planner_prompt(
            task, self.s.commander_preamble, desc, self._report_path(task), prior), wd)
        # agent 輸出一律視為不可信：型別不符就以保守值處理
        accept = [str(c).replace("\\", "/") for c in (out.get("accept_cmds") or []) if isinstance(c, str)]
        proposed = out.get("risk_proposed")
        if proposed not in RISK_ORDER:
            proposed = "high"
        actions_raw = out.get("actions") or []
        out = {**out, "risk_proposed": proposed,
               "actions": [a for a in actions_raw if isinstance(a, dict)] if isinstance(actions_raw, list) else []}
        if task.kind == "readonly":  # 唯讀任務的產出是報告：由 runner 以程式檢查報告存在且章節齊全
            rp = self._report_path(task)
            accept = [c for c in accept if "legion.checks report" not in c]  # 規劃者自己抄的不算，只留 runner 版本
            accept.append(f'python -m legion.checks report "{rp}" --section 架構 --section 測試缺口 --verify-refs'
                          f' --min-refs {self.s.report_min_refs}')
        actions = list(out.get("actions", []))
        planned_installs = list(out.get("installs", []) or [])
        lvls = []
        for r in planned_installs:
            try:
                lvls.append(classify(InstallRequest.model_validate(r)).level)
            except ValidationError:
                lvls.append("ask")
        risk, reasons = assess(out.get("risk_proposed"), actions, accept, task.kind,
                               self._worktree_path(task) if task.kind == "write" else None, lvls)
        floor = task.meta.get("risk_floor")
        if floor in RISK_ORDER and max_risk(risk, floor) != risk:
            risk = max_risk(risk, floor)
            reasons = [*reasons, f"回灌想法涉及 legion 本身，風險下限 {floor}"]
        spec_md = str(out.get("spec_md", ""))
        spec_path = self.s.ai_dir / "specs" / f"{task.id}.md"
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(spec_md + "\n", encoding="utf-8")
        await self.store.update_task(
            task.id, accept_cmds=accept, risk=risk, risk_proposed=out.get("risk_proposed"), risk_reasons=reasons,
            plan={"spec_md": spec_md, "actions": actions, "rationale": out.get("rationale", "")},
        )
        task = await self.store.get_task(task.id)
        if not accept:
            raise Halt("plan_invalid: 沒有驗收指令")
        return await self._go(task, State.SPEC_REVIEW, {"risk": risk})

    # ------------------------------------------------------------ SPEC_REVIEW
    async def _bump_retry(self, task: Task, why: str) -> Task:
        task = await self.store.update_task(task.id, retries=task.retries + 1)
        if task.retries > self.s.max_retries:
            raise Halt(f"retry_exceeded: {why}（{task.retries - 1} 次重試後仍失敗）")
        return task

    async def _save_review(self, task: Task, stage: str, out: dict[str, Any]) -> Task:
        run = await self.store.find_run(task.id, task.state.value, task.step,
                                        "spec_reviewer" if stage == "spec_review" else "reviewer")
        sid = run.session_id if run else "?"
        payload = {k: v for k, v in out.items() if not k.startswith("_")}
        ev = await self.ev.add_text(task, task.step, f"{stage}", json.dumps(payload, ensure_ascii=False, indent=2),
                                    f"{stage} 輸出（session {sid}）", producer=f"runner（記錄 {stage} session {sid}）",
                                    kind="json", ext="json")
        meta = dict(task.meta)
        reviews = dict(meta.get("reviews", {}))
        if any(r.get("ev") == ev.id for r in reviews.get(stage, [])):  # 續跑時不重複記錄
            return task
        reviews[stage] = [*reviews.get(stage, []),
                          {"verdict": out.get("verdict"), "findings": out.get("findings", []), "ev": ev.id,
                           "session": sid}]
        meta["reviews"] = reviews
        return await self.store.update_task(task.id, meta=meta, verdict=str(out.get("verdict")))

    async def _spec_review(self, task: Task) -> Task:
        wd = self._workdir(task) if task.repo else self.s.ai_dir
        out = await self._agent(task, "spec_reviewer",
                                prompts.spec_review_prompt(task, task.plan.get("spec_md", ""), task.accept_cmds,
                                                           self._report_path(task)), wd)
        findings = [str(f) for f in (out.get("findings") or []) if isinstance(f, (str, int, float))]
        if out.get("verdict") == "pass" and any(f.lstrip().startswith("必修") for f in findings):
            # 判定標準是「有必修就 revise」：審查者自相矛盾時以較嚴的一方為準
            out = {**out, "verdict": "revise", "_overridden": "pass 但含必修 finding，runner 改判 revise"}
            await self.store.add_event(task.id, "spec_review_overridden", {"message": out["_overridden"]})
        task = await self._save_review(task, "spec_review", out)
        if out.get("verdict") == "pass":
            return await self._go(task, State.GATE)
        task = await self._bump_retry(task, "規格審查退回")
        return await self._go(task, State.PLAN, {"findings": out.get("findings", [])})

    # ------------------------------------------------------------ GATE
    async def _gate(self, task: Task) -> Task:
        if task.risk == "high":
            vault.write_question(self.s, task, "high 風險任務需使用者核准", task.risk_reasons)
            return await self._go(task, State.WAIT_HUMAN, {"risk": "high"}, wait_reason="high 風險，需核准",
                                  return_state=State.EXEC)
        if task.risk == "mid":
            await self.store.add_event(task.id, "notify", {"message": "mid 風險放行：" + "；".join(task.risk_reasons)})
        return await self._go(task, State.EXEC, {"risk": task.risk})

    # ------------------------------------------------------------ EXEC
    async def _exec(self, task: Task) -> Task:
        task = await self._ensure_worktree(task)
        repo = Path(task.repo) if task.repo else None
        if repo and "baseline" not in task.meta:
            meta = dict(task.meta)
            meta["baseline"] = await self._repo_state(repo)
            task = await self.store.update_task(task.id, meta=meta)
        wd = self._workdir(task)
        pending = task.meta.get("pending_installs")
        if pending and task.meta.get("pending_installs_approved"):
            await self._do_installs(task, [InstallRequest.model_validate(r) for r in pending], wd, approved=True)
            meta = {k: v for k, v in task.meta.items() if k not in {"pending_installs", "pending_installs_approved"}}
            task = await self.store.update_task(task.id, meta=meta)
            return await self._go(task, State.VERIFY)
        out = await self._agent(
            task, "executor",
            prompts.executor_prompt(task, self.s.commander_preamble, task.plan.get("spec_md", ""),
                                    task.meta.get("last_failure")), wd)
        if task.kind == "readonly" and out.get("report_md"):
            rp = self.s.ai_dir / "reports" / f"{task.id}-report.md"
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(str(out["report_md"]), encoding="utf-8")
        reqs_raw = list(out.get("install_requests") or [])
        if reqs_raw:
            reqs: list[InstallRequest] = []
            invalid: list[str] = []
            for r in reqs_raw:
                try:
                    reqs.append(InstallRequest.model_validate(r))
                except ValidationError as exc:
                    invalid.append(f"{r}: {exc.errors()[0]['msg']}")
            if task.install_count + len(reqs_raw) > self.s.install_cap:
                return await self._wait_installs(task, reqs, f"單任務安裝數超過上限 {self.s.install_cap}",
                                                 [f"已安裝 {task.install_count}，本次請求 {len(reqs_raw)}"])
            asks = [(r, classify(r)) for r in reqs]
            asks = [(r, d) for r, d in asks if d.level == "ask"]
            if invalid or asks:
                details = invalid + [f"{r.tool} {r.version}：{'；'.join(d.reasons)}" for r, d in asks]
                return await self._wait_installs(task, reqs, "安裝落在「必須問」等級", details)
            await self._do_installs(task, reqs, wd, approved=False)
        return await self._go(task, State.VERIFY, {"claim": out.get("claim")})

    async def _wait_installs(self, task: Task, reqs: list[InstallRequest], reason: str, details: list[str]) -> Task:
        vault.write_question(self.s, task, reason, details)
        meta = dict(task.meta)
        meta["pending_installs"] = [r.model_dump() for r in reqs]
        task = await self.store.update_task(task.id, meta=meta, risk="high",
                                            risk_reasons=[*task.risk_reasons, f"high: {reason}"])
        return await self._go(task, State.WAIT_HUMAN, {"reason": reason}, wait_reason=reason,
                              return_state=State.EXEC)

    async def _do_installs(self, task: Task, reqs: list[InstallRequest], wd: Path, approved: bool) -> None:
        if task.state != State.EXEC:  # 安裝只能發生在 EXEC
            raise Halt("install_outside_exec")
        done = list(task.meta.get("installed", []))
        n = 0
        for r in reqs:
            key = f"{r.manager}:{r.tool}=={r.version}"
            if key in done:  # 續跑時不重複安裝、不重複寫清冊
                continue
            if canonical_argv(r) is None:
                # MCP／plugin／skill／hook／官方發行檔：runner 不代裝，由使用者手動處理
                await self.store.add_event(task.id, "install", {"message": f"{r.tool}：需使用者手動安裝（runner 不代裝）"})
                continue
            level = "ask" if approved else classify(r).level
            await self.installer.install(r, wd)
            row = append_ledger(self.s.install_ledger, task.id, r, level)
            done.append(key)
            n += 1
            meta = dict((await self.store.get_task(task.id)).meta)
            meta["installed"] = done
            await self.store.update_task(task.id, meta=meta)
            await self.store.add_event(task.id, "install", {"message": f"{r.tool} {r.version}（{row['level']}）",
                                                            **row})
        await self.store.update_task(task.id, install_count=task.install_count + n)

    # ------------------------------------------------------------ VERIFY
    async def _diff_gate(self, task: Task) -> Task | None:
        """依實際 diff 重新判定風險（agent 自報的 actions 可能漏列）；high → WAIT_HUMAN，mid → 記通知。"""
        if task.kind != "write" or not task.worktree:
            return None
        wt = Path(task.worktree)
        base = task.base_commit or "HEAD"
        await git(["add", "-A"], wt)
        ns = await git([*_GITQ, "diff", "--cached", "--name-status", base], wt)
        risk, reasons = assess_diff(ns)
        oos = out_of_scope(ns, self._allowed_paths(task))
        if oos:  # 允許範圍只能由人在想法檔設定（allowed_paths 或 subdir）；超出即需核准
            risk = "high"
            reasons = [*reasons, f"high: 變更超出允許範圍：{'、'.join(oos[:10])}"]
        guard = await self._test_guard_inputs(task)
        if not task.meta.get("allow_test_changes"):
            env_risks = collection_risks(guard["ns"], guard["base_files"], guard["flags"])
            if env_risks:  # 改變「哪些測試被收集、怎麼跑」：可能正當，交給人看
                risk = "high"
                reasons = [*reasons, *[f"high: {r}" for r in env_risks]]
        if risk == "low":
            return None
        sig = await self._diff_sig(wt, base)
        meta = dict(task.meta)
        if meta.get("approved_diff_sig") == sig:
            return None  # 使用者已核准這份 diff（內容層級；之後內容再變就要重新核准）
        if risk == "high" and not task.meta.get("allow_test_changes"):
            weakening = protected_test_violations(guard["ns"], guard["numstat"], guard["added"], guard["base_src"])
            reasons = [*reasons, *[f"注意（核准即一併放行）：{w}" for w in weakening]]
        new_risk = max_risk(task.risk, risk)
        reasons_all = [*task.risk_reasons, *[r for r in reasons if r not in task.risk_reasons]]
        if risk == "mid":
            if not meta.get("diff_mid_notified") == sig:
                await self.store.add_event(task.id, "notify", {"message": "實際變更為 mid：" + "；".join(reasons)})
                meta["diff_mid_notified"] = sig
            await self.store.update_task(task.id, risk=new_risk, risk_reasons=reasons_all, meta=meta)
            return None
        vault.write_question(self.s, task, "實際變更判定為 high 風險，需使用者核准", reasons)
        meta["pending_diff_sig"] = sig
        task = await self.store.update_task(task.id, risk=new_risk, risk_reasons=reasons_all, meta=meta)
        return await self._go(task, State.WAIT_HUMAN, {"reason": "diff_high"}, wait_reason="實際變更為 high 風險",
                              return_state=State.VERIFY)

    def _allowed_paths(self, task: Task) -> list[str]:
        explicit = task.meta.get("allowed_paths")
        if isinstance(explicit, list) and explicit:
            return [str(p) for p in explicit]
        return [f"{task.subdir.strip('/')}/**"] if task.subdir else []

    async def _diff_sig(self, wt: Path, base: str) -> str:
        """核准簽章：完整 diff 內容＋索引旗標的雜湊。核准後只要內容再變（例如再削弱測試），就要重新核准。"""
        full = await git([*_GITQ, "diff", "--cached", "--binary", base], wt)
        flags = [ln for ln in (await git([*_GITQ, "ls-files", "-v"], wt)).splitlines()
                 if ln and (ln[0] == "S" or ln[0].islower())]
        return hashlib.sha256((full + "\n--index-flags--\n" + "\n".join(flags)).encode("utf-8")).hexdigest()

    async def _test_guard_inputs(self, task: Task) -> dict[str, Any]:
        wt = Path(task.worktree or "")
        base = task.base_commit or "HEAD"
        ns = await git([*_GITQ, "diff", "--cached", "--no-renames", "--name-status", base], wt)
        numstat = await git([*_GITQ, "diff", "--cached", "--no-renames", "--numstat", base], wt)
        modified_tests = [ln.split("\t")[-1] for ln in ns.splitlines()
                          if ln.startswith("M\t") and is_test_path(ln.split("\t")[-1])]
        added: dict[str, str] = {}
        base_src: dict[str, str] = {}
        if modified_tests:
            added = added_lines_by_file(
                await git([*_GITQ, "diff", "--cached", "--no-renames", "-U0", base, "--", *modified_tests], wt))
            for p in modified_tests:
                base_src[p] = await git(["show", f"{base}:{p}"], wt, check=False)
        base_files = (await git([*_GITQ, "ls-tree", "-r", "--name-only", base], wt)).splitlines()
        flags = (await git([*_GITQ, "ls-files", "-v"], wt)).splitlines()
        return {"ns": ns, "numstat": numstat, "added": added, "base_src": base_src, "base_files": base_files,
                "flags": flags}

    async def _test_protection(self, task: Task, n: int) -> tuple[dict[str, Any], list[str]] | None:
        """既有測試只能新增、不能削弱（硬檢查，不經 LLM）。人可在想法檔設 allow_test_changes，或核准這份 diff。"""
        if task.kind != "write" or not task.worktree:
            return None
        wt = Path(task.worktree)
        base = task.base_commit or "HEAD"
        if task.meta.get("allow_test_changes") or task.meta.get("approved_diff_sig") == await self._diff_sig(wt, base):
            return None
        g = await self._test_guard_inputs(task)
        bad = protected_test_violations(g["ns"], g["numstat"], g["added"], g["base_src"])
        name = "既有測試未被刪除或削弱（只允許新增）"
        body = f"{name}\n\n" + ("\n".join(f"- {b}" for b in bad) if bad else "（無違規）") + \
            f"\n\nresult: {'VIOLATION' if bad else 'OK'}\n"
        ev = await self.ev.add_text(task, task.step, f"verify{n}_tests_guard", body, name)
        return {"name": name, "ok": not bad, "txt": ev.id}, bad

    async def _verify(self, task: Task) -> Task:
        gated = await self._diff_gate(task)
        if gated is not None:
            return gated
        wd = self._workdir(task)
        n = len(task.meta.get("verify_runs", [])) + 1
        cmds_res: list[dict[str, Any]] = []
        failures: list[str] = []
        for i, cmd in enumerate(task.accept_cmds, start=1):
            code, output = await run_cmd(cmd, wd, self.s.call_timeout_s)
            body = f"$ {cmd}\n# cwd: {wd}\n# exit: {code}\n\n{output}\n"
            txt = await self.ev.add_text(task, task.step, f"verify{n}_c{i}", body,
                                         f"驗收標準 {i} 第 {n} 次執行輸出")
            img = await self.ev.add_image(task, task.step, f"verify{n}_c{i}_term",
                                          render_terminal(f"# exit: {code}\n{output}", cmd),
                                          f"驗收標準 {i} 終端輸出圖")
            cmds_res.append({"cmd": cmd, "exit": code, "txt": txt.id, "img": img.id})
            if code != 0:
                failures.append(f"$ {cmd}  (exit {code})\n{output[-3000:]}")
        checks: list[dict[str, Any]] = []
        repo = Path(task.repo) if task.repo else None
        meta = dict(task.meta)
        if repo is not None and "baseline" in meta:
            now = await self._repo_state(repo)
            base = meta["baseline"]
            same = now == base
            name = "目標 repo 未被修改（HEAD 與 git status 相同）" if task.kind == "readonly" else \
                "worktree 以外沒有檔案被修改（主 repo git 狀態相同）"
            body = (f"{name}\n\nbefore HEAD: {base['head']}\nafter  HEAD: {now['head']}\n\n"
                    f"before status:\n{base['status'] or '(clean)'}\n\nafter status:\n{now['status'] or '(clean)'}\n"
                    f"\nresult: {'SAME' if same else 'CHANGED'}\n")
            ev = await self.ev.add_text(task, task.step, f"verify{n}_outside", body, name)
            checks.append({"name": name, "ok": same, "txt": ev.id})
            if not same:
                failures.append(f"{name}：未通過\n{now['status']}")
        guard = await self._test_protection(task, n)
        if guard is not None:
            check, bad = guard
            checks.append(check)
            if bad:
                failures.append("既有測試被刪除或削弱（runner 判定，不可由 agent 放寬；只能新增測試）：\n"
                                + "\n".join(bad))
        if task.kind == "write" and task.worktree:
            wt = Path(task.worktree)
            await git(["add", "-A"], wt)
            stat = await git(["diff", "--cached", "--stat", task.base_commit or "HEAD"], wt)
            dev = await self.ev.add_text(task, task.step, f"verify{n}_diffstat", stat or "（無變更）\n",
                                         "相對於起點 commit 的 diff 統計")
            meta["diffstat_ev"] = dev.id
        elif task.kind == "readonly":
            dev = await self.ev.add_text(task, task.step, f"verify{n}_diffstat", "唯讀任務：無檔案變更。\n",
                                         "唯讀任務 diff 統計")
            meta["diffstat_ev"] = dev.id
        ok = not failures
        meta["verify_runs"] = [*meta.get("verify_runs", []), {"cmds": cmds_res, "checks": checks, "ok": ok}]
        meta["last_failure"] = "\n\n".join(failures)[-6000:] if failures else None
        sig = failure_signature(failures) if failures else ""
        # 以第 n 次驗收為鍵：崩潰後重跑同一次 VERIFY 不會重複累加
        recs = [r for r in meta.get("failure_sigs", []) if isinstance(r, dict) and r.get("n") != n]
        if failures:
            recs.append({"n": n, "sig": sig})
        meta["failure_sigs"] = recs
        same_count = sum(1 for r in recs if r.get("sig") == sig) if failures else 0
        task = await self.store.update_task(task.id, meta=meta)
        if ok:
            return await self._go(task, State.REVIEW, {"verify": "pass"})
        if same_count >= self.s.same_error_limit:
            # 同一個錯誤反覆出現：agent 在原地打轉，不等重試上限，停下交給人
            raise Halt(f"same_error_x{same_count}: 相同的驗收失敗累計出現 {same_count} 次（特徵 {sig}）")
        task = await self._bump_retry(task, "VERIFY 失敗")
        return await self._go(task, State.EXEC, {"verify": "fail"})

    async def _evidence_digest(self, task: Task) -> str:
        parts = []
        for e in await self.store.evidence(task.id):
            if e.label.startswith("prompt_"):  # 提示全文不進摘要（太長，且審查者不需要）
                continue
            if e.kind in {"text", "json", "csv"}:
                txt = (self.s.record_dir(task.id) / e.path).read_text(encoding="utf-8")
                parts.append(f"### {e.id}（{e.caption}）\n```\n{txt[:1500]}\n```")
            else:
                parts.append(f"### {e.id}（{e.caption}，圖檔 {e.path}）")
        return "\n".join(parts)

    # ------------------------------------------------------------ REVIEW
    async def _review(self, task: Task) -> Task:
        wd = self._workdir(task)
        diff = ""
        if task.kind == "write" and task.worktree:
            diff = await git(["diff", "--cached", task.base_commit or "HEAD"], Path(task.worktree))
        out = await self._agent(task, "reviewer",
                                prompts.reviewer_prompt(task, task.plan.get("spec_md", ""), diff,
                                                        await self._evidence_digest(task)), wd)
        task = await self._save_review(task, "review", out)
        if out.get("verdict") == "pass":
            return await self._go(task, State.LEARN)
        task = await self._bump_retry(task, "交付審查退回")
        meta = dict(task.meta)
        meta["last_failure"] = "交付審查發現：\n" + "\n".join(out.get("findings", []))
        task = await self.store.update_task(task.id, meta=meta)
        return await self._go(task, State.EXEC, {"review": "fail"})

    # ------------------------------------------------------------ LEARN
    async def _learn_evidence(self, task: Task) -> Task:
        meta = dict(task.meta)
        runs = await self.store.runs(task.id)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["state", "step", "role", "backend", "model", "session_id", "cost_usd", "duration_s"])
        for r in runs:
            w.writerow([r.state, r.step, r.role, r.backend, r.model, r.session_id, f"{r.cost_usd:.6f}",
                        f"{r.duration_s:.3f}"])
        csv_ev = await self.ev.add_text(task, task.step, "runs_csv", buf.getvalue(), "agent 呼叫成本與耗時資料",
                                        kind="csv", ext="csv")
        chart = await self.ev.add_image(task, task.step, "runs_chart",
                                        render_runs_chart(buf.getvalue(), f"{task.id} agent 呼叫"),
                                        "agent 呼叫成本與耗時圖")
        mmd = mermaid_flow(await self.store.events(task.id))
        mm_ev = await self.ev.add_text(task, task.step, "flow_mermaid", mmd, "狀態流程 Mermaid 原始碼",
                                       kind="mermaid", ext="mmd")
        meta.update(runs_csv_ev=csv_ev.id, runs_chart_ev=chart.id, mermaid_ev=mm_ev.id)
        if self.s.render_mermaid:
            try:
                png = await render_mermaid(self.s, mmd,
                                           self.s.worktrees_dir.parent / ".legion_tmp" / "mermaid" / task.id)
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                # 只差一張圖時不讓已花錢的任務 HALT：保留 .mmd 證據、記事件，紀錄文件改引用原始碼
                await self.store.add_event(task.id, "mermaid_failed", {"message": f"Mermaid 轉圖失敗：{exc!r}"[:400]})
            else:
                img = await self.ev.add_image(task, task.step, "flow_mermaid_png", png, "狀態流程圖（Mermaid 轉圖）")
                meta["mermaid_img_ev"] = img.id
        return await self.store.update_task(task.id, meta=meta)

    async def _learn(self, task: Task) -> Task:
        task = await self._learn_evidence(task)
        rdir = self.s.record_dir(task.id)
        scribe_prompt = prompts.scribe_prompt(task, task.plan.get("spec_md", ""), await self._evidence_digest(task),
                                              task.meta.get("reviews", {}))
        if await self.store.find_run(task.id, task.state.value, task.step, "scribe") is None:
            await self._save_prompt(task, "scribe", scribe_prompt)  # 須在快照前：否則會被當成證據遭竄改
        before = snapshot_hashes(rdir)
        meta = dict(task.meta)
        meta["_evidence_ids"] = [e.id for e in await self.store.evidence(task.id)]
        task = await self.store.update_task(task.id, meta=meta)
        out = await self._agent(task, "scribe", scribe_prompt, rdir, add_dirs=[rdir], save_prompt=False)
        after = snapshot_hashes(rdir)
        if after != before:
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            await self.store.add_event(task.id, "evidence_tampered", {"message": "LEARN 前後證據雜湊不同",
                                                                      "files": changed})
            raise Halt(f"evidence_tampered: {changed[:5]}")
        for sub, key in (("lessons", "lessons_md"), ("handoffs", "handoff_md")):
            p = self.s.ai_dir / sub / f"{task.id}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(out.get(key, "")), encoding="utf-8")
        meta = dict(task.meta)
        meta["scribe"] = {k: v for k, v in out.items() if not k.startswith("_")}
        task = await self.store.update_task(task.id, meta=meta)
        await self._followups(task, list(out.get("followups") or []))
        task = await self._go(task, State.DONE)
        rec = self.s.record_dir(task.id) / "record.md"
        bad = narrative_violations(rec.read_text(encoding="utf-8"))
        if bad:
            await self.store.add_event(task.id, "narrative_uncited", {"message": f"{len(bad)} 段敘述未引用證據",
                                                                      "items": bad})
        return task

    async def _followups(self, task: Task, items: list[dict[str, Any]]) -> None:
        if task.meta.get("followups_written"):
            return
        written: list[str] = []
        if task.depth + 1 > self.s.followup_max_depth:
            for it in items:
                await self.store.add_event(task.id, "followup_dropped", {
                    "message": f"深度 {task.depth + 1} 超過上限 {self.s.followup_max_depth}：{it.get('title')}",
                    "reason": "depth", "title": it.get("title")})
            items = []
        for n, it in enumerate(items, start=1):
            if n > self.s.followup_cap:
                await self.store.add_event(task.id, "followup_dropped", {
                    "message": f"單輪回灌超過上限 {self.s.followup_cap}：{it.get('title')}", "reason": "cap",
                    "title": it.get("title")})
                continue
            hold = not self.s.followup_auto_ingest
            p = vault.write_followup(self.s, task, n, str(it.get("title", "")), str(it.get("body", "")), hold=hold)
            written.append(p.name)
            if hold:
                await self.store.add_event(task.id, "followup_held", {
                    "message": f"回灌想法暫存於 AI/inbox_hold/{p.name}，移回 INBOX 才會被領取", "title": it.get("title")})
        meta = dict(task.meta)
        meta["followups_written"] = written or ["(none)"]
        await self.store.update_task(task.id, meta=meta)

    # ------------------------------------------------------------ 人工操作（皆計入 human_touches）
    async def answer(self, task_id: str, approve: bool, by: str, note: str = "") -> Task:
        task = await self.store.get_task(task_id)
        if task.state != State.WAIT_HUMAN:
            raise ValueError(f"{task_id} 不在 WAIT_HUMAN（目前 {task.state.value}）")
        task = await self.store.human_touch(task_id, "answer", {"approve": approve, "by": by, "note": note})
        if not approve:
            return await self._halt(task, f"human_rejected: {note}")
        meta = dict(task.meta)
        if meta.get("pending_installs"):
            meta["pending_installs_approved"] = True
        if meta.get("pending_diff_sig"):
            meta["approved_diff_sig"] = meta.pop("pending_diff_sig")
        task = await self.store.update_task(task.id, meta=meta)
        return await self._go(task, task.return_state or State.EXEC, {"approved_by": by}, wait_reason=None)

    async def resume(self, task_id: str, by: str) -> Task:
        task = await self.store.get_task(task_id)
        if task.state != State.HALT or task.return_state is None:
            raise ValueError(f"{task_id} 不是可續跑的 HALT")
        task = await self.store.human_touch(task_id, "manual_state_change", {"by": by, "action": "resume"})
        # 人工續跑＝重新給機會：重試次數與同一錯誤的計數都歸零（舊紀錄封存，供事後追查）
        meta = dict(task.meta)
        if meta.get("failure_sigs"):
            meta["failure_sigs_archived"] = [*meta.get("failure_sigs_archived", []), *meta["failure_sigs"]]
            meta["failure_sigs"] = []
            task = await self.store.update_task(task.id, meta=meta)
        return await self._go(task, task.return_state, {"resumed_by": by}, halt_reason=None, retries=0)

    async def cancel(self, task_id: str, by: str, reason: str) -> Task:
        """人工取消：轉入 HALT（計入 human_touches）。"""
        task = await self.store.get_task(task_id)
        if task.state in TERMINAL_STATES:
            raise ValueError(f"{task_id} 已是 {task.state.value}")
        task = await self.store.human_touch(task_id, "manual_state_change", {"by": by, "action": "cancel",
                                                                            "reason": reason})
        return await self._halt(task, f"operator_cancel: {reason}")

    async def approve_doc(self, task_id: str, by: str) -> Task:
        task = await self.store.human_touch(task_id, "doc_approval", {"by": by})
        task = await self.store.update_task(task_id, doc_status=DOC_APPROVED, doc_approved_by=by,
                                            doc_approved_at=utcnow())
        await self._after_change(task)
        return task
