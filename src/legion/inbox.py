"""收件匣轉資料：把 03_docs/inbox.md 的各節表格轉成 JSON，給互動頁讀（不花額度、不碰資料庫）。

表格格式不一致（欄數不符、缺表頭分隔線、表頭欄名重複或空白、表格中途漏了開頭的 |）一律報錯，
不默默略過，避免頁面和 inbox 對不上。沒有表格的節不報錯，但列在 warnings 讓頁面顯示。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .config import PROJECT_ROOT

DEFAULT_INBOX = PROJECT_ROOT / "03_docs" / "inbox.md"
_SEP_CELL = re.compile(r"^:?-+:?$")


class InboxSection(BaseModel):
    title: str
    headers: list[str]
    rows: list[dict[str, str]]


class InboxData(BaseModel):
    source: str
    sha256: str  # 原始位元組 sha256 的前 12 碼
    generated_at: str
    notes: list[str] = Field(default_factory=list)  # 第一節之前的說明行（分工原則、規則、狀態圖例）
    warnings: list[str] = Field(default_factory=list)
    sections: list[InboxSection]


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    parts = re.split(r"(?<!\\)\|", s)
    return [p.strip().replace("\\|", "|") for p in parts]


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def parse_inbox(text: str, source: str = "03_docs/inbox.md", raw: bytes | None = None) -> InboxData:
    sections: list[InboxSection] = []
    notes: list[str] = []
    warnings: list[str] = []
    title: str | None = None
    tables_in_title = 0
    lines = text.splitlines()
    in_fence = False

    def close_section() -> None:
        if title is not None and tables_in_title == 0:
            warnings.append(f"「{title}」這一節沒有表格，頁面不會顯示它的內容")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue
        m = re.match(r"^(#{2,6})\s+(.*)$", line)
        if m:
            close_section()
            title, tables_in_title = m.group(2).strip(), 0
        elif title is None and stripped and not line.startswith("# ") and not _is_table_line(line):
            notes.append(stripped[2:].strip() if stripped.startswith("- ") else stripped)
        elif _is_table_line(line):
            if title is None:
                raise ValueError(f"第 {i + 1} 行：表格不在任何「## 」標題底下")
            headers = _cells(line)
            if any(not h for h in headers):
                raise ValueError(f"第 {i + 1} 行：表頭有空白欄名（{title}）")
            if len(set(headers)) != len(headers):
                raise ValueError(f"第 {i + 1} 行：表頭欄名重複（{title}）")
            if i + 1 >= len(lines) or not _is_table_line(lines[i + 1]):
                raise ValueError(f"第 {i + 1} 行：表頭下一行不是分隔線")
            sep = _cells(lines[i + 1])
            if not all(_SEP_CELL.match(c) for c in sep):
                raise ValueError(f"第 {i + 2} 行：表頭下一行不是分隔線")
            if len(sep) != len(headers):
                raise ValueError(f"第 {i + 2} 行：分隔線 {len(sep)} 欄，表頭是 {len(headers)} 欄（{title}）")
            rows: list[dict[str, str]] = []
            i += 2
            while i < len(lines) and _is_table_line(lines[i]):
                cells = _cells(lines[i])
                if len(cells) != len(headers):
                    raise ValueError(f"第 {i + 1} 行：{len(cells)} 欄，表頭是 {len(headers)} 欄（{title}）")
                rows.append(dict(zip(headers, cells, strict=True)))
                i += 1
            # 表格緊接著一行含 | 但沒以 | 開頭：多半是漏打開頭的 |，該列會被丟掉，所以報錯
            if i < len(lines) and lines[i].strip() and "|" in lines[i] and not lines[i].lstrip().startswith("#"):
                raise ValueError(f"第 {i + 1} 行：看起來是表格列但沒有以 | 開頭（{title}）")
            sections.append(InboxSection(title=title, headers=headers, rows=rows))
            tables_in_title += 1
            continue
        i += 1
    close_section()
    if not sections:
        raise ValueError("inbox 裡沒有任何表格")
    digest = hashlib.sha256(raw if raw is not None else text.encode("utf-8")).hexdigest()[:12]
    return InboxData(source=source, sha256=digest,
                     generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                     notes=notes, warnings=warnings, sections=sections)


def load_inbox(path: Path = DEFAULT_INBOX) -> InboxData:
    try:
        rel = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = path.name  # 專案外的檔案只留檔名，不外洩絕對路徑
    raw = path.read_bytes()
    return parse_inbox(raw.decode("utf-8-sig"), source=rel, raw=raw)
