"""legion phone-sync：手機互動頁的想法與答案 ↔ legion（只讀寫本機檔與 DB，不呼叫 agent）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import Env, State, low_mock, run

from legion.config import Settings
from legion.phone import parse_repos, sync
from legion.runner import CLARIFY_WAIT
from legion.vault import parse_md

QUESTIONS = [
    {"question": "要支援浮點數嗎？", "options": ["只要整數", "整數與浮點數"], "default": "整數與浮點數", "why": "影響測試"},
    {"question": "要補 docstring 嗎？", "options": ["要", "不用"], "default": "不用"},
]


def _write(d: Path, collection: str, doc_id: str, data: dict[str, Any], version: int = 1) -> None:
    """模擬 ArtifactData list 的匯出：文件內容一份檔，版本記進 versions.json（排程 session 照 list 結果寫）。"""
    (d / collection).mkdir(parents=True, exist_ok=True)
    (d / collection / f"{doc_id}.json").write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    vf = d / "versions.json"
    vs = json.loads(vf.read_text(encoding="utf-8")) if vf.exists() else {}
    vs[f"{collection}/{doc_id}"] = version
    vf.write_bytes(json.dumps(vs).encode("utf-8"))


def _settings(env: Env) -> Settings:
    return env.settings.model_copy(update={"phone_repos": f"t={env.repo};ghost=no-such-dir"})


def _sync(env: Env, in_dir: Path, out_dir: Path, s: Settings | None = None) -> Any:
    async def go() -> Any:
        st = await env.store()
        try:
            return await sync(s or _settings(env), st, in_dir, out_dir)
        finally:
            await st.close()

    return run(go())


def _manifest(out_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    m = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for w in m["writes"]:
        data = json.loads(Path(w["file_path"]).read_text(encoding="utf-8")) if w.get("file_path") else None
        out[(w["collection"], w["doc_id"])] = {**w, "data": data}
    return out


def test_parse_repos() -> None:
    r = parse_repos("a=sandbox_repo; b = . ;bad;=x;c=")
    assert set(r) == {"a", "b"} and r["a"].name == "sandbox_repo" and r["b"].is_absolute()


def test_new_idea_is_queued_once_and_bad_ones_rejected(env: Env, tmp_path: Path) -> None:
    i, o = tmp_path / "in", tmp_path / "out"
    _write(i, "ideas", "i1", {"text": " 幫 calc 加乘法 ", "repo_key": "t", "kind": "write", "status": "new"})
    _write(i, "ideas", "i2", {"text": "x", "repo_key": "water-bim", "status": "new"}, version=4)  # 白名單外
    _write(i, "ideas", "i3", {"text": "", "repo_key": "t", "status": "new"})                  # 空的
    _write(i, "ideas", "i4", {"text": "x" * 501, "repo_key": "t", "status": "new"})           # 太長
    _write(i, "ideas", "i5", {"text": "x", "repo_key": "t", "kind": "rm -rf", "status": "new"})
    _write(i, "ideas", "i6", {"text": "x", "repo_key": "ghost", "status": "new"})             # 路徑不存在
    res = _sync(env, i, o)
    assert res.queued == ["i1"] and sorted(res.rejected) == ["i2", "i3", "i4", "i5", "i6"]
    m = _manifest(o)
    assert m[("ideas", "i1")]["op"] == "update" and m[("ideas", "i1")]["if_version"] == 1
    assert m[("ideas", "i1")]["data"]["status"] == "queued"
    assert m[("ideas", "i2")]["if_version"] == 4 and "白名單" in m[("ideas", "i2")]["data"]["note"]
    files = list(env.settings.inbox_dir.glob("idea-*.md"))
    assert len(files) == 1
    fm, body = parse_md(files[0].read_text(encoding="utf-8"))
    assert body.strip() == "幫 calc 加乘法" and fm["repo"] == env.repo.resolve().as_posix()

    # 寫回失敗、頁面還是 new：不重複建想法，只補狀態
    res2 = _sync(env, i, tmp_path / "out2")
    assert res2.queued == ["i1"] and len(list(env.settings.inbox_dir.glob("idea-*.md"))) == 1


def test_queued_idea_gets_task_id_and_state(env: Env, tmp_path: Path) -> None:
    i = tmp_path / "in"
    _write(i, "ideas", "i1", {"text": "幫 calc 加乘法", "repo_key": "t", "status": "new"})
    _sync(env, i, tmp_path / "o1")
    fname = json.loads((tmp_path / "o1" / "data" / "ideas__i1.json").read_text(encoding="utf-8"))["idea_file"]
    # 想法檔沒有 mock 劇本，MockAgent 會略過不領取以外的情況：這裡改用帶劇本的想法檔模擬已被領取
    p = env.settings.inbox_dir / fname
    text = p.read_text(encoding="utf-8").replace("---\n", "---\nmock: " + json.dumps(low_mock()) + "\n", 1)
    p.write_bytes(text.encode("utf-8"))
    run(env.run_until())
    _write(i, "ideas", "i1", {"text": "幫 calc 加乘法", "repo_key": "t", "status": "queued", "idea_file": fname})
    res = _sync(env, i, tmp_path / "o2")
    assert res.refreshed == ["i1"]
    d = _manifest(tmp_path / "o2")[("ideas", "i1")]["data"]
    assert d["task_id"].startswith("T-") and d["task_state"] == "DONE"
    # 狀態沒變就不再寫
    _write(i, "ideas", "i1", {"text": "x", "repo_key": "t", "status": "queued", "idea_file": fname, **{
        k: d[k] for k in ("task_id", "task_state")}})
    assert _sync(env, i, tmp_path / "o3").refreshed == []


def _ask(env: Env) -> str:
    env.idea("c", "幫 calc 加乘法", low_mock(questions=QUESTIONS))

    async def go() -> str:
        st = await env.ticks(settings=env.settings.model_copy(update={"clarify_idle_minutes": 600.0}))
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.WAIT_HUMAN and t.wait_reason == CLARIFY_WAIT
            return t.id
        finally:
            await st.close()

    return run(go())


def test_clarify_questions_published_and_answer_applied(env: Env, tmp_path: Path) -> None:
    tid = _ask(env)
    i = tmp_path / "in"
    res = _sync(env, i, tmp_path / "o1")
    assert res.clarify_published == [tid]
    doc = _manifest(tmp_path / "o1")[("clarify", tid)]
    assert doc["op"] == "set" and "if_version" not in doc
    assert [q["question"] for q in doc["data"]["questions"]] == ["要支援浮點數嗎？", "要補 docstring 嗎？"]
    _write(i, "clarify", tid, doc["data"])
    assert _sync(env, i, tmp_path / "o2").clarify_published == []  # 沒變就不重寫

    # 手機選了非預設答案 → 回到規劃；題目從頁面移除
    _write(i, "answers", tid, {"mode": "pick", "picks": {"1": "A"}, "status": "new",
                               "asked_at": doc["data"]["asked_at"]})
    _write(i, "clarify", tid, doc["data"], version=2)
    res3 = _sync(env, i, tmp_path / "o3")
    m = _manifest(tmp_path / "o3")
    assert res3.answered == [tid] and m[("answers", tid)]["data"]["status"] == "done"
    assert "PLAN" in m[("answers", tid)]["data"]["note"]
    assert m[("clarify", tid)]["op"] == "delete" and m[("clarify", tid)]["if_version"] == 2

    # 寫回失敗、頁面上答案還是 new：已套用過就回報 done，不要誤報成拒收
    res4 = _sync(env, i, tmp_path / "o4")
    assert res4.answered == [tid] and res4.answer_rejected == []
    assert _manifest(tmp_path / "o4")[("answers", tid)]["data"]["status"] == "done"


def test_stale_or_bad_answers_rejected(env: Env, tmp_path: Path) -> None:
    tid = _ask(env)
    i = tmp_path / "in"
    _write(i, "answers", tid, {"mode": "pick", "picks": {"1": "Z"}, "status": "new"})
    _write(i, "answers", "T-9999", {"mode": "defaults", "status": "new"})
    res = _sync(env, i, tmp_path / "o1")
    assert sorted(res.answer_rejected) == sorted([tid, "T-9999"]) and res.answered == []
    (i / "answers" / "T-9999.json").unlink()  # 模擬已寫回 rejected：下一輪不再出現
    _write(i, "answers", tid, {"mode": "defaults", "status": "new", "asked_at": "2000-01-01"})
    res2 = _sync(env, i, tmp_path / "o2")
    assert res2.answer_rejected == [tid]
    assert "題目已更新" in _manifest(tmp_path / "o2")[("answers", tid)]["data"]["note"]
    # 全部預設 → 規格審查
    _write(i, "answers", tid, {"mode": "defaults", "status": "new"})
    res3 = _sync(env, i, tmp_path / "o3")
    assert res3.answered == [tid] and "SPEC_REVIEW" in _manifest(tmp_path / "o3")[("answers", tid)]["data"]["note"]


def test_empty_whitelist_keeps_ideas_waiting(env: Env, tmp_path: Path) -> None:
    """審查抓到：白名單漏設時不能把想法永久拒收；留在 new，下輪設好再處理。"""
    i = tmp_path / "in"
    _write(i, "ideas", "i1", {"text": "x", "repo_key": "t", "status": "new"})
    res = _sync(env, i, tmp_path / "o", s=env.settings.model_copy(update={"phone_repos": ""}))
    assert res.rejected == [] and res.queued == [] and any("白名單" in w for w in res.warnings)
    assert _manifest(tmp_path / "o") == {}


def test_missing_version_skips_write_with_warning(env: Env, tmp_path: Path) -> None:
    """versions.json 漏一筆：不寫回（避免蓋掉手機剛改的內容），留警告。"""
    i = tmp_path / "in"
    _write(i, "ideas", "i1", {"text": "幫 calc 加乘法", "repo_key": "t", "status": "new"})
    (i / "versions.json").write_bytes(b'{"ideas/i1": null}')
    res = _sync(env, i, tmp_path / "o")
    assert res.queued == ["i1"] and _manifest(tmp_path / "o") == {}
    assert any("ideas/i1" in w for w in res.warnings)


def test_subfolder_target_and_legion_itself(env: Env, tmp_path: Path) -> None:
    """審查抓到：spec 要求 subdir 正確。白名單指到子資料夾 → subdir；指到 legion 本身 → risk_floor mid。"""
    import subprocess

    from legion.config import PROJECT_ROOT

    (env.repo / "pkg").mkdir(exist_ok=True)
    (env.repo / "pkg" / "a.py").write_bytes(b"x = 1\n")
    for cmd in (["add", "pkg"], ["commit", "-qm", "pkg"]):
        subprocess.run(["git", *cmd], cwd=env.repo, check=True, capture_output=True)
    i = tmp_path / "in"
    _write(i, "ideas", "i1", {"text": "只改 pkg", "repo_key": "p", "status": "new"})
    _write(i, "ideas", "i2", {"text": "改 legion", "repo_key": "self", "kind": "readonly", "status": "new"})
    s = env.settings.model_copy(update={"phone_repos": f"p={env.repo / 'pkg'};self={PROJECT_ROOT}"})
    res = _sync(env, i, tmp_path / "o", s=s)
    assert sorted(res.queued) == ["i1", "i2"]
    fms = {fm["title"]: fm for fm, _ in (parse_md(p.read_text(encoding="utf-8"))
                                         for p in env.settings.inbox_dir.glob("idea-*.md"))}
    assert fms["只改 pkg"]["subdir"] == "pkg" and "risk_floor" not in fms["只改 pkg"]
    assert fms["改 legion"]["risk_floor"] == "mid"
