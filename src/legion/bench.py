"""評測基準（legion bench）：固定 9 道題目，量測閉環在各種情境下是否照預期走，並留下可比較的數字。

目前只有 mock 模式：agent 的行為由題目腳本決定，所以量的是 runner 的控制邏輯（守門、驗收、重試、審查退回、
範圍檢查、軍師、後續想法）——任何一題結果跟預期不同，就是流程被改壞了。零成本，每次改完都可以跑。
mock 結果是固定的，所以呼叫次數一律比「剛好等於」，多跑一次也算回歸。
真實 Claude 模式（量模型與 prompt 品質）要花錢，另行決定。

結果寫到 02_data/bench/bench_<時間>.json，並在 02_data/metrics.csv 追加彙總列。
"""
from __future__ import annotations

import csv
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents import MockAgent
from .config import PROJECT_ROOT, Settings
from .db import Store
from .demo import CALC_V1, CALC_V2, _commit, _idea, _rm, make_demo_repo
from .models import State, Task
from .runner import Runner
from .vault import init_vault

ACCEPT = ["python -m pytest -q"]
WRITE_CALC = [{"type": "write", "path": "calc.py"}]
OK = {"claim": "passed", "write_files": {"calc.py": CALC_V1}}
NOOP = {"claim": "passed", "write_files": {}}  # 宣稱完成但沒改檔：驗收會失敗


@dataclass(frozen=True)
class Case:
    key: str
    title: str
    what: str                       # 這題在驗什麼（給人看）
    mock: dict[str, Any]
    state: State                    # 預期最終狀態
    execs: int                      # 執行者被呼叫的次數（剛好）
    plans: int = 1                  # 規劃者被呼叫的次數（剛好）
    wait_reason: str = ""           # 預期等待原因（完全相同）
    risk: str | None = None         # 預期最終風險等級
    reason_contains: str = ""       # 預期 risk_reasons 之一含這段字（用來分辨是哪一道檢查擋下的）
    followups_held: int = 0         # 預期暫存到 inbox_hold 的後續想法數
    fm: dict[str, Any] = field(default_factory=dict)  # 想法檔額外的 frontmatter（例如 allowed_paths）


def _m(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"risk_proposed": "low", "accept_cmds": ACCEPT, "actions": WRITE_CALC, "exec": [OK]}
    base.update(kw)
    return base


CASES: tuple[Case, ...] = (
    Case("low", "新增 multiply（一次就過）", "低風險任務一路走到 DONE，不需要人",
         _m(), State.DONE, execs=1),
    Case("verify-retry", "新增 multiply（第一次沒改檔）", "不採信 agent 自述：驗收失敗會退回重做，第二次才過",
         _m(exec=[NOOP, OK]), State.DONE, execs=2),
    Case("spec-revise", "新增 multiply（規格被退回）", "規格審查退回時回到規劃重寫，再通過",
         _m(spec_review=["revise", "pass"]), State.DONE, execs=1, plans=2),
    Case("review-fail", "新增 multiply（交付審查退回）", "交付審查退回時回到執行修正，再通過",
         _m(review=["fail", "pass"], exec=[OK, OK]), State.DONE, execs=2),
    Case("high-risk", "清掉舊的測試檔", "agent 自稱 low，但動作含刪除 → 守門判 high，核准前執行者一次都不能被呼叫",
         _m(actions=[{"type": "delete", "path": "test_calc.py"}]), State.WAIT_HUMAN, execs=0,
         wait_reason="high 風險，需核准", risk="high"),
    Case("out-of-scope", "新增 multiply（多寫了範圍外檔案）",
         "想法檔限定可改的路徑，執行卻多寫了別的檔 → 執行後的 diff 檢查就要擋下（不能等到驗收後）",
         _m(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_V1, "extra.py": "X = 1\n"}}]),
         State.WAIT_HUMAN, execs=1, wait_reason="實際變更為 high 風險", risk="high",
         reason_contains="變更超出允許範圍：extra.py", fm={"allowed_paths": ["calc.py", "test_*.py"]}),
    Case("advisor", "新增 multiply（一直沒改檔）", "同一錯誤反覆出現 → 請示軍師提出錦囊，停下等人選",
         _m(exec=[NOOP, NOOP, NOOP, NOOP]), State.WAIT_HUMAN, execs=3),
    Case("clarify", "幫 calc 加個功能（想法很模糊）", "想法不清楚 → 規劃者先提問、停下等人回答，執行者一次都不能被呼叫",
         _m(questions=[{"question": "要加哪個功能？", "options": ["multiply", "power"], "default": "multiply"}]),
         State.WAIT_HUMAN, execs=0, wait_reason="需求釐清待回答"),
    Case("followup", "補 docstring（提出後續想法）", "結案時書記官提出後續想法，暫存 inbox_hold 等人放行（不自動領取）",
         _m(exec=[{"claim": "passed", "write_files": {"calc.py": CALC_V2}}],
            followups=[{"title": "bench：新增 power 函式", "body": "為 calc 加上 power(a, b)。"}]),
         State.DONE, execs=1, followups_held=1),
)
ADVISOR_WAIT_PREFIX = "軍師錦囊待決定"


