---
id: T-0006
title: 實戰 A：PipeAI_wmt 架構與測試缺口健檢
doc_status: 草稿（AI 產生，未經核可）
version: '0.4'
state: HALT
risk: low
cost_usd: 0.335412
human_touches: 0
approved_by: null
approved_at: null
---

> [!warning] 草稿（AI 產生，未經核可）

# 開發紀錄：實戰 A：PipeAI_wmt 架構與測試缺口健檢（T-0006）

## 1. 文件資訊

| 欄位 | 內容 |
|---|---|
| 編號 | T-0006 |
| 任務 | 實戰 A：PipeAI_wmt 架構與測試缺口健檢 |
| 日期 | 2026-11-11 20:28:38 |
| 版本 | 0.4（step 9） |
| 狀態 | HALT |
| 文件狀態 | 草稿（AI 產生，未經核可） |
| 風險等級 | low |
| 成本（USD，用戶端估算） | 0.3354 |
| 人工介入次數 | 0 |
| 上層任務 | —（深度 0） |

## 2. 目標與範圍

以下引自規格 `specs/T-0006.md`：

> ## T-0006 PipeAI_wmt 架構與測試缺口健檢（唯讀）
>
> ### 目標
> 對 PipeAI_wmt 做唯讀健檢並產出報告（只在對話／回報輸出，不寫入工作目錄）。
>
> ### 範圍
> - 只讀根目錄 `*.py`、`*.sh`、`data.yaml`、`.gitignore`、`03_docs/spec.md`，以及根目錄下可能存在的 `test*`／`tests/`。
> - 不遞迴掃描 `result/`、`annotated_images/`、`dataset/images`、`video/`、`runs/`（檔案量極大，之前根目錄 Glob 已逾時）。只用非遞迴列舉。
> - 不讀 `.env`、金鑰、憑證、`*.pt`。不改、不刪、不安裝、不 push。
>
> ### 報告內容
> 1. **架構**
>    - 各腳本職責：`train_yolov8_local.py`、`all_in_one_processing_bbox_easyocr.py`、`all_in_one_processing_bbox_ocr_cloaud.py`、`inference_video.py`、`save_annotated_images.py`、兩支 `.sh`。
>    - 資料流：影片／影像 → YOLO 偵測 → OCR（距離、管徑字幕）→ CSV 與標註圖。
>    - 相依關係，以及 EasyOCR／PaddleOCR／舊版腳本之間的重複程式碼。
> 2. **測試缺口**
>    - 現有測試清單；若沒有就明說。
>    - 優先補測清單與理由，預計包含：OCR 字幕解析（距離／管徑正則）、CSV 輸出（`utf-8-sig`、檔名格式）、路徑處理、`data.yaml` 結構檢查（nc 與類別、train/val 是否重疊）、標註檔格式。
> 3. **其他風險**
>    - 寫死路徑（Linux 絕對路徑）。
>    - 例外處理（影片開啟失敗、OCR 失敗、GPU OOM）。
>    - 可維護性（重複程式碼、設定散落、舊版腳本尚未移到 `99_bk/`）。
>    - `data.yaml` 已知問題只引用 CLAUDE.md，不下結論。
>
> ### 驗收標準
> - 報告涵蓋上述三大項，每個發現附 `檔案:行號`。
> - 驗證 git 工作目錄在健檢後仍乾淨，沒有任何修改。

## 3. 執行歷程

