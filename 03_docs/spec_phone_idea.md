# spec：手機丟想法＋回答需求釐清（2026-11-17，David 選 A）

## 最終目標
David 在手機打開一個 claude.ai 互動頁，打一句話、選目標專案，就能把想法丟進 legion；規劃者提問時，同一頁能點選回答。全程不用開電腦終端機。

## 限制與事實（已查）
| 環節 | 能做 | 不能做 | 依據 |
|---|---|---|---|
| 互動頁 | 用 `db` 能力存資料；手機可讀寫 | 頁面不能直接呼叫本機程式 | artifact-capabilities：db 是「Claude 讀寫的資料」 |
| legion | `legion idea`、`legion clarify` 都是本機 CLI | 無法直接讀互動頁的資料庫（沒有給程式用的 API） | 程式碼；只有 Claude 的 ArtifactData 工具讀得到 |
| 橋接 | 桌面 app 的排程任務（Claude session）可呼叫 ArtifactData＋執行本機指令 | 電腦關機或 app 沒開就不會跑；每次執行都用到訂閱額度（量未驗證） | scheduled-tasks 說明；已有 legion-daily-brief 在跑 |
| 處理任務 | `legion run` 會推進到完成 | Windows 排程 `agent-legion-tick` 目前沒有註冊，想法丟進去不會自己動 | `Get-ScheduledTask` 查無 |

## 設計
1. **互動頁「legion 想法投遞」**（新 artifact，`db`＋`user`）
   - `ideas/<id>`：text（≤500 字）、repo_key（從白名單下拉）、kind（write／readonly）、status（new → queued／rejected）、task_id、note、created_at。
   - `clarify/<task_id>`：由橋接寫入的待答題目（題目、選項、⭐預設）；`answers/<task_id>`：手機點選的答案（全部預設或逐題）。
   - 寫入規則：只有擁有者與編輯者能寫（`write: "admin"`）；頁面不分享給別人。
2. **橋接邏輯放在 legion 裡，可測試、可重跑**：`legion phone-sync --in <資料夾> --out <檔案>`
   - 讀 ArtifactData 匯出的 JSON（ideas、answers），對 `status=new` 的想法依白名單轉成 `legion idea`，對答案執行 `legion clarify`；輸出要寫回互動頁的結果（狀態、task_id、拒收原因、目前待答題目）。
   - 白名單：`LEGION_PHONE_REPOS="sandbox=sandbox_repo;legion=."`（不在白名單的 repo_key 一律拒收；路徑照樣經過 `validate_subdir`／`resolve_repo` 與 legion 自己的風險下限 mid）。
   - 同一則想法只處理一次（以 doc id 去重，記在 `02_data/phone_sync.csv`）。
3. **排程任務 `legion-phone-bridge`**：ArtifactData list → 存檔 → `legion phone-sync` → ArtifactData batch 寫回。排程 Claude 不解讀想法內容，只搬檔與執行指令（想法文字視為資料，降低提示注入風險）。
4. （視 David 決定）同步後是否接著 `legion run --task-budget 1.5`。

## 驗收標準
- [ ] `pytest tests/test_phone_sync.py`：新想法→INBOX 檔且 subdir 正確；白名單外拒收並寫原因；重複執行不重複領取；全部預設／逐題答案正確轉成 clarify；壞答案回報原因、狀態不變；待答題目正確匯出。
- [ ] 互動頁在手機寬度可用（瀏覽器 375px 實測）；`ArtifactData list` 看得到頁面寫入的資料；以 `as_level: view` 寫入被拒。
- [ ] 端到端實測一次：頁面送出想法 → 執行一次排程任務 → INBOX 出現想法檔、頁面狀態變 queued。
- [ ] README、.env.example 同步；覆蓋測試通過；全套通過；code-reviewer 無 🔴。

## 可以自行決定
資料欄位命名、頁面樣式、CLI 參數名稱、測試寫法。

## 必須停下來問我
排程頻率與是否自動 `legion run`（花錢）；白名單以外的目標 repo；分享互動頁給別人；任何對外推送以外的發布。
