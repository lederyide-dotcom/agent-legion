# spec：AI Agents 自主指揮軍團閉環 v0.4 — 精簡 Runner＋指揮官＋Vault＋開發紀錄文件
版本：v0.4｜日期：2026-11-11｜repo：202611_agent-legion（暫定，新建）
取代：v0.1（自建完整狀態機、逐案人工核准）、v0.2（未含開發紀錄文件）、v0.3（安裝一律須問）
本 spec 的安全安裝政策同樣適用於 Claude Code 開發本專案的過程。

## 最終目標（為什麼做）
給 David 自用，並作為向主管展示的 PoC：David 只把一句想法丟進 INBOX，系統自己規劃、審查、執行、驗證、沉澱，並把後續任務回灌 INBOX。
成功樣貌：一張低風險任務從 INBOX 到結案，David 的人工介入次數為 0；高風險動作一定停下來等他；全程可在 Obsidian 讀到紀錄與儀表。

## 本次任務
1. **Vault 骨架**（Obsidian 可直接開，進 git）：
   ```
   vault/
   ├─ INBOX/              David 丟想法（一個 .md 一個想法）
   ├─ STOP                存在即全系統停止（Kill Switch）
   └─ AI/                 agent 與 runner 可寫區
      ├─ tasks/<id>.md    任務筆記（frontmatter：state、risk、cost_usd、verdict、human_touches）
      ├─ specs/ handoffs/ lessons/ questions/ reports/
      ├─ records/<id>/    開發紀錄文件（record.md、assets/、evidence/）
      ├─ 儀表.base         依 state、risk、成本彙總
      └─ 流程.canvas       閉環流程圖
   ```
2. **Runner**（Python、asyncio，跑 Windows 主機）：`legion tick` 執行一輪，每個任務前進一步；可重入、可中斷續跑。
3. **PostgreSQL**（Docker Compose）：`tasks`、`task_events`（稽核）、`agent_runs`（成本、耗時、session_id）。
4. **閉環狀態**：
   ```
   INBOX → PLAN → SPEC_REVIEW → GATE → EXEC → VERIFY → REVIEW → LEARN → DONE
                     │退回 PLAN      │        └─失敗→EXEC（重試≤3）
                     │               └─ high：WAIT_HUMAN（不阻塞其他任務）
   任一狀態：超預算／超重試／逾時／STOP 檔存在 → HALT
   ```
   | 狀態 | 誰做 | 產出 |
   |---|---|---|
   | PLAN | 指揮官（握有脈絡的 session） | specs/<id>.md、風險等級、驗收指令清單（結構化輸出） |
   | SPEC_REVIEW | 規格審查者（全新 session，唯讀） | verdict＋findings |
   | GATE | Runner（程式） | low 放行；mid 放行並記通知；high 寫 questions/<id>.md 後等 David |
   | EXEC | 指揮官（可自行派子代理），cwd＝該任務的 git worktree | 程式變更或報告 |
   | VERIFY | **Runner 親自執行**驗收指令，不採信 agent 自述 | 證據檔 |
   | REVIEW | 交付審查者（全新 session，唯讀，看 diff 與證據） | verdict＋findings |
   | LEARN | 書記官 | lessons/<id>.md、handoffs/<id>.md、最多 2 個後續想法寫回 INBOX |
5. **風險分級規則**（程式判定，agent 只能提議、不能降級）：
   - high：動到 worktree 以外的路徑、刪除、對外網路寫入、發訊、涉及 `.env`、不符合「安全安裝政策」的安裝。
   - mid：會合併到主分支、修改 CLAUDE.md 或 skill。
   - low：唯讀分析、worktree 內的變更與測試。
6. **熔斷**：單任務預算、每日預算、重試上限 3、單次呼叫逾時、每輪 LEARN 回灌上限 2、回灌深度上限 2（防自我增生）。
7. **人工介入計數**：任何需要 David 操作的事件（approve、回答問卷、手動改狀態）記入 `human_touches`。
8. **匯出**：每次狀態變更後 runner 重寫 `AI/tasks/<id>.md`；`legion report` 產出 `AI/reports/weekly-<日期>.md`。
9. **排程**：提供 Windows 工作排程器的註冊腳本，每 10 分鐘（暫定）跑一次 `legion tick`。
10. **AgentBackend**：`ClaudeCliAgent`（`claude -p`）與 `MockAgent`（零成本測試）。審查者 backend 可設定為 `codex`，未安裝時退回 Claude 的全新 session。
11. **兩個實戰任務**（真實 agent）：
    - A（唯讀）：對目標 repo 做架構與測試缺口健檢。
    - B（可寫）：在本 repo 內建的 `sandbox_repo/`（玩具專案）新增一個小功能並通過其測試。