| # | 狀態 | 開始 | 結束 | 負責角色 | 模型 | agent 耗時（秒） |
|---|---|---|---|---|---|---|
| 1 | INBOX | 2026-11-11 20:28:38 | 2026-11-11 20:28:38 | Runner | — | — |
| 2 | PLAN | 2026-11-11 20:28:38 | 2026-11-11 20:29:18 | 指揮官（planner） | sonnet | 39.9 |
| 3 | SPEC_REVIEW | 2026-11-11 20:29:18 | 2026-11-11 20:29:33 | 規格審查者 | sonnet | 14.8 |
| 4 | PLAN | 2026-11-11 20:29:33 | 2026-11-11 20:30:09 | 指揮官（planner） | sonnet | 35.6 |
| 5 | SPEC_REVIEW | 2026-11-11 20:30:09 | 2026-11-11 20:30:31 | 規格審查者 | sonnet | 21.4 |
| 6 | PLAN | 2026-11-11 20:30:31 | 2026-11-11 20:31:01 | 指揮官（planner） | sonnet | 29.5 |
| 7 | SPEC_REVIEW | 2026-11-11 20:31:01 | 2026-11-11 20:31:30 | 規格審查者 | sonnet | 28.3 |
| 8 | PLAN | 2026-11-11 20:31:30 | 2026-11-11 20:32:08 | 指揮官（planner） | sonnet | 37.8 |
| 9 | SPEC_REVIEW | 2026-11-11 20:32:08 | 2026-11-11 20:32:35 | 規格審查者 | sonnet | 26.4 |
| 10 | HALT | 2026-11-11 20:32:35 | — | Runner | — | — |

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

### 5.1 驗收標準 1：`git status --porcelain`

（尚未執行驗證）

### 5.2 驗收標準 2：`git diff --stat`

（尚未執行驗證）

### 5.3 驗收標準 3：`git log --oneline -n 3`

（尚未執行驗證）

### 5.4 驗收標準 4：`python -m legion.checks report "D:/202611_agent-legion/vault/AI/reports/T-0006-report.md" --section 架構 --section 測試缺口`

（尚未執行驗證）

## 6. 審查紀錄

### 6.1 規格審查

- 第 1 次結論：revise（E-001）
- 發現：矛盾：目標寫「報告以文字產出（不寫檔）」，但驗收指令 `python -m legion.checks report "D:/202611_agent-legion/vault/AI/reports/T-0006-report.md" ...` 檢查的是一個檔案。若不寫檔，這條必然失敗；若要寫檔，就違反「不寫檔」且 readonly 類型。需決定：由 runner／其他角色把文字落地到該路徑並在規格中說明，或移除該指令，或改為允許寫入 vault 報告路徑（明確標示為工作樹外、不算修改）。；驗收指令 `python -m legion.checks ...` 不在規則允許清單（只允許 pytest、git status|diff|log|rev-parse|show）。依規則會被擋或升級風險，須改成允許的指令，或事先取得 runner 對該指令的白名單。；`git diff --exit-code` 只偵測已追蹤檔案的修改，看不到新增的未追蹤檔案；『工作樹沒有任何檔案被修改』應改用 `git status --porcelain`（或 `git status --short`）並要求輸出為空，才能涵蓋新增檔。另外 .gitignore 排除的檔案（如 runs/、*.pt）的變動也偵測不到，需承認這是已知限制。；`git rev-parse --is-inside-work-tree` 只是確認是 git repo，對驗證健檢內容沒有價值，可保留作前置檢查但不算驗收。；驗收標準『每項風險標明檔案與行號』沒有任何指令能驗證；唯一的內容檢查只涵蓋 --section 架構、測試缺口，漏掉『其他風險』一節，且只檢查章節標題存在，不檢查行號引用。建議補 --section 其他風險，並說明是否檢查 `檔名:行號` 格式，否則改由人工審查並寫明。；範圍衝突：報告要交叉對照 CLAUDE.md 的 data.yaml 問題，也要談 `99_bk/` 慣例與 nc 33 vs 18，但範圍只列 `*.py`、`*.sh`、`data.yaml`、`.gitignore`、`03_docs/`，未含 CLAUDE.md。應明列 CLAUDE.md 可讀。另 `99_bk/` 內容、`dataset/labels`（驗證 275 份標註／classes.txt）是否可讀也應說明；『nc 33 對 18』的 18 來自 classes 重編，需允許讀 classes.txt 或只引用 CLAUDE.md。；『現有測試（預期沒有，需確認）』缺少確認方式：應指定 Glob `test*.py`、`tests/`、`pytest.ini` 等，並限定在範圍內；也要注意 pytest 在此專案可能不存在，所以不能用 pytest 當驗收。；含糊：『報告涵蓋』『優先補測清單』沒有數量或格式要求（例如至少 N 項、每項含理由與建議測試層級），審查者難以判斷完成與否。另未指定報告語言（建議繁中）與行號對應的 commit（git HEAD 4a6c383）。；Git 狀態備註：gitStatus 顯示目前分支為 master，而主分支為 main；若驗收以 git diff 比對，需說明基準（HEAD）。可順帶在規格中固定基準 commit。（E-001）
- 處置：退回 PLAN（E-001）

