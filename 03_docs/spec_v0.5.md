# agent-legion spec v0.5（草稿，待 使用者確認）

- 日期：2026-11-11　前版：03_docs/spec.md v0.4（已全數驗收）
- 本版主題：補漏洞 → 以 <target-repo-b>（最常用：n8n 每小時派報＋Telegram bot）為正式試用對象

## 最終目標
legion 能在 target-repo-b 上自主完成小型、可驗證的改動與健檢，每個任務 ≤ $0.5、一次通過率 ≥ 70%、人工介入 ≤ 1 次，且不影響正在運作的每小時派報。

## 已知背景（已查證，2026-11-11）
- target-repo-b：git 只追蹤 `telegram_bot.py`；`telegram_bot.py` 有未 commit 修改；約 30 個未追蹤檔（diag_*、n8n_*.bat、.bak、tree.txt 等）
- 每小時派報在 n8n（Trigger Hours → RSS TWDev／Google News／颱風 → 模型摘要 → Send AI Summary／Send News Links），工作流程不在 git，只有 `n8n_workflow_summary.json` 與 `n8n_backup/`
- `telegram_bot.py` 呼叫本機 Ollama（127.0.0.1:11434），可寫入 `workspace/`；有 `safe_workspace_path`、`strip_code_fence` 等純函式
- `.env.bak_20261025` 未被 .gitignore 排除（有被誤提交的風險）
- legion worktree 從 HEAD 建立：未 commit 的修改不會出現在 worktree

## 階段 0：target-repo-b 上線前置（使用者做或核准，legion 不自動做）
1. target-repo-b commit 目前的 `telegram_bot.py` 修改（否則 legion 會在舊版本上改）
2. `.gitignore` 加 `.env*`、`*.bak*`、`*.log`、`bot.log`
3. 決定未追蹤檔哪些進 git（建議：n8n_*.bat、start_bot.bat、diag 整理後再進；.bak／log 不進）

## 階段 1：legion 補漏洞（約半天；最後一項真實呼叫約 $0.2）
| # | 項目 | 驗收 |
|---|---|---|
| 1 | 持久花費帳本 `02_data/cost_ledger.csv`，每日預算改由帳本加總（含 DB 重建前） | pytest：DB 重建後當日預算仍計入既有花費 |
| 2 | 回灌防護：內容涉及 legion 本身、runner、風險或熔斷規則 → 風險至少 mid；repo 不再無條件繼承 | pytest 兩案 |
| 3 | `legion.checks report --verify-refs`：報告中每個 `檔名:行號` 必須存在且行號在範圍內 | pytest：假行號被抓出；對 T-0008 報告實跑並記錄結果 |
| 4 | 每次 agent 呼叫的提示存成證據（全文＋SHA-256） | pytest：證據清冊含 prompt |
| 5 | cancel T-0012（由 #3 取代） | status 為 HALT operator_cancel |
| 6 | 真實驗證 `--no-session-persistence`：跑一個最小任務，`~/.claude/projects` 無新增紀錄 | 前後檔案數比對寫入 02_data |

## 階段 2：target-repo-b 試用（1～2 週，每日上限 $2）
建議題目（皆不需執行 bot、不連 Telegram／Ollama）：
1. readonly：target-repo-b 架構與風險健檢（含 n8n 工作流程摘要、diag 腳本盤點）
2. write：為 `safe_workspace_path` 補 pytest（路徑穿越、絕對路徑、空字串）— 安全相關，最優先
3. write：為 `strip_code_fence` 補 pytest
4. write：把 n8n 工作流程匯出成 JSON 進 git，並加結構檢查測試（Trigger Hours 存在且為每小時、RSS 來源清單、Send 節點存在）
5. write：diag_n8n1～6 合併成一支帶參數的診斷腳本（含測試）

排程：先白天手動 tick 3 個任務，穩定後註冊夜間排程（22:00～06:00 每 10 分鐘）。

指標（寫入 metrics.csv，週報彙整）：一次通過率、每任務花費、human_touches、規格審查退回次數。

## 階段 3（11/22 Codex 重置後，依階段 2 數據決定）
- legion 的 WAIT_HUMAN／HALT 與每日摘要透過 target-repo-b 的 Telegram bot 推送（沿用既有頻道或另開私訊）
- Codex 當交付審查者（跨模型）
- 依角色分模型（規格審查用較便宜模型）
- 審查通過的 worktree 分支自動開 PR

## 可以自行決定
- 階段 1 的實作細節、測試寫法、檔案結構、各角色 prompt
- 階段 2 任務的拆分與措辭（題目範圍內）

## 必須停下來問我
- 階段 0 任何一項（target-repo-b 的 commit、.gitignore、檔案去留）
- 任何會執行 telegram_bot.py、啟動或重啟 n8n／Ollama、連線 Telegram 的動作
- 修改 n8n 正在使用的工作流程（只能匯出副本進 git，不能改運作中的）
- merge legion 分支回 target-repo-b
- 單日花費超過 $2 或累計超過 $10
- 讀取 .env／.env.bak、金鑰、Telegram token
- 放寬風險規則、提高回灌上限、移除熔斷