def _settings(base: Settings, tmp: Path) -> Settings:
    """隔離：獨立 schema、vault、worktree；不碰正式資料。軍師開啟、閒置門檻拉長，讓等待狀態穩定。
    後續想法照真實 `legion tick` 的預設先暫存 inbox_hold（mock tick 會自動領取，但評測要驗的是真實預設）。"""
    return base.model_copy(update={
        "schema_name": "bench", "task_prefix": "B", "agent_backend": "mock",
        "vault": tmp / "vault", "worktrees_dir": tmp / "worktrees",
        "advisor_enabled": True, "advisor_idle_minutes": 10_000.0, "followup_auto_ingest": False,
        "clarify_enabled": True, "clarify_idle_minutes": 10_000.0,
    })


def _check(case: Case, t: Task, runs: list[Any], held: int, inbox_fu: int) -> list[str]:
    problems = []
    if t.state != case.state:
        problems.append(f"狀態 {t.state.value}，預期 {case.state.value}（{t.halt_reason or t.wait_reason or ''}）")
    n_exec = sum(r.role == "executor" for r in runs)
    n_plan = sum(r.role == "planner" for r in runs)
    if n_exec != case.execs:
        problems.append(f"執行者被呼叫 {n_exec} 次，預期剛好 {case.execs} 次")
    if n_plan != case.plans:
        problems.append(f"規劃者被呼叫 {n_plan} 次，預期剛好 {case.plans} 次")
    if case.key == "advisor":
        if not (t.wait_reason or "").startswith(ADVISOR_WAIT_PREFIX):
            problems.append(f"等待原因「{t.wait_reason}」不是軍師錦囊")
        if not sum(r.role == "advisor" for r in runs):
            problems.append("軍師沒有被請示")
    elif case.wait_reason and t.wait_reason != case.wait_reason:
        problems.append(f"等待原因「{t.wait_reason}」，預期「{case.wait_reason}」")
    if case.risk and t.risk != case.risk:
        problems.append(f"風險 {t.risk}，預期 {case.risk}")
    if case.reason_contains and not any(case.reason_contains in r for r in t.risk_reasons):
        problems.append(f"風險理由沒有「{case.reason_contains}」：{t.risk_reasons}")
    if held != case.followups_held:
        problems.append(f"暫存後續想法 {held} 個，預期 {case.followups_held} 個")
    if inbox_fu:
        problems.append(f"後續想法被放進 INBOX {inbox_fu} 個（預設應暫存 inbox_hold，等人放行）")
    if case.state == State.DONE and t.human_touches:
        problems.append(f"人工介入 {t.human_touches} 次，預期 0")
    return problems


def _dirty() -> bool:
    """工作目錄有未提交變更時，metrics 的 commit 欄要註明，否則數字對不回程式碼。"""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "src", "tests"], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return bool(out.strip())


