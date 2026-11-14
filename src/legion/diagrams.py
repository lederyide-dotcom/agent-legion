"""閉環流程圖與儀表的單一來源：README（GitHub）與 Obsidian 的流程.md、流程.canvas、儀表.base 都從這裡產生。

改流程只改這個檔，然後執行 `legion docs` 同步 README；Obsidian 端在 `legion init-vault` 或每次 tick 時更新。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

# ---------------------------------------------------------------- 顏色（README 與 Obsidian 共用）
# kind → (填色, 邊框, 說明)
KINDS: dict[str, tuple[str, str, str]] = {
    "claude": ("#e8f0fe", "#4a6cf7", "藍色＝Claude 擔任的角色"),
    "runner": ("#fff4e5", "#e8a317", "橘色＝runner 以程式判斷（不經 LLM）"),
    "human": ("#fdecea", "#d93025", "紅色＝停下來等人或熔斷"),
    "plain": ("#f1f3f4", "#9aa0a6", "灰色＝起點、終點與暫存"),
}
DOTTED_COLOR = "#9aa0a6"  # canvas 沒有虛線，例外與補救路徑改用灰線
LEGEND = "、".join(v[2] for v in KINDS.values()) + "；虛線（畫布上為灰線）是例外或補救路徑。"


@dataclass(frozen=True)
class Node:
    id: str          # canvas id 為 n-<id 小寫>
    mid: str         # mermaid 節點代號
    title: str       # 第一行（狀態名）
    desc: str        # 第二行說明，可空
    kind: str
    shape: str       # rect / stadium / hex / cylinder
    col: float       # canvas 格位
    row: float
    role: str | None = None  # 標註模型用的角色


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    label: str = ""
    dotted: bool = False
    sides: tuple[str, str] = ("right", "left")  # 只給 canvas 用


NODES: tuple[Node, ...] = (
    Node("INBOX", "INBOX", "INBOX", "使用者丟想法", "plain", "stadium", 0, 0),
    Node("PLAN", "PLAN", "PLAN", "指揮官規劃", "claude", "rect", 1, 0, "planner"),
    Node("SPEC_REVIEW", "SR", "SPEC_REVIEW", "規格審查者", "claude", "rect", 2, 0, "spec_reviewer"),
    Node("GATE", "GATE", "GATE", "依規則判定風險", "runner", "hex", 3, 0),
    Node("WAIT_HUMAN", "WH", "WAIT_HUMAN", "等使用者決定（錦囊閒置可自動決議）", "human", "stadium", 4, 0),
    Node("EXEC", "EXEC", "EXEC", "指揮官在 worktree 執行", "claude", "rect", 3, 1, "executor"),
    Node("VERIFY", "VERIFY", "VERIFY", "runner 親自跑驗收指令", "runner", "hex", 2, 1),
    Node("REVIEW", "REVIEW", "REVIEW", "交付審查者", "claude", "rect", 1, 1, "reviewer"),
    Node("LEARN", "LEARN", "LEARN", "書記官紀錄", "claude", "rect", 0, 1, "scribe"),
    Node("DONE", "DONE", "DONE", "", "plain", "stadium", 0, 2),
    Node("HOLD", "HOLD", "inbox_hold", "", "plain", "cylinder", -1, 0.5),
    Node("ADVISOR", "ADV", "ADVISOR", "軍師診斷＋錦囊", "claude", "rect", 2, 2, "advisor"),
    Node("HALT", "HALT", "HALT", "", "human", "stadium", 4, 1),
    Node("ANY", "ANY", "任一狀態", "", "plain", "rect", 4, 2),
)

EDGES: tuple[Edge, ...] = (
    Edge("INBOX", "PLAN"),
    Edge("PLAN", "SPEC_REVIEW"),
    Edge("SPEC_REVIEW", "PLAN", "revise 退回", sides=("top", "top")),
    Edge("SPEC_REVIEW", "GATE", "pass"),
    Edge("GATE", "WAIT_HUMAN", "high"),
    Edge("WAIT_HUMAN", "EXEC", "核准 / 錦囊：帶指引重試", sides=("bottom", "top")),
    Edge("WAIT_HUMAN", "HALT", "拒絕 / 錦囊：拆分、放棄", sides=("bottom", "top")),
    Edge("GATE", "EXEC", "low / mid", sides=("bottom", "top")),
    Edge("EXEC", "VERIFY", sides=("left", "right")),
    Edge("EXEC", "WAIT_HUMAN", "要安裝套件", sides=("right", "bottom")),
    Edge("VERIFY", "EXEC", "失敗，重試 ≤ 3", sides=("bottom", "bottom")),
    Edge("VERIFY", "REVIEW", "通過", sides=("left", "right")),
    Edge("VERIFY", "WAIT_HUMAN", "diff 判為 high / 範圍外檔案", sides=("top", "left")),
    Edge("WAIT_HUMAN", "VERIFY", "核准後重驗", True, sides=("left", "top")),
    Edge("REVIEW", "EXEC", "fail 退回", sides=("top", "top")),
    Edge("REVIEW", "LEARN", "pass", sides=("left", "right")),
    Edge("LEARN", "DONE", sides=("bottom", "top")),
    Edge("LEARN", "HOLD", "後續想法", True, sides=("left", "bottom")),
    Edge("HOLD", "INBOX", "使用者放行", True, sides=("top", "left")),
    Edge("VERIFY", "ADVISOR", "同一錯誤反覆 / 超重試", sides=("bottom", "top")),
    Edge("SPEC_REVIEW", "ADVISOR", "退回超過上限", True, sides=("bottom", "left")),
    Edge("REVIEW", "ADVISOR", "退回超過上限", True, sides=("bottom", "left")),
    Edge("ADVISOR", "WAIT_HUMAN", "至少 3 個錦囊", sides=("right", "right")),
    Edge("ADVISOR", "HALT", "呼叫失敗 / 預算不足 / 錦囊不足", True, sides=("right", "left")),
    Edge("WAIT_HUMAN", "PLAN", "錦囊：改寫規格", sides=("top", "top")),
    Edge("ANY", "HALT", "超預算 / 逾時 / STOP / 軍師關閉或問滿", True, sides=("top", "bottom")),
    Edge("HALT", "ANY", "legion resume 回原狀態", True, sides=("right", "right")),
)

_BY_ID = {n.id: n for n in NODES}

# 動態流程圖重播的真實任務：T-0022。依據 vault/AI/records/T-0022/record.md 的狀態時間軸與證據（軍師在第 14 列 VERIFY
# 期間執行，E-036、E-037），加上之後 `legion choose T-0022 B` 與手動驗證合併（02_data/verify_20261114.md 第 14 節）
REPLAY_TASK = "T-0022"
REPLAY: tuple[tuple[str, str], ...] = (
    ("INBOX", "收到想法：safe_workspace_path 補邊界測試"),
    ("PLAN", "指揮官規劃（Sonnet）"),
    ("SPEC_REVIEW", "規格審查：退回重寫"),
    ("PLAN", "依審查意見重寫規格"),
    ("SPEC_REVIEW", "規格審查：通過"),
    ("GATE", "守門：判為 high 風險"),
    ("WAIT_HUMAN", "等你核准 → 核准"),
    ("EXEC", "在 worktree 執行（Sonnet）"),
    ("VERIFY", "守門檢查不過：改到既有測試行"),
    ("EXEC", "升級 Opus 重做"),
    ("VERIFY", "驗收通過"),
    ("REVIEW", "交付審查：退回"),
    ("EXEC", "依審查意見修正"),
    ("VERIFY", "同一錯誤反覆出現"),
    ("ADVISOR", "軍師診斷：規格與守門規則衝突，提出 4 個錦囊"),
    ("WAIT_HUMAN", "高風險不自動決議 → 你選 B：核准那一行例外"),
    ("HALT", "錦囊 B 需人工 → 手動驗證後合併"),
)


# ---------------------------------------------------------------- mermaid（README 與 Obsidian 流程.md）
_SHAPES = {"rect": ("[", "]"), "stadium": ("([", "])"), "hex": ("{{", "}}"), "cylinder": ("[(", ")]")}


def _mermaid_label(n: Node) -> str:
    return f"{n.title}<br/>{n.desc}" if n.desc else n.title


def mermaid() -> str:
    """閉環流程的 mermaid 原始碼（不含 ``` 圍欄）。"""
    lines = ["flowchart TD"]
    declared: set[str] = set()

    def ref(nid: str) -> str:
        n = _BY_ID[nid]
        if n.id in declared:
            return n.mid
        declared.add(n.id)
        o, c = _SHAPES[n.shape]
        return f"{n.mid}{o}{_mermaid_label(n)}{c}"

    for e in EDGES:
        a = ref(e.a)
        arrow = (f" -. {e.label} .-> " if e.label else " -.-> ") if e.dotted else (
            f" -- {e.label} --> " if e.label else " --> ")
        lines.append(f"    {a}{arrow}{ref(e.b)}")
    lines.append("")
    for kind, (fill, stroke, _) in KINDS.items():
        lines.append(f"    classDef {kind} fill:{fill},stroke:{stroke},color:#111")
    for kind in KINDS:
        members = [n.mid for n in NODES if n.kind == kind]
        lines.append(f"    class {','.join(members)} {kind}")
    return "\n".join(lines)


# 動態 SVG 的位置（相對於 repo 根目錄與 vault）；內容由 motion.py 產生
FLOW_SVG = "03_docs/img/flow.svg"
DASHBOARD_SVG = "03_docs/img/dashboard.svg"
VAULT_IMG = "AI/img"
MOTION_NOTE = (f"橘色光暈與底部字幕依序重播任務 {REPLAY_TASK} 的真實路徑，連線上的虛線往流向移動；"
               "系統開啟「減少動態」時不播放。")


def flow_markdown() -> str:
    """Obsidian 的 AI/流程.md：與 README 同一張動態圖；下方附靜態 mermaid。"""
    return ("# 閉環流程\n\n> 由 `src/legion/diagrams.py` 產生，與 GitHub README 的圖相同；請改程式，不要手改此檔。\n\n"
            f"![[{VAULT_IMG}/flow.svg]]\n\n圖例：{LEGEND}{MOTION_NOTE}\n\n"
            f"## 靜態版\n\n```mermaid\n{mermaid()}\n```\n\n"
            "互動版（可拖曳、標註各角色模型）：[[流程.canvas]]；任務總覽：[[儀表]]\n")


def dashboard_note() -> str:
    """Obsidian 的 AI/儀表.md：上方動態 KPI 卡，下方嵌入儀表.base 表格。"""
    return ("# 儀表\n\n> 由 `src/legion/diagrams.py` 產生；KPI 卡在 `legion brief` 或 `legion docs` 時更新。\n\n"
            f"![[{VAULT_IMG}/dashboard.svg]]\n\n![[儀表.base]]\n")


# ---------------------------------------------------------------- canvas（Obsidian 流程.canvas）
_COL, _ROW, _W = 340, 230, 250


def canvas_json(models: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """閉環流程畫布。models：角色 → 要附加的模型說明行（由 vault 依設定算好傳入）。"""
    nodes: list[dict[str, Any]] = []
    for n in NODES:
        text = f"**{n.title}**" + (f"\n{n.desc}" if n.desc else "")
        if models is not None:
            if n.role:
                text += "".join(f"\n{x}" for x in models.get(n.role, []))
            elif n.kind == "runner":
                text += "\n不用模型（程式判斷）"
        h = 60 + 26 * text.count("\n")
        nodes.append({"id": f"n-{n.id.lower()}", "type": "text", "text": text,
                      "x": int(n.col * _COL), "y": int(n.row * _ROW), "width": _W, "height": h,
                      "color": KINDS[n.kind][1]})
    nodes.append({"id": "n-legend", "type": "text", "x": int(-1 * _COL), "y": int(2 * _ROW), "width": _W + 60,
                  "height": 200, "text": "**圖例**\n" + "\n".join(f"- {v[2]}" for v in KINDS.values())
                  + "\n- 灰線＝例外或補救路徑\n\n與 README、[[流程]] 同一份定義"})
    edges: list[dict[str, Any]] = []
    for i, e in enumerate(EDGES):
        d: dict[str, Any] = {"id": f"e-{i:02d}", "fromNode": f"n-{e.a.lower()}", "toNode": f"n-{e.b.lower()}",
                             "fromSide": e.sides[0], "toSide": e.sides[1], "toEnd": "arrow"}
        if e.label:
            d["label"] = e.label
        if e.dotted:
            d["color"] = DOTTED_COLOR
        edges.append(d)
    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- 儀表（Obsidian 儀表.base）
STATE_LABEL = {"DONE": "✅ 完成", "HALT": "⛔ 熔斷", "WAIT_HUMAN": "✋ 等你"}
RISK_LABEL = {"high": "🔴 高", "mid": "🟡 中", "low": "🟢 低"}


def _if_chain(prop: str, mapping: dict[str, str], default: str) -> str:
    expr = default
    for k, v in reversed(list(mapping.items())):
        expr = f'if({prop} == "{k}", "{v}", {expr})'
    return expr


DASHBOARD: dict[str, Any] = {
    "filters": {"and": ['file.inFolder("AI/tasks")', 'file.ext == "md"']},
    "formulas": {
        "state_label": _if_chain("state", STATE_LABEL, '"⏳ " + state'),
        "risk_label": _if_chain("risk", RISK_LABEL, '""'),
        "cost_label": 'if(cost_usd, "$" + cost_usd.toFixed(4), "")',
    },
    "properties": {
        "file.name": {"displayName": "任務"},
        "title": {"displayName": "標題"},
        "state": {"displayName": "狀態代碼"},
        "risk": {"displayName": "風險代碼"},
        "cost_usd": {"displayName": "成本 USD"},
        "human_touches": {"displayName": "人工介入"},
        "verdict": {"displayName": "審查結論"},
        "wait_reason": {"displayName": "等待原因"},
        "halt_reason": {"displayName": "熔斷原因"},
        "formula.state_label": {"displayName": "狀態"},
        "formula.risk_label": {"displayName": "風險"},
        "formula.cost_label": {"displayName": "成本"},
    },
    "views": [
        {"type": "table", "name": "依狀態", "groupBy": {"property": "state", "direction": "ASC"},
         "order": ["file.name", "title", "formula.state_label", "formula.risk_label", "formula.cost_label",
                   "human_touches", "verdict"],
         "summaries": {"cost_usd": "Sum", "human_touches": "Sum"}},
        {"type": "table", "name": "依風險", "groupBy": {"property": "risk", "direction": "DESC"},
         "order": ["file.name", "title", "formula.risk_label", "formula.state_label", "cost_usd"],
         "summaries": {"cost_usd": "Sum"}},
        {"type": "table", "name": "等待使用者",
         "filters": {"or": ['state == "WAIT_HUMAN"', 'state == "HALT"']},
         "order": ["file.name", "title", "formula.state_label", "wait_reason", "halt_reason"]},
    ],
}


def base_yaml() -> str:
    return ("# 由 src/legion/diagrams.py 產生；請改程式，不要手改此檔。\n"
            + yaml.safe_dump(DASHBOARD, allow_unicode=True, sort_keys=False, width=200))


def _group_label(v: dict[str, Any]) -> str:
    g = v.get("groupBy")
    if g:
        name = DASHBOARD["properties"].get(g["property"], {}).get("displayName", g["property"])
        return f"依{name.removesuffix('代碼')}分組"
    return "只列 " + "、".join(re.findall(r'"([A-Z_]+)"', " ".join(v.get("filters", {}).get("or", []))))


def dashboard_markdown() -> str:
    """README 的「Obsidian 儀表」說明表：與儀表.base 同一份定義。"""
    props = DASHBOARD["properties"]
    rows = ["| 檢視 | 篩選或分組 | 欄位 |", "|---|---|---|"]
    for v in DASHBOARD["views"]:
        cols = "、".join(props.get(p, {}).get("displayName", p) for p in v["order"])
        rows.append(f"| {v['name']} | {_group_label(v)} | {cols} |")
    icons = "、".join([*STATE_LABEL.values(), "⏳ 進行中"]) + "；風險：" + "、".join(RISK_LABEL.values())
    return "\n".join(rows) + f"\n\n狀態圖示：{icons}。"


# ---------------------------------------------------------------- README 同步
MARKS = {"flow": ("<!-- legion:flow:start -->", "<!-- legion:flow:end -->"),
         "dashboard": ("<!-- legion:dashboard:start -->", "<!-- legion:dashboard:end -->")}


def _blocks() -> dict[str, str]:
    flow = (f'<p align="center"><img src="{FLOW_SVG}" width="100%" '
            f'alt="閉環流程動態圖：虛線表示流向，橘色光暈重播 {REPLAY_TASK} 的真實路徑"></p>\n\n'
            f"圖例：{LEGEND}{MOTION_NOTE}\n\n"
            "<details><summary>靜態版（mermaid 原始碼，GitHub 直接渲染）</summary>\n\n"
            f"```mermaid\n{mermaid()}\n```\n\n</details>")
    dashboard = (f'<p align="center"><img src="{DASHBOARD_SVG}" width="100%" '
                 'alt="儀表 KPI 卡：進行中、等你處理、熔斷、完成的任務數、花費，以及最近幾次評測基準的結果"></p>\n\n'
                 "上圖是 `legion docs` 執行當下的快照（卡片上有資料時間）；Obsidian 的 `AI/儀表.md` 每次 `legion brief` 都會更新。\n\n"
                 + dashboard_markdown())
    return {"flow": flow, "dashboard": dashboard}


def sync_readme(text: str) -> str:
    """把 README 標記之間的內容換成最新產生的版本；缺標記就拋錯。"""
    for key, body in _blocks().items():
        start, end = MARKS[key]
        pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
        if not pat.search(text):
            raise ValueError(f"README 缺少標記 {start} … {end}")
        text = pat.sub(lambda _m, s=start, b=body, e=end: f"{s}\n{b}\n{e}", text, count=1)
    return text


def source_hash() -> str:
    """流程定義＋重播路徑的指紋：嵌進動態 SVG，測試用來確認 SVG 有跟著定義重新產生。"""
    import hashlib
    import json

    return hashlib.sha256((mermaid() + json.dumps(REPLAY, ensure_ascii=False)).encode("utf-8")).hexdigest()[:12]
