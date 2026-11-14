"""流程圖與儀表的單一來源：README（GitHub）、Obsidian 的流程.md／流程.canvas／儀表.base 必須一致。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from legion import diagrams as d
from legion.cli import main
from legion.config import PROJECT_ROOT
from legion.models import State

README = Path(PROJECT_ROOT) / "README.md"


def test_readme_blocks_are_in_sync() -> None:
    text = README.read_text(encoding="utf-8")
    assert d.sync_readme(text) == text, "README 過期：請執行 legion docs"
    assert main(["docs", "--check"]) == 0


def test_sync_readme_requires_markers() -> None:
    with pytest.raises(ValueError):
        d.sync_readme("# 沒有標記")


def test_nodes_and_edges_are_consistent() -> None:
    ids = [n.id for n in d.NODES]
    assert len(ids) == len(set(ids)) and len({n.mid for n in d.NODES}) == len(ids)
    used = {e.a for e in d.EDGES} | {e.b for e in d.EDGES}
    assert used == set(ids), "每個節點都要有連線，連線只能接到已定義的節點"
    assert {s.value for s in State} <= {n.title for n in d.NODES}
    assert all(n.kind in d.KINDS for n in d.NODES)


def test_mermaid_declares_every_node_once_with_its_class() -> None:
    src = d.mermaid()
    for n in d.NODES:
        o, c = d._SHAPES[n.shape]
        assert src.count(f"{n.mid}{o}{d._mermaid_label(n)}{c}") == 1, n.id
    for kind in d.KINDS:
        line = next(x for x in src.splitlines() if x.strip().startswith("class ") and x.endswith(f" {kind}"))
        assert set(line.split()[1].split(",")) == {n.mid for n in d.NODES if n.kind == kind}
    assert sum("-." in x for x in src.splitlines()) == sum(e.dotted for e in d.EDGES)


def test_obsidian_flow_note_is_the_same_chart() -> None:
    assert f"```mermaid\n{d.mermaid()}\n```" in d.flow_markdown()
    assert f"```mermaid\n{d.mermaid()}\n```" in README.read_text(encoding="utf-8")


def test_canvas_matches_definition() -> None:
    c = d.canvas_json({"planner": ["模型：X"]})
    nodes = {n["id"]: n for n in c["nodes"]}
    for n in d.NODES:
        cn = nodes[f"n-{n.id.lower()}"]
        assert cn["color"] == d.KINDS[n.kind][1] and n.title in cn["text"]
        assert cn["height"] >= 60 + 26 * cn["text"].count("\n")
    assert "模型：X" in nodes["n-plan"]["text"] and "不用模型" in nodes["n-gate"]["text"]
    assert len(c["edges"]) == len(d.EDGES)
    for e, ce in zip(d.EDGES, c["edges"]):
        assert ce["fromNode"] in nodes and ce["toNode"] in nodes
        assert ce.get("label", "") == e.label and (ce.get("color") == d.DOTTED_COLOR) == e.dotted
    boxes = [(n["x"], n["y"]) for n in c["nodes"]]
    assert len(boxes) == len(set(boxes)), "節點位置重疊"


def test_models_canvas_nodes_do_not_overlap() -> None:
    from legion.config import Settings
    from legion.vault import models_canvas_json

    boxes = [(n["x"], n["y"], n["x"] + n["width"], n["y"] + n["height"]) for n in models_canvas_json(Settings())["nodes"]]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], f"重疊：{a} {b}"


def test_dashboard_base_is_valid_and_labelled() -> None:
    base = yaml.safe_load(d.base_yaml())
    assert base == d.DASHBOARD
    for v in base["views"]:
        for prop in v["order"]:
            assert prop in base["properties"], f"{v['name']} 的 {prop} 沒有中文欄名"
            if prop.startswith("formula."):
                assert prop.split(".", 1)[1] in base["formulas"]
    assert set(d.STATE_LABEL) <= {s.value for s in State}
    md = d.dashboard_markdown()
    assert all(v["name"] in md for v in base["views"])