- 第 2 次結論：revise（E-002）
- 發現：驗收指令與交付方式矛盾：規格說報告以對話回覆交付（不寫檔），但第 4 條指令 `python -m legion.checks report ".../T-0006-report.md"` 要檢查 vault 裡的報告檔，該檔按規格不會存在，必定失敗。需二選一：允許寫入該報告檔並在範圍註明例外（vault 在專案外，工作樹仍不變），或刪掉這條指令。；第 4 條指令違反 runner 白名單：只允許 `python -m pytest`、`pytest`、`git status|diff|log|rev-parse|show`，`python -m legion.checks` 不在其中，會被擋或升級風險。要保留須先納入白名單，或改用白名單內的指令。；驗收標準大多無法用指令驗證：「涵蓋三大項」「每個發現附 檔案:行號」「未觸碰大型資料夾」「未安裝任何東西」都沒有對應指令，需補人工檢核項，或改成 runner 能檢查的產物。；工作樹無修改的檢查不夠嚴：`git diff --quiet` 只看已追蹤檔案的未暫存變更，抓不到未追蹤的新檔；`git status --short` 只輸出內容、不判成敗。建議改用 `git status --porcelain` 並明訂輸出必須為空，另可加 `git diff --cached --quiet` 涵蓋已暫存變更。；`git rev-parse --is-inside-work-tree` 只是前置檢查，沒有驗證任何目標，不應算進覆蓋度。；範圍有小缺口：「初步 glob 未找到 test*.py」只是前提，未說明是否再確認 tests/ 目錄、pytest.ini、conftest.py；根目錄 *.py 未說明是否排除 99_bk/；.sh 與 data.yaml 的行號引用方式未寫明。；建議在規格註明「只回報、不改」，以與 CLAUDE.md 的 data.yaml 規定一致（改之前須先跟使用者確認）。本任務只讀不改，不衝突。（E-002）
- 處置：退回 PLAN（E-002）

- 第 3 次結論：revise（E-003）
- 發現：第三條驗收指令 `python -m legion.checks ...` 違反 runner 白名單（只允許 pytest 與 git status|diff|log|rev-parse|show），會被擋或升級風險。；報告交付方式自相矛盾：目標寫「只以回覆文字交付、不改任何檔案」，驗收卻檢查專案外的 D:/202611_agent-legion/vault/AI/reports/T-0006-report.md，且沒人被指定去寫該檔。請明確授權寫入該路徑並列為唯一例外，或改成純回覆文字、由 runner／人工驗收。；`git diff --quiet` 驗不出「沒有任何檔案被修改」：它只看 tracked 且未暫存的變更，看不到 untracked 新檔、被 .gitignore 排除的目錄（result/、runs/、*.pt）與已暫存變更。建議改用 `git status --porcelain`（要求輸出為空），再加 `git diff --quiet HEAD`。；`git rev-parse --verify HEAD` 沒有比對 4a6c383，只要 repo 存在就會成功。可改為 `git rev-parse --verify 4a6c383` 加 `git diff --quiet 4a6c383 HEAD`，或讓 runner 比對輸出字串。；「每個發現都附 檔案:行號」沒有任何指令能驗證；且 legion.checks 只檢查「架構」「測試缺口」兩區段，漏掉第三大項「其他風險」。請補 `--section 其他風險`，並加上行號格式檢查，例如 regex `\S+\.(py|sh|yaml):\d+`。；「不安裝東西、不做網路寫入」沒有對應的驗收，應在規格中註明由 runner 以程式強制。；範圍矛盾：要比對 nc 與標註實際用到的 class id，卻限制 dataset/labels 只能抽樣，抽樣無法證明 15–32 以外沒有其他 id。解法：允許用 Get-ChildItem 或單次統計腳本全量掃描 275 個小標註檔，或讓報告只能寫「抽樣範圍內」的結論。；「已知現況」缺少可驗證的前提：99_bk/ 是否存在、inference_video.py 在根目錄還是 99_bk/ 都未確認。請加前置步驟用 Glob 確認，不存在時在報告中註明。；小問題：目前分支是 master，CLAUDE.md 的主分支是 main。建議在規格註明這是預期狀態，或把「分支不變」也列入驗收。（E-003）
- 處置：退回 PLAN（E-003）

