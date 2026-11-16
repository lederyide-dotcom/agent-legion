# spec：想法入口＋需求釐清（2026-11-15，David 選 A）

## 最終目標
使用者隨口丟一句想法，legion 就能產生完善的計畫：想法不清楚時先問 2～4 題（每題有選項與預設答案，手機上點選即可），使用者沒空回答時採用預設答案繼續。之後照原本的閉環執行。

## 範圍
1. `legion idea "一句話" [--repo 路徑] [--kind write|readonly]`：在 vault/INBOX 寫出想法檔。目標 repo 依序取 `--repo`、`LEGION_DEFAULT_REPO`、目前所在的 git repo；都沒有就報錯並說明怎麼指定（不再進到 runner 才熔斷 `no_repo`）。
2. 規劃者輸出新增選填欄位 `questions`：想法缺少關鍵資訊時，最多 4 題，每題 2～4 個選項並指定預設；規格仍依預設答案寫出。
3. runner：規劃者有提問、且這個任務還沒問過時，停在 WAIT_HUMAN，等待原因「需求釐清待回答」，問題寫到 vault/AI/questions（手機文件庫看得到）。
   - `legion clarify <任務> --defaults`：採用預設答案，直接進規格審查（不重新規劃、不多花錢）。
   - `legion clarify <任務> 1=B 2=A`：有任何答案不是預設，就帶著答案回到規劃重寫；第二次規劃不再發問。
   - 使用者閒置超過 `LEGION_CLARIFY_IDLE_MINUTES`（預設 15 分鐘）：自動採用預設答案。
   - `LEGION_CLARIFY=0` 關閉整個釐清關卡。
4. 不新增狀態、不改 Task 欄位（存在 meta），沿用 WAIT_HUMAN。改狀態清單與 Task 欄位屬「必須停下來問」。

## 驗收標準（可自動驗證）
- `pytest tests/test_clarify.py`：
  - 有提問 → WAIT_HUMAN、等待原因「需求釐清待回答」、執行者 0 次、questions 筆記存在。
  - 採用預設 → 進規格審查並完成，規劃者只被呼叫 1 次。
  - 有非預設答案 → 規劃者被呼叫 2 次，第 2 次的提示含答案，第 2 次不再停下發問。
  - 閒置超時 → 自動採用預設並完成；未超時 → 繼續等。
  - `LEGION_CLARIFY=0` → 不停下。
  - 答案格式錯（題號不存在、選項不存在）→ 報錯、狀態不變。
- `pytest tests/test_idea.py`：寫出的想法檔可被領取；repo 推斷順序正確；沒有 repo 時回傳 1 並說明。
- `legion bench` 新增「clarify」題（9 題全符合）。
- README、`.env.example`、流程圖（diagrams.py）同步；全套測試通過。

## 可以自行決定
選項與預設的資料格式、CLI 參數細節、問題筆記的版面、評測題目設計。

## 必須停下來問
新增狀態或 Task 欄位；真實 Claude 試跑（花錢）；改預設模型或風險規則。
