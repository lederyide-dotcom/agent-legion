# T-0013 PipeAI_wmt 現況報告（唯讀）

## 架構

### 主要腳本與資料流
資料流為：`video/*.mp4` → YOLO（`best.pt`）逐影格偵測 → 有偵測結果的影格才對固定區域做 OCR → 解析成欄位 → CSV 與標註影像。

- **主流程** `all_in_one_processing_bbox_easyocr.py`
  - 以 `os.listdir` 找 `.mp4/.avi/.mov/.mkv`（`all_in_one_processing_bbox_easyocr.py:255`）。
  - 每格呼叫 `model(frame)`（`:310`）。
  - 只有 `len(results[0].boxes) > 0` 才做 OCR（`:312`）。
  - 四個固定相對座標 OCR 區域：distance、slope、well_info、pipe_info（`:465-470`）。
  - OCR 引擎為 EasyOCR，`easyocr.Reader(['ch_tra','en'])`（`:235`）。
  - 每個偵測框一列，欄位含 VideoName、FrameNumber、bbox、Distance、Slope、WellInfo、PipeMaterial、PipeDiameter、Status（`:347-362`）。
  - 每支影片處理完就整份覆寫 CSV（階段性儲存，`:398-403`），結束時再寫一次（`:416-420`）。
  - 標註影像存成 `<影片>/<類別>/frame_%05d_<類別>.jpg`（`:377-379`）。
  - 一格有 N 個框，就會把同一張整張標註圖寫 N 次（`:371-379`）。這是影像數量爆量的原因之一，與 `result/` 約 150 萬檔相符。
- **PaddleOCR 版** `all_in_one_processing_bbox_ocr_cloaud.py`：改用 `PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=...)`（`:252`）。匯入 `draw_ocr`（`:11`）。CSV 同樣 `utf-8-sig`（`:444`）。
- **舊版** `inference_video.py`：用 pytesseract（`:4`、`:148`、`:169`），CSV 為 `utf-8-sig`（`:198`）。依 CLAUDE.md 應移到 `99_bk/` 並加時間戳。
- **只輸出標註圖** `save_annotated_images.py`：輸入 `./video`、模型 `./best.pt`、輸出 `./annotated_images`（`save_annotated_images.py:73-77`），不含 OCR。函式與參數同名，容易混淆（`:14`）。
- **訓練** `train_yolov8_local.py`：每次執行都用 Linux 路徑重寫 `data.yaml`（`:7`、`:24-25`），再以 `yolov8n.pt` 訓練 `epochs=200, imgsz=640`（`:30-33`）。
- **啟動選單**：`run_choice_no_docker.sh:10-12` 只提供主流程與 `inference_video.py` 兩個選項。`Auto_run_no_docker.sh` 負責 cd 到專案並啟用 venv。

### 模型與資料位置
- 模型：`./best.pt`（`all_in_one_processing_bbox_easyocr.py:432`）；訓練輸出在 `runs/detect/train`、`runs/detect/train2`（Glob 回傳 `runs\detect\train\args.yaml`、`runs\detect\train2\args.yaml`）。
- 資料集：`data.yaml:3-4` 的 train 與 val 指向同一個資料夾（驗證指標不可信）。`data.yaml:7` 為 `nc: 33`，`data.yaml:10` 列出 33 個名稱，其中 0–14 為非下水道類別。
- 規格與類別統計：`03_docs/spec.md:20-42`。待決事項在 `03_docs/spec.md:44-49`。
- 輸出目錄：`./result`（`all_in_one_processing_bbox_easyocr.py:437`）。標註圖在 `result/annotated_images_improved`（`:448`），OCR 裁切圖在 `result/processed_images_improved`（`:449`）。
- CSV 檔名為 `detection_results_%Y%m%d_%H%M%S.csv`（`:441-442`），符合 CLAUDE.md 慣例。

### Linux／Windows 路徑相依點
- `data.yaml:3-4`：`/home/docker17de/PipeAI/PipeAI_wmt/dataset/images`，寫死 Linux 絕對路徑。
- `train_yolov8_local.py:7`：`dataset_root_path` 寫死 Linux 路徑。`:24` 的 `open('data.yaml','w')` 在 Windows 執行時會把 data.yaml 改寫成同一個 Linux 路徑，因此無法直接在本機訓練。
- `Auto_run_no_docker.sh:8`、`:12`、`:17`：註解與 `cd` 指向 `/home/docker17de`，venv 位於 `/home/docker17de/PipeAI/venv`。
- `inference_video.py:85-86`：tesseract 路徑只以註解提供 Linux 與 Windows 兩種。
- 主流程與 `save_annotated_images.py` 使用 `./video`、`./best.pt` 相對路徑，跨平台可用，但依賴「從專案根目錄執行」。
- `all_in_one_processing_bbox_easyocr.py:255` 用 `f.endswith(('.mp4',...))`，區分大小寫，`.MP4` 會被漏掉。`save_annotated_images.py:96` 同樣有此問題。

