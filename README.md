# agent-legion — 人掌舵、AI 自主執行的開發閉環

把一句想法丟進 Obsidian 的 `vault/INBOX/`，agent-legion 就會讓 Claude 分工完成**規劃 → 規格審查 → 風險判定 → 執行 → 驗證 → 交付審查 → 紀錄**，需要人決定的事才停下來問。

設計原則：**判斷交給 LLM（怎麼拆、怎麼做），邊界交給程式（能不能做、花多少、何時停）。** agent 的自述一律不採信，驗收指令由 runner 親自執行，證據以 SHA-256 鎖定。

```
INBOX → PLAN → SPEC_REVIEW → GATE → EXEC → VERIFY → REVIEW → LEARN → DONE
                 │退回 PLAN      │        └─失敗→EXEC（重試≤3）       └─後續想法→inbox_hold（人放行）
                 │               └─ high：WAIT_HUMAN（不阻塞其他任務）
任一狀態：超過預算／重試／逾時，或 vault/STOP 存在 → HALT
```

| 角色 | 由誰擔任 | 權限 |
|---|---|---|
| 指揮官（規劃、執行） | Claude（`claude -p`，每次全新 session） | 規劃唯讀；執行只能改自己的 git worktree |
| 規格審查者、交付審查者 | Claude 全新 session | 唯讀 |
| 書記官 | Claude 全新 session | 只寫敘述，不能改證據 |
| 風險閘、驗證、熔斷、帳本 | runner（Python 程式） | 程式規則，不經 LLM |

## 環境需求

| 項目 | 用途 | 備註 |
|---|---|---|
| Windows 10/11 + PowerShell 5.1 | 主要開發環境 | 程式本身跨平台，啟動腳本為 `.bat`／`.ps1` |
| Python 3.10 | runner | 以 `py -3.10` 建立 `.venv` |
| Docker Desktop | PostgreSQL 16 | 只綁 `127.0.0.1` |
| Claude Code CLI（`claude`） | 真實 agent | 需已登入；只跑 mock 時不需要 |
| Node.js | Mermaid 轉圖（`tools/mermaid`） | 選用；失敗時任務不會中斷 |
| Edge 或 Chrome | Mermaid 轉圖用的瀏覽器 | 自動偵測，或設 `LEGION_BROWSER` |
| LibreOffice | 紀錄文件轉 PDF | 選用；自動偵測，或設 `LEGION_SOFFICE` |
| Obsidian | 看 vault 儀表與紀錄 | 選用 |

## 快速開始

```bat
git clone <this repo>
cd agent-legion
scripts\start.bat
```

`start.bat` 會依序：啟動 DB → 建立 `.venv` 並安裝套件（第一次）→ 建表 → 建 vault 骨架 → 跑一次**零成本**的 mock demo（3 個任務＋1 個回灌，示範正常完成、高風險攔下、回灌）。完成後用 Obsidian 開啟 `vault/` 資料夾。

## 設定

所有路徑都是**相對於專案根目錄**，或由環境變數覆寫，程式裡沒有寫死個人環境的路徑。可設定的變數與預設值見 [.env.example](.env.example)。

PowerShell 中臨時覆寫的例子：

