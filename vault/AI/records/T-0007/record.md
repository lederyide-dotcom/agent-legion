---
id: T-0007
title: 實戰 A（重跑）：PipeAI_wmt 架構與測試缺口健檢
doc_status: 草稿（AI 產生，未經核可）
version: '0.4'
state: HALT
risk: low
cost_usd: 0.420086
human_touches: 0
approved_by: null
approved_at: null
---

> [!warning] 草稿（AI 產生，未經核可）

# 開發紀錄：實戰 A（重跑）：PipeAI_wmt 架構與測試缺口健檢（T-0007）

## 1. 文件資訊

| 欄位 | 內容 |
|---|---|
| 編號 | T-0007 |
| 任務 | 實戰 A（重跑）：PipeAI_wmt 架構與測試缺口健檢 |
| 日期 | 2026-11-11 20:37:22 |
| 版本 | 0.4（step 9） |
| 狀態 | HALT |
| 文件狀態 | 草稿（AI 產生，未經核可） |
| 風險等級 | low |
| 成本（USD，用戶端估算） | 0.4201 |
| 人工介入次數 | 0 |
| 上層任務 | —（深度 0） |

## 2. 目標與範圍

以下引自規格 `specs/T-0007.md`：

> # T-0007 PipeAI_wmt 架構與測試缺口健檢（唯讀）
>
> ## 目標
> 對 D:\PipeAI_wmt 做唯讀健檢，報告全文放在結構化輸出 `report_md`（由 runner 寫到 vault，執行者自己不寫檔）。
>
> ## 範圍（已由審查者核對存在）
> - 根目錄 5 支 .py：train_yolov8_local.py、all_in_one_processing_bbox_easyocr.py、all_in_one_processing_bbox_ocr_cloaud.py、inference_video.py、save_annotated_images.py
> - 根目錄 2 支 .sh：run_choice_no_docker.sh、Auto_run_no_docker.sh
> - data.yaml、CLAUDE.md、03_docs/spec.md、99_bk/ 的 2 支舊版
> - HEAD 4a6c383
>
> ## 探索規則
> - 禁止 `**/` 與任何遞迴 Glob。Glob 只用非遞迴的 `*` 形式。
> - 不得掃描、列出或讀取 `result/`、`annotated_images/`、`dataset/`、`runs/`、`video/`。不得讀 `.env`、金鑰、憑證。
> - 測試盤點只做以下非遞迴 Glob：
>   - 根目錄：`test*.py`、`*_test.py`、`conftest.py`、`pytest.ini`、`pyproject.toml`、`setup.cfg`、`tox.ini`
>   - `03_docs/*`
>   - `99_bk/*`
>   - 不得用根目錄 `*.{py,sh,yaml,md}` 的 Glob，因為它會連帶列出 `runs\detect\*\args.yaml`。
> - 讀檔順序：先 5 支 .py，再 .sh、data.yaml，最後 03_docs/spec.md 與 99_bk。
> - 99_bk 與現行版本只用 Grep/Read 對照，至少比對三個面向：
>   1. OCR 初始化與使用方式
>   2. CSV 欄位與編碼
>   3. 路徑與模型載入
> - 執行者不得寫入任何檔案，包括 scratchpad 以外的位置。不得安裝、執行腳本、跑 pytest 或載入模型。
>
> ## 預算
> - 可用預算 $2.19。累計花費達 $1.50 就停止讀新檔，改為撰寫報告。
> - 報告開頭必須有「未讀完／因預算略過」段落，列出沒讀完的檔案。若全部讀完，要明寫「無」。
>
> ## 報告必須包含的章節
> 標題必須是「## 架構」「## 測試缺口」「## 其他風險」，runner 會檢查前兩個。
>
> ### 架構
> - 每支腳本的職責。
> - 資料流：影像／影片 → YOLO 偵測 → OCR → CSV／標註圖，可用文字圖表示。
> - 腳本間相依關係，以及重複程式碼（EasyOCR 版與 PaddleOCR 版的差異、與 99_bk 的差異）。
>
> ### 測試缺口
> - 現有測試盤點。若沒有，要明說無，並列出所 Glob 的模式。
> - 優先補測清單，每項包含：測什麼、理由、「可否不依賴 GPU／模型」欄位（是／否＋原因）。
>
> ### 其他風險
> - 寫死路徑、例外處理、可維護性。
>
> ## 具體檢查點（缺一則退回）
> - 實際寫死 Linux 路徑的檔案與行號，涵蓋 data.yaml 與 .sh 腳本，及 .py 內有寫死路徑者。
> - data.yaml：`nc: 33` 與 train/val 指向同一資料夾，兩點都要寫出，並附行號。
> - 例外處理：列出裸 `except`、吞例外、缺少檢查檔案是否存在的位置，附行號。
> - CSV：檔名是否符合 `detection_results_YYYYMMDD_HHMMSS.csv`、是否用 `utf-8-sig`，逐支腳本回報。
> - 每個發現附 `檔名:行號`，總數至少 15 筆。篇幅以內容完整為準，不靠灌水。
>
> ## 驗收標準
> 1. 目標 repo 的 `git rev-parse HEAD` 執行前後同為 4a6c383。
> 2. `git status --porcelain` 為空。這個判定依賴 .gitignore 已排除大目錄，所以它對被 ignore 的檔案（runs/、*.pt 等）沒有保護力。此類保護靠上面的「不得寫入任何檔案」規則和人工審查。
> 3. runner 自動附加 `python -m legion.checks report` 來檢查報告存在、章節齊全、長度足夠。規劃者不列入 accept_cmds。
> 4. 交付審查者人工核對上面的檢查點與行號是否真實。

