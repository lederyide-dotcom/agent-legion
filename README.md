# 202611_agent-legion — AI Agents 自主指揮軍團閉環 PoC v0.4

David 只把一句想法丟進 `vault/INBOX/`，系統自己規劃、審查、執行、驗證、沉澱，並把後續任務回灌 INBOX。
判斷交給 LLM（怎麼拆、怎麼做），邊界交給程式（能不能做、花多少、何時停）。

```
INBOX → PLAN → SPEC_REVIEW → GATE → EXEC → VERIFY → REVIEW → LEARN → DONE
                 │退回 PLAN      │        └─失敗→EXEC（重試≤3）
                 │               └─ high：WAIT_HUMAN（不阻塞其他任務）
任一狀態：超預算／超重試／逾時／STOP 檔存在 → HALT
```

## 快速開始
```bat
scripts\start.bat
```
啟動 DB（Docker，埠 55432）→ 建表 → 建 vault 骨架 → 跑 mock demo（零成本）。用 Obsidian 開 `vault/`。

## 日常操作
| 動作 | 指令 |
|---|---|
| 丟想法 | 在 `vault/INBOX/` 新增一個 `.md`（可選 frontmatter：`title`、`kind: readonly\|write`、`repo`、`subdir`） |
| 跑一輪 | `.venv\Scripts\python.exe -m legion tick --backend claude --model sonnet` |
| 看狀態 | `.venv\Scripts\python.exe -m legion status` |
| 回答高風險問卷 | `.venv\Scripts\python.exe -m legion answer <id> approve\|reject` |
| HALT 後續跑 | `.venv\Scripts\python.exe -m legion resume <id>` |
| 核可紀錄文件 | `.venv\Scripts\python.exe -m legion approve-doc <id>` |
| 週報 | `.venv\Scripts\python.exe -m legion report` |
| 匯出正式文件 | `.venv\Scripts\python.exe -m legion export <id> --format docx\|pdf`（存到 `01_output/`） |
| 全系統停止 | 建立 `vault/STOP` 檔 |
| 排程（每 10 分鐘） | `powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1`（`-Unregister` 移除） |

## 結構
```
src/legion/   runner.py（狀態機）、agents.py（ClaudeCliAgent／MockAgent、角色工具權限）、risk.py、installs.py、
              db.py、vault.py、evidence.py、record.py、checks.py、export.py、demo.py、cli.py
tests/        pytest 驗收（需 DB 啟動）
vault/        Obsidian vault（INBOX、STOP、AI/）
sandbox_repo/ 實戰 B 用玩具專案
scripts/      start.bat、wait_db.ps1、register_schedule.ps1、verify_artifacts.py、smoke_claude.ps1
02_data/      驗收證據、metrics、安裝清冊
03_docs/      spec.md、progress.md
```

## 安全邊界（程式強制）
- 風險分級：agent 只能提議，最終 = max(規則, 提議)。
- 角色工具：唯讀角色只給 `Read,Glob,Grep`；executor 的 Bash 有 allow／deny 清單（安裝、push、merge、`.env` 一律 deny）。
  官方文件明言 Bash 規則不是安全邊界，因此硬邊界由 runner 承擔：VERIFY 親自執行驗收指令、比對 worktree 外的 git 狀態、證據唯讀並比對雜湊。
- 安裝：只在 EXEC，由 runner 分級（自動／自動＋通知／必須問），全部寫入 `02_data/install_ledger.csv`。
- 熔斷：單任務預算、每日預算、重試 3、單次呼叫逾時、回灌每輪 2、回灌深度 2。

## 已知限制
- 電腦關機或 Claude 未登入時排程不會動；排程只測過「使用者登入時執行」模式。
- `total_cost_usd` 是用戶端估算。
- Codex 審查者 backend：本機未安裝，一律退回 Claude 全新 session。
