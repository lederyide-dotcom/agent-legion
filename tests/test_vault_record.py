"""Vault 匯出、紀錄文件完整、證據可追溯、敘述不得無憑據、證據不可被改寫、圖確實產生、正式文件匯出、文件狀態。"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
from pathlib import Path

import yaml
from conftest import ACCEPT, Env, State, low_mock, run

from legion.agents import INSTALL_CMD_RE, tool_profile
from legion.checks import check_record, narrative_violations
from legion.evidence import image_stats
from legion.export import append_export_check, export
from legion.models import DOC_APPROVED, DOC_DRAFT
from legion.record import CHAPTERS
from legion.runner import Runner
from legion.vault import parse_md


def _done(env: Env, **kw: object) -> str:
    env.idea("a", "recorded task", low_mock(**kw))

    async def go() -> str:
        st = await env.ticks()
        t = (await st.list_tasks())[0]
        assert t.state == State.DONE, t.halt_reason
        await st.close()
        return t.id

    return run(go())


def test_task_note_frontmatter_matches_db_and_base_canvas_are_valid(env: Env) -> None:
    env.idea("a", "note task", low_mock())
    env.idea("h", "high note", low_mock(actions=[{"type": "delete", "path": "x"}]))

    async def go() -> None:
        st = await env.ticks()
        for t in await st.list_tasks():
            fm, _ = parse_md((env.settings.ai_dir / "tasks" / f"{t.id}.md").read_text(encoding="utf-8"))
            assert fm["id"] == t.id and fm["state"] == t.state.value and fm["risk"] == t.risk
            assert fm["cost_usd"] == round(t.cost_usd, 6) and fm["human_touches"] == t.human_touches
            assert fm["verdict"] == t.verdict
        await st.close()

    run(go())
    base = yaml.safe_load((env.settings.ai_dir / "儀表.base").read_text(encoding="utf-8"))
    assert isinstance(base["views"], list) and base["views"]
    for v in base["views"]:
        assert v["type"] in {"table", "cards", "list", "map"} and v["name"] and v["order"]
        for prop in v["order"]:
            if prop.startswith("formula."):
                assert prop.split(".", 1)[1] in base["formulas"]
    assert {"state", "risk", "cost_usd"} <= {v.get("groupBy", {}).get("property") for v in base["views"]} | {
        "cost_usd"}
    canvas = json.loads((env.settings.ai_dir / "流程.canvas").read_text(encoding="utf-8"))
    ids = [n["id"] for n in canvas["nodes"]]
    assert len(ids) == len(set(ids))
    for n in canvas["nodes"]:
        assert {"id", "type", "x", "y", "width", "height"} <= set(n)
    for e in canvas["edges"]:
        assert e["fromNode"] in ids and e["toNode"] in ids
    assert {n["id"] for n in canvas["nodes"]} >= {f"n-{s.lower()}" for s in
                                                    ("INBOX", "PLAN", "GATE", "VERIFY", "DONE", "HALT")}


def test_record_has_8_chapters_and_every_criterion(env: Env) -> None:
    accept = [*ACCEPT, "git status --porcelain"]
    tid = _done(env, accept_cmds=accept)
    rec = env.settings.record_dir(tid) / "record.md"
    text = rec.read_text(encoding="utf-8")
    for c in CHAPTERS:
        assert f"## {c}" in text
    r = check_record(rec, accept)
    assert r.ok, r
    assert r.n_evidence > 5


def test_record_checker_detects_untraceable_and_uncited(env: Env) -> None:
    tid = _done(env)
    rdir = env.settings.record_dir(tid)
    rec = rdir / "record.md"
    text = rec.read_text(encoding="utf-8")
    assert check_record(rec, ACCEPT).ok
    # 1) 證據檔被改 → SHA-256 不符
    ev = next((rdir / "evidence").glob("*_verify1_c1.txt"))
    os.chmod(ev, stat.S_IWRITE | stat.S_IREAD)
    ev.write_text("tampered", encoding="utf-8")
    assert check_record(rec, ACCEPT).hash_mismatch
    # 2) 結論沒有引用證據 → 列出並失敗
    bad = text.replace("**結論**：規格審查通過", "**結論**：我覺得規格很好。規格審查通過")
    # 證據編號會因前面多存的證據（例如提示全文）而變動：找出實際引用的編號再移除，斷言意圖不變
    cited = re.search(r"規格審查通過（(E-\d{3})）。", bad)
    assert cited, "紀錄文件應以證據編號引用規格審查結論"
    bad = bad.replace(cited.group(0), "規格審查通過。")
    rec.write_text(bad, encoding="utf-8")
    viol = narrative_violations(bad)
    assert any("我覺得規格很好" in v for v in viol)
    # 3) 引用不存在的證據 → unknown
    rec.write_text(text + "\nE-999\n", encoding="utf-8")
    assert "E-999" in check_record(rec, ACCEPT).unknown_evidence
    # 4) 圖沒有圖說
    rec.write_text(text.replace("*圖 1：", "圖說遺失 1："), encoding="utf-8")
    assert check_record(rec, ACCEPT).uncaptioned_images


def test_scribe_cannot_write_evidence_and_hashes_unchanged(env: Env) -> None:
    prof = tool_profile("scribe")
    assert not {"Write", "Edit", "Bash", "NotebookEdit"} & set(prof.tools)
    assert {"Edit", "Write", "Bash"} <= set(prof.deny)
    tid = _done(env)

    async def go() -> None:
        st = await env.store()
        evs = await st.evidence(tid)
        rdir = env.settings.record_dir(tid)
        for e in evs:
            p = rdir / e.path
            assert not os.access(p, os.W_OK), f"{p} 應為唯讀"
            from legion.evidence import sha256_file
            assert sha256_file(p) == e.sha256  # LEARN 之後（結案）雜湊仍與登錄時相同
        learn_runs = [r for r in await st.runs(tid) if r.role == "scribe"]
        assert len(learn_runs) == 1
        await st.close()

    run(go())


def test_runner_halts_if_evidence_changed_during_learn(env: Env) -> None:
    env.idea("x", "tamper", low_mock(tamper_evidence=True))

    async def go() -> None:
        st = await env.ticks()
        t = (await st.list_tasks())[0]
        assert t.state == State.HALT and t.halt_reason and t.halt_reason.startswith("evidence_tampered")
        assert t.return_state == State.LEARN
        await st.close()

    run(go())


def test_images_terminal_chart_mermaid_are_real(env: Env) -> None:
    env.settings.render_mermaid = True
    tid = _done(env)
    rec = env.settings.record_dir(tid) / "record.md"
    text = rec.read_text(encoding="utf-8")
    imgs = [ln.split("(")[1].rstrip(")") for ln in text.splitlines() if ln.startswith("![")]
    kinds = {"term": False, "chart": False, "mermaid": False}
    for rel in imgs:
        w, h, sd = image_stats(rec.parent / rel)
        assert w >= 200 and h >= 80 and sd > 5, (rel, w, h, sd)
        kinds["term"] |= "_term" in rel
        kinds["chart"] |= "runs_chart" in rel
        kinds["mermaid"] |= "mermaid" in rel
    assert all(kinds.values()), kinds
    assert "```mermaid" in text


def test_export_docx_and_pdf_contain_toc_chapters_images(env: Env) -> None:
    env.settings.render_mermaid = True
    tid = _done(env)
    n_img = sum(1 for ln in (env.settings.record_dir(tid) / "record.md").read_text(encoding="utf-8").splitlines()
                if ln.startswith("!["))
    out = env.settings.data_dir / "export_check.csv"
    for fmt in ("docx", "pdf"):
        path = run(export(env.settings, tid, fmt))
        assert path.exists() and path.parent == env.settings.output_dir
        row = append_export_check(out, tid, path, n_img)
        assert row["ok"], row
    assert out.exists()


def test_doc_status_draft_until_approved(env: Env) -> None:
    tid = _done(env)
    rec = env.settings.record_dir(tid) / "record.md"
    assert DOC_DRAFT in rec.read_text(encoding="utf-8")

    async def go() -> None:
        st = await env.store()
        before = await st.get_task(tid)
        t = await Runner(env.settings, st, env.agent).approve_doc(tid, "David")
        assert t.doc_status == DOC_APPROVED and t.doc_approved_by == "David" and t.doc_approved_at
        assert t.human_touches == before.human_touches + 1
        ev = await st.events(tid, "human_touch")
        assert ev[-1].detail["category"] == "doc_approval"
        await st.close()

    run(go())
    text = rec.read_text(encoding="utf-8")
    fm, _ = parse_md(text)
    assert fm["doc_status"] == DOC_APPROVED and fm["approved_by"] == "David"
    assert f"> [!warning] {DOC_DRAFT}" not in text and "核可人：David" in text


def test_reviewer_and_scribe_tool_lists_have_no_install_commands() -> None:
    for role in ("spec_reviewer", "reviewer", "scribe", "planner"):
        prof = tool_profile(role)
        assert "Bash" not in prof.tools
        for rule in prof.allow:
            assert not INSTALL_CMD_RE.search(rule), (role, rule)
    ex = tool_profile("executor")
    for needed in ("Bash(pip *)", "Bash(* -m pip *)", "Bash(npm *)", "Bash(winget *)", "Bash(curl *)"):
        assert needed in ex.deny
    for rule in ex.allow:
        assert not INSTALL_CMD_RE.search(rule), rule


def test_cleanup_tmp_ok(tmp_path: Path) -> None:
    # 確保唯讀證據檔不會讓暫存目錄清不掉（Windows）
    p = tmp_path / "e.txt"
    p.write_text("x", encoding="utf-8")
    p.chmod(stat.S_IREAD)
    shutil.rmtree(tmp_path, onerror=lambda f, q, _e: (os.chmod(q, stat.S_IWRITE), f(q)))
    assert not tmp_path.exists()