## 3. 執行歷程

| # | 狀態 | 開始 | 結束 | 負責角色 | 模型 | agent 耗時（秒） |
|---|---|---|---|---|---|---|
| 1 | INBOX | 2026-11-11 20:37:22 | 2026-11-11 20:37:22 | Runner | — | — |
| 2 | PLAN | 2026-11-11 20:37:22 | 2026-11-11 20:38:07 | 指揮官（planner） | sonnet | 44.9 |
| 3 | SPEC_REVIEW | 2026-11-11 20:38:07 | 2026-11-11 20:38:23 | 規格審查者 | sonnet | 15.0 |
| 4 | PLAN | 2026-11-11 20:38:23 | 2026-11-11 20:38:53 | 指揮官（planner） | sonnet | 29.4 |
| 5 | SPEC_REVIEW | 2026-11-11 20:38:53 | 2026-11-11 20:39:26 | 規格審查者 | sonnet | 33.0 |
| 6 | PLAN | 2026-11-11 20:39:26 | 2026-11-11 20:39:49 | 指揮官（planner） | sonnet | 22.1 |
| 7 | SPEC_REVIEW | 2026-11-11 20:39:49 | 2026-11-11 20:40:14 | 規格審查者 | sonnet | 24.6 |
| 8 | PLAN | 2026-11-11 20:40:14 | 2026-11-11 20:40:36 | 指揮官（planner） | sonnet | 21.8 |
| 9 | SPEC_REVIEW | 2026-11-11 20:40:36 | 2026-11-11 20:41:06 | 規格審查者 | sonnet | 29.8 |
| 10 | HALT | 2026-11-11 20:41:06 | — | Runner | — | — |

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

### 5.1 驗收標準 1：`git rev-parse HEAD`

（尚未執行驗證）

### 5.2 驗收標準 2：`git diff --exit-code`

（尚未執行驗證）

### 5.3 驗收標準 3：`python -m legion.checks report "D:/202611_agent-legion/vault/AI/reports/T-0007-report.md" --section 架構 --section 測試缺口`

（尚未執行驗證）

## 6. 審查紀錄

### 6.1 規格審查

- 第 1 次結論：revise（E-001）
- 發現：驗收指令列表自相矛盾：列出的第三條 `python -m legion.checks report ...` 與下方「runner 自動附加、規劃者不用自己寫」重複。請從規格的驗收指令欄移除，或明確註明只是示意，避免重複執行或白名單判定歧義。；`git status --porcelain` 與 `git rev-parse HEAD` 只是單次輸出，沒有「執行前後比對」的基準。規格需寫明預期值（例如 status 輸出為空），或說明 runner 負責前後比對，否則這兩條無法單獨驗證「沒改檔」。目前 gitStatus 為 clean，可直接寫「預期空輸出」。；「每個發現都附 檔案:行號」只靠人工審查，沒有任何機器可檢查的下限。建議在 checks 加上可驗證項（例如報告中符合 `\w+\.(py|sh|yaml):\d+` 的樣式至少 N 筆），或接受此項為人工驗收並在驗收標準標明未自動化。；章節檢查只驗「架構」「測試缺口」。「其他風險」「建議優先順序」是必備章節卻沒被 runner 檢查，可加 `--section 其他風險 --section 建議優先順序`，或說明為何不強制。；範圍與工具限制有矛盾：要求「找檔案時用限定在根目錄的非遞迴列舉」，但可用工具只有 Glob/Grep/Read，Glob 不保證非遞迴。請明確指示用 `Glob pattern="*.py"`（不含 `**`、路徑限根目錄）這類具體寫法；並說明只有 Read/Grep 時如何確認 `tests/` 是否存在（例如 Glob `tests/*`、`test_*.py`、`pytest.ini`）。同時 Grep 必須指定 path 與 glob，禁止對根目錄無限制遞迴搜尋，否則仍會進入 `result/`。；範圍清單含 `99_bk/*.py`、`03_docs/spec.md`，但沒說這些路徑不存在時如何處理（CLAUDE.md 只說舊版會移到 99_bk，不保證已存在）。應規定缺檔時在報告中註明「不存在」而非失敗。；報告長度要求（「長度足夠」）沒有具體門檻，無法判斷 checks 通過條件；請寫明最低字元／行數，讓執行者可自我檢查。；預算只剩約 $2.44，但範圍涵蓋 6 支腳本加舊版備份的全文閱讀與行號引用。建議規定大檔用 Grep 先定位、Read 用 offset/limit，並設定超出預算時的降級策略（例如優先讀主流程兩支腳本）。；「報告中沒有修改任何檔案的建議被實際執行」措辭含糊，且無對應驗收手段；實際可驗證的是 git 狀態不變。建議改為與 git 檢查綁定，或刪除。（E-001）
- 處置：退回 PLAN（E-001）

