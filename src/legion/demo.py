"""mock 端到端 demo：三張任務（low、high、會回灌的），零成本。結果寫入 02_data/metrics.csv。"""
from __future__ import annotations

import csv
import os
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .agents import MockAgent
from .config import PROJECT_ROOT, Settings
from .db import Store
from .models import State
from .runner import Runner
from .vault import init_vault

CALC_V0 = 'def add(a, b):\n    return a + b\n'
CALC_V1 = 'def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n'
CALC_V2 = ('"""小計算機。"""\n\n\ndef add(a, b):\n    """相加。"""\n    return a + b\n\n\n'
           'def multiply(a, b):\n    """相乘。"""\n    return a * b\n')
CALC_V3 = CALC_V2 + '\n\ndef power(a, b):\n    """次方。"""\n    return a ** b\n'
TEST = ("from calc import add, multiply\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\n"
        "def test_multiply():\n    assert multiply(4, 5) == 20\n")


def _rm(path: Path) -> None:
    def onerror(func: Any, p: str, _exc: Any) -> None:
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if path.exists():
        shutil.rmtree(path, onerror=onerror)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_demo_repo(root: Path) -> Path:
    _rm(root)
    root.mkdir(parents=True)
    (root / "calc.py").write_text(CALC_V0, encoding="utf-8")
    (root / "test_calc.py").write_text(TEST, encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    _git(["init", "-q", "-b", "main"], root)
    _git(["-c", "user.name=legion-demo", "-c", "user.email=demo@localhost", "add", "-A"], root)
    _git(["-c", "user.name=legion-demo", "-c", "user.email=demo@localhost", "commit", "-q", "-m", "init"], root)
    return root


def _idea(path: Path, fm: dict[str, Any], body: str) -> None:
    path.write_text(f"---\n{yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)}---\n{body}\n", encoding="utf-8")


def clean_demo_vault(settings: Settings, prefix: str) -> None:
    for sub in ("tasks", "specs", "handoffs", "lessons", "questions", "reports"):
        for p in (settings.ai_dir / sub).glob(f"{prefix}-*.md"):
            p.unlink()
    for p in (settings.ai_dir / "records").glob(f"{prefix}-*"):
        _rm(p)
    for p in settings.inbox_dir.glob("demo-*.md"):
        p.unlink()
    for p in settings.inbox_dir.glob(f"fu-{prefix}-*.md"):
        p.unlink()


def write_ideas(settings: Settings, repo: Path) -> None:
    accept = ["python -m pytest -q"]
    _idea(settings.inbox_dir / "demo-1-low.md",
          {"title": "demo：為 calc 新增 multiply", "kind": "write", "repo": str(repo),
           "mock": {"risk_proposed": "low", "accept_cmds": accept,
                    "actions": [{"type": "write", "path": "calc.py"}],
                    # 第一次執行故意宣稱完成但沒寫檔：VERIFY 會失敗退回 EXEC，展示「不採信自述」
                    "exec": [{"claim": "passed", "write_files": {}},
                             {"claim": "passed", "write_files": {"calc.py": CALC_V1}}]}},
          "低風險：在 worktree 內新增 multiply 並通過測試。")
    _idea(settings.inbox_dir / "demo-2-high.md",
          {"title": "demo：清掉舊的測試檔", "kind": "write", "repo": str(repo),
           "mock": {"risk_proposed": "low", "accept_cmds": accept,
                    "actions": [{"type": "delete", "path": "test_calc.py"}]}},
          "高風險：agent 提議 low，但動作含刪除，規則判定 high → WAIT_HUMAN。")
    _idea(settings.inbox_dir / "demo-3-followup.md",
          {"title": "demo：為 calc 補 docstring", "kind": "write", "repo": str(repo),
           "mock": {"risk_proposed": "low", "accept_cmds": accept,
                    "actions": [{"type": "write", "path": "calc.py"}],
                    "exec": [{"claim": "passed", "write_files": {"calc.py": CALC_V2}}],
                    "followups": [{"title": "demo：新增 power 函式", "body": "書記官回灌的後續想法。"}],
                    "child": {"risk_proposed": "low", "accept_cmds": accept,
                              "actions": [{"type": "write", "path": "calc.py"}],
                              "exec": [{"claim": "passed", "write_files": {"calc.py": CALC_V3}}]}}},
          "會回灌：結案時書記官提出 1 個後續想法寫回 INBOX。")


def _commit() -> str:
    try:
        return _git(["rev-parse", "--short", "HEAD"], PROJECT_ROOT).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


async def run_demo(settings: Settings, max_ticks: int = 40) -> dict[str, Any]:
    tmp = PROJECT_ROOT / ".legion_tmp"
    settings = settings.model_copy(update={
        "schema_name": "demo", "task_prefix": "D", "worktrees_dir": tmp / "demo_worktrees",
        "agent_backend": "mock",
    })
    init_vault(settings)
    clean_demo_vault(settings, settings.task_prefix)
    _rm(settings.worktrees_dir)
    repo = make_demo_repo(tmp / "demo_repo")
    store = await Store.connect(settings.dsn, settings.schema_name)
    try:
        await store.drop_schema()
        await store.close()
        store = await Store.connect(settings.dsn, settings.schema_name)
        await store.init_schema()
        write_ideas(settings, repo)
        runner = Runner(settings, store, MockAgent())
        ticks = 0
        for ticks in range(1, max_ticks + 1):
            summary = await runner.tick()
            if not summary["ingested"] and not summary["advanced"]:
                break
        tasks = await store.list_tasks()
        result: dict[str, Any] = {"ticks": ticks, "tasks": []}
        rows = []
        commit = _commit()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        for t in tasks:
            dur = (t.updated_at - t.created_at).total_seconds() if t.updated_at and t.created_at else 0.0
            result["tasks"].append({"id": t.id, "title": t.title, "state": t.state.value, "risk": t.risk,
                                    "human_touches": t.human_touches, "cost_usd": t.cost_usd,
                                    "duration_s": round(dur, 2), "parent_id": t.parent_id})
            for metric, value in (("state", t.state.value), ("risk", t.risk), ("human_touches", t.human_touches),
                                  ("cost_usd", f"{t.cost_usd:.4f}"), ("duration_s", f"{dur:.2f}"),
                                  ("parent_id", t.parent_id or "")):
                rows.append({"date": now, "commit": commit, "metric": f"demo_mock.{t.id}.{metric}",
                             "value": value, "command": "python -m legion demo --mock"})
        out = settings.data_dir / "metrics.csv"
        new = not out.exists()
        with out.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "commit", "metric", "value", "command"])
            if new:
                w.writeheader()
            w.writerows(rows)
        # demo 的想法檔與回灌檔不留在共用 INBOX，避免被正式 tick 領取
        for p in [*settings.inbox_dir.glob("demo-*.md"), *settings.inbox_dir.glob(f"fu-{settings.task_prefix}-*.md")]:
            p.unlink()
        states = {t.title: t.state for t in tasks}
        result["ok"] = (
            states.get("demo：為 calc 新增 multiply") == State.DONE
            and states.get("demo：清掉舊的測試檔") == State.WAIT_HUMAN
            and states.get("demo：為 calc 補 docstring") == State.DONE
            and states.get("demo：新增 power 函式") == State.DONE
        )
        return result
    finally:
        await store.close()
