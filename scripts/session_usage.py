"""Claude Code 對話用量：依「主對話／子代理類型 × 模型」統計 token（不花額度、不連網）。

用法：
    .venv\\Scripts\\python.exe scripts\\session_usage.py <對話紀錄.jsonl>       # 單一對話（含它的子代理）
    .venv\\Scripts\\python.exe scripts\\session_usage.py <專案紀錄資料夾>        # 該資料夾所有對話
    加 --json 輸出 JSON。

對話紀錄在 %USERPROFILE%\\.claude\\projects\\<專案>\\<session>.jsonl；子代理在 <session>\\subagents\\agent-*.jsonl，
類型讀同名 .meta.json 的 agentType。同一則回覆串流時會寫多行（同一個 message.id），只算一次。
只統計 token，不換算金額：訂閱方案的額度不是按 token 價目計算。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def _messages(path: Path) -> dict[str, tuple[str, dict[str, int]]]:
    """message.id → (model, usage)；同 id 取最後一行（串流結束時的完整用量）。"""
    out: dict[str, tuple[str, dict[str, int]]] = {}
    with path.open(encoding="utf-8", errors="replace") as f:  # 一份壞檔不該讓整個統計中斷
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # 寫到一半的最後一行
            msg = rec.get("message") if isinstance(rec, dict) else None
            if not isinstance(msg, dict) or msg.get("role") != "assistant" or not isinstance(msg.get("usage"), dict):
                continue
            model = str(msg.get("model") or "?")
            if model == "<synthetic>":
                continue
            usage = {k: int(msg["usage"].get(k) or 0) for k in FIELDS}
            out[str(msg.get("id") or f"{path.name}:{len(out)}")] = (model, usage)
    return out


def _agent_type(sub: Path) -> str:
    meta = sub.with_name(sub.name.removesuffix(".jsonl") + ".meta.json")
    try:
        return str(json.loads(meta.read_text(encoding="utf-8")).get("agentType") or "子代理")
    except (OSError, json.JSONDecodeError):
        return "子代理"


def sources(target: Path) -> list[tuple[str, Path]]:
    mains = sorted(target.glob("*.jsonl")) if target.is_dir() else [target]
    out: list[tuple[str, Path]] = []
    for m in mains:
        out.append(("主對話", m))
        for sub in sorted((m.parent / m.stem / "subagents").glob("agent-*.jsonl")):
            out.append((f"子代理：{_agent_type(sub)}", sub))
    return out


def summarize(target: Path) -> list[dict[str, object]]:
    agg: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: dict.fromkeys((*FIELDS, "messages"), 0))
    for label, path in sources(target):
        for model, usage in _messages(path).values():
            a = agg[(label, model)]
            a["messages"] += 1
            for k in FIELDS:
                a[k] += usage[k]
    total_out = sum(a["output_tokens"] for a in agg.values()) or 1
    rows = [{"source": s, "model": m, **a, "output_share": round(a["output_tokens"] / total_out, 4)}
            for (s, m), a in agg.items()]
    return sorted(rows, key=lambda r: -int(r["output_tokens"]))  # type: ignore[call-overload]


def render(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "沒有找到任何回覆紀錄。"
    lines = ["來源\t模型\t回覆數\t輸入\t快取寫入\t快取讀取\t輸出\t輸出佔比"]
    for r in rows:
        lines.append(f"{r['source']}\t{r['model']}\t{r['messages']}\t{r['input_tokens']:,}\t"
                     f"{r['cache_creation_input_tokens']:,}\t{r['cache_read_input_tokens']:,}\t"
                     f"{r['output_tokens']:,}\t{float(r['output_share']):.0%}")  # type: ignore[arg-type]
    by_model: dict[str, int] = defaultdict(int)
    for r in rows:
        by_model[str(r["model"])] += int(r["output_tokens"])  # type: ignore[call-overload]
    total = sum(by_model.values()) or 1
    lines.append("依模型（輸出 token）：" + "、".join(f"{m} {v / total:.0%}" for m, v in
                                                sorted(by_model.items(), key=lambda x: -x[1])))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="對話紀錄 .jsonl 或整個專案紀錄資料夾")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.target.exists():
        print(f"找不到 {args.target}", file=sys.stderr)
        return 1
    rows = summarize(args.target)
    print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else render(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