- 第 2 次結論：revise（E-002）
- 發現：範圍數字自相矛盾:寫「根目錄 6 支 .py」,但只列 5 支,後文又寫「實測 5 支」。請改成 5 支,避免執行者找不存在的檔案或湊數。；驗收指令與說明衝突:第 4 點與「報告交付」段都說 `python -m legion.checks report ...` 由 runner 自動附加、不列在 accept_cmds,但驗收指令陣列又列了它。請擇一(移除陣列中的項目,或刪掉「不列」的說法),避免重複執行或被當成規劃者自加的指令。；git 三條指令不能單獨證明「沒有修改」:`git status --porcelain` 的 exit code 永遠是 0,「輸出必須為空」沒寫進通過條件;`git diff --exit-code` 看不到未追蹤的新檔;`git log -1 --format=%h` 沒寫預期值 `4a6c383`。請明寫每條的通過條件(status 輸出為空、log 輸出為 4a6c383),並說明實際判定靠 runner 前後比對,這三條只是輔助。；驗收標準 1(至少 6000 字元、120 行)沒有明確的自動化覆蓋:不確定 `legion.checks report` 的預設門檻是否與規格一致。請確認門檻相符,或註明由人工驗收。；驗收標準 2(至少 15 筆 `檔名:行號`)只靠人工驗收,可以接受。但請要求行號必須來自 Grep -n 或 Read 的實際輸出,不得憑記憶或推測,以免捏造行號。；預算數字不一致:規格寫剩約 $2.38,環境顯示剩 $2.34;「已用約 70%」也沒說基準總額。請改用絕對值,例如「已花費約 $1.60 即停止讀新檔」。；探索規則大致可行,但有兩個缺口:一是 data.yaml 與 .sh 的 Grep 要指定單一檔案路徑,規則沒明寫;二是 99_bk 差異比對沒說明用什麼工具,請限定為 Grep/Read 對照,或寫明唯讀下允許的指令。；「上一輪規劃的 Glob 已誤列出 dataset/labels」屬歷史背景,對執行者沒有操作價值。建議刪掉,只保留「不得 Glob dataset/labels」。（E-002）
- 處置：退回 PLAN（E-002）

- 第 3 次結論：revise（E-003）
- 發現：已核對：範圍內的檔案都存在。根目錄有 5 支 .py、2 支 .sh、data.yaml、CLAUDE.md；03_docs/spec.md 存在；99_bk/ 恰好 2 支舊版。HEAD 4a6c383 與 git 狀態和規格一致。範圍本身沒問題。；必修（矛盾）：驗收標準 4 與「報告交付」都說 `legion.checks report` 由 runner 自動附加、規劃者不列入 accept_cmds。但「驗收指令」JSON 第 4 項又把它列進去了。請擇一：從 JSON 移除，或刪掉「不列入」的說法。否則 runner 可能重複執行，或在白名單比對時出問題。；必修（探索規則自相矛盾）：測試盤點寫「Glob 根目錄與子目錄 test*.py、*_test.py…」，但探索規則又禁止遞迴 Glob，也不准掃 runs/、dataset/ 等。請明確寫成對 `*` 的非遞迴 Glob：根目錄 `test*.py`、`*_test.py`、`conftest.py`、`pytest.ini`，以及 `03_docs/*`、`99_bk/*`。並註明不要使用 `**/`。我已確認根目錄 `*.{py,sh,yaml,md}` 的 Glob 會連帶列出 runs\detect\*\args.yaml，所以遞迴範圍很容易失控。；建議補強：`git status --porcelain` 輸出須為空，是靠 .gitignore 排除了大目錄才成立。HEAD 是 4a6c383、工作樹乾淨，所以目前可行。但規格應註明這項判定依賴 .gitignore。另外 `git diff --exit-code` 加上 git status 對被 ignore 的檔案（例如 runs/、*.pt）完全沒有保護力。建議在規則裡明說執行者不得寫入任何檔案，包括 scratchpad 以外的位置。；建議補強（驗收可驗證性）：「至少 15 筆 檔名:行號」與「至少 6000 字元／120 行」都只靠人工。可行，但很容易被空洞內容灌水。請明列必須涵蓋的項目作為具體檢查點，例如：寫死 Linux 路徑的實際檔案與行號、data.yaml 的 nc:33 與 train/val 相同這兩點、每個優先補測項目都要有「可否不依賴 GPU／模型」欄位。；建議補強（預算）：規格寫約 $1.60 就停止讀新檔，而可用預算是 $2.23。這樣合理，因為留了撰寫報告的餘裕。但「約」不明確，請改成明確的停讀條件，並要求報告開頭註明哪些檔案因預算沒讀完，避免默默漏掉。；小問題：「99_bk 與現行版本差異只用 Grep/Read 對照」可行，但沒有指定比對哪些面向，例如 OCR 初始化、CSV 欄位、路徑。請至少列出 2–3 個要比對的面向，以免報告泛泛而談。（E-003）
- 處置：退回 PLAN（E-003）