12. **圖文並茂的開發紀錄文件**（每張任務一份，結案時自動產生）：
    - 位置：`vault/AI/records/<id>/record.md`，圖檔與證據放同資料夾的 `assets/`、`evidence/`；Obsidian 可直接閱讀。
    - 固定章節：
      1. 文件資訊（編號、任務、日期、版本、狀態、風險等級、成本、人工介入次數）
      2. 目標與範圍（引自 spec）
      3. 執行歷程（時間軸：每個狀態的起訖、負責角色、模型、耗時）
      4. 設計與變更說明（架構圖、資料流圖用 Mermaid；變更檔案清單與 diff 統計）
      5. 驗證證據（每條驗收標準一小節：指令、結果、證據圖、原始檔連結）
      6. 審查紀錄（規格審查與交付審查的結論、發現、處置）
      7. 問題與教訓
      8. 附錄：證據清冊（證據編號、檔名、SHA-256、產生時間、產生者）
    - **敘述與證據分離**：證據（指令輸出、測試結果、圖表、截圖、diff 統計）一律由 runner 以程式產生並編號（E-001…）；書記官只寫敘述，且每個結論必須引用證據編號。書記官不得自行產生或改寫證據。
    - **圖的來源**（依任務類型自動選用）：
      | 類型 | 做法 |
      |---|---|
      | 終端輸出 | 把驗收指令的實際輸出渲染成圖（保留原始文字檔） |
      | 數據 | 由 `02_data` 的 CSV 以程式畫圖（成本、耗時、測試結果） |
      | 流程與架構 | Mermaid（Obsidian 原生顯示；匯出時轉成圖） |
      | 畫面截圖 | 任務有 Web 介面時，以無頭瀏覽器對指定網址截圖 |
    - **正式文件匯出**：`legion export <id> --format docx|pdf` 產出含封面、目錄、章節編號、圖表編號與圖說、頁碼的文件，存到 `01_output/`。
    - **狀態標示**：自動產生的文件一律標「草稿（AI 產生，未經核可）」；`legion approve-doc <id>` 後才改為「已核可」並記錄核可人與時間。核可計入 `human_touches`，但不影響任務本身的自主性指標。
    - 過程中即時累積：每次狀態變更就追加執行歷程與新證據，不是結案才一次回想。

13. **安全安裝政策**（開發所需工具可自主安裝；由 runner 以程式判定等級，agent 不能自行認定安全）：
    | 等級 | 範圍 | 處理 |
    |---|---|---|
    | 自動 | 專案層級：venv 內的 pip／uv、專案內的 npm、官方 Docker image；來源為官方 registry（PyPI、npm、Docker Hub 官方或已驗證發行者） | 直接安裝，寫入安裝清冊 |
    | 自動＋通知 | 使用者層級、不需管理員權限的工具，來源為 winget 官方來源或工具官方發行頁（例如 pandoc、無頭瀏覽器執行檔） | 安裝並在週報列出，可事後移除 |
    | 必須問 | 需要管理員權限或 UAC；修改系統設定、全域 PATH、登錄檔、驅動程式、防火牆；付費或需要帳號授權；MCP server、plugin、skill、hook；`curl … | sh` 這類直接執行遠端腳本；來源不是上述官方管道 | 寫問卷等 David |
    - 共同規則：
      - 版本一律鎖定並寫入 lockfile；不得使用未指定版本的安裝。
      - 套件名稱必須逐字出自該工具的官方文件或既有 lockfile，不得憑印象拼寫（防仿冒套件）。
      - 安裝前後記錄到 `02_data/install_ledger.csv`：時間、任務、工具、版本、來源、等級、安裝指令、移除指令、授權條款。
      - 授權條款非開放原始碼或無法判定時，升為「必須問」。
      - 單一任務安裝數量上限 10（暫定），超過轉人工。
      - 安裝只能發生在 EXEC 狀態；審查者與書記官的 session 沒有安裝權。
    - MCP、plugin、skill、hook 維持必須問的理由：它們會改變 agent 自己的行為與權限，等於改寫軍團的指揮規則，不屬於一般開發工具。

