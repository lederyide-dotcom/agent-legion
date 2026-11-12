"""共用 fixture：每個測試用獨立的 PostgreSQL schema 與暫存 vault，互不干擾。需要 `docker compose up -d db`。"""
from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
import yaml

from legion.agents import MockAgent
from legion.config import Settings
from legion.db import Store
from legion.demo import make_demo_repo
from legion.installs import RecordingInstaller
from legion.models import State, Task
from legion.runner import Runner
from legion.vault import init_vault

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

T = TypeVar("T")
ACCEPT = ["python -m pytest -q"]
CALC_OK = 'def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n'


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class Env:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.schema = f"test_{uuid.uuid4().hex[:10]}"
        self.settings = Settings(
            schema_name=self.schema, vault=tmp / "vault", data_dir=tmp / "data", output_dir=tmp / "out",
            worktrees_dir=tmp / "wt", render_mermaid=False, task_budget_usd=2.0, daily_budget_usd=1000.0,
            # 熔斷相關測試要驗的是熔斷本身；軍師另在 test_advisor.py 開啟測試
            advisor_enabled=False,
        )
        init_vault(self.settings)
        self.repo = make_demo_repo(tmp / "repo")
        self.agent = MockAgent()
        self.installer = RecordingInstaller()

    def idea(self, name: str, title: str, mock: dict[str, Any], **fm: Any) -> Path:
        meta = {"title": title, "kind": "write", "repo": str(self.repo), "mock": mock, **fm}
        p = self.settings.inbox_dir / f"{name}.md"
        p.write_text(f"---\n{yaml.safe_dump(meta, allow_unicode=True)}---\n{title}\n", encoding="utf-8")
        return p

    async def store(self) -> Store:
        st = await Store.connect(self.settings.dsn, self.schema)
        await st.init_schema()
        return st

    async def ticks(self, n: int = 30, settings: Settings | None = None) -> Store:
        st = await self.store()
        runner = Runner(settings or self.settings, st, self.agent, installer=self.installer)
        for _ in range(n):
            s = await runner.tick()
            if not s["ingested"] and not s["advanced"]:
                break
        return st

    async def run_until(self, n: int = 30) -> list[Task]:
        st = await self.ticks(n)
        try:
            return await st.list_tasks()
        finally:
            await st.close()


@pytest.fixture()
def env(tmp_path: Path) -> Iterator[Env]:
    e = Env(tmp_path)
    yield e

    async def drop() -> None:
        st = await Store.connect(e.settings.dsn, e.schema)
        await st.drop_schema()
        await st.close()

    run(drop())


def low_mock(**kw: Any) -> dict[str, Any]:
    m: dict[str, Any] = {
        "risk_proposed": "low", "accept_cmds": ACCEPT, "actions": [{"type": "write", "path": "calc.py"}],
        "exec": [{"claim": "passed", "write_files": {"calc.py": CALC_OK}}],
    }
    m.update(kw)
    return m


def by_title(tasks: list[Task], title: str) -> Task:
    return next(t for t in tasks if t.title == title)


__all__ = ["ACCEPT", "CALC_OK", "Env", "State", "by_title", "low_mock", "run"]
