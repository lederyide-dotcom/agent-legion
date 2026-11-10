# 開工前未查證事項確認（2026-11-11）

| # | 事項 | 結論 | 證據 |
|---|---|---|---|
| 1 | `claude --version` 是否 ≥ 2.1.259（`--permission-prompts none` 需求） | ✅ `2.1.319 (Claude Code)` | 指令 `claude --version` |
| 2 | Bash 白名單與 `.env` 拒讀語法 | ✅ 語法已依官方文件確認並實測 deny 生效；⚠️ 白名單不是硬邊界（見下） | 官方 docs permissions 頁；實測輸出 `.legion_tmp/smoke/out.json` |
| 3 | `claude -p` 在 Windows 排程下能否用訂閱登入 | ✅ 可以（限「使用者登入時執行」模式）；「不論登入與否」模式未測（需存 Windows 密碼，依 David 同意範圍不測） | `scripts/smoke_claude.ps1`：exit=0、6.9 秒 |
| 4 | Codex CLI 非互動唯讀呼叫 | 本機未安裝（`Get-Command codex` 無結果）→ 審查者一律退回 Claude 全新 session（spec 允許）；codex 呼叫語法未驗證，程式內不猜 | `Get-Command codex` |

## 事項 2 細節（官方文件 code.claude.com/docs/en/permissions）
- 評估順序：deny → ask → allow，第一個命中者決定；allow 無法在 deny 中開例外。
- Bash 前綴：`Bash(git status *)` 與 `Bash(git status:*)` 等價；尾端 ` *` 也匹配不帶參數的指令。
- 複合指令：`&&`、`||`、`;`、`|`、`&`、換行會被拆開，每個子指令都要被允許；deny 只要任一子指令命中就擋。
- `.env`：`Read(.env)` 與 `Read(**/.env)` 等價（gitignore 語意，任意深度）；`Read(**/.env.*)` 擋變體。
- 文件明言 Bash deny 規則「isn't a security boundary」（`/bin/rm`、`bash -c` 等變形可繞過）。

## 實測（工作排程器，使用者層級、Interactive logon、RunLevel Limited；跑完即 Unregister）
參數：`--tools Read,Glob,Grep,Bash --allowedTools "Read,Glob,Grep,Bash(git status *)" --permission-mode dontAsk --permission-prompts none --setting-sources project --strict-mcp-config --settings <deny 規則> --model haiku --max-budget-usd 0.05 --output-format json --json-schema <schema>`

| 檢查 | 結果 |
|---|---|
| 訂閱登入 | ✅ `subtype=success`、`is_error=false` |
| JSON 欄位 | ✅ 有 `result`、`session_id`、`total_cost_usd`、`structured_output`、`permission_denials` |
| deny 規則（canary 檔 `Read(**/canary_secret.txt)`） | ✅ 被擋，出現在 `permission_denials`，內容未外洩 |
| 白名單外 Bash（`whoami`） | ⚠️ **仍被執行**：`whoami` 屬內建唯讀指令，dontAsk 下自動放行，不受 allow 清單限制 |
| 花費 | $0.0020（client 估算） |

### 為什麼用 canary 檔而不是假 `.env`
David 的全域 PreToolUse hook（guard.py）會擋任何路徑含 `.env` 的工具呼叫，包括建立假檔。為了不繞過 hook，改用 canary 檔驗證 deny 機制；`.env` 規則語法與 canary 規則同一機制，`Read(**/.env)` 已一併放在設定中。

## 對設計的影響
1. 唯讀角色（規格審查、交付審查、書記官、PLAN）**不給 Bash**：`--tools Read,Glob,Grep`，從工具層移除，不靠 allow 清單。
2. EXEC 給 Bash，但 deny 安裝類（pip、npm、uv、winget、choco、scoop、curl、Invoke-WebRequest…）與 `*.env*`；並在文件中註明 Bash 規則非硬邊界，硬邊界由 runner 的事後檢查（worktree 外 git 狀態比對、VERIFY 親自執行）承擔。
3. `--setting-sources project` + `--strict-mcp-config`：不載入 David 的使用者層 plugin、hook、MCP，避免影響 agent 行為。
