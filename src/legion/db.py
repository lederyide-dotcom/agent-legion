"""PostgreSQL 存取層（psycopg async）。tasks／task_events（稽核）／agent_runs（成本、耗時、session_id）／evidence。"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import AgentRun, Evidence, State, Task, TaskEvent

LOCK_KEY = 74_2026_11  # pg_advisory_lock 的 key：同一時間只允許一個 tick

DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'write',
    state TEXT NOT NULL,
    risk TEXT,
    risk_proposed TEXT,
    risk_reasons JSONB NOT NULL DEFAULT '[]',
    cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    verdict TEXT,
    human_touches INT NOT NULL DEFAULT 0,
    parent_id TEXT,
    depth INT NOT NULL DEFAULT 0,
    retries INT NOT NULL DEFAULT 0,
    step INT NOT NULL DEFAULT 0,
    halt_reason TEXT,
    return_state TEXT,
    wait_reason TEXT,
    accept_cmds JSONB NOT NULL DEFAULT '[]',
    plan JSONB NOT NULL DEFAULT '{}',
    repo TEXT,
    subdir TEXT,
    worktree TEXT,
    base_commit TEXT,
    install_count INT NOT NULL DEFAULT 0,
    source_path TEXT,
    source_sha TEXT UNIQUE,
    doc_status TEXT NOT NULL,
    doc_approved_by TEXT,
    doc_approved_at TIMESTAMPTZ,
    meta JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS task_events (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    kind TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    detail JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS task_events_task ON task_events(task_id, id);
CREATE TABLE IF NOT EXISTS agent_runs (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    state TEXT NOT NULL,
    step INT NOT NULL,
    role TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT,
    session_id TEXT NOT NULL,
    cost_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    duration_s DOUBLE PRECISION NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    output JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (task_id, state, step, role)
);
CREATE TABLE IF NOT EXISTS evidence (
    task_id TEXT NOT NULL REFERENCES tasks(id),
    id TEXT NOT NULL,
    step INT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    producer TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (task_id, id),
    UNIQUE (task_id, step, label)
);
"""

_TASK_JSON_FIELDS = {"risk_reasons", "accept_cmds", "plan", "meta"}
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _row_to_task(row: dict[str, Any]) -> Task:
    row = dict(row)
    row["cost_usd"] = float(row["cost_usd"])
    return Task.model_validate(row)


