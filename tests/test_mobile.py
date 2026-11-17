"""手機文件庫：vault 匯出成 JSON（分類、標題、遮蔽機密、圖片與 wikilink 轉換、只讀不寫）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from legion.cli import main
from legion.mobile import CATEGORIES, MASK, export_vault, redact


def _vault(tmp_path: Path) -> Path:
    ai = tmp_path / "AI"
    for sub in ("questions", "reports", "records/T-0001", "handoffs", "lessons", "missions", "inbox_hold", "tasks"):
        (ai / sub).mkdir(parents=True)
    (ai / "questions" / "T-0001.md").write_text("---\ntask: T-0001\nreason: high 風險\n---\n# 需要決定\n請核准", encoding="utf-8")
    (ai / "reports" / "r.md").write_text("# 報告\n見 [[流程|流程圖]] 與 ![[a.png]]\n", encoding="utf-8")
    (ai / "records" / "T-0001" / "record.md").write_text(
        "# 紀錄\n| 檔 | sha256 |\n|---|---|\n| a | " + "ab" * 32 + " |\n", encoding="utf-8")
    (ai / "handoffs" / "h.md").write_text("沒有標題的交接", encoding="utf-8")
    (ai / "tasks" / "T-0001.md").write_text("# 任務筆記不匯出", encoding="utf-8")
    (ai / "流程.md").write_text("# 閉環流程\n```mermaid\nflowchart TD\n```", encoding="utf-8")
    (ai / "scout").mkdir()
    (ai / "scout" / "s.md").write_text("---\nquery: \"agent\"\n---\n# 找 repo：agent\n", encoding="utf-8")
    return tmp_path


def test_export_categories_titles_and_scope(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    before = {p: p.read_bytes() for p in v.rglob("*") if p.is_file()}
    data = export_vault(v)
    by_path = {d.path: d for d in data.docs}
    assert set(by_path) == {"AI/questions/T-0001.md", "AI/reports/r.md", "AI/records/T-0001/record.md",
                            "AI/handoffs/h.md", "AI/流程.md", "AI/scout/s.md"}
    assert by_path["AI/scout/s.md"].category == "找 repo" and by_path["AI/scout/s.md"].title == "找 repo：agent"
    assert by_path["AI/questions/T-0001.md"].category == "待你決定"
    assert by_path["AI/questions/T-0001.md"].meta == {"task": "T-0001", "reason": "high 風險"}
    assert by_path["AI/handoffs/h.md"].title == "h" and by_path["AI/流程.md"].title == "閉環流程"
    assert data.categories == list(CATEGORIES) and len({d.id for d in data.docs}) == len(data.docs)
    # 只讀：vault 內容不變
    assert before == {p: p.read_bytes() for p in v.rglob("*") if p.is_file()}


def test_images_and_wikilinks_become_phone_friendly(tmp_path: Path) -> None:
    text = next(d.text for d in export_vault(_vault(tmp_path)).docs if d.path.endswith("r.md"))
    assert "[[" not in text and "流程圖" in text and "桌機 Obsidian" in text


def test_hashes_are_not_masked(tmp_path: Path) -> None:
    data = export_vault(_vault(tmp_path))
    assert not data.warnings
    assert "ab" * 32 in next(d.text for d in data.docs if d.category == "開發紀錄")


@pytest.mark.parametrize("secret", [
    "123456789:AAH" + "x" * 32,                      # Telegram bot token
    "sk-" + "a1B2" * 6,                              # API 金鑰
    "ghp_" + "Z9" * 18,                              # GitHub token
    "AKIA" + "ABCDEFGHIJKLMNOP",                     # AWS key
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.c2lnbmF0dXJlX3h4",  # JWT
])
def test_redact_masks_secret_shapes(secret: str) -> None:
    out, n = redact(f"值是 {secret} 結束")
    assert secret not in out and MASK in out and n == 1


def test_redact_keeps_key_name_and_warns(tmp_path: Path) -> None:
    out, n = redact("TELEGRAM_TOKEN = 'abcdefgh12345678'\npassword: hunter2hunter2")
    assert "abcdefgh12345678" not in out and "hunter2hunter2" not in out and n == 2
    assert out.startswith(f"TELEGRAM_TOKEN = {MASK}")
    # 讀環境變數的程式碼不是機密，不遮
    for code in ("TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')", "token=${TELEGRAM_TOKEN}", "password = None"):
        assert redact(code) == (code, 0)
    v = _vault(tmp_path)
    (v / "AI" / "reports" / "leak.md").write_text("# 外洩\napi_key=ABCDEFGH12345678", encoding="utf-8")
    data = export_vault(v)
    assert any("leak.md" in w for w in data.warnings)
    assert "ABCDEFGH12345678" not in data.model_dump_json()


def test_cli_writes_json_without_bom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    v = _vault(tmp_path / "v")
    monkeypatch.setenv("LEGION_VAULT", str(v))
    out = tmp_path / "vault.json"
    assert main(["vault-json", "--out", str(out)]) == 0
    raw = out.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert len(json.loads(raw.decode("utf-8"))["docs"]) == 6  # _vault 的 6 份（含 scout）