- 第 4 次結論：revise（E-004）
- 發現：Grep 沒有被限制：規格只禁遞迴 Glob，但 Grep 預設遞迴，對根目錄 Grep 會掃進 result/（約150萬檔）、annotated_images/、dataset/、runs/，與「不得掃描」衝突。請明定 Grep 的 path 只能是範圍內單一檔案或 99_bk/，不得以根目錄為 path。；寫入規則自相矛盾：「不得寫入任何檔案，包括 scratchpad 以外的位置」可讀成 scratchpad 內可寫。請改成單一明確說法（例如完全不寫檔，scratchpad 也不寫）。；預算數字不一致：規格寫 $2.19，執行環境上限為 $2.14。另外「累計花費達 $1.50 就停止」執行者未必拿得到累計花費，請對齊數字，並改成可操作的條件（例如最多讀幾支檔案）。；`git rev-parse HEAD` 只印雜湊，不會判定是否等於 4a6c383。請寫清通過條件是輸出以 4a6c383 開頭，並由 runner 比對前後值。；`git status --porcelain` 沒列入 accept_cmds，只靠 runner 比對；`git diff --exit-code` 抓不到未追蹤的新檔案。若 runner 比對不是強制的，請把 git status --porcelain 加進 accept_cmds。；讀檔順序漏了 CLAUDE.md：範圍列了它，但順序沒提。請補上位置，或說明只作背景參考。；「缺一則退回」的檢查點與預算耗盡有衝突：對所有 .py 要求列出寫死路徑，但某支腳本可能沒有，或因預算沒讀完。請改成逐支列出（沒有就寫無），未讀完的檔案可豁免。；legion.checks 只檢查「架構」「測試缺口」兩節，「其他風險」與 15 筆發現下限只靠人工審查。規格已說明，可接受；若要機器可驗，可考慮加 --section 其他風險。（E-004）
- 處置：退回 PLAN（E-004）

### 6.2 交付審查

（尚未進行）

## 7. 問題與教訓

- 重試次數：4
- HALT 原因：retry_exceeded: 規格審查退回（3 次重試後仍失敗）

## 8. 附錄：證據清冊

| 證據編號 | 檔名 | SHA-256 | 產生時間 | 產生者 |
|---|---|---|---|---|
| E-001 | evidence/E-001_spec_review.json | 72d9a2c45d1c66217560ca08e39779a9b342c5db10d93dcfa0d4743f51b9ac77 | 2026-11-11 20:38:23 | runner（記錄 spec_review session 93465b74-eda4-4e97-8c34-c24a31818f32） |
| E-002 | evidence/E-002_spec_review.json | b054f029e643b1f1eef80645539a375a2c28e78fd11ad1fdae5383b317543b0c | 2026-11-11 20:39:26 | runner（記錄 spec_review session bd3124ff-ea41-4ea4-83a5-d557f05c8d4a） |
| E-003 | evidence/E-003_spec_review.json | 7905de52d404b76491dd20a27f4d59c122aa15a14338d577660a4790ca4be63e | 2026-11-11 20:40:14 | runner（記錄 spec_review session a1e6395b-0071-43fd-b493-dc6f8830ed2f） |
| E-004 | evidence/E-004_spec_review.json | badf742f72cfa4bfa95e2964d9eca335327585cd44219420d23a3568837b3032 | 2026-11-11 20:41:06 | runner（記錄 spec_review session 309161bb-79fb-4358-93ce-68dcf742281c） |
