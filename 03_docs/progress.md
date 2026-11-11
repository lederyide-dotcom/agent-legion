# 進度（2026-11-11 07:55）

## 已完成
- 開工查證（02_data/env_check.md）：claude 2.1.319；權限語法（docs＋實測）；排程下訂閱登入可用；Codex 未安裝
- runner 閉環、風險／安裝分級、熔斷、可重入續跑、vault、紀錄文件、證據、docx／pdf 匯出、mock demo
- 實戰 B（T-0005）：DONE，$0.1669，human_touches 0 → 02_data/sandbox_check.txt
- code-reviewer 審查：🔴 8 項已修（見下）；pytest 68 項全過；start.bat 從乾淨狀態實測通過

## 實戰 A 第三次（T-0008）：DONE
- 2026-11-11 20:46 開跑（David 同意第三次重跑），$0.5708，human_touches 0；報告 vault/AI/reports/T-0008-report.md
- 驗收紀錄：02_data/verify_20261111.md、readonly_check.txt、autonomy.csv

## 事故 4：回灌鏈被自動領取（約 $1.68）
- 我的 tick 迴圈條件是「沒有任何進展才停」，T-0008 結案時書記官回灌 2 個後續想法到 INBOX，迴圈繼續領取，
  形成 T-0009～T-0014（深度上限 2 有生效）。5 張 DONE、T-0012 判 high 停在 WAIT_HUMAN。
- 這些是 spec「真實呼叫只在兩個實戰任務」以外的花費，未經 David 同意。合計實戰花費約 $3.82，未超過 $5。
- 這些任務都是 readonly、目標 D:\PipeAI_wmt，前後狀態未變。
- 程式層防護（審查後補上）：真實 backend 的 tick 預設把回灌寫到 vault/AI/inbox_hold/，需 `--auto-followups` 才進 INBOX。
- 審查另指出：回灌繼承 parent 的 repo（T-0009～T-0013 內容其實在改 legion 自己卻掛在 D:/PipeAI_wmt）；
  T-0009、T-0011 報告引用了 D:\202611_agent-legion 下的檔案（含 .venv 設定），唯讀 executor 讀到目標 repo 以外。
  已補絕對路徑的 .env 拒讀規則；未見讀取 .env 的跡象。
- 當日預算只看 DB；DB 重建後先前花費未計入，`--daily-budget` 會低估（未修，列待決定）。

## 事故 5：legion 的呼叫出現在 ChatGPT／Codex
- David 截圖：ChatGPT 對話「你是指揮官，負責規劃。任務編號 T-0010…」時間 20:50，與 T-0010 planner 開始時間 20:50:38 相同。
- 查證：該次呼叫由 Claude 回答（~/.claude/projects/D--PipeAI-wmt/4693a13b….jsonl，model claude-sonnet-5-5，6 則 assistant），
  ANTHROPIC_BASE_URL 為 api.anthropic.com，已啟用 plugin 沒有轉送 hook。推論：ChatGPT／Codex 讀取了 Claude Code
  寫在 ~/.claude/projects 的本機逐字紀錄並顯示成對話（未驗證是哪個功能、是否耗用 Codex 額度）。
- 我先前回報「legion 只用 Claude、和 ChatGPT 無關」只查了 legion 程式與 DB，沒考慮本機紀錄被其他工具讀取，說法不完整。
- 修正：每次 `claude -p` 加 `--no-session-persistence`，不再寫入 ~/.claude/projects（CLI 解析已確認接受此參數；未以真實呼叫實測）。
- 已存在的今日紀錄檔（D--PipeAI-wmt 42 個、各 worktree／records 資料夾）未刪除，等 David 決定。

## 等待 David
- T-0012（high，WAIT_HUMAN）要 answer reject／cancel 或保留
- vault 內 18 個舊檔在 20:49 被改成 CRLF（內容不變）、新增 vault/.obsidian/：疑似 Obsidian 開啟所致，未 commit、未還原
- D:\PipeAI_wmt 在 21:03:25 出現未追蹤的 AGENTS.md（Codex 工作說明），非 legion 建立，未動

## 實戰 A 第一次（T-0006）：HALT
- 2026-11-11 20:28 開跑，SPEC_REVIEW 連續退回 4 次 → retry_exceeded，花費 $0.3354，human_touches 0；目標 repo 未被修改
- 原因（系統 bug，非 agent）：
  1. planner／spec_reviewer 提示沒說明唯讀報告由 runner 寫入 vault、`legion.checks report` 是 runner 附加的白名單指令，審查者每輪都判「自相矛盾、違反白名單」
  2. 退回 PLAN 時 planner 沒拿到審查意見，等於盲改
- 修正：提示加上唯讀交付說明與白名單例外；退回意見帶回 planner；去重 planner 自抄的報告檢查；新增回歸測試（共 69 項全過）

## 實戰 A 第二次（T-0007）：HALT
- 2026-11-11 20:37 開跑（David 同意重跑），SPEC_REVIEW 退回 4 次 → retry_exceeded，$0.4201，human_touches 0；目標 repo 未被修改
- 退回意見已正確帶回 planner（規格逐輪修正），但：
  1. 審查者沒有通過門檻，任何「建議補強」都判 revise；第 3、4 輪已無阻擋性問題
  2. 審查提示中的驗收指令清單混入 runner 附加的報告檢查，審查者每輪判為「重複／矛盾」
- 修正：審查判定標準（findings 標「必修／建議」，只有必修才 revise）；驗收指令分「規劃者提出／runner 自動附加」顯示；planner 只需修必修項、規格保持精簡；回歸測試補斷言（69 項全過）
- 同一問題（規格審查無法收斂）已修 2 次；若第三次仍不收斂，依規則停下整理
- 實戰真實花費累計約 $1.58（B 0.1669、誤領取約 0.65、smoke 0.002、T-0006 0.3354、T-0007 0.4201）

- 另：`.venv\Scripts\legion.exe` 被 Windows 應用程式控制原則擋下，改用 `python -m legion`（沒有呼叫 Claude、零成本）

## 事故紀錄（誠實揭露）
1. demo 想法檔留在共用 INBOX，被正式 tick 以真實 Claude 誤領取（T-0001～T-0004，約 $0.65）。
   已 cancel（HALT: operator_cancel）；修正：demo 結束清除 INBOX、真實 backend 跳過帶 mock 劇本的檔案、領取後封存到 AI/inbox_done/。
2. 第二次從乾淨狀態實測 start.bat 時執行了 `docker compose down -v`，連帶清掉正式 schema 的 DB 紀錄
   （T-0001～T-0005 的 tasks／task_events／agent_runs）。vault 筆記、record.md、證據檔已在 git，不受影響。
   修正：任務編號同時參考 vault 既有筆記，DB 重建不會覆蓋舊紀錄；INBOX 領取後封存，不會被重複領取。
3. 安裝清冊 DEV 列的時間最初是我估填的整點時間，後來改為檔案實際建立時間（事後補記，非安裝當下寫入）。

## 已知限制
- Bash 白名單不是硬邊界；硬邊界由 runner 承擔（VERIFY 親自執行、實際 diff 重判風險、worktree 外狀態比對、證據雜湊）
- 重試次數為 SPEC_REVIEW 退回、VERIFY 失敗、REVIEW 退回的合計
- 「官方發行頁」安裝本輪一律轉人工（比 spec 嚴格）
- 實戰 B 回灌的後續想法 fu-T-0005-1.md 暫放 vault/AI/inbox_hold/，等 David 決定是否放回 INBOX
