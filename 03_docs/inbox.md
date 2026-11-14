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
| D1 | 水利計算函式庫戰役的範圍：哪些公式或規範、放哪個 repo | 先做曼寧公式＋管渠滿管／非滿管水力，以教科書例題當驗收 | 回覆後 Claude Code 寫戰役任務檔 |
| D2 | 小型 write 任務的規劃＋規格審查改用 sonnet | 試跑 2～3 個任務再比較（預估每任務省約 $0.19） | `02_data/cost_analysis_20261114.md` |
| D3 | `strip_code_fence` 多重圍欄行為要不要改 | 維持現狀即可，除非 bot 實際遇到多段程式碼 | target-repo-b `tests/test_strip_code_fence.py` |
| D4 | 刪除 target-repo-b 的 `legion/T-0020` 分支（未併入的舊 commit，內容已被 T-0021 取代） | 刪（需 `git branch -D`，屬刪除未合併工作） | `02_data/verify_20261114.md` |
| D5 | target-repo 的 `legion/T-0015`（sandbox 驗證任務，worktree 有未提交變更） | 封存不合併：它是階段 1 的試驗 | 晨報「待 merge」 |
| D6 | 研究第 2 步「實測 deny 規則與 hook」要花真錢（約 $0.3～0.5） | 等有新的真實任務時順便驗，不單獨花 | spec v0.5 |
| D7 | inbox_hold 剩下 6 個後續想法的取捨 | 見下方「inbox_hold 分流建議」 | `vault/AI/inbox_hold/` |
| D8 | 手機有沒有收到推播；要不要加 Telegram 第 2 層 | 桌面 app 開著時推播會被壓下；離開電腦時再測一次 | — |
| D9 | 對進行中的任務 `legion cancel` 時，要不要一次就收尾（目前會先停成可續跑的 HALT，要再 cancel 一次） | 維持現狀：第一次 cancel 保留後悔空間；README 已寫明 | code-reviewer 建議 4 |

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

## inbox_hold 分流建議（給 D7）

| 想法檔 | 建議 | 理由 |
|---|---|---|
| fu-T-0001-1、fu-T-0005-1、fu-T-0015-1、fu-T-0018-2、fu-T-0021-1 | ✅ 已由 A9 解決並封存 | 範圍驗收在 commit 後輸出為空、看不到未追蹤檔 |
| fu-T-0021-2（-k 預期收集筆數） | ✅ 已封存 | pytest 收集 0 筆時 exit 5，驗收本來就會失敗 |
| fu-T-0018-1（safe_workspace_path 邊界測試） | 值得做，約 $0.2 | 補 `NUL .log` 等邊界，真實安全價值；花費需 D 同意 |
| fu-T-0016-1（人工抽查 T-0016 報告機密處理） | 人做 | 涉及機密判斷，留給人 |
| fu-T-0016-2（報告內容檢查） | 低優先 | 目前 `--verify-refs` 已擋最大風險 |
| fu-T-0017-2（legion 測試 sys.path） | 封存 | 全套測試穩定通過，沒有實際問題 |
| fu-T-0019-1（移除未使用 import） | 封存 | T-0020 試過，runner 禁止刪既有測試行；價值低 |
| fu-T-0019-2（diff 驗收與 parametrize id） | 封存 | 已由 T-0021 涵蓋 |
