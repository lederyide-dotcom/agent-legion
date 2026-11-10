---
id: T-0002
title: demo：清掉舊的測試檔
doc_status: 草稿（AI 產生，未經核可）
version: '0.4'
state: HALT
risk: high
cost_usd: 0.194787
human_touches: 1
approved_by: null
approved_at: null
---

> [!warning] 草稿（AI 產生，未經核可）

# 開發紀錄：demo：清掉舊的測試檔（T-0002）

## 1. 文件資訊

| 欄位 | 內容 |
|---|---|
| 編號 | T-0002 |
| 任務 | demo：清掉舊的測試檔 |
| 日期 | 2026-11-11 01:39:14 |
| 版本 | 0.4（step 9） |
| 狀態 | HALT |
| 文件狀態 | 草稿（AI 產生，未經核可） |
| 風險等級 | high |
| 成本（USD，用戶端估算） | 0.1948 |
| 人工介入次數 | 1 |
| 上層任務 | —（深度 0） |

## 2. 目標與範圍

以下引自規格 `specs/T-0002.md`：

> ## 目標
> 清除工作目錄中舊的測試檔 `test_calc.py`。
>
> ## 現況
> - 檔案：`calc.py`（僅有 `add`）、`test_calc.py`（測 `add` 與 `multiply`）。
> - `test_calc.py` 從 `calc` 匯入 `multiply`，但 `calc.py` 沒有這個函式，所以該檔目前一執行就會 ImportError。
>
> ## 範圍
> - 只刪除 `test_calc.py`。
> - 不改 `calc.py`、`.gitignore` 與 `.git`。
> - 不 push、不 merge、不安裝任何東西。
>
> ## 驗收標準
> 1. 工作目錄中不再有 `test_calc.py`。`git status --short` 應顯示 ` D test_calc.py`。
> 2. `calc.py` 沒有被改動，`git diff --stat` 只列出 `test_calc.py`。
> 3. 驗收指令只能用白名單，無法直接斷言「檔案不存在」。上述兩點由人工或 runner 對照指令輸出確認。
>
> ## 風險備註
> 動作含刪除，我提議 high，需人工核准後才執行。

風險判定理由（程式判定）：

- high: 動作 delete

## 3. 執行歷程

| # | 狀態 | 開始 | 結束 | 負責角色 | 模型 | agent 耗時（秒） |
|---|---|---|---|---|---|---|
| 1 | INBOX | 2026-11-11 01:39:14 | 2026-11-11 01:39:14 | Runner | — | — |
| 2 | PLAN | 2026-11-11 01:39:14 | 2026-11-11 01:39:37 | 指揮官（planner） | sonnet | 12.7 |
| 3 | SPEC_REVIEW | 2026-11-11 01:39:37 | 2026-11-11 01:40:49 | 規格審查者 | sonnet | 19.2 |
| 4 | PLAN | 2026-11-11 01:40:49 | 2026-11-11 01:41:37 | 指揮官（planner） | sonnet | 14.1 |
| 5 | SPEC_REVIEW | 2026-11-11 01:41:37 | 2026-11-11 01:42:33 | 規格審查者 | sonnet | 19.7 |
| 6 | PLAN | 2026-11-11 01:42:33 | 2026-11-11 01:44:07 | 指揮官（planner） | sonnet | 14.7 |
| 7 | SPEC_REVIEW | 2026-11-11 01:44:07 | 2026-11-11 01:44:29 | 規格審查者 | sonnet | 13.8 |
| 8 | PLAN | 2026-11-11 01:44:29 | 2026-11-11 01:45:59 | 指揮官（planner） | sonnet | 15.4 |
| 9 | SPEC_REVIEW | 2026-11-11 01:45:59 | 2026-11-11 07:41:20 | 規格審查者 | — | — |
| 10 | HALT | 2026-11-11 07:41:20 | — | Runner | — | — |

## 4. 設計與變更說明

### 4.1 流程圖（Mermaid）

```mermaid
flowchart LR
    INBOX([INBOX]) --> PLAN([PLAN])
    PLAN([PLAN]) -->|4 次| SPEC_REVIEW([SPEC_REVIEW])
    SPEC_REVIEW([SPEC_REVIEW]) -->|3 次| PLAN([PLAN])
    SPEC_REVIEW([SPEC_REVIEW]) --> HALT([HALT])
```

### 4.3 變更檔案與 diff 統計

（尚無）

## 5. 驗證證據

### 5.1 驗收標準 1：`git status --short`

（尚未執行驗證）

### 5.2 驗收標準 2：`git diff --stat`

（尚未執行驗證）

## 6. 審查紀錄

### 6.1 規格審查

- 第 1 次結論：revise（E-001）
- 發現：有一項驗收標準沒有對應指令:「刪除可由 git 還原(檔案在 d724fcd)」目前沒有任何指令驗證。建議加上 `git rev-parse d724fcd:test_calc.py`(在白名單內,可確認 blob 存在),或 `git show --stat d724fcd`。；`git diff --stat -- calc.py` 的輸出是空的,容易誤判:空輸出代表未修改,但也可能是指令或路徑寫錯。請在規格中寫明預期輸出為空。`git status --short` 的預期輸出也應寫成只有一行刪除紀錄(` D test_calc.py`),這樣才能同時證明 .gitignore 與其他檔案沒被動。；刪除的狀態有歧義:「git status 顯示為刪除」沒說是未暫存(` D`)還是已暫存(`D `)。規格應指定其一或兩者都接受,並寫明刪除後不 commit,只留在工作樹。；規則與任務互相衝突:runner 規則寫「不得…刪除檔案」,但任務本身就是刪除。規格只用風險備註帶過,沒說明誰、用什麼方式執行刪除。建議註明這是經人工確認後的例外,否則 runner 可能直接擋掉,任務無法完成。；缺少前置檢查(次要):規格宣稱 calc.py 沒有 multiply、test_multiply 會失敗,但驗收沒有確認這一點,也沒確認執行前 git status 是乾淨的。可加一次 `git status --short` 作為執行前基準。（E-001）
- 處置：退回 PLAN（E-001）

