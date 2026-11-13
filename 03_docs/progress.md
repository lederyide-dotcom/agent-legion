# 進度（2026-11-11 07:55）

## 已完成
- 開工查證（02_data/env_check.md）：claude 2.1.319；權限語法（docs＋實測）；排程下訂閱登入可用；Codex 未安裝
- runner 閉環、風險／安裝分級、熔斷、可重入續跑、vault、紀錄文件、證據、docx／pdf 匯出、mock demo
- 實戰 B（T-0005）：DONE，$0.1669，human_touches 0 → 02_data/sandbox_check.txt
- code-reviewer 審查：🔴 8 項已修（見下）；pytest 68 項全過；start.bat 從乾淨狀態實測通過

## 實戰 A 第三次（T-0008）：DONE
- 2026-11-11 20:46 開跑（使用者同意第三次重跑），$0.5708，human_touches 0；報告 vault/AI/reports/T-0008-report.md
- 驗收紀錄：02_data/verify_20261111.md、readonly_check.txt、autonomy.csv

## 事故 4：回灌鏈被自動領取（約 $1.68）
- 我的 tick 迴圈條件是「沒有任何進展才停」，T-0008 結案時書記官回灌 2 個後續想法到 INBOX，迴圈繼續領取，
  形成 T-0009～T-0014（深度上限 2 有生效）。5 張 DONE、T-0012 判 high 停在 WAIT_HUMAN。
- 這些是 spec「真實呼叫只在兩個實戰任務」以外的花費，未經 使用者同意。合計實戰花費約 $3.82，未超過 $5。
- 這些任務都是 readonly、目標 <target-repo-a>，前後狀態未變。
- 程式層防護（審查後補上）：真實 backend 的 tick 預設把回灌寫到 vault/AI/inbox_hold/，需 `--auto-followups` 才進 INBOX。
- 審查另指出：回灌繼承 parent 的 repo（T-0009～T-0013 內容其實在改 legion 自己卻掛在 <target-repo-a>）；
  T-0009、T-0011 報告引用了 . 下的檔案（含 .venv 設定），唯讀 executor 讀到目標 repo 以外。
  已補絕對路徑的 .env 拒讀規則；未見讀取 .env 的跡象。
- 當日預算只看 DB；DB 重建後先前花費未計入，`--daily-budget` 會低估（未修，列待決定）。

## 事故 5：legion 的呼叫出現在 ChatGPT／Codex
- 使用者截圖：ChatGPT 對話「你是指揮官，負責規劃。任務編號 T-0010…」時間 20:50，與 T-0010 planner 開始時間 20:50:38 相同。
- 查證：該次呼叫由 Claude 回答（~/.claude/projects/<target-repo-a>/4693a13b….jsonl，model claude-sonnet-5-5，6 則 assistant），
  ANTHROPIC_BASE_URL 為 api.anthropic.com，已啟用 plugin 沒有轉送 hook。
- 已確認來源（使用者截圖）：ChatGPT「設定 → 匯入 → 從 Claude Code 匯入」開著「保持匯入同步」，會把
  ~/.claude/projects 的 Claude Code 紀錄同步成 ChatGPT 對話。使用者已於 2026-11-11 關閉同步。是否耗用 Codex 額度未驗證。
- 我先前回報「legion 只用 Claude、和 ChatGPT 無關」只查了 legion 程式與 DB，沒考慮本機紀錄被其他工具讀取，說法不完整。
- 修正：每次 `claude -p` 加 `--no-session-persistence`，不再寫入 ~/.claude/projects（CLI 解析已確認接受此參數；未以真實呼叫實測）。
- 已存在的今日紀錄檔（<target-repo-a> 42 個、各 worktree／records 資料夾）未刪除，等 使用者決定。

## spec v0.5 階段 1：完成（2026-11-11 晚間）
- 03_docs/spec_v0.5.md（由草稿轉正）；驗收見 02_data/verify_20261111.md 末段
- 持久帳本、回灌防護、--verify-refs、提示存證、cancel T-0012、真實驗證不留紀錄檔（T-0015，$0.1966）
- 下一步：階段 0（target-repo-b 前置，使用者做或核准）→ 階段 2 試用

## spec v0.5 階段 0：完成（2026-11-11，使用者說「你來做」）
- <target-repo-b>（master，無遠端，未推送）：
  - 057ac36 commit telegram_bot.py 既有未提交修改（安全加固；token 由環境變數讀取，無寫死機密）
  - 1c65ed9 .gitignore 補 `.env.*`（保留 .env.example）、`*.bak*`、`tree.txt`；啟動、n8n 維運、diag 腳本納入 git（掃描命中處皆為 os.getenv 或註解）
- 驗證：`git check-ignore` 確認 .env 備份檔與 .bak 檔被排除；git status 乾淨；追蹤檔 1 → 24
- 未讀取 .env；未執行 bot、n8n、Ollama
- 階段 2 可開始，但今日帳本 $4.02 已超過每日 $2，真實任務要等明天

## 研究報告第 1 步：硬防線完成（2026-11-12）
- 既有測試只能新增、改變測試收集方式要人核准、核准綁定 diff 內容、改動範圍允許清單、同一錯誤 3 次即停、每次呼叫 agent 前檢查 STOP
- 驗收：02_data/verify_20261112.md 末段；98 passed；code-reviewer 🔴 4 項已修
- 下一步（研究報告第 2 步）：實測 deny 規則與 hook 真的會擋（需要真實呼叫，會花額度）

