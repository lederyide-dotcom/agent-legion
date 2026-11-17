"""手機互動頁 ↔ legion 的橋接（`legion phone-sync`）：純本機、可測試，不呼叫 agent、不花額度。

互動頁的資料庫只有 Claude 的 ArtifactData 工具讀得到，所以排程 session 只負責搬檔：
  1. ArtifactData list（ideas、answers、clarify，out_dir=<in>）→ 每份文件存成 <in>/<集合>/<id>.json
  2. 把 list 結果裡每份文件的 version 寫成 <in>/versions.json：{"ideas/<id>": 3, ...}
  3. `legion phone-sync --in <in> --out <out>` → <out>/manifest.json（要寫回的 batch 清單）
  4. 照 manifest 呼叫 ArtifactData batch（每筆 file_path 指向 <out> 裡的資料檔）

頁面寫進來的文字一律當資料：只會原樣交給 `legion idea`，不會被當成指令。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import PROJECT_ROOT, Settings
from .db import Store
from .intake import resolve_repo, subdir_for, write_idea
from .models import State, Task
from .runner import CLARIFY_WAIT, Runner, UserError

TEXT_MAX = 500
LEDGER_FIELDS = ["time", "doc_id", "idea_file", "repo_key", "kind"]


class Write(BaseModel):
    op: str                      # set／update／delete
    collection: str
    doc_id: str
    file_path: str | None = None
    if_version: int | None = None


class SyncResult(BaseModel):
    queued: list[str] = []
    rejected: list[str] = []
    refreshed: list[str] = []
    answered: list[str] = []
    answer_rejected: list[str] = []
    clarify_published: list[str] = []
    clarify_removed: list[str] = []
    warnings: list[str] = []
    writes: list[Write] = []


def parse_repos(spec: str) -> dict[str, Path]:
    """`sandbox=sandbox_repo;legion=.` → {key: 絕對路徑}；相對路徑以 legion 專案根目錄為準。"""
    out: dict[str, Path] = {}
    for part in spec.split(";"):
        key, sep, path = part.partition("=")
        if not sep or not key.strip() or not path.strip():
            continue
        p = Path(path.strip())
        out[key.strip()] = (p if p.is_absolute() else Path(PROJECT_ROOT) / p).resolve()
    return out


def _docs(in_dir: Path, collection: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for f in sorted((in_dir / collection).glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out[f.stem] = data
    return out


def _ledger(settings: Settings) -> Path:
    return settings.data_dir / "phone_sync.csv"


def _seen(settings: Settings) -> dict[str, str]:
    p = _ledger(settings)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8", newline="") as f:
        return {r["doc_id"]: r["idea_file"] for r in csv.DictReader(f)}


def _record(settings: Settings, doc_id: str, idea_file: str, repo_key: str, kind: str) -> None:
    p = _ledger(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({"time": datetime.now().astimezone().isoformat(timespec="seconds"), "doc_id": doc_id,
                    "idea_file": idea_file, "repo_key": repo_key, "kind": kind})


def _check_idea(v: dict[str, Any], repos: dict[str, Path]) -> tuple[str, str, str]:
    text, key, kind = v.get("text"), v.get("repo_key"), v.get("kind", "write")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("想法是空的")
    if len(text) > TEXT_MAX:
        raise ValueError(f"想法超過 {TEXT_MAX} 字")
    if not isinstance(key, str) or key not in repos:
        raise ValueError(f"目標專案不在白名單：{key!r}（可用：{'、'.join(repos) or '無，請設定 LEGION_PHONE_REPOS'}）")
    if kind not in ("write", "readonly"):
        raise ValueError(f"類型必須是 write 或 readonly：{kind!r}")
    return text.strip(), key, kind


def _task_for(tasks: list[Task], idea_file: str) -> Task | None:
    for t in tasks:
        if t.source_path and Path(t.source_path).name in (idea_file, f"{t.id}__{idea_file}"):
            return t
    return None


def _task_fields(t: Task) -> dict[str, Any]:
    state = t.state.value + (f"（{t.wait_reason}）" if t.state == State.WAIT_HUMAN and t.wait_reason else "")
    return {"task_id": t.id, "task_state": state}


class _Out:
    def __init__(self, out_dir: Path, versions: dict[str, int], existing: set[str]) -> None:
        self.dir, self.versions, self.existing = out_dir, versions, existing
        self.writes: list[Write] = []
        self.warnings: list[str] = []
        (out_dir / "data").mkdir(parents=True, exist_ok=True)

    def put(self, op: str, collection: str, doc_id: str, data: dict[str, Any] | None = None) -> None:
        key = f"{collection}/{doc_id}"
        if key in self.existing and key not in self.versions:
            # 沒有版本就寫，可能蓋掉手機剛改的內容：寧可這輪不寫，下輪再補
            self.warnings.append(f"versions.json 缺 {key}：這筆不寫回")
            return
        fp = None
        if data is not None:
            f = self.dir / "data" / f"{collection}__{doc_id}.json"
            f.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            fp = str(f.resolve())  # 絕對路徑：排程 session 的工作目錄不一定相同
        self.writes.append(Write(op=op, collection=collection, doc_id=doc_id, file_path=fp,
                                 if_version=self.versions.get(f"{collection}/{doc_id}")))


async def sync(settings: Settings, store: Store, in_dir: Path, out_dir: Path, by: str = "phone",
               repos_spec: str | None = None) -> SyncResult:
    repos = parse_repos(settings.phone_repos if repos_spec is None else repos_spec)
    versions_file = in_dir / "versions.json"
    versions: dict[str, int] = {}
    if versions_file.exists():
        raw = json.loads(versions_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("versions.json 必須是物件")
        versions = {str(k): int(v) for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}
    docs = {c: _docs(in_dir, c) for c in ("ideas", "answers", "clarify")}
    existing = {f"{c}/{d}" for c, ds in docs.items() for d in ds}
    out, res = _Out(out_dir, versions, existing), SyncResult()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = _seen(settings)
    tasks = await store.list_tasks()
    if not repos:  # 白名單沒設（例如環境變數漏設）：想法留在 new，下輪再處理，不要永久拒收
        res.warnings.append("白名單是空的（LEGION_PHONE_REPOS 或 --repos）：這輪不處理新想法")

    # 1. 新想法 → INBOX；已排入的 → 回填任務編號與狀態
    for doc_id, v in docs["ideas"].items():
        status = v.get("status")
        if status == "new" and not repos and doc_id not in seen:
            continue
        if status == "new":
            if doc_id in seen:  # 上次寫回失敗：不重複建想法，只補狀態
                out.put("update", "ideas", doc_id, {"status": "queued", "idea_file": seen[doc_id],
                                                    "note": "已排入", "synced_at": now})
                res.queued.append(doc_id)
                continue
            try:
                text, key, kind = _check_idea(v, repos)
                repo = resolve_repo(str(repos[key]), settings, Path(PROJECT_ROOT))
                if repo is None:
                    raise ValueError(f"{key} 找不到 git repo")
                sub = subdir_for(str(repos[key]), settings, repo, kind)
                path = write_idea(settings, text, repo, kind, subdir=sub)
            except (ValueError, OSError) as exc:
                out.put("update", "ideas", doc_id, {"status": "rejected", "note": str(exc)[:200], "synced_at": now})
                res.rejected.append(doc_id)
                continue
            _record(settings, doc_id, path.name, key, kind)
            out.put("update", "ideas", doc_id, {"status": "queued", "idea_file": path.name, "note": "已排入",
                                                "synced_at": now})
            res.queued.append(doc_id)
        elif status == "queued" and isinstance(v.get("idea_file"), str):
            t = _task_for(tasks, v["idea_file"])
            if t is not None:
                fields = _task_fields(t)
                if any(v.get(k) != val for k, val in fields.items()):
                    out.put("update", "ideas", doc_id, {**fields, "synced_at": now})
                    res.refreshed.append(doc_id)

    # 2. 手機的答案 → legion clarify（題目已換過或任務不在等答案，就拒收並說明）
    runner = Runner(settings, store, _NoAgent())
    for task_id, v in docs["answers"].items():
        if v.get("status") != "new":
            continue
        answer_key = f"answers/{task_id}@{v.get('asked_at', '')}"
        if answer_key in seen:  # 上次已套用但寫回失敗：不要誤報成拒收
            out.put("update", "answers", task_id, {"status": "done", "note": "已套用", "synced_at": now})
            res.answered.append(task_id)
            continue
        try:
            task = await store.get_task(task_id)
        except (KeyError, LookupError, ValueError):
            task = None
        try:
            if task is None:
                raise UserError(f"找不到任務 {task_id}")
            c = Runner._clarify_pending(task)
            if c is None:
                raise UserError(f"{task_id} 已不在等需求釐清（{task.state.value}）")
            if v.get("asked_at") and str(v["asked_at"]) != str(c.get("asked_at")):
                raise UserError("題目已更新，請重新回答")
            picks = v.get("picks") if isinstance(v.get("picks"), dict) else {}
            answers = None if v.get("mode") == "defaults" or not picks else {str(k): str(x) for k, x in picks.items()}
            t = await runner.clarify(task_id, answers, by)
            _record(settings, answer_key, "", "", "answer")
            out.put("update", "answers", task_id, {"status": "done", "note": f"已套用 → {t.state.value}",
                                                   "synced_at": now})
            res.answered.append(task_id)
        except (UserError, ValueError) as exc:
            out.put("update", "answers", task_id, {"status": "rejected", "note": str(exc)[:200], "synced_at": now})
            res.answer_rejected.append(task_id)

    # 3. 待答題目 → 互動頁（答完或不再等待的就移除）
    tasks = await store.list_tasks([State.WAIT_HUMAN])
    pending = {t.id: (t, c) for t in tasks if (c := Runner._clarify_pending(t)) is not None
               and t.wait_reason == CLARIFY_WAIT}
    existing = docs["clarify"]
    for task_id, (t, c) in pending.items():
        doc = {"title": t.title, "asked_at": str(c.get("asked_at", "")),
               "questions": [{k: q.get(k) for k in ("id", "question", "options", "default", "why")}
                             for q in c.get("questions", [])]}
        if existing.get(task_id) != doc:
            out.put("set", "clarify", task_id, doc)
            res.clarify_published.append(task_id)
    for task_id in existing:
        if task_id not in pending:
            out.put("delete", "clarify", task_id)
            res.clarify_removed.append(task_id)

    res.writes = out.writes
    res.warnings += out.warnings
    manifest = {"writes": [w.model_dump(exclude_none=True) for w in out.writes],
                "summary": res.model_dump(exclude={"writes"})}
    (out_dir / "manifest.json").write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return res


class _NoAgent:
    """phone-sync 不呼叫 agent；clarify 只改狀態。被呼叫就是程式錯誤。"""

    name = "none"

    async def run(self, call: Any) -> Any:  # pragma: no cover
        raise RuntimeError("phone-sync 不應呼叫 agent")
