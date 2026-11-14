"""動態 SVG：GitHub README 與 Obsidian 共用的流程動態圖與儀表 KPI 卡。"""
from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from legion import diagrams as d
from legion.config import PROJECT_ROOT, Settings
from legion.models import State, Task
from legion.motion import animate_flow, dashboard_svg, flow_fingerprint, render_flow_svg, write_dashboard
from legion.vault import init_vault

ROOT = Path(PROJECT_ROOT)
STATS: dict[str, Any] = {"generated_at": "2026-11-15 01:00", "counts": {"running": 1, "waiting": 2, "halt": 3, "done": 4},
                         "total": 10, "cost_today": 1.9, "daily_budget": 2.0, "cost_7d": 5.0, "cost_all": 9.0,
                         "waiting_ids": ["T-0001", "T-0002"], "last_halt": "T-0003：<budget> & 超預算"}


def _check_flow(svg: str) -> None:
    ET.fromstring(svg)  # 合法 XML：GitHub 與 Obsidian 才會當圖片顯示
    assert "foreignObject" not in svg and "<script" not in svg
    assert "<title>" in svg and "<desc>" in svg and "prefers-reduced-motion" in svg
    caps = re.findall(r'class="lg-cap lg-cap-(\d+)"', svg)
    assert [int(c) for c in caps] == list(range(len(d.REPLAY)))
    for i, (nid, text) in enumerate(d.REPLAY):
        assert f"{i + 1}/{len(d.REPLAY)}｜{nid}：" in svg and text.replace("&", "&amp;") in svg
    assert len(re.findall(r'class="lg-step lg-step-\d+"', svg)) == len(d.REPLAY) - 1
    # 流動規則必須在 mermaid 的 `.edge-pattern-solid{stroke-dasharray:0}` 之後，否則實線不會動（審查抓到過）
    ours = svg.index(".flowchart-link.edge-pattern-solid{stroke-dasharray:7 5")
    theirs = [m.start() for m in re.finditer(r"\.edge-pattern-solid\{stroke-dasharray:0", svg)]
    assert theirs and all(x < ours for x in theirs)
    assert ".node .lg-ring{fill:none!important" in svg  # 外框層蓋過 mermaid 的 !important 填色


def test_committed_flow_svg_is_fresh_and_valid() -> None:
    """03_docs/img/flow.svg 是 README 嵌入的那張；流程定義或重播路徑改了卻沒執行 legion docs 就會失敗。"""
    svg = (ROOT / d.FLOW_SVG).read_text(encoding="utf-8")
    assert f"legion-src:{flow_fingerprint()}" in svg, "動態流程圖過期：請在 PowerShell 執行 legion docs"
    _check_flow(svg)


def test_render_and_animate_flow(tmp_path: Path) -> None:
    raw = asyncio.run(render_flow_svg(Settings(), tmp_path))
    _check_flow(animate_flow(raw))


def test_animate_flow_rejects_html_labels() -> None:
    with pytest.raises(ValueError):
        animate_flow('<svg id="x"><foreignObject/></svg>')


def test_replay_follows_real_edges() -> None:
    edges = {(e.a, e.b) for e in d.EDGES}
    for (a, _), (b, _) in zip(d.REPLAY, d.REPLAY[1:]):
        assert (a, b) in edges, f"重播 {a} → {b} 在流程圖上沒有連線"


def test_dashboard_svg_complete_at_rest() -> None:
    svg = dashboard_svg(STATS)
    ET.fromstring(svg)
    for n in ("1", "2", "3", "4"):
        assert f">{n}</text>" in svg
    assert "&lt;budget&gt; &amp; 超預算" in svg  # 內容有逸出
    assert "opacity:0" not in svg and "scaleX(0)" not in svg  # 動畫不播放時也看得到全部數字
    assert 'class="tile t1 pulse"' in svg  # 有事等你 → 外框呼吸提醒
    assert "prefers-color-scheme: dark" in svg and "prefers-reduced-motion" in svg
    quiet = dashboard_svg({**STATS, "counts": {**STATS["counts"], "waiting": 0}})
    assert "pulse" not in re.sub(r"<style>.*</style>", "", quiet, flags=re.S)


def test_write_dashboard_to_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEGION_VAULT", str(tmp_path / "vault"))
    s = Settings()
    tasks = [Task(id=f"T-{i}", title="t", state=st, cost_usd=0.5)
             for i, st in enumerate([State.DONE, State.DONE, State.EXEC])]

    class Store:
        async def list_tasks(self) -> list[Task]:
            return tasks

    out = asyncio.run(write_dashboard(s, Store()))
    svg = out.read_text(encoding="utf-8")
    assert out == s.ai_dir / "img" / "dashboard.svg" and ">2</text>" in svg and "$1.5000" in svg  # 累計


def test_init_vault_embeds_motion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEGION_VAULT", str(tmp_path / "vault"))
    s = Settings()
    init_vault(s)
    assert f"![[{d.VAULT_IMG}/flow.svg]]" in (s.ai_dir / "流程.md").read_text(encoding="utf-8")
    note = (s.ai_dir / "儀表.md").read_text(encoding="utf-8")
    assert f"![[{d.VAULT_IMG}/dashboard.svg]]" in note and "![[儀表.base]]" in note
    assert (s.vault / d.VAULT_IMG / "flow.svg").exists()  # 從 repo 複製，Obsidian 嵌入不會破圖


def test_readme_embeds_both_svgs() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for rel in (d.FLOW_SVG, d.DASHBOARD_SVG):
        assert f'<img src="{rel}"' in text and (ROOT / rel).exists()
    ET.parse(ROOT / d.DASHBOARD_SVG)
