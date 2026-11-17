"""命令列：legion tick｜answer｜resume｜approve-doc｜report｜export｜demo｜init-db｜init-vault｜status"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from . import ATTRIBUTION, __author__
from .agents import AgentBackend, ClaudeCliAgent, MockAgent, reviewer_backend
from .config import Settings
from .db import Store
from .installs import RecordingInstaller, ShellInstaller
from .models import State
from .runner import Runner, UserError
from .vault import init_vault, weekly_report


def _windows_loop() -> None:
    # psycopg async 在 Windows 不能用 ProactorEventLoop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]


ROLE_LABELS = {"planner": "指揮官（規劃）", "spec_reviewer": "規格審查者", "executor": "指揮官（執行）",
               "reviewer": "交付審查者", "scribe": "書記官", "advisor": "軍師（卡住時才請示）",
               "strategist": "參謀（戰役中決定下一步）"}


def models_table(s: Settings) -> str:
    rows = ["角色\t第 1 次\t重做時（第 2 次起）"]
    for role, label in ROLE_LABELS.items():
        m, e = s.model_for(role, 0, False)
        m2, e2 = s.model_for(role, 1, True)
        first = f"{m or '(CLI 預設)'} / effort {e or '預設'}"
        later = f"{m2 or '(CLI 預設)'} / effort {e2 or '預設'}"
        rows.append(f"{label}\t{first}\t{later if later != first else '同左'}")
    if s.claude_model:
        rows.append(f"（已用 --model／LEGION_MODEL 指定 {s.claude_model}：全部角色統一，不升級）")
    return "\n".join(rows)


async def run_until_idle(runner: Runner, st: Store, max_ticks: int, wait_minutes: float = 0.0,
                         poll_s: float = 30.0) -> dict[str, Any]:
    """重複 tick 直到沒有進展。有軍師錦囊在等使用者時，可選擇再等一段時間（讓閒置自動決議有機會發生）。"""
    import time

    ticks, waited, log = 0, 0.0, []
    stop = "max_ticks"
    while ticks < max_ticks:
        summary = await runner.tick()
        ticks += 1
        if summary.get("advanced") or summary.get("ingested") or summary.get("auto_decided"):
            log.append({k: summary[k] for k in ("ingested", "advanced", "auto_decided", "halted") if summary.get(k)})
            continue
        if not summary.get("locked"):
            stop = "另一個 tick 正在執行"
            break
        pending = [t for t in await st.list_tasks([State.WAIT_HUMAN]) if runner._advisor_pending(t)]
        if pending and waited < wait_minutes * 60:
            await asyncio.to_thread(time.sleep, poll_s)
            waited += poll_s
            continue
        stop = "idle"
        break
    tasks = await st.list_tasks()
    return {"ticks": ticks, "stopped": stop, "steps": log[-30:],
            "waiting_human": [t.id for t in tasks if t.state == State.WAIT_HUMAN],
            "halted": [t.id for t in tasks if t.state == State.HALT and not (t.halt_reason or "").startswith("operator")],
            "done": len([t for t in tasks if t.state == State.DONE])}


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


def build_parser() -> argparse.ArgumentParser:
    """建立 legion 的命令列解析器（測試也用它列出所有子命令）。"""
    ap = argparse.ArgumentParser(prog="legion", formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--schema", default=os.environ.get("LEGION_SCHEMA", "legion"))
    ap.add_argument("--version", action="version",
                    version=f"{ATTRIBUTION}\n© 2026 {__author__}，保留所有權利（見 LICENSE、NOTICE）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    sub.add_parser("init-vault")
    tp = sub.add_parser("tick")
    tp.add_argument("--backend", choices=["mock", "claude"], default=os.environ.get("LEGION_BACKEND", "claude"))
    tp.add_argument("--model", default=os.environ.get("LEGION_MODEL"),
                    help="所有角色統一用這個模型（覆蓋依角色分配）；不指定時依 `legion models` 的角色表")
    tp.add_argument("--task-budget", type=float, default=None)
    tp.add_argument("--daily-budget", type=float, default=None)
    tp.add_argument("--auto-followups", action="store_true",
                    help="真實 backend 時讓回灌想法直接進 INBOX 自動領取（預設暫存到 AI/inbox_hold/）")
    rn = sub.add_parser("run", help="持續推進：重複 tick 直到沒有事可做（或達到上限）")
    rn.add_argument("--backend", choices=["mock", "claude"], default=os.environ.get("LEGION_BACKEND", "claude"))
    rn.add_argument("--model", default=os.environ.get("LEGION_MODEL"))
    rn.add_argument("--task-budget", type=float, default=None)
    rn.add_argument("--daily-budget", type=float, default=None)
    rn.add_argument("--auto-followups", action="store_true")
    rn.add_argument("--max-ticks", type=int, default=200)
    rn.add_argument("--wait-minutes", type=float, default=0.0,
                    help="沒事可做時，若有軍師錦囊在等閒置時限，最多再等這麼久（每 30 秒檢查一次）")
    a = sub.add_parser("answer")
    a.add_argument("task_id")
    a.add_argument("decision", choices=["approve", "reject"])
    a.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    a.add_argument("--note", default="")
    ch = sub.add_parser("choose", help="採用軍師的某個錦囊")
    ch.add_argument("task_id")
    ch.add_argument("option_id")
    ch.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    cl = sub.add_parser("clarify", help="回答需求釐清：--defaults 全部採用預設，或逐題 1=B 2=A")
    cl.add_argument("task_id")
    cl.add_argument("answers", nargs="*", help="題號=選項代號或原文，例如 1=B 2=A；沒寫的題目採用預設")
    cl.add_argument("--defaults", action="store_true", help="全部採用預設答案")
    cl.add_argument("--by", default=os.environ.get("USERNAME", "user"))
    idea = sub.add_parser("idea", help="一句話丟想法：寫進 vault/INBOX，下一輪 tick 就會領取（不花額度）")
    idea.add_argument("text", help="想法，一句話即可；不清楚的地方規劃者會先問你")
    idea.add_argument("--repo", help="目標 repo（預設：LEGION_DEFAULT_REPO，再來是目前所在的 git repo）")
    idea.add_argument("--kind", choices=["write", "readonly"], default="write")
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
    sub.add_parser("bench", help="評測基準：9 道固定題目驗證閉環控制邏輯（mock，不花額度），結果寫入 02_data/bench")
    dm = sub.add_parser("demo")
    dm.add_argument("--mock", action="store_true", required=True)
    sub.add_parser("status")
    mo = sub.add_parser("models", help="顯示各角色目前分配的模型與 effort（含環境變數覆寫）；--usage 加看派工成效")
    mo.add_argument("--usage", action="store_true",
                    help="各角色 × 模型的次數、花費、失敗，與執行者一次過比例（只算真實呼叫；不花額度）")
    mo.add_argument("--all", action="store_true", help="同 --usage，但連 mock 呼叫一起算")
    sub.add_parser("brief", help="每日晨報：等你處理的任務、停下的任務、待 merge 分支、戰役、花費（不花額度）")
    cl = sub.add_parser("cleanup", help="列出可清理的已併入分支與 worktree；加 --apply 才刪")
    cl.add_argument("--apply", action="store_true", help="真的刪除（只刪已併入 HEAD 且 worktree 乾淨的）")
    ib = sub.add_parser("inbox", help="把 03_docs/inbox.md 的表格轉成 JSON（給互動頁讀；不花額度）")
    ib.add_argument("--file", help="inbox 檔案路徑（預設 03_docs/inbox.md）")
    ib.add_argument("--out", help="寫入這個檔案（UTF-8、無 BOM）。給頁面用一定要用這個，PowerShell 5.1 的 > 會轉成 UTF-16")
    vj = sub.add_parser("vault-json", help="把 vault 的報告、紀錄、待決事項轉成 JSON（給手機互動頁讀；不花額度）")
    vj.add_argument("--out", required=True, help="寫入這個檔案（UTF-8、無 BOM）")
    sc = sub.add_parser("scout", help="找有價值的 GitHub repo：用 gh 抓活躍度、維護、人員、採用、動能、成熟度並打分（不用 AI）")
    sc.add_argument("keywords", help="搜尋關鍵字（GitHub 搜尋語法）")
    sc.add_argument("--lang", help="限定語言，例如 python")
    sc.add_argument("--license", help="限定授權，多個用逗號，例如 mit,apache-2.0")
    sc.add_argument("--per-query", type=int, default=25, help="每次搜尋取幾個候選（依星數、依相關度各一次；預設 25）")
    sc.add_argument("--top", type=int, default=10, help="報告列前幾名（預設 10）")
    sc.add_argument("--weights", help="覆寫權重，例如 activity=0.3,adoption=0.05（會自動正規化）")
    ps = sub.add_parser("phone-sync", help="手機互動頁的想法與答案 ↔ legion（讀 ArtifactData 匯出檔、產生寫回清單；不花額度）")
    ps.add_argument("--in", dest="in_dir", required=True, help="ArtifactData list 的 out_dir（含 versions.json）")
    ps.add_argument("--out", dest="out_dir", required=True, help="輸出資料夾：manifest.json 與要寫回的資料檔")
    ps.add_argument("--repos", help="目標專案白名單 key=路徑;key=路徑（覆寫 LEGION_PHONE_REPOS）")
    dc = sub.add_parser("docs", help="從 diagrams.py 同步 README 的流程圖與儀表說明（不花額度）")
    dc.add_argument("--check", action="store_true", help="只檢查，README 過期時回傳 1")
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    _windows_loop()
    ap = build_parser()
    args = ap.parse_args(argv)

    s = Settings(schema_name=args.schema)

    if args.cmd == "models":
        print(models_table(s))
        if args.usage or args.all:
            from .dispatch import executor_outcomes, render, usage_by_role_model

            async def usage(st: Store) -> str:
                runs, tasks = await st.runs(), await st.list_tasks()
                backend = None if args.all else "claude"
                return render(usage_by_role_model(runs, backend), executor_outcomes(runs, tasks, backend),
                              ROLE_LABELS)

            print("\n派工成效（schema " + s.schema_name + "）\n" + asyncio.run(_with_store(s, usage)))
        return 0
    if args.cmd == "brief":
        from .brief import build

        async def make(st: Store) -> dict[str, Any]:
            b, _ = await build(s, st)
            return {k: b[k] for k in ("headline", "file", "waiting", "recent_halts", "pending_merge",
                                      "cost_yesterday", "cost_today")}

        print(json.dumps(asyncio.run(_with_store(s, make)), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "vault-json":
        from pathlib import Path

        from .mobile import export_vault

        data = export_vault(s.vault)
        try:
            Path(args.out).write_text(data.model_dump_json() + "\n", encoding="utf-8", newline="\n")  # 無 BOM
        except OSError as e:
            print(f"寫入失敗：{e}", file=sys.stderr)
            return 1
        print(f"已寫入 {args.out}（{len(data.docs)} 份文件，遮蔽警告 {len(data.warnings)} 筆，sha {data.sha256}）")
        for w in data.warnings:
            print(f"  ⚠ {w}")
        return 0

    if args.cmd == "docs":
        from .config import PROJECT_ROOT
        from .diagrams import sync_readme

        readme = PROJECT_ROOT / "README.md"
        old = readme.read_text(encoding="utf-8")
        try:
            new = sync_readme(old)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
        if args.check:
            if new != old:
                print("README 的流程圖或儀表說明過期：請執行 legion docs", file=sys.stderr)
                return 1
            print("README 已是最新")
            return 0
        if new != old:
            readme.write_bytes(new.encode("utf-8"))
        print("已更新 README 的流程圖與儀表說明" if new != old else "README 已是最新")
        # 動態 SVG：流程圖需要瀏覽器與 mmdc，儀表需要 DB。環境問題（沒瀏覽器、逾時、DB 連不上）只提示並保留舊檔；
        # animate_flow 的 ValueError 表示 mermaid 輸出格式變了，是程式要改，回傳 1
        import subprocess

        import psycopg

        from .motion import write_dashboard, write_flow

        rc = 0
        try:
            print(f"流程動態圖：{asyncio.run(write_flow(s, PROJECT_ROOT))}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            print(f"流程動態圖未更新（環境問題，保留舊檔）：{e}", file=sys.stderr)
        except ValueError as e:
            print(f"流程動態圖產生失敗，需要修改 motion.py：{e}", file=sys.stderr)
            rc = 1
        try:
            out = asyncio.run(_with_store(s, lambda st: write_dashboard(s, st, PROJECT_ROOT)))
            print(f"儀表 KPI 卡：{out}")
        except (OSError, psycopg.Error) as e:
            print(f"儀表 KPI 卡未更新（{type(e).__name__}，保留舊檔）：{e}", file=sys.stderr)
        return rc

    if args.cmd == "idea":
        from pathlib import Path

        from .intake import resolve_repo, subdir_for, write_idea

        try:
            repo = resolve_repo(args.repo, s, Path.cwd())
            if repo is None:
                print("找不到目標 repo：請加 --repo <路徑>、設定 LEGION_DEFAULT_REPO，或在目標 repo 裡執行。",
                      file=sys.stderr)
                return 1
            sub = subdir_for(args.repo, s, repo, args.kind)
            p = write_idea(s, args.text, repo, args.kind, subdir=sub)
        except (ValueError, OSError) as e:
            print(f"idea 失敗：{e}", file=sys.stderr)
            return 1
        where = f"{repo}（只改子資料夾 {sub}）" if sub else str(repo)
        print(f"已收下想法 → {p}\n目標 repo：{where}\n下一輪 `legion tick` 會領取；不清楚的地方規劃者會先問你。")
        return 0

    if args.cmd == "scout":
        from .scout import GhFetcher, parse_weights, scout

        try:
            w = parse_weights(args.weights)
            lic = [x.strip() for x in (args.license or "").split(",") if x.strip()]
            res = asyncio.run(scout(s, GhFetcher(), args.keywords, args.lang, lic, args.per_query, args.top, w))
        except (ValueError, RuntimeError, OSError) as e:
            print(f"scout 失敗：{e}", file=sys.stderr)
            return 1
        for x in res.ranked[: args.top]:
            flag = "（已封存）" if x.metrics.archived else ""
            print(f"{x.rank:>2}. {x.total:>5g}  {x.metrics.full_name}{flag}  ★{x.metrics.stars:,}")
        print(f"候選 {res.candidates}｜API 呼叫 {res.api_calls}｜{res.wall_s} 秒\n報告：{res.md_path}\n數據：{res.json_path}")
        return 0
    if args.cmd == "phone-sync":
        from pathlib import Path

        from .phone import sync

        init_vault(s)
        try:
            res = asyncio.run(_with_store(s, lambda st: sync(s, st, Path(args.in_dir), Path(args.out_dir),
                                                             repos_spec=args.repos)))
        except (OSError, ValueError) as e:
            print(f"phone-sync 失敗：{e}", file=sys.stderr)
            return 1
        print(json.dumps(res.model_dump(exclude={"writes"}) | {"writes": len(res.writes),
                                                             "manifest": str(Path(args.out_dir) / "manifest.json")},
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "inbox":
        from pathlib import Path

        from .inbox import DEFAULT_INBOX, load_inbox

        try:
            data = load_inbox(Path(args.file) if args.file else DEFAULT_INBOX)
        except (OSError, ValueError) as e:
            print(f"inbox 解析失敗：{e}", file=sys.stderr)
            return 1
        out = data.model_dump_json(indent=2)
        if args.out:
            try:
                Path(args.out).write_text(out + "\n", encoding="utf-8", newline="\n")  # 無 BOM
            except OSError as e:
                print(f"寫入失敗：{e}", file=sys.stderr)
                return 1
            print(f"已寫入 {args.out}（{sum(len(x.rows) for x in data.sections)} 列，sha {data.sha256}）")
        else:
            print(out)
        return 0

    if args.cmd == "cleanup":
        from .cleanup import run_cleanup

        res = asyncio.run(_with_store(s, lambda st: run_cleanup(s, st, args.apply)))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if not res.get("error") and all(not r["errors"] for r in res.get("results", [])) else 1

    if args.cmd == "init-vault":
        init_vault(s)
        print(f"vault 骨架已建立：{s.vault}")
        return 0
    if args.cmd == "init-db":
        asyncio.run(_with_store(s, lambda st: asyncio.sleep(0)))
        print(f"資料表已建立（schema {s.schema_name}）")
        return 0
    if args.cmd == "bench":
        from .bench import run_bench, save

        res = asyncio.run(run_bench(s))
        path = save(res, s.data_dir)
        for r in res["rows"]:
            mark = "✅" if r["ok"] else "❌"
            print(f"{mark} {r['key']:<13} {r.get('state', '-'):<11} {r['what']}")
            for prob in r["problems"]:
                print(f"     ↳ {prob}")
        print(f"符合預期 {res['passed']}/{res['cases']}｜agent 呼叫 {res['agent_calls']} 次｜{res['wall_s']} 秒｜{path}")
        return 0 if res["passed"] == res["cases"] else 1
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
    if args.cmd == "run":
        upd_r: dict[str, Any] = {"agent_backend": args.backend, "claude_model": args.model,
                                 "followup_auto_ingest": args.backend == "mock" or args.auto_followups}
        if args.task_budget is not None:
            upd_r["task_budget_usd"] = args.task_budget
        if args.daily_budget is not None:
            upd_r["daily_budget_usd"] = args.daily_budget
        s = s.model_copy(update=upd_r)
        init_vault(s)
        main_b, rev_b, note = _backends(s, args.backend)
        if note:
            print(note)

        async def loop(st: Store) -> dict[str, Any]:
            installer = ShellInstaller() if args.backend == "claude" else RecordingInstaller()
            runner = Runner(s, st, main_b, rev_b, installer=installer)
            return await run_until_idle(runner, st, args.max_ticks, args.wait_minutes)

        print(json.dumps(asyncio.run(_with_store(s, loop)), ensure_ascii=False, indent=2))
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
        if args.cmd == "choose":
            t = await runner.choose(args.task_id, args.option_id, args.by)
            return f"{t.id} 採用錦囊 {args.option_id} → {t.state.value}（human_touches={t.human_touches}）"
        if args.cmd == "clarify":
            t = await runner.clarify(args.task_id, clarify_answers, args.by)
            return f"{t.id} 需求釐清已回答 → {t.state.value}"
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

    clarify_answers: dict[str, str] | None = None
    if args.cmd == "clarify":  # 先檢查格式再連 DB：格式錯就不碰任何 schema
        try:
            clarify_answers = parse_clarify_args(args.answers, args.defaults)
        except UserError as e:
            print(f"clarify 失敗：{e}", file=sys.stderr)
            return 1
    try:
        print(asyncio.run(_with_store(s, act)))
    except UserError as e:  # 使用者輸入或狀態不符：說明原因，不丟 traceback（程式錯誤照常顯示堆疊）
        print(f"{args.cmd} 失敗：{e}", file=sys.stderr)
        return 1
    return 0


def parse_clarify_args(answers: list[str], defaults: bool) -> dict[str, str] | None:
    """`legion clarify` 的答案：--defaults → None（全部預設）；否則 題號=選項，題號不可重複；兩者都沒給要報錯。"""
    if defaults and answers:
        raise UserError("--defaults 與逐題答案只能擇一")
    if defaults:
        return None
    if not answers:
        raise UserError("請給 --defaults（全部採用預設）或逐題答案，例如 1=B 2=A")
    out: dict[str, str] = {}
    for a in answers:
        k, sep, v = a.partition("=")
        if not sep or not k.strip() or not v.strip():
            raise UserError(f"答案「{a}」格式不對：要寫 題號=選項，例如 1=B")
        if k.strip() in out:
            raise UserError(f"第 {k.strip()} 題回答了兩次")
        out[k.strip()] = v.strip()
    return out


if __name__ == "__main__":
    sys.exit(main())
