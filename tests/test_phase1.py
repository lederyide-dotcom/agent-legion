"""spec v0.5 階段 1：持久花費帳本、回灌防護、行號驗證、提示存證。"""
from __future__ import annotations

import hashlib
import subprocess
from datetime import date
from pathlib import Path

from conftest import Env, State, low_mock, run

from legion.checks import check_report, verify_refs
from legion.config import PROJECT_ROOT
from legion.ledger import append_cost, total_on
from legion.models import Task
from legion.risk import accept_cmd_allowed
from legion.vault import is_self_referential, parse_md, write_followup


# ---- 1. 持久花費帳本
def test_ledger_records_calls_and_daily_budget_survives_db_rebuild(env: Env) -> None:
    s = env.settings.model_copy(update={"ledger_include_mock": True, "daily_budget_usd": 5.0})
    # DB 重建前的花費只剩帳本（模擬事故 2）：同 schema 今日已花 5 美元
    append_cost(s.cost_ledger, schema=s.schema_name, task="T-OLD", role="(task total)", backend="claude",
                model="sonnet", session_id="(backfill)", status="backfill", cost_usd=5.0, note="測試回填")
    # 其他 schema（demo）的花費不得算進來
    append_cost(s.cost_ledger, schema="demo", task="D-0001", role="planner", backend="mock", model=None,
                session_id="x", status="completed", cost_usd=99.0)
    env.idea("a", "budget after rebuild", low_mock())

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.HALT and (t.halt_reason or "").startswith("budget_daily"), t.halt_reason
            assert await st.cost_on(date.today()) == 0.0  # DB 本身看不到舊花費，靠帳本擋下
        finally:
            await st.close()

    run(go())
    assert total_on(s.cost_ledger, date.today(), s.schema_name) == 5.0


def test_ledger_real_spend_counts_across_schemas(tmp_path: Path) -> None:
    led = tmp_path / "cost_ledger.csv"
    append_cost(led, schema="other_project", task="O-1", role="planner", backend="claude", model="sonnet",
                session_id="a", status="completed", cost_usd=1.5)
    append_cost(led, schema="demo", task="D-1", role="planner", backend="mock", model=None,
                session_id="b", status="completed", cost_usd=9.0)
    # 真實花費共用同一個帳號額度：換 schema 也要算進來；mock 只算自己的 schema
    assert total_on(led, date.today(), "legion") == 1.5
    assert total_on(led, date.today(), "demo") == 10.5
    # mock backend（demo）只看自己的 schema：不花錢的 demo 不會被真實額度擋下（start.bat 回歸）
    assert total_on(led, date.today(), "demo", real_account=False) == 9.0
    assert total_on(led, date.today(), "legion", real_account=False) == 0.0


def test_real_backend_is_blocked_by_spend_in_other_schemas_but_mock_is_not(env: Env) -> None:
    from legion.agents import MockAgent
    from legion.runner import Runner

    class FakeReal(MockAgent):
        name = "claude"  # 模擬真實 backend：零成本，但預算判斷走帳號共用額度

    s = env.settings.model_copy(update={"daily_budget_usd": 2.0})
    append_cost(s.cost_ledger, schema="other", task="X-1", role="executor", backend="claude", model="sonnet",
                session_id="z", status="completed", cost_usd=3.0)
    # 真實 backend 會跳過帶 mock 劇本的想法檔（既有安全規則），所以這裡寫不帶劇本的想法
    (s.inbox_dir / "a.md").write_text(f"---\ntitle: shared account budget\nkind: write\nrepo: {env.repo}\n---\n加功能\n",
                                      encoding="utf-8")

    async def go(agent: MockAgent) -> State:
        st = await env.store()
        try:
            runner = Runner(s, st, agent, installer=env.installer)
            for _ in range(20):
                summary = await runner.tick()
                if not summary["ingested"] and not summary["advanced"]:
                    break
            return (await st.list_tasks())[0].state
        finally:
            await st.close()

    assert run(go(FakeReal())) == State.HALT  # 其他 schema 的真實花費 3 美元 ≥ 2 → 熔斷
    env.idea("b", "mock ignores other schemas", low_mock())
    assert total_on(s.cost_ledger, date.today(), s.schema_name, real_account=False) == 0.0


def test_ledger_appends_one_row_per_agent_call(env: Env) -> None:
    s = env.settings.model_copy(update={"ledger_include_mock": True})
    env.idea("a", "ledger rows", low_mock())

    async def go() -> None:
        st = await env.ticks(settings=s)
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.DONE
            runs = await st.runs(t.id)
            assert abs(total_on(s.cost_ledger, date.today(), s.schema_name) - sum(r.cost_usd for r in runs)) < 1e-9
            rows = s.cost_ledger.read_text(encoding="utf-8").strip().splitlines()
            assert len(rows) == 1 + len(runs)
        finally:
            await st.close()

    run(go())


def test_ledger_skips_mock_by_default(env: Env) -> None:
    env.idea("a", "no ledger for mock", low_mock())
    run(env.run_until())
    assert not env.settings.cost_ledger.exists()