class Store:
    def __init__(self, conn: psycopg.AsyncConnection[dict[str, Any]], schema: str) -> None:
        self.conn = conn
        self.schema = schema

    @classmethod
    async def connect(cls, dsn: str, schema: str) -> Store:
        if not _SCHEMA_RE.match(schema):
            raise ValueError(f"非法 schema 名稱：{schema}")
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row)
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await conn.execute(f'SET search_path TO "{schema}"')
        return cls(conn, schema)

    async def close(self) -> None:
        await self.conn.close()

    async def init_schema(self) -> None:
        await self.conn.execute(DDL)

    async def drop_schema(self) -> None:
        await self.conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')

    # ---- 鎖 ----
    async def try_lock(self) -> bool:
        cur = await self.conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (LOCK_KEY,))
        row = await cur.fetchone()
        return bool(row and row["ok"])

    async def unlock(self) -> None:
        await self.conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))

    # ---- tasks ----
    async def next_task_id(self, prefix: str) -> str:
        cur = await self.conn.execute(
            "SELECT id FROM tasks WHERE id LIKE %s ORDER BY id DESC LIMIT 1", (f"{prefix}-%",)
        )
        row = await cur.fetchone()
        n = int(row["id"].split("-")[-1]) + 1 if row else 1
        return f"{prefix}-{n:04d}"

    async def insert_task(self, task: Task) -> Task:
        data = task.model_dump(exclude={"created_at", "updated_at"})
        data["state"] = task.state.value
        data["return_state"] = task.return_state.value if task.return_state else None
        for k in _TASK_JSON_FIELDS:
            data[k] = Jsonb(data[k])
        cols = ", ".join(data)
        vals = ", ".join(f"%({k})s" for k in data)
        async with self.conn.transaction():
            await self.conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({vals})", data)
            await self._event(task.id, "created", None, task.state.value, {"title": task.title})
        return await self.get_task(task.id)

    async def get_task(self, task_id: str) -> Task:
        cur = await self.conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        row = await cur.fetchone()
        if row is None:
            raise KeyError(task_id)
        return _row_to_task(row)

    async def list_tasks(self, states: list[State] | None = None) -> list[Task]:
        if states is None:
            cur = await self.conn.execute("SELECT * FROM tasks ORDER BY id")
        else:
            cur = await self.conn.execute(
                "SELECT * FROM tasks WHERE state = ANY(%s) ORDER BY id", ([s.value for s in states],)
            )
        return [_row_to_task(r) for r in await cur.fetchall()]

    async def has_source(self, sha: str) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM tasks WHERE source_sha = %s", (sha,))
        return await cur.fetchone() is not None

    async def update_task(self, task_id: str, **fields: Any) -> Task:
        if not fields:
            return await self.get_task(task_id)
        data: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in Task.model_fields or k in {"id", "state", "step", "created_at", "updated_at"}:
                raise ValueError(f"update_task 不可直接改 {k}（狀態變更請用 transition）")
            if k in _TASK_JSON_FIELDS:
                v = Jsonb(v)
            elif isinstance(v, State):
                v = v.value
            data[k] = v
        sets = ", ".join(f"{k} = %({k})s" for k in data)
        data["_id"] = task_id
        await self.conn.execute(f"UPDATE tasks SET {sets}, updated_at = now() WHERE id = %(_id)s", data)
        return await self.get_task(task_id)

    async def transition(
        self, task: Task, to_state: State, detail: dict[str, Any] | None = None, **fields: Any
    ) -> Task:
        """單一交易：改狀態、step+1、寫一筆 task_events（每次轉移一筆）。"""
        extra = dict(fields)
        for k, v in list(extra.items()):
            if k in _TASK_JSON_FIELDS:
                extra[k] = Jsonb(v)
            elif isinstance(v, State):
                extra[k] = v.value
        sets = "".join(f", {k} = %({k})s" for k in extra)
        params = {**extra, "_to": to_state.value, "_id": task.id, "_from": task.state.value, "_step": task.step}
        async with self.conn.transaction():
            cur = await self.conn.execute(
                f"UPDATE tasks SET state = %(_to)s, step = step + 1, updated_at = now(){sets} "
                "WHERE id = %(_id)s AND state = %(_from)s AND step = %(_step)s",
                params,
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"{task.id} 狀態已被其他程序變更（預期 {task.state.value}/step {task.step}）")
            await self._event(task.id, "transition", task.state.value, to_state.value, detail or {})
        return await self.get_task(task.id)

    # ---- events ----
    async def _event(
        self, task_id: str, kind: str, from_state: str | None, to_state: str | None, detail: dict[str, Any]
    ) -> None:
        await self.conn.execute(
            "INSERT INTO task_events (task_id, kind, from_state, to_state, detail) VALUES (%s,%s,%s,%s,%s)",
            (task_id, kind, from_state, to_state, Jsonb(detail)),
        )

    async def add_event(self, task_id: str, kind: str, detail: dict[str, Any] | None = None) -> None:
        await self._event(task_id, kind, None, None, detail or {})

    async def events(self, task_id: str, kind: str | None = None) -> list[TaskEvent]:
        if kind is None:
            cur = await self.conn.execute("SELECT * FROM task_events WHERE task_id = %s ORDER BY id", (task_id,))
        else:
            cur = await self.conn.execute(
                "SELECT * FROM task_events WHERE task_id = %s AND kind = %s ORDER BY id", (task_id, kind)
            )
        return [TaskEvent.model_validate(r) for r in await cur.fetchall()]

    async def all_events(self, kind: str) -> list[TaskEvent]:
        cur = await self.conn.execute("SELECT * FROM task_events WHERE kind = %s ORDER BY id", (kind,))
        return [TaskEvent.model_validate(r) for r in await cur.fetchall()]

    async def human_touch(self, task_id: str, category: str, detail: dict[str, Any]) -> Task:
        async with self.conn.transaction():
            await self.conn.execute(
                "UPDATE tasks SET human_touches = human_touches + 1, updated_at = now() WHERE id = %s", (task_id,)
            )
            await self._event(task_id, "human_touch", None, None, {"category": category, **detail})
        return await self.get_task(task_id)

    # ---- agent_runs ----
    async def find_run(self, task_id: str, state: str, step: int, role: str) -> AgentRun | None:
        cur = await self.conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=%s AND state=%s AND step=%s AND role=%s",
            (task_id, state, step, role),
        )
        row = await cur.fetchone()
        return _row_to_run(row) if row else None

    async def record_run(self, run: AgentRun) -> None:
        """單一交易：寫入 agent_run 並把成本加到任務（之後中斷續跑會重用這筆，不重複扣預算）。"""
        async with self.conn.transaction():
            await self.conn.execute(
                "INSERT INTO agent_runs (task_id, state, step, role, backend, model, session_id, cost_usd, "
                "duration_s, status, output, started_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    run.task_id, run.state, run.step, run.role, run.backend, run.model, run.session_id,
                    run.cost_usd, run.duration_s, run.status, Jsonb(run.output), run.started_at,
                ),
            )
            await self.conn.execute(
                "UPDATE tasks SET cost_usd = cost_usd + %s, updated_at = now() WHERE id = %s",
                (run.cost_usd, run.task_id),
            )

    async def runs(self, task_id: str | None = None) -> list[AgentRun]:
        if task_id is None:
            cur = await self.conn.execute("SELECT * FROM agent_runs ORDER BY id")
        else:
            cur = await self.conn.execute("SELECT * FROM agent_runs WHERE task_id = %s ORDER BY id", (task_id,))
        return [_row_to_run(r) for r in await cur.fetchall()]

    async def cost_on(self, day: date) -> float:
        """本地時區當日（午夜起算）的 agent 成本合計；不用 ::date，避免 DB 的 UTC 日期與本地日期錯開。"""
        start = datetime(day.year, day.month, day.day).astimezone()
        end = start + timedelta(days=1)
        cur = await self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM agent_runs WHERE finished_at >= %s AND finished_at < %s",
            (start, end),
        )
        row = await cur.fetchone()
        return float(row["c"]) if row else 0.0

    # ---- evidence ----
    async def next_evidence_id(self, task_id: str) -> str:
        cur = await self.conn.execute("SELECT count(*) AS n FROM evidence WHERE task_id = %s", (task_id,))
        row = await cur.fetchone()
        return f"E-{(int(row['n']) if row else 0) + 1:03d}"

    async def find_evidence(self, task_id: str, step: int, label: str) -> Evidence | None:
        cur = await self.conn.execute(
            "SELECT * FROM evidence WHERE task_id=%s AND step=%s AND label=%s", (task_id, step, label)
        )
        row = await cur.fetchone()
        return Evidence.model_validate(row) if row else None

    async def add_evidence(self, ev: Evidence) -> None:
        await self.conn.execute(
            "INSERT INTO evidence (task_id, id, step, label, kind, path, sha256, producer, caption) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (ev.task_id, ev.id, ev.step, ev.label, ev.kind, ev.path, ev.sha256, ev.producer, ev.caption),
        )

    async def evidence(self, task_id: str) -> list[Evidence]:
        cur = await self.conn.execute("SELECT * FROM evidence WHERE task_id = %s ORDER BY id", (task_id,))
        return [Evidence.model_validate(r) for r in await cur.fetchall()]


def _row_to_run(row: dict[str, Any]) -> AgentRun:
    row = dict(row)
    row["cost_usd"] = float(row["cost_usd"])
    row.pop("id", None)
    return AgentRun.model_validate(row)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