## 等待使用者
- T-0012（high，WAIT_HUMAN）要 answer reject／cancel 或保留
- vault 內 18 個舊檔在 20:49 被改成 CRLF（內容不變）、新增 vault/.obsidian/：疑似 Obsidian 開啟所致，未 commit、未還原
- <target-repo-a> 在 21:03:25 出現未追蹤的 AGENTS.md（Codex 工作說明），非 legion 建立，未動

## 實戰 A 第一次（T-0006）：HALT
- 2026-11-11 20:28 開跑，SPEC_REVIEW 連續退回 4 次 → retry_exceeded，花費 $0.3354，human_touches 0；目標 repo 未被修改
- 原因（系統 bug，非 agent）：
  1. planner／spec_reviewer 提示沒說明唯讀報告由 runner 寫入 vault、`legion.checks report` 是 runner 附加的白名單指令，審查者每輪都判「自相矛盾、違反白名單」
  2. 退回 PLAN 時 planner 沒拿到審查意見，等於盲改
- 修正：提示加上唯讀交付說明與白名單例外；退回意見帶回 planner；去重 planner 自抄的報告檢查；新增回歸測試（共 69 項全過）

## 實戰 A 第二次（T-0007）：HALT
- 2026-11-11 20:37 開跑（使用者同意重跑），SPEC_REVIEW 退回 4 次 → retry_exceeded，$0.4201，human_touches 0；目標 repo 未被修改
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
- 實戰 B 回灌的後續想法 fu-T-0005-1.md 暫放 vault/AI/inbox_hold/，等 使用者決定是否放回 INBOX

## 目前狀態（2026-11-12 深夜，換 session 從這裡接）
- 已完成：硬防線、依角色分配模型、軍師、戰役與 legion run；126 項測試全過
- 模型：規劃／規格審查 Opus medium，執行 Sonnet（失敗升 Opus high），交付審查 Sonnet high，書記官 Haiku，軍師 Opus high，參謀 Opus medium
- 使用者方案含 Fable（有獨立每週額度）；軍師可用 LEGION_MODEL_ADVISOR=fable 切換，尚未切換
- 未驗證：軍師、戰役、依角色分配模型都還沒有真實任務跑過
- 下一步建議：在 target-repo-b 用真實 backend 試跑一場小戰役（max_tasks 3、budget 1.5），對照 metrics 的每任務花費
## 真實戰役試跑（2026-11-13，詳見 02_data/verify_20261113.md）
- 戰役 repo-b-tests（目標 target-repo-b，max_tasks 3、budget $1.5）：T-0019 DONE（分支 legion/T-0019，42 passed，只改 telegram_bot.py 一行 CRLF 正則＋新增 tests/test_strip_code_fence.py）；參謀判定未完成，開 T-0020 補「結尾缺換行」「多重圍欄」案例，判斷合理
- T-0020 停在 WAIT_HUMAN（high 風險）：驗收指令 `git diff --exit-code -- telegram_bot.py` 被判不在白名單。原因是 risk.accept_cmd_allowed 把 `--` 當旗標先拒絕，屬 legion 誤判；未代為核准
- 花費：戰役 $0.8927（T-0019 $0.529、T-0020 $0.364），未超任何上限；比 T-0017 $0.25、T-0018 $0.17 貴 2～3 倍，主因規劃／規格審查改用 Opus
- 角色模型實測與角色表一致：規劃／規格審查／參謀 opus、執行／交付審查 sonnet、書記官 haiku；effort 未記錄（未驗證）；軍師未觸發（未驗證）
- target-repo-b 主分支與工作目錄未動；未新增 session jsonl
- 目前未達成戰役目標；多重圍欄目前會把兩個區塊合併、殘留中間圍欄，行為可議

### 下一步建議
1. 修 risk.accept_cmd_allowed：允許 git 的 `--` 分隔符（加測試），再讓使用者決定 T-0020 要 approve 或 reject 後改丟新戰役檔（base_branch: legion/T-0019）
2. ~~在 cost_ledger 記錄 effort~~（2026-11-13 已完成，見 verify_20261113.md 末段；真實呼叫套用與否未驗證）
3. 評估規劃／規格審查用 Opus 的性價比：小任務可考慮 sonnet，或讓規格審查 revise 前先比對白名單
4. 使用者檢查 legion/T-0019 後自行 merge；多重圍欄行為是否要改，由使用者決定

## 2026-11-13 戰役試跑後的狀態（新 session 從這裡接）
- 戰役 repo-b-tests：T-0019 DONE（成果在 target-repo-b 的分支 legion/T-0019，尚未 merge）；T-0020 HALT（戰役預算用完；成果只在 .worktrees/T-0020，未審查未提交，不採用）。合計 $1.51
- 已修的 bug：白名單誤判 git 的 `--`；戰役接續任務的規劃改在接續分支的 worktree；戰役剩餘額度低於 $0.05 先停。皆只經 mock 驗證
- 使用者 2026-11-13 指示「交給你自主處理」：重做 T-0020 那一步（從 legion/T-0019 接續的新戰役）、獨立驗證後把最終分支 fast-forward 合併進 target-repo-b 的 master（僅限 ff、僅限 tests/ 與 telegram_bot.py 的變更、合併後測試全過）
- 排程工作結束必須主動通知使用者（手機推播），不能只寫檔
- 詳見 02_data/verify_20261113.md
## 2026-11-13 深夜：cost_ledger 記錄 effort（雲端 session）
- 帳本新增 effort 欄，舊帳本自動補欄；mock 驗證與角色表一致。130 passed（3 項為雲端環境既有失敗）
- 未驗證：Windows 上全部測試與 start.bat；下次真實戰役後用 ledger 對照 `legion models` 的 effort