- 第 2 次結論：revise（E-002）
- 發現：驗收指令無法驗證目標：`git diff --quiet HEAD -- calc.py` 只檢查 calc.py，即使 test_calc.py 沒被刪也會通過；`git status --short` 永遠 exit 0，runner 沒有斷言依據。兩者合起來無法證明第 1 點（已刪除）與第 3 點（沒有其他檔案被改動）。；建議補上可程式判定的檢查：`git diff --name-status HEAD`，預期輸出恰為 `D\ttest_calc.py`（runner 需比對輸出內容）；或 `git diff --quiet HEAD -- . :(exclude)test_calc.py`，非 test_calc.py 的路徑無變動時 exit 0。也可在驗收標準註明 `git status --short` 應恰為 ` D test_calc.py`，且沒有其他行（含 untracked）。；前提未確認：規格假設 test_calc.py 已被 git 追蹤。若是 untracked，刪除後 git status 不會顯示 deleted，第 1 點不成立。「import 不存在的 multiply」只是背景說明，建議執行前先驗證（例如 `git show HEAD:calc.py`）。；規則衝突已知但處理不夠明確：執行規則禁止刪除檔案而任務本身就是刪除，備註已走 WAIT_HUMAN 合理，但建議寫清楚人工核准後以哪個動作執行刪除（如 `git rm test_calc.py` 或直接刪檔），且核准前不得動手。；範圍（只刪一個檔、不 push/merge/install）與 high 風險判定清楚合理，無問題。（E-002）
- 處置：退回 PLAN（E-002）

- 第 3 次結論：revise（E-003）
- 發現：驗收指令 `git status --short` 只會輸出文字，不論結果如何 exit code 皆為 0，無法機械化驗證「test_calc.py 已被刪除」（驗收標準 2 實質上未被驗證）。建議改用能以結果判定的指令，例如 `git ls-files --deleted`（需符合白名單 git 子命令的話則不行）；在白名單內可改為 `git diff --name-status --diff-filter=D` 並明定期望輸出為 `D\ttest_calc.py`，或要求 runner 比對 stdout 與期望字串。；驗收標準 2 假設 test_calc.py 已被 git 追蹤（` D` 表示已追蹤且工作樹刪除）。repo 內 test_calc.py 確實存在，但規格沒有先確認它是 tracked；建議加入前置檢查（如 `git ls-files test_calc.py`），避免若為 untracked/ignored 時狀態不是 ` D`。；驗收指令沒有涵蓋「範圍」中的限制：未驗證 .gitignore 未被修改，也未驗證沒有其他檔案被動到。建議加 `git diff --exit-code --diff-filter=M` （不限路徑，檢查無任何已修改檔）或 `git status --short` 結果須只含 ` D test_calc.py` 一行。；驗收標準 1 的 `--diff-filter=M -- calc.py` 可行但意義較弱；`git diff --exit-code -- calc.py .gitignore` 更直接涵蓋兩個不得修改的檔案。；規則衝突需明講：runner 規則「不得刪除檔案」與本任務目標（刪除 test_calc.py）矛盾。規格雖標 high/WAIT_HUMAN，但未說明刪除如何被授權執行（由人工批准後 runner 放行，或由人手動刪除）。建議明確寫出執行主體與批准流程。；未驗證目標本身的根因（ImportError）已消除，例如沒有留下其他引用 test_calc.py 的設定；以目前 repo 內容（僅 .gitignore、calc.py、test_calc.py）風險低，可接受，但可補一條 `python -m pytest --collect-only` 預期無 ImportError 的驗證。（E-003）
- 處置：退回 PLAN（E-003）

### 6.2 交付審查

（尚未進行）

## 7. 問題與教訓

- 重試次數：3
- HALT 原因：operator_cancel: demo 想法檔被正式 tick 誤領取，停止以免繼續花費

## 8. 附錄：證據清冊

| 證據編號 | 檔名 | SHA-256 | 產生時間 | 產生者 |
|---|---|---|---|---|
| E-001 | evidence/E-001_spec_review.json | c2a481907c61c86b7d6dc66e1d32bb3f02a0cf40f5c1da861292f7cfa8378aba | 2026-11-11 01:40:49 | runner（記錄 spec_review session bd659a16-bae9-4318-bda3-34a73f7cdc7c） |
| E-002 | evidence/E-002_spec_review.json | b070b6d19bf5ec639497e97108a833de176e4fb3b8f6057940522c957081da03 | 2026-11-11 01:42:33 | runner（記錄 spec_review session 943bbe41-b67a-43c4-b079-94e23e6fcba5） |
| E-003 | evidence/E-003_spec_review.json | 47591e99f83a0641b9ae4c9eb3563b027a50c9c63361291f9b66c087d483972c | 2026-11-11 01:44:29 | runner（記錄 spec_review session 75a87471-fd6e-4dc7-873d-791971e677f7） |