### 呼叫 claude CLI（已查官方文件，2026-11-10）
- `claude -p --output-format json`：讀 `result`、`session_id`、`total_cost_usd`。
- 結構化輸出：`--json-schema`，讀 `structured_output`（可能不存在，要檢查）。
- 唯讀角色：`--allowedTools "Read,Glob,Grep" --permission-mode dontAsk`。
- EXEC：`--permission-mode acceptEdits`，Bash 只放行白名單指令（測試、git 的唯讀與 commit 類）。
- 無人值守：`--permission-prompts none`（需 v2.1.259 以上）；單次預算 `--max-budget-usd`。
- 不用 `--bare`（需要 API key，等於新增付費項目）；不用 `--continue`／`--resume`（審查者必須是新 session）。

## 不在範圍內
- 第三方 skill（pstack、mattpocock、EGM、obsidian-skills）的安裝與整合：由 David 手動完成，本輪驗收不得依賴它們。指揮官 prompt 留一個可設定的「前置指令」欄位，之後填入 `/poteto-mode` 之類即可。
- GitHub Issues 當黑板、LINE 通知、知識與營運指揮官、哨兵事件觸發。
- 真正的作業系統層級沙箱（Docker／WSL2 內不限制工具）：v0.3。本輪以 worktree＋工具白名單限縮。
- 合併到主分支的自動化（本輪最多做到在 worktree 內 commit）。
- Web UI。

## 驗收標準（必須能自動驗證）
- [ ] DB 可啟動：`docker compose up -d db` 後 30 秒內 healthy。
- [ ] 完整閉環（mock）：pytest 驗證低風險任務 INBOX→DONE，`human_touches == 0`，`task_events` 每次轉移一筆。
- [ ] 回灌成立：pytest 驗證 LEARN 產生的後續想法出現在 `vault/INBOX/`，下一輪 tick 被領取，且 `parent_id` 正確。
- [ ] 回灌有上限：pytest 驗證單輪超過 2 個、或深度超過 2 的回灌被丟棄並記錄。
- [ ] 高風險必停：pytest 驗證 high 任務停在 WAIT_HUMAN、產生 questions 檔、`human_touches` 在回答後為 1；同時另一張 low 任務照常前進。
- [ ] 風險不可降級：pytest 驗證 agent 回報 low 但規則判定 high 時，以 high 為準。
- [ ] VERIFY 不採信自述：pytest 讓 mock agent 宣稱通過但驗收指令實際失敗，任務退回 EXEC。
- [ ] 重試、預算、逾時、STOP 檔：pytest 各一案，皆進入 HALT 且 halt_reason 有值。
- [ ] 審查獨立：pytest 驗證 SPEC_REVIEW、REVIEW 的 session_id 與 PLAN、EXEC 的不同。
- [ ] 可中斷續跑：pytest 在任一狀態中途殺掉 runner，重跑 `legion tick` 後任務從原狀態繼續，不重複扣預算。
- [ ] Vault 匯出：pytest 驗證 `AI/tasks/<id>.md` 的 frontmatter 可解析且與 DB 一致；`儀表.base`、`流程.canvas` 為合法檔案。
- [ ] 紀錄文件完整：pytest 驗證結案任務的 `record.md` 具備 8 個固定章節，且每條驗收標準在第 5 章都有對應小節。
- [ ] 證據可追溯：腳本檢查 `record.md` 內每個證據編號都存在於證據清冊、對應檔案存在且 SHA-256 相符；每張圖都有圖號與圖說；結果寫入 `02_data/record_check.csv`。
- [ ] 敘述不得無憑據：腳本檢查第 5、6 章每個結論段落至少引用一個證據編號，違反者列出並使測試失敗。
- [ ] 證據不可被 agent 改寫：pytest 驗證書記官 session 對 `evidence/` 沒有寫入權，且 LEARN 前後證據檔雜湊不變。
- [ ] 圖確實產生：mock demo 的紀錄文件至少含 1 張終端輸出圖、1 張數據圖、1 張 Mermaid 圖，圖檔可開啟且非空白（檢查尺寸與像素變異）。
- [ ] 正式文件匯出：`legion export <id> --format docx` 與 `--format pdf` 產出檔案，含目錄與圖片；以程式讀回驗證章節數與圖片數，寫入 `02_data/export_check.csv`。
- [ ] 文件狀態：pytest 驗證未核可文件帶「草稿」標示，`approve-doc` 後才變更並留下核可紀錄。
- [ ] 安裝分級正確：pytest 以表列案例驗證分級器（venv 內 pip → 自動；winget 官方來源的使用者層級工具 → 自動＋通知；需管理員、遠端腳本直執、MCP／plugin／skill、非官方來源、未鎖版本 → 必須問）。
- [ ] 安裝清冊：pytest 驗證每次安裝都在 `02_data/install_ledger.csv` 留下完整欄位，且含可執行的移除指令。
- [ ] 安裝不逾越：pytest 驗證審查者與書記官 session 的工具白名單不含任何安裝指令；單任務超過安裝上限時轉 WAIT_HUMAN。
- [ ] mock 端到端：`python -m legion demo --mock` 跑完三張任務（low、high、會回灌的），結果寫入 `02_data/metrics.csv`（含每張的 human_touches、cost、耗時）。
- [ ] 實戰 A（唯讀）：跑到 DONE；目標 repo 執行前後 `git status --porcelain` 與 `git rev-parse HEAD` 相同，寫入 `02_data/readonly_check.txt`。
- [ ] 實戰 B（可寫）：跑到 DONE；`sandbox_repo` 的測試通過；worktree 以外沒有任何檔案被修改（以 git 狀態比對），寫入 `02_data/sandbox_check.txt`。
- [ ] 自主性指標：兩個實戰任務的 `human_touches` 皆為 0，寫入 `02_data/autonomy.csv`。
- [ ] 所有測試通過：`pytest -q`
- [ ] 一鍵啟動可用：`scripts\start.bat`（啟動 DB、建表、建 vault 骨架、跑 mock demo）。

