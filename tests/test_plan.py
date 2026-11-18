"""計畫動態圖：由 03_docs/inbox.md 產生，GitHub README、Obsidian 總覽.md、手機文件庫共用同一張 SVG。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from legion import diagrams as d
from legion.config import PROJECT_ROOT, Settings
from legion.inbox import load_inbox, parse_inbox
from legion.mobile import _for_phone, copy_phone_images
from legion.plan_motion import PLAN_LIST_MAX, PLAN_RECENT, _fit, plan_data, plan_is_fresh, plan_svg, write_plan
from legion.vault import init_vault

ROOT = Path(PROJECT_ROOT)

INBOX = """# 收件匣

## 待掌舵（David）

| # | 決定什麼 | 建議 | 依據 |
|---|---|---|---|
| D1 | 範圍 <b>&</b> 規範 | 先做 | — |

## 已決定

| # | 決定 | 執行結果 | 證據 |
|---|---|---|---|
| D2 | 結案的事 | 結案 | — |
| D6 | 還在試 | 再試 1～2 個才下結論 | — |
| D3 | 等測試 | ⏳ David 測 | — |
| D4 | 已做 | ✅ 2026-11-10 完成 | x |
| D5 | 卡住 | ⛔ 等外部 | — |

## Claude Code 可自主做

| # | 任務 | 狀態 | 完成條件 | 證據 |
|---|---|---|---|---|
| A1 | `早的` | ✅ 2026-11-01 | t | e |
| A2 | 同日較前 | ✅ 2026-11-12 | t | e |
| A3 | 同日較後 | ✅ 2026-11-12 | t | e |
| A4 | 還沒做 | ⏳ | t | e |
| A5 | 被擋 | ⛔ 缺資料 | t | e |

## inbox_hold 分流建議（給 D7）

