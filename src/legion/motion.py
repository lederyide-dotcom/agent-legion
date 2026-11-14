"""動態 SVG：流程圖（連線流動＋重播真實任務路徑）與儀表 KPI 卡。

GitHub README 不能跑 JavaScript，Obsidian 的 Canvas／Bases 沒有動畫，但兩邊都能顯示「內含 CSS 動畫的 SVG 圖片」。
所以動畫只用 SVG 內的 CSS，不用腳本；跟隨系統「減少動態」設定；配色在亮、暗背景上都看得清楚。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from . import diagrams
from .config import Settings

# mermaid 設定：文字用純 SVG（不用 HTML foreignObject，當成圖片顯示時才不會消失）；線與標籤選亮暗都看得到的中性色
MERMAID_CONFIG: dict[str, Any] = {
    "theme": "base",
    "htmlLabels": False,
    "flowchart": {"htmlLabels": False, "curve": "basis"},
    "themeVariables": {"lineColor": "#8a94a0", "edgeLabelBackground": "#eef1f4", "textColor": "#1b2430",
                       "primaryTextColor": "#1b2430",
                       "fontFamily": "Noto Sans TC, Microsoft JhengHei, PingFang TC, sans-serif"},
}
FONT = "'Noto Sans TC','Microsoft JhengHei','PingFang TC',sans-serif"
HIGHLIGHT = "#f59e0b"
STEP_S = 1.6   # 重播每一步的秒數
PAUSE_S = 2.4  # 重播一輪後停頓


async def render_flow_svg(settings: Settings, workdir: Path) -> str:
    """用 mmdc 把 diagrams.mermaid() 轉成 SVG 原始碼（尚未加動畫）。"""
    workdir.mkdir(parents=True, exist_ok=True)
    src, out, cfg, pp = (workdir / n for n in ("flow.mmd", "flow.svg", "mermaid.json", "puppeteer.json"))
    src.write_text(diagrams.mermaid(), encoding="utf-8", newline="\n")
    cfg.write_text(json.dumps(MERMAID_CONFIG), encoding="utf-8", newline="\n")
    pp.write_text(json.dumps({"executablePath": str(settings.browser), "args": ["--no-sandbox"]}), encoding="utf-8", newline="\n")
    if out.exists():
        out.unlink()
    cmd = [str(settings.mermaid_cli), "-i", str(src), "-o", str(out), "-c", str(cfg), "-p", str(pp), "-b", "transparent"]

    def go() -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=dict(os.environ))

    proc = await asyncio.to_thread(go)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"Mermaid 轉 SVG 失敗：{proc.stderr[-400:]}")
    return out.read_text(encoding="utf-8")


def _window_keyframes(name: str, frac: float, on: str, off: str) -> str:
    """一輪中只在前 frac 比例「亮」的關鍵影格；搭配負的 animation-delay 讓第 i 步在對的時間亮起。"""
    p = round(frac * 100, 3)
    return f"@keyframes {name}{{0%,{p}%{{{on}}}{min(p + 0.01, 100)}%,100%{{{off}}}}}"


def animate_flow(svg: str) -> str:
    """在 mermaid 產生的 SVG 加上：連線流動、依 diagrams.REPLAY 逐步點亮節點與連線、底部字幕。"""
    if "foreignObject" in svg:
        raise ValueError("SVG 內含 HTML 文字（foreignObject），當成圖片顯示時會消失：請用 MERMAID_CONFIG 轉圖")
    m = re.search(r'<svg id="([^"]+)"', svg)
    if not m:
        raise ValueError("不是 mermaid 產生的 SVG")
    root = m.group(1)
    node_ids = {mid: full for full, mid in re.findall(rf'id="({re.escape(root)}-flowchart-([A-Za-z0-9]+)-\d+)"', svg)}
    edge_ids = {(a, b): full for full, a, b in re.findall(rf'id="({re.escape(root)}-L_([A-Za-z0-9]+)_([A-Za-z0-9]+)_\d+)"', svg)}
    mid_of = {n.id: n.mid for n in diagrams.NODES}
    steps = diagrams.REPLAY
    n = len(steps)
    cycle = n * STEP_S + PAUSE_S
    frac = STEP_S / cycle

    css = [
        # 所有連線：虛線往箭頭方向流動，表示資料流向。mermaid 有 `.edge-pattern-solid{stroke-dasharray:0}`，
        # 所以選擇器要更具體，而且整段 <style> 放在 mermaid 自己的樣式之後
        f"#{root} .flowchart-link.edge-pattern-solid{{stroke-dasharray:7 5;animation:lg-flow 1.4s linear infinite}}",
        f"#{root} .flowchart-link.edge-pattern-dotted{{stroke-dasharray:2 5;animation:lg-flow 2.4s linear infinite}}",
        # 外框層要蓋過 mermaid 的 `.claude rect{fill:…!important}`：(1,2,0) 高於 (1,1,1)
        f"#{root} .node .lg-ring{{fill:none!important;stroke:{HIGHLIGHT}!important}}",
        "@keyframes lg-flow{to{stroke-dashoffset:-24}}",
        f"#{root} .edgeLabel rect{{opacity:.92!important}}",
        _window_keyframes("lg-node", frac, f"stroke-width:4px;filter:drop-shadow(0 0 6px {HIGHLIGHT})",
                          "stroke-width:0;filter:none"),
        _window_keyframes("lg-edge", frac, f"stroke:{HIGHLIGHT};stroke-width:4px", "stroke:transparent;stroke-width:4px"),
        _window_keyframes("lg-cap", frac, "opacity:1", "opacity:0"),
    ]
    rules: list[str] = []
    prev: str | None = None
    for i, (nid, _) in enumerate(steps):
        delay = round(i * STEP_S - cycle, 3)
        anim = f"{cycle:.2f}s linear {delay}s infinite"
        full = node_ids.get(mid_of[nid])
        if full is None:
            raise ValueError(f"SVG 找不到節點 {nid}")
        # 同一節點出現多次（例如 EXEC）時，每次各加一層動畫
        rules.append(f"#{full} .lg-ring-{i}{{animation:lg-node {anim}}}")
        if prev is not None:
            e = edge_ids.get((mid_of[prev], mid_of[nid]))
            if e is None:
                raise ValueError(f"重播路徑 {prev} → {nid} 在流程圖上沒有連線")
            rules.append(f"#{root} .lg-step-{i}{{animation:lg-edge {anim}}}")
        rules.append(f"#{root} .lg-cap-{i}{{opacity:0;animation:lg-cap {anim}}}")
        prev = nid
    reduce = (f"@media (prefers-reduced-motion: reduce){{#{root} *{{animation:none!important}}"
              f"#{root} .lg-cap{{opacity:0!important}}#{root} .lg-cap-static{{opacity:1!important}}}}")
    style = "<style>" + "".join(css + rules) + reduce + "</style>"
    # 疊層直接放在最外層座標；若 mermaid 對連線群組加了位移（例如用了 subgraph），疊層會錯位 → 直接報錯
    if re.search(r'<g class="edgePaths"[^>]*transform=', svg):
        raise ValueError("連線群組有 transform，重播疊層會錯位：請調整 animate_flow")

    # 節點外框：在每個重播節點裡加一個透明外框層承接動畫（原本外框的顏色寫死 !important，不能直接動）
    ring_by_node: dict[str, list[int]] = {}
    for i, (nid, _) in enumerate(steps):
        ring_by_node.setdefault(node_ids[mid_of[nid]], []).append(i)
    for full, idxs in ring_by_node.items():
        # 外框可能直接是 rect／polygon／path，也可能包在 <g class="basic ..."> 裡；結尾可能是 /> 或 </path>
        g = re.search(rf'<g class="node[^"]*" id="{re.escape(full)}"[^>]*>(?:\s*<g class="basic[^"]*">)?'
                      r'\s*(<(rect|polygon|path)\b[^>]*?(?:/>|>\s*</(?:rect|polygon|path)>))', svg)
        if not g:
            raise ValueError(f"找不到節點外框：{full}")
        tag = g.group(2)
        bare = re.sub(r'\s(class|style|id|fill|stroke|stroke-width|stroke-dasharray)="[^"]*"', "", g.group(1))
        rings = "".join(bare.replace(f"<{tag}", f'<{tag} class="lg-ring lg-ring-{i}" fill="none" stroke="{HIGHLIGHT}" '
                                     'stroke-width="0"', 1) for i in idxs)
        svg = svg.replace(g.group(0), g.group(0) + rings, 1)
    # 連線：同一條線在重播中可能走多次（animation 會互蓋），所以每一步複製一條路徑當疊層，只帶 class
    overlays: list[str] = []
    prev = None
    for i, (nid, _) in enumerate(steps):
        if prev is not None:
            full = edge_ids[(mid_of[prev], mid_of[nid])]
            path = re.search(rf'<path d="([^"]+)" id="{re.escape(full)}"', svg)
            if not path:
                raise ValueError(f"找不到連線路徑：{full}")
            overlays.append(f'<path d="{path.group(1)}" class="lg-step lg-step-{i}" fill="none" stroke="none" '
                            'stroke-linecap="round"/>')
        prev = nid

    # 底部字幕：每一步一行，只在該步亮起；放在加高的畫布下方
    vb = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    if not vb:
        raise ValueError("SVG 沒有 viewBox")
    x0, y0, w, h = (float(v) for v in vb.groups())
    cap_h = 64.0
    cy = y0 + h + 20
    caps = [f'<g class="lg-cap lg-cap-{i}"><text x="{x0 + w / 2:.1f}" y="{cy + 26:.1f}" text-anchor="middle" '
            f'font-size="17" font-family="{FONT}" fill="#ffffff">{escape(diagrams.REPLAY_TASK)} 重播 {i + 1}/{n}｜'
            f'{escape(nid)}：{escape(text)}</text></g>' for i, (nid, text) in enumerate(steps)]
    static = (f'<text class="lg-cap-static" opacity="0" x="{x0 + w / 2:.1f}" y="{cy + 26:.1f}" text-anchor="middle" '
              f'font-size="17" font-family="{FONT}" fill="#ffffff">{escape(diagrams.REPLAY_TASK)} 共 {n} 步，經過 '
              f'{escape("、".join(dict.fromkeys(s for s, _ in steps)))}（動畫已依系統設定關閉）</text>')
    caption = (f'<g aria-hidden="true"><rect x="{x0 + 8:.1f}" y="{cy:.1f}" width="{w - 16:.1f}" height="40" rx="20" '
               f'fill="#1b2430" opacity=".88"/>{"".join(caps)}{static}</g>')
    svg = svg.replace(vb.group(0), f'viewBox="{x0} {y0} {w} {h + cap_h}"', 1)
    a11y = (f'<title>agent-legion 閉環流程（動態）</title><desc>連線上的虛線表示流向；橘色光暈依序重播任務 '
            f'{escape(diagrams.REPLAY_TASK)} 的真實路徑：{escape(" → ".join(s for s, _ in steps))}。{escape(diagrams.LEGEND)}</desc>'
            f'<metadata>legion-src:{flow_fingerprint()}</metadata>')
    first_gt = svg.index(">") + 1
    svg = svg[:first_gt] + a11y + svg[first_gt:]
    end = svg.rindex("</svg>")
    return svg[:end] + style + "".join(overlays) + caption + svg[end:]


def flow_fingerprint() -> str:
    """動態流程圖的來源指紋：流程定義、重播、圖例與本模組（CSS、時間、mermaid 設定）任一改變都會不同。"""
    h = hashlib.sha256()
    for part in (diagrams.source_hash(), diagrams.LEGEND, diagrams.REPLAY_TASK, diagrams.MOTION_NOTE):
        h.update(part.encode("utf-8"))
    h.update(Path(__file__).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]



# ---------------------------------------------------------------- 儀表 KPI 卡

def dashboard_stats(settings: Settings, tasks: list[Any], brief: dict[str, Any] | None = None) -> dict[str, Any]:
    """KPI 卡的數字。brief：晨報已算好的 collect() 結果（避免重跑 git）；花費一律取自花費帳本，口徑與晨報相同。"""
    from datetime import date, timedelta

    from . import ledger
    from .brief import collect
    from .models import State

    b = brief if brief is not None else collect(settings, tasks)
    today = date.today()
    cost_7d = sum(ledger.total_on(settings.cost_ledger, today - timedelta(days=i), settings.schema_name)
                  for i in range(7))
    counts = {"running": 0, "waiting": 0, "halt": 0, "done": 0}
    for t in tasks:
        if t.state == State.HALT and (t.halt_reason or "").startswith("operator_cancel"):
            continue  # 手動取消不算熔斷（與晨報「最近熔斷」口徑一致）
        key = {State.DONE: "done", State.HALT: "halt", State.WAIT_HUMAN: "waiting"}.get(t.state, "running")
        counts[key] += 1
    last = b["recent_halts"][0] if b["recent_halts"] else None
    return {"generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), "counts": counts,
            "total": len(tasks), "cost_today": b["cost_today"], "daily_budget": b["daily_budget"],
            "cost_7d": round(cost_7d, 4), "cost_all": round(sum(t.cost_usd for t in tasks), 4),
            "waiting_ids": [w["id"] for w in b["waiting"]][:4],
            "last_halt": f"{last['id']}：{last['reason']}" if last else "",
            "bench": _bench_history(settings)}


def _bench_history(settings: Settings) -> list[dict[str, Any]]:
    from .bench import history

    return history(settings.data_dir)


def _bench_row(runs: list[dict[str, Any]], y: int) -> str:
    """評測趨勢：最近幾次 legion bench，每次一個點（全部符合＝綠、有不符＝紅），最後一次寫出比數。"""
    if not runs:
        return f'<text class="muted" x="24" y="{y}" font-size="13">評測基準：尚未執行（legion bench）</text>'
    last = runs[-1]
    dots = "".join(
        f'<circle class="{"ok" if r["passed"] == r["cases"] and r["cases"] else "bad"}" cx="{178 + i * 16}" '
        f'cy="{y - 4}" r="5"><title>{escape(str(r["at"]))}：{int(r["passed"])}/{int(r["cases"])}</title></circle>'
        for i, r in enumerate(runs))
    x = 178 + len(runs) * 16 + 4
    return (f'<text class="muted" x="24" y="{y}" font-size="13">評測基準（最近 {len(runs)} 次）</text>{dots}'
            f'<text class="muted" x="{x}" y="{y}" font-size="13">最新 {last["passed"]}/{last["cases"]} 符合預期'
            f'｜{escape(str(last["commit"]))}</text>')


def dashboard_svg(st: dict[str, Any]) -> str:
    """儀表 KPI 卡：靜止時就完整；動態只有花費條流光、資料時間旁的即時點、有事等你時外框呼吸提醒。亮暗配色跟隨系統。"""
    W, H = 860, 326
    c = st["counts"]
    tiles = [("進行中", c["running"], "run"), ("等你處理", c["waiting"], "wait"), ("熔斷", c["halt"], "halt"),
             ("完成", c["done"], "done")]
    tw, gap, x0 = 190, 16, 24
    parts: list[str] = []
    for i, (label, value, kind) in enumerate(tiles):
        x = x0 + i * (tw + gap)
        pulse = " pulse" if kind == "wait" and value else ""
        parts.append(
            f'<g class="tile t{i}{pulse}"><rect class="tbg {kind}" x="{x}" y="70" width="{tw}" height="96" rx="12"/>'
            f'<text class="num {kind}" x="{x + 18}" y="128" font-size="40">{value}</text>'
            f'<text class="lbl" x="{x + 18}" y="152" font-size="14">{escape(label)}</text></g>')
    budget = max(float(st["daily_budget"]), 0.01)
    ratio = min(float(st["cost_today"]) / budget, 1.0)
    bar_w = W - 48
    fill_w = max(bar_w * ratio, 4)
    over = "over" if st["cost_today"] >= budget * 0.8 else ""
    waiting = "、".join(st["waiting_ids"]) or "沒有"
    halt = st["last_halt"] or "最近 36 小時沒有"
    halt = halt if len(halt) <= 60 else halt[:59] + "…"
    css = f"""