### 其他觀察
- `all_in_one_processing_bbox_easyocr.py:43` 使用裸 `except:`。
- `:453` 的 `batch_size` 傳入後未使用。
- `:463` 的 `enhancement_method` 未使用。
- `:285` 在 `save_ocr_images=True` 且 `fixed_ocr_regions=None` 時會 TypeError。
- `:422` 的 `df['Distance']` 欄位是字串，與 `''` 比較而計數，邏輯可行但脆弱。

## 測試缺口

### 現有測試
**沒有。** 根目錄的 Glob `*.py` 只回傳 `train_yolov8_local.py`、`save_annotated_images.py`、`inference_video.py`、`all_in_one_processing_bbox_ocr_cloaud.py`、`all_in_one_processing_bbox_easyocr.py` 與 `99_bk\` 下兩份備份。沒有 `test_*.py`、`conftest.py` 或 `tests/`。我沒有另外 Glob `tests/` 目錄，只能就上述 `*.py` 結果判斷。`03_docs/spec.md:51-54` 的驗收指標（mAP50、處理時間、OCR 正確率）也都還是空白。

### 沒有測試保護的模組與風險
1. **OCR 解析**（純函式，最容易補測）
   - `parse_distance_flexible`（`all_in_one_processing_bbox_easyocr.py:91-119`）：第二個 regex `([\d]+\.?[\d]*)` 會抓任何數字。像 `管徑300` 或 `DN300` 會被當成距離。第三個 regex（`:112`）在第二個之後，幾乎不可能走到，屬於死碼。`[\d.]+` 可吃到 `1.2.3`，使 `float()` 失敗後被吞掉。
   - `parse_pipe_diameter_flexible`（`:121-136`）：fallback `\d{2,4}` 會把距離或日期當管徑。
   - `parse_region_specific_text`（`:138-182`）：Status 的 regex 在 `\b\w{1,4}水\b` 上對中文行為不明確（中文都是 `\w`，`\b` 邊界不穩）。合併 Status 時的 sort/set 順序也沒有保證。
   - `find_text_in_region`（`:58-89`）：座標換算與邊界裁切（`:64-71`）沒有測試。
2. **CSV 編碼 utf-8-sig**：寫入在 `:402`、`:419`，另外 `all_in_one_processing_bbox_ocr_cloaud.py:444`、`inference_video.py:198` 也有。沒有測試確認 BOM 與中文欄位／內容能被 `pandas.read_csv(encoding='utf-8-sig')` 讀回。OCR 欄位 `OCR_Text_*` 是動態欄位（`:365`），若第一列沒有該欄位，欄位順序會不穩定。
3. **檔名格式**：`detection_results_YYYYMMDD_HHMMSS.csv`（`:441-442`）與 `frame_%05d_<class>.jpg`（`:377`、`save_annotated_images.py:60`）。沒有測試。類別名稱含空白或特殊字元時（例如 `data.yaml:10` 的 `marinara sauce`）會直接成為資料夾名。
4. **路徑寫死**：`data.yaml:3-4`、`train_yolov8_local.py:7`、`Auto_run_no_docker.sh:8,12,17`。沒有任何檢查在 Windows 上會失敗。
5. **資料設定一致性**：`nc: 33` 與 names 數量（`data.yaml:7,10`）、train／val 相同（`data.yaml:3-4`）、標註 class id 是否在範圍內，都沒有驗證。`03_docs/spec.md:42` 計畫重編號 0–17，重編號腳本沒有測試就不安全。
6. **主流程整合**：GPU／CPU 切換（`:199-232`）、階段性覆寫 CSV、`fixed_ocr_regions=None` 的例外（`:285`），都需要以假的 YOLO／OCR 物件做 smoke test。

### 優先補測清單
1. P0：`parse_distance_flexible`、`parse_pipe_diameter_flexible`、`parse_region_specific_text` 的參數化單元測試。涵蓋 `距離:12.5`、`距12.5`、`DN300`、空字串、亂碼、`1.2.3`、`管徑300` 誤判。這些是純函式，不需要 GPU 或模型。
2. P0：CSV 寫入測試，檢查 `utf-8-sig` BOM、中文內容回讀、檔名 regex `^detection_results_\d{8}_\d{6}\.csv$`。需要先把 CSV 寫入抽成可獨立呼叫的函式。
3. P1：座標換算與邊界裁切測試（`find_text_in_region`，以假 OCR reader 注入）。
4. P1：設定檢查腳本與測試：`data.yaml` 中不含 `/home/`、train≠val、`nc == len(names)`。
5. P2：影片副檔名大小寫、`fixed_ocr_regions=None` 的 smoke test（用 2–3 格的小影片，放在測試用 fixture，不要用 `video/` 或 `result/`）。
6. P2：標註檔類別 id 範圍與重編號映射的測試（在 g5-2 之前補）。

## 工具呼叫紀錄

| # | 工具 | path | pattern／檔案 |
|---|---|---|---|
| 1 | Glob | D:\PipeAI_wmt | `*.py` |
| 2 | Glob | D:\PipeAI_wmt\03_docs | `*` |
| 3 | Glob | D:\PipeAI_wmt | `*.sh` |
| 4 | Glob | D:\PipeAI_wmt | `*.yaml` |
| 5 | Read | D:\PipeAI_wmt\all_in_one_processing_bbox_easyocr.py | 全檔 |
| 6 | Read | D:\PipeAI_wmt\data.yaml | 全檔 |
| 7 | Read | D:\PipeAI_wmt\train_yolov8_local.py | 全檔 |
| 8 | Read | D:\PipeAI_wmt\save_annotated_images.py | 全檔 |
| 9 | Read | D:\PipeAI_wmt\run_choice_no_docker.sh | 全檔 |
| 10 | Read | D:\PipeAI_wmt\03_docs\spec.md | 全檔 |
| 11 | Grep | D:\PipeAI_wmt\inference_video.py | `/home/\|cd \|encoding\|strftime\|pytesseract\|tesseract_cmd\|PaddleOCR\(` |
| 12 | Grep | D:\PipeAI_wmt\Auto_run_no_docker.sh | `/home/\|cd \|docker\|python` |
| 13 | Grep | D:\PipeAI_wmt\all_in_one_processing_bbox_ocr_cloaud.py | `PaddleOCR\|utf-8\|strftime\|\./video\|\./best\|\./result\|/home/` |

共 13 次呼叫。沒有其他工具呼叫（Bash 未使用）。

## 禁止目錄檢查

**結論：不能宣稱完全沒碰到禁止目錄。**

逐筆對照：
- #2–#3、#5–#13：path 都是具體檔案或 `03_docs/`。#3 的 `*.sh` 結果只有根目錄兩個 `.sh`。這些呼叫不在禁止目錄內。
- **#1（Glob `*.py`）**：雖然 path 是專案根目錄，pattern 也沒有 `**`，但回傳了 `99_bk\all_in_one_processing_bbox_easyocr-10150917.py` 等子目錄檔案。這表示 Glob 對 `*` 是遞迴比對（不限單層）。
- **#4（Glob `*.yaml`）**：回傳了 `runs\detect\train\args.yaml` 與 `runs\detect\train2\args.yaml`。**這次 Glob 實際走訪並回傳了禁止目錄 `runs/` 下的路徑。** 我沒有 Read 這些檔案內容，但 Glob 本身已碰到 `runs/`。
- `result/`、`annotated_images/`、`dataset/images`、`video/`：輸出中沒有出現這些路徑，所以沒有證據顯示回傳了其中的檔案。但既然 Glob 是遞迴的，**無法排除 #1、#3、#4 在內部走訪過這些目錄**（尤其是 `result/` 約 150 萬檔）。這點只能由 runner 端的實際觀測（耗時或檔案存取紀錄）確認，我無法自行驗證。
- 原因說明：規格要求 `path` 指到根目錄並限定單層，但實測 Glob 並不會限定單層。這是任務限制與工具行為的落差，不是我刻意讀取 `runs/`。

建議的後續處理：把規格改成不使用 Glob 找副檔名，或請 runner 提供單層列舉的方式。runner 檢查要把「回傳結果路徑」也納入比對，而不只比對呼叫參數。

## runner 建議

供後續 write 任務（目標 repo：`D:/202611_agent-legion`）使用：

1. **紀錄欄位**：每次 Glob/Grep/Read 記錄 `seq`、`tool`、`path`、`pattern`（或 `file_path`）、`glob`／`type` 等過濾參數、時間戳，以及「回傳的路徑清單」（Glob 的輸出、Grep 的 files_with_matches）。我這次的缺口就在只記錄呼叫參數看不到實際碰到的路徑。
2. **路徑正規化**：用 `pathlib.Path(...).resolve()` 轉成絕對路徑，統一斜線，Windows 下 casefold。相對路徑以任務工作目錄為基準。
3. **比對禁止清單**：禁止清單為 `result/`、`annotated_images/`、`dataset/images`、`runs/`、`video/`，解析後用 `is_relative_to` 判斷。要同時比對三件事：呼叫的 `path`、Read 的 `file_path`、以及回傳的每個路徑。`path` 為專案根目錄且 pattern 含 `**` 或遞迴行為時，視為「可能走訪禁止目錄」，要標記出來。
4. **通過／失敗判定**：
   - 失敗：任何呼叫的 path 或回傳路徑落在禁止目錄內，或對根目錄使用 `**/*`、`*` 這種無界 pattern。
   - 警告：根目錄的遞迴 Glob 無法證明未走訪（如本次），要求執行者在報告中明說。
   - 通過：所有路徑都在允許範圍內，且報告「工具呼叫紀錄」筆數與 runner 實際記錄一致。
5. **交叉驗證**：以 runner 自己的紀錄為準，與報告中的表格比對筆數與參數。不一致就升級人工審查。報告章節檢查（`legion.checks report`）不能取代這項檢查。
6. **執行前後**：保留 `git rev-parse HEAD` 與 `git status --porcelain` 的前後比對（驗收標準已列出）。