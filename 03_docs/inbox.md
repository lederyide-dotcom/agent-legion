# 任務收件匣（/next 從這裡接）

規則：`/next` 由上而下找第一個狀態不是 ✅ 的列。負責人是 David 的不代做；標 blocked 的跳過並說明原因。
完成時狀態改 ✅＋日期，證據欄填檔案路徑或 commit。規格依據：`03_docs/spec.md`、`03_docs/spec_v0.5.md`，交接細節見 `03_docs/progress.md`。

狀態：⏳ 待做｜🔄 進行中｜⛔ blocked｜✅ 完成

| # | 任務 | 負責人 | 狀態 | 依據／完成條件 | 證據 |
|---|---|---|---|---|---|
| 1 | 查 repo-b-tests-2 排程戰役結果並回報（list_task_runs → list_events；核對分支、測試、是否 ff-merge、花費） | Claude Code | ⛔ blocked：排程 2026-11-14 04:05 才開跑 | progress.md「2026-11-13 戰役試跑後的狀態」；結果寫入 `02_data/verify_20261114.md` | |
| 2 | 查每日晨報排程（約 08:07）是否產生 `vault/AI/reports/brief-2026-11-14.md` 並推播 | Claude Code | ⛔ blocked：2026-11-14 08:07 之後 | 晨報檔存在、內容與 `legion brief` 一致 | |
| 3 | 在 Claude App 的排程頁對 `legion-daily-brief` 按一次「Run now」，預先核准它要用的工具 | David | ⏳ | 之後每天 08:00 不再卡權限 | |
| 4 | 回覆：手機有沒有收到測試推播「測試推播：agent-legion 通知驗證」 | David | ⏳ | 確認 Remote Control 推播可用；沒收到就改評估 Telegram 通知 | |
| 5 | 決定是否合併 `claude/ecstatic-gates-ww9mp9`（6eb52f1：花費帳本加 effort 欄、mmdc 路徑可用 `LEGION_MERMAID_CLI` 覆寫） | David | ⏳ | 本機已驗證：132 過＋1 環境因素補驗通過；start.bat 乾淨跑完。合併方式：GitHub PR，或叫 Claude Code 在本機 ff-merge | 驗證紀錄見雲端分支 `02_data/verify_20261113.md` |
| 6 | docker compose 固定專案名稱（compose 頂層 `name:` 或 start.bat 設 `COMPOSE_PROJECT_NAME`），避免在其他資料夾跑 start.bat 時另建同名容器 | Claude Code | ⏳ | 加測試或實測：在臨時 worktree 跑 `docker compose config` 專案名稱等於既有容器；不得 down／-v | |
| 7 | 評估規劃／規格審查用 Opus 的性價比（小任務改 sonnet 是否夠） | Claude Code | ⛔ blocked：等 #5 合併後帳本才有 effort 欄 | 用 cost_ledger 的 role／model／effort 比對每任務花費，寫成建議交 David 決定，不自行改預設 | |
| 8 | 研究報告第 2 步：實測 deny 規則與 hook 真的會擋 | Claude Code | ⛔ blocked：需要真實呼叫，花費要 David 先同意 | spec v0.5「必須停下來問我」：真實任務花費 | |
| 9 | 提供水利計算函式庫戰役的範圍：要涵蓋的公式或規範（例如曼寧公式、管渠水力、IDF、逕流係數；台灣雨水下水道設計規範），以及要放在哪個 repo | David | ⏳ | 提供後由 Claude Code 寫戰役任務檔（mission frontmatter、allowed_paths、以例題當驗收）給 David 確認，再放進 INBOX | |
| 10 | 挑選 `vault/AI/inbox_hold/` 裡 10 個後續想法：要做的搬回 INBOX，不做的搬到 99_archive | David | ⏳ | 真實 backend 不自動領取回灌想法（事故 4） | |
| 11 | 決定 target-repo-b 的 `legion/T-0015` 分支（sandbox 時期成果）要合併還是封存 | David | ⏳ | `legion brief` 列為待 merge | |
| 12 | 決定是否加 Telegram 通知作為第 2 層推播 | David | ⏳ | 依 #4 結果再決定；會碰 bot token，屬「必須停下來問我」 | |
| 13 | progress.md 補記 `legion brief` 晨報與雲端／本機交接方式 | Claude Code | ⏳ | 新 session 只讀 progress.md 就知道有晨報與交接流程 | |