| 想法檔 | 建議 | 理由 |
|---|---|---|
| fu-1 | ✅ 已封存 | 不算計畫項目 |
"""


def _plan(text: str = INBOX):
    return plan_data(parse_inbox(text))


def test_lanes_and_recent_order() -> None:
    p = _plan()
    assert [i.id for i in p.lane("wait")] == ["D1", "D3", "D5"]  # 待掌舵全部＋已決定裡的 ⏳／⛔
    # 已決定但沒標 ✅／結案（還在試、延後）不算完成 → 進行中；可自主做未完成 → 待做
    assert [i.id for i in p.lane("todo")] == ["D6", "A4", "A5"]
    assert [i.id for i in p.lane("done")] == ["D2", "D4", "A1", "A2", "A3"]  # 分流建議表不算
    assert [i.id for i in p.recent()] == ["A3", "A2", "D4", "A1"]  # 新到舊、同日較後者先；沒日期的 D2 不列
    assert [i.id for i in p.items if i.blocked] == ["D5", "A5"]
    assert p.lane("done")[2].title == "早的"  # 反引號等 markdown 記號拿掉


def test_svg_counts_match_inbox_and_complete_at_rest() -> None:
    p = _plan()
    svg = plan_svg(p)
    ET.fromstring(svg)  # 合法 XML，GitHub 與 Obsidian 才會當圖片顯示
    assert "<script" not in svg and "foreignObject" not in svg
    for n in (len(p.lane("wait")), len(p.lane("todo")), len(p.lane("done"))):
        assert f'font-size="32">{n}</text>' in svg
    assert "完成 5／11（45%）" in svg
    assert "範圍 &lt;b&gt;&amp;&lt;/b&gt; 規範" in svg  # 內容有逸出
    assert "⛔ A5" in svg and "⛔ D5" in svg
    for it in p.recent():
        assert f">{it.date}</text>" in svg and f">{it.id}　" in svg
    assert "另有 1 項完成但 inbox 未記日期" in svg
    # 靜止時就完整：基本樣式不藏任何東西，動畫只在關鍵影格裡改透明度；減少動態時全部停
    base = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", svg)
    assert "opacity:0" not in base and "display:none}" not in base.replace(".sheen{display:none}", "")
    assert "prefers-reduced-motion: reduce" in svg and "prefers-color-scheme: dark" in svg
    assert 'class="tile pulse"' in svg  # 有事等你決定 → 外框呼吸
    assert f"legion-plan:{p.sha256}:" in svg


def test_lists_are_capped_and_say_how_many_more() -> None:
    rows = "\n".join(f"| D{i} | 事情{i} | 建議 | — |" for i in range(PLAN_LIST_MAX + 3))
    text = INBOX.replace("| D1 | 範圍 <b>&</b> 規範 | 先做 | — |", rows)
    svg = plan_svg(_plan(text))
    assert f"等你決定／處理（另 {3 + 2} 項）" in svg  # 待掌舵 7 筆＋已決定的 D3、D5，只列 4 筆
    assert svg.count('class="dot wait"') == PLAN_LIST_MAX
    assert len(re.findall(r'class="rc rc\d+"', svg)) <= PLAN_RECENT


def test_nothing_waiting_has_no_pulse_and_long_titles_are_cut() -> None:
    text = INBOX.replace("| D1 | 範圍 <b>&</b> 規範 | 先做 | — |\n", "").replace("⏳ David 測", "✅ 2026-11-11")
    text = text.replace("⛔ 等外部", "結案").replace("同日較後", "很長" * 60)
    svg = plan_svg(_plan(text))
    assert "pulse" not in re.sub(r"<style>.*</style>", "", svg, flags=re.S)
    assert "很長" * 60 not in svg and "很長…" in svg


def test_same_inbox_same_bytes_and_stale_detection(tmp_path: Path) -> None:
    assert plan_svg(_plan()) == plan_svg(_plan())  # 內容只取決於 inbox：不放產生時間
    inbox = tmp_path / "inbox.md"
    inbox.write_text(INBOX, encoding="utf-8", newline="\n")
    out = tmp_path / "plan.svg"
    out.write_bytes(plan_svg(plan_data(load_inbox(inbox))).encode("utf-8"))
    assert plan_is_fresh(out, inbox)
    inbox.write_text(INBOX.replace("| A4 | 還沒做 | ⏳ |", "| A4 | 還沒做 | ✅ 2026-11-13 |"), encoding="utf-8", newline="\n")
    assert not plan_is_fresh(out, inbox)  # inbox 改了圖沒重產 → legion docs --check 會失敗
    assert not plan_is_fresh(tmp_path / "missing.svg", inbox)


def test_missing_sections_fail_loudly() -> None:
    text = INBOX.split("## Claude Code 可自主做")[0]
    with pytest.raises(ValueError, match="可自主做"):
        _plan(text)
    no_status = INBOX.replace("| # | 任務 | 狀態 | 完成條件 | 證據 |", "| # | 任務 | 情況 | 完成條件 | 證據 |")
    with pytest.raises(ValueError, match="狀態"):  # 找不到狀態欄不默默全部算待做
        _plan(no_status)


def test_fit_counts_emoji_as_wide() -> None:
    assert _fit("⛔" * 12, 100, 10) == "⛔" * 9 + "…"  # emoji 以 1em 計，不會估短而超出卡片
    assert _fit("abc", 100, 10) == "abc"


def test_rows_wait_in_first_keyframe_during_delay() -> None:
    """除了第一列，延遲期間也要先套用起始影格（backwards），第一輪才不會先完整、瞬間變暗再滑入。"""
    svg = plan_svg(_plan())
    rules = re.findall(r"\.rc\d+\{animation:lp-in [^}]*\}", svg)
    assert rules and all(r.endswith("infinite backwards}") for r in rules)


def test_committed_plan_svg_is_fresh() -> None:
    """03_docs/img/plan.svg 是 README 嵌入的那張；改了 inbox.md 卻沒執行 legion docs 就會失敗。"""
    assert plan_is_fresh(ROOT / d.PLAN_SVG), "計畫動態圖過期：請在 PowerShell 執行 legion docs"


def test_readme_obsidian_and_phone_embed_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f'<img src="{d.PLAN_SVG}"' in text and "<!-- legion:plan:start -->" in text
    monkeypatch.setenv("LEGION_VAULT", str(tmp_path / "vault"))
    s = Settings()
    init_vault(s)
    note = (s.vault / d.OVERVIEW_NOTE).read_text(encoding="utf-8")  # 計畫與儀表合成總覽（2026-11-18）
    assert note.index(f"![[{d.VAULT_IMG}/plan.svg]]") < note.index(f"![[{d.VAULT_IMG}/dashboard.svg]]")
    assert "[[總覽]]" in (s.ai_dir / "計畫.md").read_text(encoding="utf-8")  # 舊連結轉址
    assert (s.vault / d.VAULT_IMG / "plan.svg").exists()  # 從 repo 複製，Obsidian 嵌入不會破圖
    out = write_plan(s, inbox_path=ROOT / "03_docs" / "inbox.md")
    assert out == s.ai_dir / "img" / "plan.svg"
    # 手機文件庫：legion 產生的三張動態圖改成 img/<檔名>，其他圖片仍改成提示
    phone = _for_phone(note + "\n![[AI/img/other.png]]\n![[AI/img/plan.svg|x]]")
    assert "![計畫動態圖](img/plan.svg)" in phone and "（圖片請在桌機 Obsidian 看）" in phone
    assert phone.count("img/plan.svg") == 1
    page = (ROOT / "03_docs" / "vault_page.html").read_text(encoding="utf-8")
    assert ".md img{display:block;max-width:100%" in page  # 560px 以上的 SVG 在手機不會撐出橫向捲動
    # 網格欄不能被內容撐寬（inbox 全表在 375px 曾撐到 431px），寬表格改在 .tbl 內捲動
    assert "display:grid;grid-template-columns:minmax(0,1fr)" in page
    copied = copy_phone_images(s.vault, tmp_path / "pub" / "img")
    assert {p.name for p in copied} >= {"plan.svg"}
    assert (tmp_path / "pub" / "img" / "plan.svg").read_bytes() == out.read_bytes()


def test_phone_export_has_overview_with_inbox_and_sha_tracks_changes(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """收件匣互動頁併入文件庫：總覽分類 = 總覽.md＋inbox 全表；sha 只隨內容（含動態圖）變，排程用它決定要不要發布。"""
    from legion.mobile import export_vault

    monkeypatch.setenv("LEGION_VAULT", str(tmp_path / "vault"))
    s = Settings()
    init_vault(s)
    repo = tmp_path / "repo"
    (repo / "03_docs").mkdir(parents=True)
    (repo / "03_docs" / "inbox.md").write_text(INBOX, encoding="utf-8", newline="\n")
    data = export_vault(s.vault, repo)
    assert data.categories[0] == "總覽"
    head = [(x.category, x.title, x.path) for x in data.docs[:2]]
    assert head == [("總覽", "總覽", d.OVERVIEW_NOTE), ("總覽", "收件匣（inbox 全表）", "03_docs/inbox.md")]
    assert "| A4 | 還沒做 | ⏳ |" in data.docs[1].text
    assert "![計畫動態圖](img/plan.svg)" in data.docs[0].text
    assert not any(x.path.endswith(("計畫.md", "儀表.md")) for x in data.docs)  # 轉址頁不匯出
    assert export_vault(s.vault, repo).sha256 == data.sha256  # 內容沒變 → 相同
    import os

    flow = s.ai_dir / "流程.md"
    os.utime(flow, (1, 1))  # 只改檔案時間（排序會變）→ sha 不變
    assert export_vault(s.vault, repo).sha256 == data.sha256
    (repo / "03_docs" / "vault_page.html").write_text("<p>新頁面</p>", encoding="utf-8")
    assert export_vault(s.vault, repo).sha256 != data.sha256  # 只改手機頁也要重新發布
    (repo / "03_docs" / "vault_page.html").unlink()
    (s.vault / d.VAULT_IMG / "plan.svg").write_bytes(b"<svg/>")
    assert export_vault(s.vault, repo).sha256 != data.sha256  # 只有圖變也算變更
    assert export_vault(s.vault).sha256 != export_vault(s.vault, repo).sha256  # 沒給 repo 就沒有 inbox
    missing = export_vault(s.vault, tmp_path / "nowhere")
    assert any("找不到" in w for w in missing.warnings)


def test_vault_json_cli_reports_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    from legion.cli import main

    monkeypatch.setenv("LEGION_VAULT", str(tmp_path / "vault"))
    init_vault(Settings())
    out = tmp_path / "pub" / "vault.json"  # 資料夾不存在也要能寫（排程第一次跑）
    assert main(["vault-json", "--refresh-plan", "--out", str(out)]) == 0
    assert "CHANGED: yes" in capsys.readouterr().out
    assert (tmp_path / "pub" / "img" / "plan.svg").exists()
    assert (tmp_path / "vault" / d.VAULT_IMG / "plan.svg").read_bytes() == (ROOT / d.PLAN_SVG).read_bytes()
    # 還沒標記已發布（例如上一輪發布失敗）→ 下一輪仍要發布，不會漏發
    assert main(["vault-json", "--refresh-plan", "--out", str(out)]) == 0
    assert "CHANGED: yes" in capsys.readouterr().out
    assert main(["vault-json", "--mark-published", "--out", str(out)]) == 0
    capsys.readouterr()
    assert main(["vault-json", "--refresh-plan", "--out", str(out)]) == 0
    assert "CHANGED: no" in capsys.readouterr().out
    (tmp_path / "vault" / "AI" / "reports" / "new.md").write_text("# 新報告\n", encoding="utf-8")
    assert main(["vault-json", "--out", str(out)]) == 0
    assert "CHANGED: yes" in capsys.readouterr().out
    assert main(["vault-json", "--mark-published", "--out", str(tmp_path / "nope" / "vault.json")]) == 1