:root{{--bg:#ffffff;--line:#d9e0e7;--fg:#1b2430;--muted:#5d6b7a;--run:#2f5f8a;--wait:#a5620f;--halt:#a33a3a;--done:#2e7d4f;
--run-s:#e3edf6;--wait-s:#fbefdc;--halt-s:#f7e3e3;--done-s:#e2f2e8;--track:#eef1f4;--bar:#2f5f8a}}
@media (prefers-color-scheme: dark){{:root{{--bg:#1a2129;--line:#2c3743;--fg:#e4e9ee;--muted:#93a1af;--run:#7fb0dc;--wait:#e2a656;
--halt:#e58a8a;--done:#6cc690;--run-s:#1f3245;--wait-s:#3a2c17;--halt-s:#3b2121;--done-s:#1c3326;--track:#2c3743;--bar:#7fb0dc}}}}
text{{font-family:{FONT};fill:var(--fg)}}
.card{{fill:var(--bg);stroke:var(--line)}}
.muted,.lbl{{fill:var(--muted)}}
.num{{font-weight:700;font-variant-numeric:tabular-nums}}
.num.run{{fill:var(--run)}}.num.wait{{fill:var(--wait)}}.num.halt{{fill:var(--halt)}}.num.done{{fill:var(--done)}}
.tbg.run{{fill:var(--run-s)}}.tbg.wait{{fill:var(--wait-s)}}.tbg.halt{{fill:var(--halt-s)}}.tbg.done{{fill:var(--done-s)}}
.tbg{{stroke:transparent;stroke-width:3}}
.track{{fill:var(--track)}}.bar{{fill:var(--bar)}}.bar.over{{fill:var(--wait)}}
.ok{{fill:var(--done)}}.bad{{fill:var(--halt)}}
/* 靜止時就完整：數字與花費條一開始就在；動態只用在流光、即時點與提醒，不影響閱讀 */
.pulse .tbg{{animation:lg-pulse 2s ease-in-out 1s infinite}}
@keyframes lg-pulse{{0%,100%{{stroke:transparent}}50%{{stroke:var(--wait)}}}}
.sheen{{animation:lg-sheen 2.8s ease-in-out infinite}}
@keyframes lg-sheen{{from{{transform:translateX(-80px)}}to{{transform:translateX({fill_w:.0f}px)}}}}
.live{{fill:var(--done);animation:lg-live 1.6s ease-in-out infinite}}
@keyframes lg-live{{50%{{opacity:.25}}}}
@media (prefers-reduced-motion: reduce){{*{{animation:none!important}}.sheen{{display:none}}}}
"""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img">'
        f'<title>agent-legion 儀表</title><desc>任務 {st["total"]} 個：進行中 {c["running"]}、等你處理 {c["waiting"]}、'
        f'熔斷 {c["halt"]}、完成 {c["done"]}；今日花費 ${st["cost_today"]:.4f}／上限 ${budget:.2f}；資料時間 {escape(st["generated_at"])}</desc>'
        f"<style>{css}</style>"
        f'<rect class="card" x="1" y="1" width="{W - 2}" height="{H - 2}" rx="16"/>'
        f'<text x="24" y="42" font-size="20" font-weight="700">agent-legion 儀表</text>'
        f'<defs><linearGradient id="lg-sheen"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="#fff" stop-opacity=".55"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>'
        f'<circle class="live" cx="{W - 24 - 8}" cy="37" r="4"/>'
        f'<text class="muted" x="{W - 24 - 18}" y="42" font-size="13" text-anchor="end">資料時間 {escape(st["generated_at"])}'
        f'｜共 {st["total"]} 個任務</text>'
        + "".join(parts)
        + f'<text x="24" y="200" font-size="14">今日花費 <tspan font-weight="700">${st["cost_today"]:.4f}</tspan>'
        f' ／ 每日上限 ${budget:.2f}　近 7 日 ${st["cost_7d"]:.4f}　累計 ${st["cost_all"]:.4f}</text>'
        f'<rect class="track" x="24" y="212" width="{bar_w}" height="10" rx="5"/>'
        f'<rect class="bar {over}" x="24" y="212" width="{fill_w:.1f}" height="10" rx="5"/>'
        f'<clipPath id="lg-barclip"><rect x="24" y="212" width="{fill_w:.1f}" height="10" rx="5"/></clipPath>'
        f'<g clip-path="url(#lg-barclip)"><rect class="sheen" x="24" y="212" width="80" height="10" fill="url(#lg-sheen)"/></g>'
        f'<text class="muted" x="24" y="252" font-size="13">等你處理：{escape(waiting)}</text>'
        f'<text class="muted" x="24" y="276" font-size="13">最近熔斷：{escape(halt)}</text>'
        + _bench_row(st.get("bench") or [], 304)
        + "</svg>")


def _write(svg: str, targets: list[Path]) -> None:
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(svg.encode("utf-8"))


async def write_dashboard(settings: Settings, store: Any, project_root: Path | None = None,
                          brief: dict[str, Any] | None = None) -> Path:
    """依 DB 產生儀表 KPI 卡，寫到 vault（與 project_root 下的 03_docs/img，若有給）。"""
    svg = dashboard_svg(dashboard_stats(settings, await store.list_tasks(), brief))
    out = settings.ai_dir / diagrams.VAULT_IMG.split("/", 1)[1] / "dashboard.svg"
    _write(svg, [out] + ([project_root / diagrams.DASHBOARD_SVG] if project_root else []))
    return out


async def write_flow(settings: Settings, project_root: Path | None = None) -> Path:
    """mermaid 轉 SVG＋加動畫，寫到 vault（與 project_root 下的 03_docs/img，若有給）。需要瀏覽器與 mmdc。"""
    svg = animate_flow(await render_flow_svg(settings, Path(tempfile.gettempdir()) / "legion_motion"))
    out = settings.ai_dir / diagrams.VAULT_IMG.split("/", 1)[1] / "flow.svg"
    _write(svg, [out] + ([project_root / diagrams.FLOW_SVG] if project_root else []))
    return out
