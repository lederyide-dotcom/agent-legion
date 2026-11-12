"""命令列：legion tick｜answer｜resume｜approve-doc｜report｜export｜demo｜init-db｜init-vault｜status"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from .agents import AgentBackend, ClaudeCliAgent, MockAgent, reviewer_backend
from .config import Settings
from .db import Store
from .installs import RecordingInstaller, ShellInstaller
from .runner import Runner
from .vault import init_vault, weekly_report


def _windows_loop() -> None:
    # psycopg async 在 Windows 不能用 ProactorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


def _backends(s: Settings, name: str) -> tuple[AgentBackend, AgentBackend, str | None]:
    if name == "mock":
        m = MockAgent()
        return m, m, None
    main = ClaudeCliAgent(model=s.claude_model)
    rev, note = reviewer_backend(s.reviewer_backend, ClaudeCliAgent(model=s.claude_model))
    return main, rev, note


async def _with_store(s: Settings, fn: Callable[[Store], Awaitable[Any]]) -> Any:
    store = await Store.connect(s.dsn, s.schema_name)
    try:
        await store.init_schema()
        return await fn(store)
    finally:
        await store.close()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    _windows_loop()
    ap = argparse.ArgumentParser(prog="legion")
    ap.add_argument("--schema", default=os.environ.get("LEGION_SCHEMA", "legion"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sub.add_parser("init-vault")
    tp = sub.add_parser("tick")
    tp.add_argument("--backend", choices=["mock", "claude"], default=os.environ.get("LEGION_BACKEND", "claude"))
    tp.add_argument("--model", default=os.environ.get("LEGION_MODEL"))
    tp.add_argument("--task-budget", type=float, default=None)
    tp.add_argument("--daily-budget", type=float, default=None)
    tp.add_argument("--auto-followups", action="store_true",
                    help="真實 backend 時讓回灌想法直接進 INBOX 自動領取（預設暫存到 AI/inbox_hold/）")
    a = sub.add_parser("answer")
    a.add_argument("task_id")
    a.add_argument("decision", choices=["approve", "reject"])
    a.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    a.add_argument("--note", default="")
    r = sub.add_parser("resume")
    r.add_argument("task_id")
    r.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    cc = sub.add_parser("cancel")
    cc.add_argument("task_id")
    cc.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    cc.add_argument("--reason", required=True)
    ad = sub.add_parser("approve-doc")
    ad.add_argument("task_id")
    ad.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    sub.add_parser("report")
    ex = sub.add_parser("export")
    ex.add_argument("task_id")
    ex.add_argument("--format", choices=["docx", "pdf"], required=True)
    dm = sub.add_parser("demo")
    dm.add_argument("--mock", action="store_true", required=True)
    sub.add_parser("status")
    args = ap.parse_args(argv)

    s = Settings(schema_name=args.schema)

    if args.cmd == "init-vault":
        init_vault(s)
        print(f"vault 骨架已建立：{s.vault}")
        return 0
    if args.cmd == "init-db":
        asyncio.run(_with_store(s, lambda st: asyncio.sleep(0)))
        print(f"資料表已建立（schema {s.schema_name}）")
        return 0
    if args.cmd == "demo":
        from .demo import run_demo

        res = asyncio.run(run_demo(s))
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0 if res["ok"] else 1
    if args.cmd == "export":
        from .export import export

        out = asyncio.run(export(s, args.task_id, args.format))
        print(out)
        return 0
    if args.cmd == "tick":
        upd: dict[str, Any] = {"agent_backend": args.backend, "claude_model": args.model,
                               # 事故 4：真實 backend 的回灌預設不自動領取，避免未經同意的連鎖花費
                               "followup_auto_ingest": args.backend == "mock" or args.auto_followups}
        if args.task_budget is not None:
            upd["task_budget_usd"] = args.task_budget
        if args.daily_budget is not None:
            upd["daily_budget_usd"] = args.daily_budget
        s = s.model_copy(update=upd)
        init_vault(s)
        main_b, rev_b, note = _backends(s, args.backend)
        if note:
            print(note)

        async def go(st: Store) -> Any:
            installer = ShellInstaller() if args.backend == "claude" else RecordingInstaller()
            return await Runner(s, st, main_b, rev_b, installer=installer).tick()

        print(json.dumps(asyncio.run(_with_store(s, go)), ensure_ascii=False, indent=2))
        return 0

    async def act(st: Store) -> Any:
        runner = Runner(s, st, MockAgent())
        if args.cmd == "answer":
            t = await runner.answer(args.task_id, args.decision == "approve", args.by, args.note)
            return f"{t.id} → {t.state.value}（human_touches={t.human_touches}）"
        if args.cmd == "resume":
            t = await runner.resume(args.task_id, args.by)
            return f"{t.id} → {t.state.value}"
        if args.cmd == "cancel":
            t = await runner.cancel(args.task_id, args.by, args.reason)
            return f"{t.id} → {t.state.value}（{t.halt_reason}）"
        if args.cmd == "approve-doc":
            t = await runner.approve_doc(args.task_id, args.by)
            return f"{t.id} 文件 → {t.doc_status}（{t.doc_approved_by}）"
        if args.cmd == "report":
            return str(await weekly_report(s, st))
        if args.cmd == "status":
            return "\n".join(f"{t.id}  {t.state.value:<12} {t.risk or '-':<5} ${t.cost_usd:.4f}  "
                             f"touch={t.human_touches}  {t.title}" for t in await st.list_tasks())
        raise ValueError(args.cmd)

    print(asyncio.run(_with_store(s, act)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
