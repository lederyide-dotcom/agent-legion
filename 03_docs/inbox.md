# 任務收件匣（/next 從這裡接）

分工原則（David 2026-11-14：「人只負責掌舵，其他依建議自主持續完成」）：
- **掌舵（David）**：定目標與範圍、花真錢、刪除未合併的工作或原始資料、碰機密或對外服務、改預設模型或風險規則
- **其餘由 Claude Code 自主完成**：實作、驗證、合併已驗證的分支、整理清單、寫證據；完成後在晨報或回報中告知

規則：`/next` 由上而下找第一個狀態不是 ✅ 的列；負責人是 David 的不代做；blocked 的跳過並說明原因。
完成時狀態改 ✅＋日期，證據欄填檔案路徑或 commit。交接細節見 `03_docs/progress.md`。

狀態：⏳ 待做｜⛔ blocked｜✅ 完成

## 待掌舵（David）

| # | 決定什麼 | 建議 | 依據 |
|---|---|---|---|
| D1 | 水利計算函式庫戰役的範圍：哪些公式或規範、放哪個 repo（2026-11-14 David：之後再說） | 先做曼寧公式＋管渠滿管／非滿管水力，以教科書例題當驗收 | 回覆後 Claude Code 寫戰役任務檔 |
| D8 | 手機有沒有收到推播；要不要加 Telegram 第 2 層（2026-11-14 David：之後再說） | 桌面 app 開著時推播會被壓下；離開電腦時再測一次 | — |
| D10 | fu-T-0016-1 人工抽查 T-0016 報告的機密處理（2026-11-14 David：之後再說） | 人做 | `vault/AI/inbox_hold/fu-T-0016-1.md` |
| D14 | water-bim 凍結的提案 v1、v2 與 case-metrics_v1 仍含「漢華」：測試以 SHA-256 鎖定「不得變更」；另 anti-todo-tw skill 由 claude.ai 同步，本機改會被覆蓋 | 凍結檔：改內容並同步更新測試裡的鎖定雜湊（需你同意改測試）；skill：請在 claude.ai 的 skill 設定修改 | water-bim `tests/test_water_bim.py:180-229` |

## 已決定（2026-11-14 David 從互動頁回覆）

| # | 決定 | 執行結果 | 證據 |
|---|---|---|---|
| D2 | 小型 write 任務的規劃＋規格審查試用 sonnet，跑 2～3 個任務再比較 | 第 1 個（T-0022）：規劃便宜但規格和守門規則衝突，全任務 $0.85；已補提示（A13），再試 1～2 個才下結論 | `02_data/cost_analysis_20261114.md` |
| D3 | `strip_code_fence` 多重圍欄維持現狀 | 結案 | target-repo-b `tests/test_strip_code_fence.py` |
| D4 | 刪除 target-repo-b 的 `legion/T-0020` | ✅ 已移除 worktree 並 `git branch -D`（原 aec50ea）；master 不變 0b9d364 | `02_data/verify_20261114.md` 第 13 節 |
| D5 | `legion/T-0015` 封存不合併 | ✅ 未提交變更 commit 成 f1a2f9b，分支改名 `archive/legion-T-0015`，worktree 已移除 | 同上 |
| D6 | deny 規則與 hook 實測等真實任務時順便驗 | 延後，不單獨花費 | spec v0.5 |
| D7 | inbox_hold 依分流建議 | ✅ 0017-2、0019-1、0019-2 封存到 `vault/AI/inbox_done/archived-D7__*`；0018-1 放行（A12）；0016-2 低優先留在 hold；0016-1 改列 D10 | 下方分流表 |
| D9 | 對進行中的任務 cancel 維持兩段式 | 結案；README 已寫明 | README HALT 列 |
| D11 | T-0022 閘門核准＋第 17 行只追加元素的例外（「依你建議」） | ✅ 手動驗證後合併；守門規則本身不改 | `02_data/verify_20261114.md` 第 14 節 |
| D12 | 公開版授權採方案 A：程式碼 PolyForm Noncommercial 1.0.0＋文件 CC BY-NC-SA 4.0 | 記錄決定；NOTICE 先加 `Required Notice:` 行；公開時才切換 LICENSE | `03_docs/public_release_license.md` |
| D13 | 刪除「漢華 I&C」字眼 | ✅ legion 本來就沒有；water-bim 現行檔 255 個已刪（commit 4ddcfe5，未推送）；凍結提案 3 檔與 anti-todo-tw skill 待處理（見 D14） | `02_data/verify_20261114.md` 第 16 節 |

## Claude Code 可自主做

