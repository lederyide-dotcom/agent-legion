# 任務收件匣（/next 從這裡接）

規則：`/next` 由上而下找第一個狀態不是 ✅ 的列。負責人是 David 的不代做；標 blocked 的跳過並說明原因。
完成時狀態改 ✅＋日期，證據欄填檔案路徑或 commit。規格依據：`03_docs/spec.md`、`03_docs/spec_v0.5.md`，交接細節見 `03_docs/progress.md`。

狀態：⏳ 待做｜🔄 進行中｜⛔ blocked｜✅ 完成

| # | 任務 | 負責人 | 狀態 | 依據／完成條件 | 證據 |
|---|---|---|---|---|---|
| 1 | 查 repo-b-tests-2 排程戰役結果並回報 | Claude Code | ✅ 2026-11-14 | 本機親自核對：target-repo-b master = 0b9d364，legion/T-0021 是 HEAD 的祖先；298c048..HEAD 只動 telegram_bot.py（+1 −1，來自 T-0019）與新增 tests/test_strip_code_fence.py（+72）；重跑 50 passed；工作目錄乾淨；未 push | `02_data/verify_20261114.md`、commit 11f27f0 |
| 2 | 查每日晨報排程是否產生晨報並推播 | Claude Code | ✅ 2026-11-14 | 08:07 執行成功，產生晨報；推播沒送出，因為桌面 app 開著（Remote Control 在桌面活躍時不推手機） | `vault/AI/reports/brief-2026-11-14.md` |
| 3 | 在排程頁對 `legion-daily-brief` 按一次「Run now」，預先核准工具 | David | ✅ 2026-11-14 | 不需要了：08:07 那次沒有卡權限，自己跑完 | 同 #2 |
| 4 | 回覆：手機有沒有收到測試推播「測試推播：agent-legion 通知驗證」 | David | ⏳ | 桌面 app 開著時推播會被壓下；要測就在離開電腦時測 | |
| 5 | 決定是否合併 `claude/ecstatic-gates-ww9mp9`（6eb52f1：花費帳本加 effort 欄、mmdc 路徑可用 `LEGION_MERMAID_CLI` 覆寫） | David | ⏳ | 本機已驗證：132 過＋1 項環境因素補驗通過；start.bat 乾淨跑完。合併方式：GitHub PR，或叫 Claude Code 在本機 ff-merge（main 已前進到 11f27f0，需確認仍可 ff 或改用 merge） | 驗證紀錄見雲端分支 `02_data/verify_20261113.md` |
| 6 | docker compose 固定專案名稱（compose 頂層 `name:` 或 start.bat 設 `COMPOSE_PROJECT_NAME`），避免在其他資料夾跑 start.bat 時另建同名容器 | Claude Code | ⏳ | 在臨時 worktree 跑 `docker compose config`，專案名稱等於既有容器；不得 down／-v | |
| 7 | 評估規劃／規格審查用 Opus 的性價比（目前占單任務花費 57%；小型 write 任務改 sonnet 規劃是否夠） | Claude Code | ⛔ blocked：等 #5 合併後帳本才有 effort 欄 | 用 cost_ledger 的 role／model／effort 比對每任務花費，寫成建議交 David 決定，不自行改預設 | |
| 8 | 研究報告第 2 步：實測 deny 規則與 hook 真的會擋 | Claude Code | ⛔ blocked：需要真實呼叫，花費要 David 先同意 | spec v0.5「必須停下來問我」：真實任務花費 | |
| 9 | 提供水利計算函式庫戰役的範圍：要涵蓋的公式或規範，以及要放在哪個 repo | David | ⏳ | 提供後由 Claude Code 寫戰役任務檔給 David 確認，再放進 INBOX | |
| 10 | 決定 `strip_code_fence` 多重圍欄的行為要不要改（目前測試把「兩段合併、中間圍欄殘留」固定成現狀） | David | ⏳ | 要改就開新戰役：先改測試期望（需 David 核准，屬改既有測試），再改 telegram_bot.py | target-repo-b `tests/test_strip_code_fence.py` |
| 11 | 做 `legion cleanup`：列出已併入目標 repo 的 `legion/*` 分支與 worktree、HALT 任務的殘留 worktree，預設只列不刪；加 `--apply` 才刪，且只刪「已是 HEAD 祖先」的分支 | Claude Code | ✅ 2026-11-14 | 10 項反例測試、全套 139 passed；code-reviewer 必修 4 項已修 | `src/legion/cleanup.py`、`tests/test_cleanup.py`、`02_data/verify_20261114.md` 第 8 節 |
| 12 | 同意對 target-repo-b 執行 `legion cleanup --apply`：dry-run 清單只會刪 T-0017、T-0018、T-0021 的分支與 worktree。T-0015（未提交變更）、T-0019（T-0020 要從它接續）、T-0020（可續跑）保留；.worktrees/T-0001、T-0003、T-0004 是孤兒，只列不刪 | David | ✅ 2026-11-14 | David「依你建議自主決定」→ 已刪 T-0017、T-0018、T-0021；target-repo-b master 0b9d364 未變、50 passed。以後晨報會列出「可清理」項目，同意後跑 `legion cleanup --apply` | `02_data/verify_20261114.md` 第 9 節 |
| 12b | 決定 T-0020（HALT、可續跑，內容已被 T-0021 取代）要怎麼收尾：`legion cancel` 不接受 HALT，需要新增「把 HALT 標為不再續跑」的指令，之後 T-0019、T-0020 才能清 | David | ⏳ | 回「加指令」就由 Claude Code 實作（含測試）；或維持現狀 | |
| 13 | 挑選 `vault/AI/inbox_hold/` 裡 10 個後續想法：要做的搬回 INBOX，不做的搬到 99_archive | David | ⏳ | 真實 backend 不自動領取回灌想法（事故 4） | |
| 14 | 決定 target-repo-b 的 `legion/T-0015` 分支（晨報列為唯一待 merge）要合併還是封存 | David | ⏳ | 合併前 Claude Code 可先跑測試、列 diff 給你看 | `vault/AI/reports/brief-2026-11-14.md` |
| 15 | 決定是否加 Telegram 通知作為第 2 層推播 | David | ⏳ | 依 #4 結果再決定；會碰 bot token，屬「必須停下來問我」 | |
| 16 | progress.md 補記 `legion brief` 晨報、雲端／本機交接方式與 inbox | Claude Code | ⏳ | 新 session 只讀 progress.md 就知道有晨報、交接流程與 inbox | |
