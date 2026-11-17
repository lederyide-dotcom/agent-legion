"""scripts/session_usage.py：依主對話／子代理類型 × 模型統計 token；串流重複行只算一次。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from legion.config import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location("session_usage", Path(PROJECT_ROOT) / "scripts" / "session_usage.py")
assert _spec and _spec.loader
su = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(su)


def _line(mid: str, model: str, out: int, cache_read: int = 0) -> str:
    return json.dumps({"message": {"id": mid, "role": "assistant", "model": model,
                                   "usage": {"input_tokens": 1, "output_tokens": out,
                                             "cache_read_input_tokens": cache_read}}})


def test_counts_main_and_subagents_once_per_message(tmp_path: Path) -> None:
    main = tmp_path / "s1.jsonl"
    main.write_bytes("\n".join([
        _line("m1", "opus", 10), _line("m1", "opus", 10),          # 同一則回覆串流兩行
        _line("m2", "sonnet", 30, cache_read=5),
        json.dumps({"message": {"role": "user", "content": "hi"}}),
        _line("m3", "<synthetic>", 99),
        '{"message": 半行',                                        # 寫到一半
    ]).encode("utf-8"))
    sub = tmp_path / "s1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_bytes(_line("x1", "opus", 60).encode("utf-8"))
    (sub / "agent-a.meta.json").write_bytes(json.dumps({"agentType": "code-reviewer"}).encode("utf-8"))

    rows = {(r["source"], r["model"]): r for r in su.summarize(main)}
    assert set(rows) == {("主對話", "opus"), ("主對話", "sonnet"), ("子代理：code-reviewer", "opus")}
    assert rows[("主對話", "opus")]["messages"] == 1 and rows[("主對話", "opus")]["output_tokens"] == 10
    assert rows[("主對話", "sonnet")]["cache_read_input_tokens"] == 5
    assert rows[("子代理：code-reviewer", "opus")]["output_share"] == 0.6
    assert su.summarize(tmp_path) == su.summarize(main)  # 給資料夾也一樣
    text = su.render(su.summarize(main))
    assert "依模型（輸出 token）：opus 70%、sonnet 30%" in text


def test_missing_target_returns_1(tmp_path: Path) -> None:
    assert su.main([str(tmp_path / "nope.jsonl")]) == 1
    assert su.render([]) == "沒有找到任何回覆紀錄。"