async def run_bench(base: Settings, max_ticks: int = 80, tmp: Path | None = None) -> dict[str, Any]:
    tmp = tmp or PROJECT_ROOT / ".legion_tmp" / "bench"
    _rm(tmp)
    s = _settings(base, tmp)
    init_vault(s)
    repo = make_demo_repo(tmp / "repo")
    for c in CASES:
        _idea(s.inbox_dir / f"bench-{c.key}.md", {"title": f"bench：{c.title}", "kind": "write", "repo": str(repo),
                                                 "mock": c.mock, **c.fm}, c.what)
    store = await Store.connect(s.dsn, s.schema_name)
    started = time.perf_counter()
    try:
        await store.drop_schema()
        await store.close()
        store = await Store.connect(s.dsn, s.schema_name)
        await store.init_schema()
        runner = Runner(s, store, MockAgent())
        ticks = 0
        converged = False
        for ticks in range(1, max_ticks + 1):
            summary = await runner.tick()
            if not summary["ingested"] and not summary["advanced"]:
                converged = True
                break
        wall = time.perf_counter() - started
        tasks = {t.title: t for t in await store.list_tasks() if t.parent_id is None}
        rows: list[dict[str, Any]] = []
        for c in CASES:
            t = tasks.get(f"bench：{c.title}")
            if t is None:
                rows.append({"key": c.key, "what": c.what, "ok": False, "problems": ["沒有被領取成任務"]})
                continue
            runs = await store.runs(t.id)
            held = len(list((s.ai_dir / "inbox_hold").glob(f"fu-{t.id}-*.md")))
            inbox_fu = len(list(s.inbox_dir.glob(f"fu-{t.id}-*.md")))
            problems = _check(c, t, runs, held, inbox_fu)
            dur = (t.updated_at - t.created_at).total_seconds() if t.updated_at and t.created_at else 0.0
            rows.append({"key": c.key, "what": c.what, "id": t.id, "ok": not problems, "problems": problems,
                         "state": t.state.value, "expected": c.state.value, "human_touches": t.human_touches,
                         "agent_calls": len(runs), "cost_usd": round(t.cost_usd, 6), "duration_s": round(dur, 2)})
    finally:
        await store.close()
    passed = sum(r["ok"] for r in rows)
    return {"backend": "mock", "commit": _commit(), "dirty": _dirty(),
            "at": datetime.now().astimezone().isoformat(timespec="seconds"), "converged": converged,
            "cases": len(CASES), "passed": passed, "match_rate": round(passed / len(CASES), 4), "ticks": ticks,
            "wall_s": round(wall, 2), "agent_calls": sum(r.get("agent_calls", 0) for r in rows),
            "cost_usd": round(sum(r.get("cost_usd", 0.0) for r in rows), 6), "rows": rows}


def save(result: dict[str, Any], data_dir: Path) -> Path:
    """結果存成 JSON，並在 metrics.csv 追加 3 列彙總（符合預期比例、agent 呼叫數、牆鐘秒數）。換行一律 LF。"""
    out_dir = data_dir / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = result["at"].replace(":", "").replace("-", "")[:15]
    path = out_dir / f"bench_{stamp}.json"
    path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    metrics = data_dir / "metrics.csv"
    if metrics.exists():
        raw = metrics.read_bytes()
        if raw and not raw.endswith(b"\n"):
            metrics.write_bytes(raw + b"\n")  # 檔尾沒換行時先補，避免新列黏到上一列
    new = not metrics.exists()
    commit = result["commit"] + ("（未提交工作目錄）" if result.get("dirty") else "")
    with metrics.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["date", "commit", "metric", "value", "command"])
        for name, value in (("bench.mock.match_rate", result["match_rate"]),
                            ("bench.mock.agent_calls", result["agent_calls"]),
                            ("bench.mock.wall_s", result["wall_s"])):
            w.writerow([result["at"], commit, name, value, "legion bench"])
    return path


def history(data_dir: Path, limit: int = 8) -> list[dict[str, Any]]:
    """最近幾次評測的彙總（舊到新），給儀表畫趨勢。壞掉的 JSON 跳過，數字一律轉成 int。"""
    files = sorted((data_dir / "bench").glob("bench_*.json"))[-limit:]
    out = []
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            out.append({"at": str(r.get("at", "")), "passed": int(r.get("passed", 0)),
                        "cases": int(r.get("cases", 0)), "commit": str(r.get("commit", ""))})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return out