## 可以自行決定
- 套件選擇、檔案結構、各角色 prompt 內容、JSON Schema 細節。
- tick 的排程方式與鎖機制、逾時秒數（暫定單次 15 分鐘）。
- `sandbox_repo` 的內容與實戰 B 的題目（越小越好）。
- 任務筆記的版面、Bases 的檢視設計、Canvas 的排版。
- Bash 白名單的具體規則寫法（先確認語法）。
- 紀錄文件的版面、圖表樣式、終端輸出轉圖與 docx／pdf 匯出所用的 Python 套件（優先用已安裝的工具，見 pc-dev-env-win）。

## 必須停下來問我
- 目標 repo 的實際路徑（實戰 A 用）。
- 兩個實戰任務合計超過 5 美元（暫定），或需要重跑。
- 任何 worktree 與 `vault/AI/` 以外的寫入。
- 放寬風險規則、提高回灌上限、或移除任一熔斷。
- 讀取 `.env`、金鑰、憑證；新增付費服務或 API key；安裝 MCP、plugin、skill、hook。
- 任何落在安全安裝政策「必須問」等級的安裝。
- 改動狀態清單或 Task 既有欄位的定義。
- 要套用公司正式文件範本、文件編號規則或頁首頁尾（請先向我索取範本）。
- 截圖會拍到 worktree 以外的畫面，或畫面含客戶資料。

## 環境與限制
- Windows 原生；runner 跑主機，只有 PostgreSQL 在 Docker。
- 本輪不用本機模型，與 8GB VRAM 無關。
- Claude Pro 額度有限：開發與測試一律 MockAgent，真實呼叫只在兩個實戰任務。
- `total_cost_usd` 是用戶端估算，只作熔斷與比較用。
- 電腦關機或 Claude 未登入時排程不會動；這是已知限制。

## 已知背景
- 上位規劃：專案文件 `agent-legion-closed-loop-plan.md`、`agent-legion-skill-reference.md`。
- 設計決定：判斷交給 LLM（怎麼拆、派給誰），邊界交給程式（能不能做、花多少、何時停）。
- 設計決定：人不當傳送帶——取消逐案核准，改為風險分級；VERIFY 由程式執行。
- 開工時請先確認（未查證）：
  1. 本機 `claude --version` 是否達到所需版本。
  2. Bash 工具白名單與 `.env` 拒絕讀取的規則語法。
  3. `claude -p` 在 Windows 排程（無互動桌面）下能否使用訂閱登入。
  4. Codex CLI 的非互動唯讀呼叫方式（若要啟用跨廠牌審查）。
- 參考：https://code.claude.com/docs/en/headless