- 第 4 次結論：revise（E-004）
- 發現：驗收指令違反 runner 規則：第 4 條 `python -m legion.checks report ...` 不在允許清單（僅 pytest、python -m pytest、git status|diff|log|rev-parse|show），會被擋，驗收無法通過。請改用清單內指令，或先讓 runner 將該檢查加入白名單。；輸出位置自相矛盾：規格說報告只在對話／回報輸出、不寫入工作目錄，驗收卻檢查檔案 D:/202611_agent-legion/vault/AI/reports/T-0006-report.md。規格沒說誰寫這個檔案，且任務類型是 readonly。請二選一：報告只在對話輸出（驗收不檢查檔案），或明確授權由 runner 寫入 vault 並在範圍中註明。；驗收無法驗證實質目標：「每個發現附 檔案:行號」沒有任何指令檢查；「涵蓋三大項」只檢查『架構』『測試缺口』兩個 section，漏了『其他風險』。建議把這些列為 reviewer 人工驗收項，並明列章節標題與引用格式。；git 驗收有冗餘與缺口：`git log --oneline -n 3` 不驗證任何東西，建議改用 `git rev-parse HEAD` 並在任務前記錄基準 commit 供比對；`git status --porcelain` 看不到被 .gitignore 排除的目錄（result/、runs/ 等）的變動，規格要註明此限制可接受。；範圍有小缺漏：沒說 03_docs/spec.md 或 test* 不存在時如何處理（建議在報告中明說不存在）；沒說明非遞迴列舉的具體方式，前次根目錄 Glob 逾時的風險沒有緩解辦法；目前分支是 master，CLAUDE.md 寫主分支為 main，基準 commit 要明確。；「預計包含」的補測清單預設了答案（正則、utf-8-sig、data.yaml 檢查等），容易變成對照打勾。請改為依實際讀到的程式碼判斷，並要求每項附程式碼證據。（E-004）
- 處置：退回 PLAN（E-004）

### 6.2 交付審查

（尚未進行）

## 7. 問題與教訓

- 重試次數：4
- HALT 原因：retry_exceeded: 規格審查退回（3 次重試後仍失敗）

## 8. 附錄：證據清冊

| 證據編號 | 檔名 | SHA-256 | 產生時間 | 產生者 |
|---|---|---|---|---|
| E-001 | evidence/E-001_spec_review.json | dbad516cd2f83f7c909d2b0b11ca26c32cdc2d2a0a293657a6c9cd5c88f2c908 | 2026-11-11 20:29:33 | runner（記錄 spec_review session e1277e7f-5e71-4f2b-8065-638a92e9c330） |
| E-002 | evidence/E-002_spec_review.json | b2d22b6ea9d2632169664e1df89f1c5f0ead253ad4bd6333e15023e454756097 | 2026-11-11 20:30:31 | runner（記錄 spec_review session 6a8f66fb-163a-4fcc-b646-54dd727e32b2） |
| E-003 | evidence/E-003_spec_review.json | 910c401a8ed5b5e62f65607879cd06f3357758c78d01dd2221d9d405546e4b96 | 2026-11-11 20:31:30 | runner（記錄 spec_review session 15143d20-6005-47e7-b9cf-872c9adf8cd1） |
| E-004 | evidence/E-004_spec_review.json | f4accf208e9709acd37e3bbf17a10c3c9e6dd83890826afc44ef11d6a4b497a5 | 2026-11-11 20:32:35 | runner（記錄 spec_review session 18827f17-6275-4dc6-9f09-3c0164ec718e） |
