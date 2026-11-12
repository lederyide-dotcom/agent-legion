"""證據：一律由 runner 以程式產生並編號（E-001…），寫入後設為唯讀並登錄 SHA-256。書記官不得產生或改寫。"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import stat
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

from .config import Settings
from .db import Store
from .models import Evidence, Task

_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
# 終端輸出轉圖用的字型；可用環境變數覆寫，找不到時退回 PIL 預設字型
FONT_MONO = Path(os.environ.get("LEGION_FONT_MONO", str(_FONTS / "consola.ttf")))
FONT_CJK = Path(os.environ.get("LEGION_FONT_CJK", str(_FONTS / "msjh.ttc")))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_readonly(path: Path) -> None:
    path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def snapshot_hashes(record_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for sub in ("evidence", "assets"):
        d = record_dir / sub
        if d.exists():
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    out[p.relative_to(record_dir).as_posix()] = sha256_file(p)
    return out


class EvidenceStore:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    async def _register(
        self, task: Task, step: int, label: str, kind: str, data: bytes, ext: str, caption: str, producer: str
    ) -> Evidence:
        existing = await self.store.find_evidence(task.id, step, label)
        if existing is not None:  # 中斷續跑：同一步同一標籤的證據只產生一次
            return existing
        eid = await self.store.next_evidence_id(task.id)
        sub = "assets" if kind == "image" else "evidence"
        rdir = self.settings.record_dir(task.id)
        rel = f"{sub}/{eid}_{label}.{ext}"
        path = rdir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():  # 上次寫檔後、登錄前被中斷
            path.chmod(stat.S_IWRITE | stat.S_IREAD)
        path.write_bytes(data)
        _make_readonly(path)
        ev = Evidence(
            id=eid, task_id=task.id, step=step, label=label, kind=kind,  # type: ignore[arg-type]
            path=rel, sha256=sha256_file(path), producer=producer, caption=caption,
        )
        await self.store.add_evidence(ev)
        return ev

    async def add_text(self, task: Task, step: int, label: str, text: str, caption: str,
                       producer: str = "runner", kind: str = "text", ext: str = "txt") -> Evidence:
        return await self._register(task, step, label, kind, text.encode("utf-8"), ext, caption, producer)

    async def add_image(self, task: Task, step: int, label: str, png: bytes, caption: str,
                        producer: str = "runner") -> Evidence:
        return await self._register(task, step, label, "image", png, "png", caption, producer)


# ---------------------------------------------------------------- 終端輸出轉圖
def render_terminal(text: str, title: str, max_lines: int = 48, max_cols: int = 110) -> bytes:
    lines = [f"$ {title}", ""]
    for raw in text.replace("\r\n", "\n").split("\n"):
        while len(raw) > max_cols:
            lines.append(raw[:max_cols])
            raw = raw[max_cols:]
        lines.append(raw)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [f"…（其餘 {len(lines) - max_lines + 1} 行見原始文字檔）"]
    size = 15
    mono = ImageFont.truetype(str(FONT_MONO), size) if FONT_MONO.exists() else ImageFont.load_default()
    cjk = ImageFont.truetype(str(FONT_CJK), size) if FONT_CJK.exists() else mono
    cw, lh, pad = 9, 20, 16
    width = pad * 2 + cw * (max_cols + 2)
    height = pad * 2 + lh * len(lines)
    img = Image.new("RGB", (width, height), (24, 26, 33))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        x = pad
        y = pad + i * lh
        color = (130, 200, 255) if i == 0 else (220, 220, 220)
        for ch in line:
            wide = ord(ch) > 0x2E7F
            draw.text((x, y), ch, font=cjk if wide else mono, fill=color)
            x += cw * (2 if wide else 1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- 數據圖
def render_runs_chart(csv_text: str, title: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.family"] = ["Microsoft JhengHei", "DejaVu Sans"]
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    labels = [f"{r['state']}\n{r['role']}" for r in rows]
    cost = [float(r["cost_usd"]) for r in rows]
    dur = [float(r["duration_s"]) for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), dpi=110)
    axes[0].bar(range(len(rows)), cost, color="#4C78A8")
    axes[0].set_title("每次 agent 呼叫成本（USD，用戶端估算）")
    axes[1].bar(range(len(rows)), dur, color="#F58518")
    axes[1].set_title("每次 agent 呼叫耗時（秒）")
    for ax in axes:
        ax.set_xticks(range(len(rows)))
        ax.set_xticklabels(labels, fontsize=7)
        ax.grid(axis="y", alpha=0.3)
    fig.suptitle(title)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- Mermaid
async def render_mermaid(settings: Settings, mmd: str, workdir: Path) -> bytes:
    workdir.mkdir(parents=True, exist_ok=True)
    src = workdir / "flow.mmd"
    out = workdir / "flow.png"
    src.write_text(mmd, encoding="utf-8")
    if out.exists():
        out.unlink()
    # puppeteer 設定在執行時產生：瀏覽器路徑來自 LEGION_BROWSER 或自動偵測，不進版控
    cfg = workdir / "puppeteer.json"
    cfg.write_text(json.dumps({"executablePath": str(settings.browser), "args": ["--no-sandbox"]}), encoding="utf-8")
    cmd = [str(settings.mermaid_cli), "-i", str(src), "-o", str(out), "-p", str(cfg), "-b", "white", "-s", "2"]

    def go() -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=dict(os.environ))

    proc = await asyncio.to_thread(go)
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"Mermaid 轉圖失敗：{proc.stderr[-400:]}")
    return out.read_bytes()


def image_stats(path: Path) -> tuple[int, int, float]:
    """回傳 (寬, 高, 灰階標準差)；標準差太小代表空白圖。"""
    with Image.open(path) as im:
        im.load()
        gray = im.convert("L")
        return im.width, im.height, float(ImageStat.Stat(gray).stddev[0])