```powershell
$env:LEGION_DB_PORT = "55433"
$env:LEGION_BROWSER = "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

主要變數：

| 變數 | 預設 | 說明 |
|---|---|---|
| `LEGION_DB_USER`／`PASSWORD`／`NAME`／`PORT` | `legion`／`legion_local_only`／`legion`／`55432` | 本機開發用 DB，docker-compose 也讀同一組 |
| `LEGION_SCHEMA` | `legion` | 正式資料的 schema；demo 用 `demo`，測試用隨機 schema |
| `LEGION_VAULT`、`LEGION_DATA_DIR`、`LEGION_OUTPUT_DIR`、`LEGION_WORKTREES` | `./vault`、`./02_data`、`./01_output`、`./.worktrees` | 目錄位置 |
| `LEGION_BACKEND`、`LEGION_MODEL` | `claude`、CLI 預設 | agent backend 與模型 |
| `LEGION_SOFFICE`、`LEGION_BROWSER` | 自動偵測 | 外部工具位置 |

熔斷數值（單任務 $2、每日 $2、重試 3、逾時 900 秒、回灌每輪 2／深度 2）在 [src/legion/config.py](src/legion/config.py)，`tick` 也可用 `--task-budget`、`--daily-budget` 暫時覆寫。

## 使用方式

指令一律在專案根目錄執行。下表的 `legion` 代表 `.venv\Scripts\python.exe -m legion`；部分 Windows 環境的應用程式控制原則會擋 `.venv\Scripts\legion.exe`，用 `python -m` 形式即可。

### 1. 丟一個任務

在 `vault/INBOX/` 新增一個 `.md`，一個檔案一個任務：

```markdown
---
title: 為 downloader 加上重試
kind: write            # write＝可改檔（只在 worktree 內）；readonly＝只產報告
repo: ../my-project    # 目標 repo 的本機路徑（相對或絕對）
subdir: src            # 選填：限縮在子目錄
---
下載失敗最多重試 3 次、間隔 2 秒，補 pytest 並全部通過。
```

完成條件最好能用 `pytest` 或 `git` 指令驗證，runner 會親自執行。唯讀任務的報告寫到 `vault/AI/reports/<任務編號>-report.md`，報告中的 `檔名:行號` 會被程式逐筆核對。

### 2. 讓它跑

| 動作 | 指令 |
|---|---|
| 推進一輪（每輪每個任務走一步） | `legion tick --backend claude --model sonnet` |
| 看狀態 | `legion status` |
| 定時自動跑（每 10 分鐘） | `powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1`（加 `-Unregister` 移除） |

AI 只在 `.worktrees/<任務編號>/` 的獨立副本裡改檔，**原 repo 不會被動到，也不會自動 merge**。

### 3. 它停下來等你時

| 狀態 | 意思 | 處理 |
|---|---|---|
| `WAIT_HUMAN` | 高風險動作（刪檔、改 `.claude/`、需人工核准的安裝等） | 讀 `vault/AI/questions/<任務編號>.md`，再 `legion answer <任務編號> approve` 或 `reject` |
| `HALT` | 熔斷（超預算、超重試、逾時、STOP 檔） | 排除原因後 `legion resume <任務編號>`，或 `legion cancel <任務編號> --reason "原因"` |

緊急全部停止：建立 `vault/STOP` 檔（內容不限）。

### 4. 做完之後

| 需求 | 指令或位置 |
|---|---|
| 看改了什麼 | `.worktrees/<任務編號>` 的分支，確認後自行 merge |
| 看開發紀錄文件（8 章，結論都引用證據編號） | `vault/AI/records/<任務編號>/record.md` |
| 核可紀錄文件 | `legion approve-doc <任務編號>` |
| 匯出 Word／PDF（存到 `01_output/`） | `legion export <任務編號> --format docx` 或 `--format pdf` |
| 週報 | `legion report` |
| 後續想法 | 預設暫存在 `vault/AI/inbox_hold/`；要做就把檔案移回 `vault/INBOX/`。`tick --auto-followups` 可改為自動領取 |

### 5. 零成本驗證

```bat
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m legion demo --mock
```

pytest 需要 DB 已啟動（`start.bat` 或 `docker compose up -d db`）。

## 安全邊界（程式強制）

- **風險只升不降**：agent 只能提議風險，最終取「規則判定」與「提議」的較高者；執行後再依實際 diff 重新判定。
- **角色工具最小化**：唯讀角色只拿得到 `Read`、`Glob`、`Grep`；執行者的 Bash 有允許與拒絕清單（安裝、push、merge、`.env`、金鑰一律拒絕）。
- **runner 才是硬邊界**：Bash 規則不是安全邊界，所以驗收指令由 runner 以白名單親自執行、比對 worktree 以外的 git 狀態、證據設為唯讀並比對雜湊。
- **原生 Windows 沒有 sandbox**：Claude Code 內建 sandbox 不支援原生 Windows，worktree 只隔離檔案。要給更高自主權的任務，請放在 WSL2 或容器裡執行。
- **安裝分級**：只在執行階段，由 runner 分成自動／自動＋通知／必須問，全部寫入 `02_data/install_ledger.csv`。
- **花費帳本**：每次 agent 呼叫都寫入 `02_data/cost_ledger.csv`（不隨 DB 重建消失），每日預算以帳本與 DB 較大者判定。
- **不留本機逐字紀錄**：`claude -p` 加上 `--no-session-persistence`；提示全文只存在本機 `.legion_tmp/prompts/`（不進 git），vault 只留雜湊。

## 專案結構

```
src/legion/      runner.py（狀態機）、agents.py（Claude CLI／Mock、角色權限）、prompts.py、risk.py、
                 installs.py、ledger.py、db.py、vault.py、evidence.py、record.py、checks.py、export.py、
                 demo.py、config.py、cli.py
tests/           pytest 驗收（需 DB）
scripts/         start.bat、wait_db.ps1、register_schedule.ps1、verify_artifacts.py、smoke_claude.ps1
sandbox_repo/    給 agent 練習用的玩具專案
tools/mermaid/   Mermaid 轉圖工具（npm）
vault/           Obsidian vault 骨架；任務紀錄在執行時產生，不進版控
02_data/         驗收證據、metrics、花費帳本、安裝清冊
03_docs/         spec.md（v0.4）、spec_v0.5.md、progress.md（進度與事故紀錄）
reports/         研究報告
```

## 已知限制

- 排程只測過「使用者登入時執行」模式；電腦關機或 Claude 未登入時不會動。
- 花費是 Claude CLI 回報的用戶端估算（`total_cost_usd`），不是帳單金額。
- 規格審查與交付審查目前都用 Claude；跨廠商審查者（Codex）尚未實作。
- 開發過程中的事故與修正都記在 [03_docs/progress.md](03_docs/progress.md)。
