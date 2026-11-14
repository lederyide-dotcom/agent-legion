"""指揮官（runner）依角色分配模型與 effort；執行失敗後升級，審查者不低於執行者。"""
from __future__ import annotations

from pathlib import Path

from conftest import CALC_OK, Env, State, low_mock, run

from legion.agents import AgentCall, ClaudeCliAgent
from legion.config import Settings
from legion.models import Task


def test_model_for_roles_and_escalation() -> None:
    s = Settings()
    assert s.model_for("planner", 0, False) == ("opus", "medium")
    assert s.model_for("executor", 0, False) == ("sonnet", None)
    assert s.model_for("executor", 1, False) == ("opus", "high")  # 重做時升級
    assert s.model_for("reviewer", 0, False) == ("sonnet", "high")
    assert s.model_for("reviewer", 0, True) == ("opus", "high")  # 執行升級過 → 審查跟著升
    assert s.model_for("scribe", 3, True) == ("claude-haiku-5-5", None)  # 書記官不受升級影響
    # --model 總開關：全部角色統一、不升級
    one = s.model_copy(update={"claude_model": "sonnet"})
    assert {one.model_for(r, 2, True) for r in ("planner", "executor", "reviewer", "scribe")} == {("sonnet", None)}
    # 關閉升級
    off = s.model_copy(update={"escalation": None})
    assert off.model_for("executor", 2, True) == ("sonnet", None)


def test_role_table_env_overrides(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LEGION_MODEL_SCRIBE", "sonnet")
    monkeypatch.setenv("LEGION_EFFORT_PLANNER", "none")
    monkeypatch.setenv("LEGION_EFFORT_REVIEWER", "bogus")  # 不合法的值退回預設，不會傳給 CLI
    monkeypatch.setenv("LEGION_ESCALATE_MODEL", "off")
    s = Settings()
    assert s.model_for("scribe", 0, False) == ("sonnet", None)
    assert s.model_for("planner", 0, False) == ("opus", None)
    assert s.model_for("reviewer", 0, False) == ("sonnet", "high")
    assert s.model_for("executor", 1, False) == ("sonnet", None)


def test_cli_args_carry_model_and_effort(tmp_path: Path) -> None:
    task = Task(id="T-1", title="t", kind="write")
    call = AgentCall(role="executor", prompt="p", cwd=tmp_path, schema={}, task=task, model="opus", effort="high")
    argv = ClaudeCliAgent().build_cmd(call, tmp_path / "s.json")
    assert argv[argv.index("--model") + 1] == "opus" and argv[argv.index("--effort") + 1] == "high"
    plain = ClaudeCliAgent().build_cmd(call.model_copy(update={"model": None, "effort": None}), tmp_path / "s.json")
    assert "--model" not in plain and "--effort" not in plain


def test_runner_assigns_models_per_role_and_escalates_after_failure(env: Env) -> None:
    env.idea("m", "escalate", low_mock(exec=[
        {"claim": "passed", "write_files": {}},  # 第一次沒改 → 驗收失敗
        {"claim": "passed", "write_files": {"calc.py": CALC_OK}},
    ]))
    t = run(env.run_until())[0]
    assert t.state == State.DONE, t.halt_reason
    used = [(role, model, effort) for tid, role, model, effort in env.agent.models if tid == t.id]
    assert ("planner", "opus", "medium") in used and ("spec_reviewer", "opus", "medium") in used
    execs = [(m, e) for role, m, e in used if role == "executor"]
    assert execs == [("sonnet", None), ("opus", "high")]
    assert [(m, e) for role, m, e in used if role == "reviewer"] == [("opus", "high")]
    assert [(m, e) for role, m, e in used if role == "scribe"] == [("claude-haiku-5-5", None)]
    assert t.meta.get("executor_escalated") is True


def test_model_canvases_follow_settings() -> None:
    from legion.vault import canvas_json, models_canvas_json

    s = Settings()
    d = models_canvas_json(s)
    ids = {n["id"] for n in d["nodes"]}
    assert all(e["fromNode"] in ids and e["toNode"] in ids for e in d["edges"])  # 合法的 canvas
    texts = " ".join(n["text"] for n in d["nodes"])
    assert "Opus 5.5" in texts and "Sonnet 5.5" in texts and "Haiku 5.5" in texts and "$4／$20" in texts
    red = [e for e in d["edges"] if e.get("color") == "1"]
    assert len(red) == 1 and "指揮官（執行）重做時｜high" in red[0]["label"] and "審查者隨之升級" in red[0]["label"]
    # 關閉升級 → 沒有紅線；改書記官模型 → 圖跟著變
    off = models_canvas_json(s.model_copy(update={
        "escalation": None, "role_models": {**s.role_models, "scribe": ("sonnet", None)}}))
    assert not [e for e in off["edges"] if e.get("color") == "1"]
    assert "Haiku" not in " ".join(n["text"] for n in off["nodes"])
    # 流程畫布的角色節點標註模型；runner 負責的節點標註不用模型
    flow = {n["id"]: n["text"] for n in canvas_json(s)["nodes"]}
    assert "模型：Opus 5.5 / medium" in flow["n-plan"] and "重做時：Opus 5.5 / high" in flow["n-exec"]
    assert "不用模型" in flow["n-verify"] and "模型" not in flow["n-inbox"]


def test_one_pass_task_never_escalates(env: Env) -> None:
    env.idea("o", "one pass", low_mock())
    t = run(env.run_until())[0]
    assert t.state == State.DONE
    used = {(role, m, e) for tid, role, m, e in env.agent.models if tid == t.id}
    assert ("executor", "sonnet", None) in used and ("reviewer", "sonnet", "high") in used
    assert not any(role == "executor" and m == "opus" for role, m, _ in used)


def test_mermaid_cli_env_override(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from legion.config import PROJECT_ROOT
    monkeypatch.delenv("LEGION_MERMAID_CLI", raising=False)
    assert Settings().mermaid_cli == PROJECT_ROOT / "tools" / "mermaid" / "node_modules" / ".bin" / "mmdc.cmd"
    monkeypatch.setenv("LEGION_MERMAID_CLI", str(tmp_path / "mmdc.cmd"))
    assert Settings().mermaid_cli == tmp_path / "mmdc.cmd"
    monkeypatch.setenv("LEGION_MERMAID_CLI", "")  # 空字串＝未設定
    assert Settings().mermaid_cli.name == "mmdc.cmd" and Settings().mermaid_cli.parent.name == ".bin"