# ---- 2. 回灌防護
def test_self_referential_followup_becomes_readonly_proposal_on_legion(env: Env) -> None:
    parent = Task(id="T-0100", title="p", kind="write", repo=str(env.repo), depth=0)
    p = write_followup(env.settings, parent, 1, "擴充 runner 的熔斷規則", "讓 risk.py 白名單更嚴", hold=True)
    fm, body = parse_md(p.read_text(encoding="utf-8"))
    assert fm["kind"] == "readonly" and fm["risk_floor"] == "mid" and fm["self_ref"] is True
    assert Path(fm["repo"]) == PROJECT_ROOT and "唯讀提案" in body
    q = write_followup(env.settings, parent, 2, "為 calc 加上 power", "補對應測試", hold=True)
    fq, _ = parse_md(q.read_text(encoding="utf-8"))
    assert fq["kind"] == "write" and fq["repo"] == str(env.repo) and "risk_floor" not in fq
    # 正例（審查者實測漏抓的）：預算、風險門檻、權限、設定檔都屬於 legion 自身規則
    for s in ("提高每日預算上限", "放寬風險門檻", "在 .claude/settings.json 加 allow", "修改 daily_budget_usd",
              "調整權限 deny 清單", "Legion runner.py 重構", "驗收流程加入 git diff --stat"):
        assert is_self_referential(s), s
    # 反例（審查者實測誤抓的）：目標 repo 的一般工作
    for s in ("規格審查建議補上邊界測試", "修正 telegram 白名單 chat_id", "為 config.py 補測試",
              "pytest runner 改用 xdist", "新增 word_count 函式", "書記官建議補 README"):
        assert not is_self_referential(s), s


def test_risk_floor_from_idea_raises_risk_to_mid(env: Env) -> None:
    env.idea("f", "floored", low_mock(), risk_floor="mid")
    t = run(env.run_until())[0]
    assert t.risk == "mid" and any("風險下限 mid" in r for r in t.risk_reasons)
    assert t.state == State.DONE  # mid 只通知、不擋


# ---- 3. 行號驗證
def _repo_with_files(tmp: Path) -> Path:
    root = tmp / "r"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (root / "data.yaml").write_text("nc: 2\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def test_verify_refs_accepts_real_and_rejects_bad_refs(tmp_path: Path) -> None:
    root = _repo_with_files(tmp_path)
    good = "見 `pkg/mod.py:2`、pkg/mod.py:1-3、`data.yaml:1`、只寫檔名 mod.py:3、中文緊貼定義於pkg/mod.py:1"
    n, probs = verify_refs(good, root)
    assert n == 5 and probs == [], probs
    bad = "pkg/mod.py:9、pkg/none.py:1、pkg/mod.py:3-1、D:/elsewhere/x.py:1"
    n, probs = verify_refs(bad, root)
    assert n == 4 and len(probs) == 4
    assert any("超出範圍" in p for p in probs) and any("不存在" in p for p in probs)
    assert any("之外" in p for p in probs)


def test_check_report_verify_refs_exit_codes(tmp_path: Path) -> None:
    root = _repo_with_files(tmp_path)
    rp = tmp_path / "AI" / "reports" / "T-1-report.md"
    rp.parent.mkdir(parents=True)
    body = "# 報告\n## 架構\n" + "說明。" * 300 + "\n## 測試缺口\n- pkg/mod.py:2 未測\n"
    rp.write_text(body, encoding="utf-8")
    assert check_report(rp, ["架構", "測試缺口"], 800, verify=True, root=root) == 0
    assert check_report(rp, ["架構"], 800, verify=True, root=root, min_refs=2) == 1
    rp.write_text(body.replace("pkg/mod.py:2", "pkg/mod.py:99"), encoding="utf-8")
    assert check_report(rp, ["架構"], 800, verify=True, root=root) == 1


def test_report_check_flags_are_whitelisted_narrowly() -> None:
    base = 'python -m legion.checks report "D:/v/AI/reports/T-1-report.md"'
    assert accept_cmd_allowed(base + " --section 架構 --verify-refs")
    assert accept_cmd_allowed(base + " --verify-refs --min-refs 5")
    assert not accept_cmd_allowed(base + " --min-refs x")
    assert not accept_cmd_allowed(base + " --root D:/")  # 根目錄由 cwd 決定，agent 不能指定
    assert not accept_cmd_allowed(base + " --csv out.csv")


# ---- 4. 提示存證
def test_every_agent_prompt_is_saved_as_evidence_and_kept_out_of_digest(env: Env) -> None:
    env.idea("a", "prompts kept", low_mock())

    async def go() -> None:
        st = await env.ticks()
        try:
            t = (await st.list_tasks())[0]
            assert t.state == State.DONE, t.halt_reason
            evs = {e.label: e for e in await st.evidence(t.id)}
            sent = {role: p for tid, role, p in env.agent.prompts if tid == t.id}
            for role in ("planner", "spec_reviewer", "executor", "reviewer", "scribe"):
                ev = evs[f"prompt_{role}"]
                stored = (env.settings.record_dir(t.id) / ev.path).read_text(encoding="utf-8")
                sha = hashlib.sha256(sent[role].encode("utf-8")).hexdigest()
                # vault 只留雜湊，不含全文（全文可能有目標 repo 的 diff，不能 commit）
                assert f"sha256: {sha}" in stored and sent[role][:200] not in stored, role
                local = next(p for p in (env.settings.prompt_dir / t.id).glob("step*_*.md")
                             if p.name.split("_", 1)[1] == f"{role}.md")
                assert local.read_text(encoding="utf-8") == sent[role]
                assert not local.resolve().is_relative_to(env.settings.vault.resolve())
            assert "提示雜湊" not in sent["reviewer"]  # 提示存證不進審查者的證據摘要
        finally:
            await st.close()

    run(go())
