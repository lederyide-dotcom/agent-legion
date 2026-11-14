"""收件匣轉資料：互動頁的內容必須和 03_docs/inbox.md 一致，格式不對就報錯。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from legion.cli import main
from legion.inbox import DEFAULT_INBOX, load_inbox, parse_inbox


def test_real_inbox_matches_markdown_rows() -> None:
    text = DEFAULT_INBOX.read_text(encoding="utf-8")
    data = load_inbox()
    assert data.source == "03_docs/inbox.md"
    table_rows = [ln for ln in text.splitlines() if ln.lstrip().startswith("|")]
    seps = [ln for ln in table_rows if re.match(r"^\|[\s:|-]+\|$", ln.strip())]
    # 每張表 = 表頭 + 分隔線 + 資料列
    assert sum(len(s.rows) for s in data.sections) == len(table_rows) - 2 * len(seps)
    ids = [r[s.headers[0]] for s in data.sections for r in s.rows]
    for line in table_rows:
        first = line.strip().strip("|").split("|")[0].strip()
        if re.fullmatch(r"[AD]\d+", first):
            assert first in ids
    assert data.notes  # 分工原則有被帶出來


def test_pipe_escape_and_backticks_kept() -> None:
    d = parse_inbox("## 節\n\n| # | 說明 |\n|---|---|\n| X1 | `a \\| b` 與 `legion cleanup` |\n")
    assert d.sections[0].rows == [{"#": "X1", "說明": "`a | b` 與 `legion cleanup`"}]


@pytest.mark.parametrize("bad, msg", [
    ("## 節\n| a | b |\n|---|---|\n| 1 | 2 | 3 |\n", "3 欄"),
    ("## 節\n| a | b |\n| 1 | 2 |\n", "分隔線"),
    ("| a | b |\n|---|---|\n| 1 | 2 |\n", "標題"),
    ("## 節\n沒有表格\n", "沒有任何表格"),
    ("## 節\n| a | b |\n|---|---|\n| 1 | 2 |\n3 | 4 |\n", "沒有以 \\| 開頭"),  # 漏打開頭的 |
    ("## 節\n| a | a |\n|---|---|\n| 1 | 2 |\n", "重複"),
    ("## 節\n| a |  |\n|---|---|\n| 1 | 2 |\n", "空白欄名"),
    ("## 節\n| a | b | c |\n|---|\n| 1 | 2 | 3 |\n", "分隔線 1 欄"),
])
def test_malformed_inbox_raises(bad: str, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        parse_inbox(bad)


def test_cli_writes_json_without_bom(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "inbox.json"
    assert main(["inbox", "--out", str(out)]) == 0
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    assert data["sections"] and "已寫入" in capsys.readouterr().out
    bad = tmp_path / "bad.md"
    bad.write_text("## x\n| a |\n| b |\n", encoding="utf-8")
    assert main(["inbox", "--file", str(bad)]) == 1
    assert "解析失敗" in capsys.readouterr().err
    assert main(["inbox", "--out", str(tmp_path / "nope" / "inbox.json")]) == 1
    assert "寫入失敗" in capsys.readouterr().err


def test_bom_fence_subheading_and_warnings(tmp_path: Path) -> None:
    md = tmp_path / "inbox.md"
    body = ("# 標題\n\n規則：由上而下\n- 原則一\n\n## 有表\n\n```\n| 程式碼 | 不是表格\n```\n\n"
            "| # | x |\n|---|---|\n| A1 | y |\n\n## 只有文字\n- 沒表格\n\n### 小節\n\n| # | z |\n|:--|--:|\n| B1 | w |\n")
    raw = b"\xef\xbb\xbf" + body.encode("utf-8")
    md.write_bytes(raw)
    d = load_inbox(md)
    assert d.source == "inbox.md"  # 專案外只留檔名
    assert [s.title for s in d.sections] == ["有表", "小節"]
    assert d.notes == ["規則：由上而下", "原則一"]
    assert d.warnings == ["「只有文字」這一節沒有表格，頁面不會顯示它的內容"]
    assert d.sha256 == hashlib.sha256(raw).hexdigest()[:12]  # 對原始位元組算，和 sha256sum 一致