| # | 任務 | 狀態 | 完成條件 | 證據 |
|---|---|---|---|---|
| A1 | 查 repo-b-tests-2 排程戰役結果 | ✅ 2026-11-14 | 親自核對合併與測試 | `02_data/verify_20261114.md` |
| A2 | 查每日晨報排程 | ✅ 2026-11-14 | 08:07 成功產生 | `vault/AI/reports/brief-2026-11-14.md` |
| A3 | 合併雲端分支 claude/ecstatic-gates-ww9mp9 | ✅ 2026-11-14 | 合併後 144 passed | commit 467f256 |
| A4 | `legion cleanup`（只刪已併入且乾淨的） | ✅ 2026-11-14 | 10 項反例測試；已清 T-0017／18／19／21 | `02_data/verify_20261114.md` 第 8～9 節 |
| A5 | 晨報列出「可清理」 | ✅ 2026-11-14 | test_brief | 同上 |
| A6 | `legion cancel` 收尾可續跑的 HALT；T-0020 已收尾 | ✅ 2026-11-14 | tests/test_cancel_halted.py | 同上第 10 節 |
| A7 | start.bat 固定 compose 專案名稱 | ✅ 2026-11-14 | 主目錄與 worktree 都解析成同一名稱 | 同上第 10 節 |
| A8 | 花費分析：Opus 規劃＋審查占比 | ✅ 2026-11-14 | 數字取自帳本 | `02_data/cost_analysis_20261114.md` |
| A9 | 範圍驗收自動化：runner 產生「變更範圍」證據（相對起點 commit、含已 commit 與未追蹤新檔）；驗收後才出現的範圍外檔案停下等核准，核准以路徑為單位；規劃者提示不必再寫範圍指令 | ✅ 2026-11-14 | 5 項測試；code-reviewer 必修 1 項已修；相關 6 個想法檔已封存到 `vault/AI/inbox_done/resolved-A9__*` | `tests/test_scope_check.py`、`02_data/verify_20261114.md` 第 11 節 |
| A10 | progress.md 交接段落 | ✅ 2026-11-14 | 新 session 只讀 progress.md 即可接手 | `03_docs/progress.md` 最後一段 |
| A11 | 收件匣互動頁：`legion inbox` 把本檔表格轉 JSON，頁面讀它顯示；改本檔後重產並重新發布（連結不變） | ✅ 2026-11-14 | 12 項測試；code-reviewer 必修 2 項已修；本機實測頁面 27 列與本檔一致 | `tests/test_inbox.py`、`03_docs/inbox_page.html`、`02_data/verify_20261114.md` 第 12 節 |
| A12 | 依 D2＋D7 跑 fu-T-0018-1（T-0022）：safe_workspace_path 補邊界測試，sonnet 規劃＋規格審查（D2 第 1 個試跑） | ✅ 2026-11-14 | David 核准閘門與第 17 行例外（D11）；手動驗證後 ff 合併進 target-repo-b master 24c090c（53 passed） | `02_data/verify_20261114.md` 第 14 節、`02_data/cost_analysis_20261114.md` 補充 |
| A13 | 規劃提示補「既有測試只增不減以行為單位」：新案例寫新行或新測試函式（T-0022 根因） | ✅ 2026-11-14 | `tests/test_scope_check.py` 5 passed | `src/legion/prompts.py` write_scope_note |
| A14 | 作者權益：LICENSE（保留所有權利＋署名不得移除）、NOTICE、CITATION.cff、分享與引用規範；作者與 GitHub 出處內建在 `legion --version`、套件中繼資料、開發紀錄與晨報頁尾、互動頁 | ✅ 2026-11-14 | 全套 166 passed；code-reviewer 必修 1 項已修 | `02_data/verify_20261114.md` 第 15 節、`03_docs/sharing_and_citation.md` |

## inbox_hold 分流建議（給 D7）

| 想法檔 | 建議 | 理由 |
|---|---|---|
| fu-T-0001-1、fu-T-0005-1、fu-T-0015-1、fu-T-0018-2、fu-T-0021-1 | ✅ 已由 A9 解決並封存 | 範圍驗收在 commit 後輸出為空、看不到未追蹤檔 |
| fu-T-0021-2（-k 預期收集筆數） | ✅ 已封存 | pytest 收集 0 筆時 exit 5，驗收本來就會失敗 |
| fu-T-0018-1（safe_workspace_path 邊界測試） | ✅ D7 放行 → A12 | 補 `NUL .log` 等邊界，真實安全價值；花費需 D 同意 |
| fu-T-0016-1（人工抽查 T-0016 報告機密處理） | ✅ 已決定：改列 D10（之後再說） | 涉及機密判斷，留給人 |
| fu-T-0016-2（報告內容檢查） | ✅ 已決定：低優先，留在 hold | 目前 `--verify-refs` 已擋最大風險 |
| fu-T-0017-2（legion 測試 sys.path） | ✅ 已封存（D7） | 全套測試穩定通過，沒有實際問題 |
| fu-T-0019-1（移除未使用 import） | ✅ 已封存（D7） | T-0020 試過，runner 禁止刪既有測試行；價值低 |
| fu-T-0019-2（diff 驗收與 parametrize id） | ✅ 已封存（D7） | 已由 T-0021 涵蓋 |
