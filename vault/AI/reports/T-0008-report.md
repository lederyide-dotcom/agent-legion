# T-0008 PipeAI_wmt 架構與測試缺口健檢報告（唯讀）

- 範圍：根目錄七支腳本、`data.yaml`、`03_docs/spec.md`、`CLAUDE.md`、`.gitignore`、`99_bk/` 兩個舊版腳本。
- 沒有掃描 `result/`、`annotated_images/`、`dataset/images`、`runs/`。
- 沒有執行任何腳本，沒有讀取 `.env` 或金鑰，沒有安裝任何東西。
- 標記說明：**【事實】** 是直接讀到的內容，附「檔案:行號」。**【推測】** 是我的推論，尚未驗證。

---

## 1. 架構

### 1.1 各腳本職責表

| 檔案 | 職責 | OCR 引擎 | 輸出 |
|---|---|---|---|
| `all_in_one_processing_bbox_easyocr.py` | **主流程**。批次處理 `./video`，每影格做 YOLO 偵測；有偵測時對 4 個固定字幕區域做 OCR 並解析；輸出 CSV 與標註圖、OCR 裁切圖（:185-426、:428-481） | EasyOCR `['ch_tra','en']`（:235） | `./result/detection_results_<時間戳>.csv`、`result/annotated_images_improved`、`result/processed_images_improved`（:437-449） |
| `all_in_one_processing_bbox_ocr_cloaud.py` | 同上，OCR 換成 PaddleOCR（:252）。檔名有拼字錯誤（cloaud） | PaddleOCR（`det=False, rec=True`，:85） | 固定寫到 `./detection_results_improved.csv`、`./annotated_images_improved`、`./processed_images_improved`（:461-464） |
| `inference_video.py` | 舊版。YOLO 加 pytesseract，輸出 CSV 與一支標註影片（:41-201） | pytesseract（:148、:169） | `./detection_results.csv`、`./analyzed_video.mp4`（:211-213） |
| `save_annotated_images.py` | 只做 YOLO 推論，依影片與類別存標註圖，不做 OCR（:14-68） | 無 | `./annotated_images/<影片>/<類別>/frame_*.jpg`（:77） |
| `train_yolov8_local.py` | 把 `data.yaml` 內容寫死在腳本內並覆寫檔案（:11-25），再用 `yolov8n.pt` 訓練 200 epochs、imgsz=640（:30-33） | 無 | `runs/detect/trainN` |
| `run_choice_no_docker.sh` | 互動選單，只能選 easyocr 主流程或 `inference_video.py`（:10-27），再執行 `python`（:40） | – | – |
| `Auto_run_no_docker.sh` | `cd ./PipeAI/PipeAI_wmt`、啟動 `../venv`，再呼叫上一支 `.sh`（:9-30） | – | – |
| `data.yaml` | 33 類、train 與 val 都指向同一個 Linux 絕對路徑（:3-4、:7） | – | – |

### 1.2 資料流（事實）

```
video/*.mp4|avi|mov|mkv
  └ cv2.VideoCapture 逐影格（easyocr:264-293）
      ├ YOLO(best.pt) 推論（easyocr:310）
      │    └ 有框才繼續（easyocr:312）
      │        ├ 4 個固定相對座標區域 → 裁切 → EasyOCR/PaddleOCR/pytesseract（easyocr:314-333）
      │        │    └ 正規表達式解析 Distance / Slope / PipeMaterial / PipeDiameter / WellInfo / Status（easyocr:138-182）
      │        ├ 每個 bbox 一列 dict → pandas DataFrame → CSV（utf-8-sig）（easyocr:340-368、:399-402）
      │        └ results[0].plot() → 依類別存 jpg（easyocr:338、:370-379）
      └ 另存 OCR 裁切圖（easyocr:317-330）
```

- 影片層級進度每 100 影格列印一次（easyocr:298-307）。
- CSV 在每支影片處理完後會以累積內容覆寫一次（easyocr:398-403）。
- 流程結束時會再寫一次最終 CSV（easyocr:416-420）。

### 1.3 腳本之間的相依（事實）

- 沒有任何 `import` 互相引用。七支腳本各自獨立，共用邏輯全靠複製貼上。
- 唯一的耦合是：
  - `.sh` 以檔名呼叫 Python（run_choice:21、:26）。
  - 腳本都假設根目錄有 `./best.pt` 與 `./video`（easyocr:431-432、cloud:459-460）。
  - `train_yolov8_local.py` 產生的 `data.yaml` 是 `yolo val` 的輸入（CLAUDE.md 指令段）。
- `best.pt` 來自 `runs/detect/train*/weights`（train:40 的訊息），但沒有任何程式自動複製或登記版本。

### 1.4 重複程式碼與可抽出的共用函式

**【事實】** 以下函式在多個檔案內容幾乎相同：

| 函式 | 出現位置 | 差異 |
|---|---|---|
| `create_directory` | easyocr:50、cloud:53、inference:10、save_annotated:6 | 四份完全相同 |
| `check_system_resources` | easyocr:13、cloud:13 | 只差註解 |
| `parse_distance_flexible` | easyocr:91、cloud:100 | 相同。`99_bk` 兩版也相同（bk:91） |
| `parse_pipe_diameter_flexible` | easyocr:121、cloud:133 | 相同。inference:31 的 `parse_pipe_diameter` 少了「純數字」退路 |
| `parse_distance`（舊版） | inference:18 | 比 flexible 版更簡單，任何數字都當距離 |
| bbox 比例轉像素加邊界裁剪 | easyocr:64-69 與 :323-327；cloud:71-76 與 :348-352；inference:136-142 | 同一個運算在**同一檔內也重複兩次** |
| `find_text_in_region` | easyocr:58、cloud:65 | 只有 OCR 呼叫那幾行不同 |
| 裝置選擇（cuda/xpu/cpu） | easyocr:199-232、cloud:209-240、inference:63-68 | 邏輯重複 |
| 影片副檔名過濾 | easyocr:255、cloud:273、inference:93、save_annotated:96 | 四處 |
| 標註圖存檔迴圈 | easyocr:370-379、cloud:405-415、save_annotated:49-65 | 三處 |

**與 `99_bk/` 的關係（事實）：** 兩個備份都是 easyocr 主流程的舊版。

- `99_bk/all_in_one_processing_bbox_easyocr-10150917.py` 的 `well_info_region` 是 `(0.20,0.02,0.45,0.07)`（bk:440）。現行版是 y=0.03（easyocr:468）。
- `-10150211` 版同樣是 y=0.02（bk:468），且有階段性存檔（:402、:419）。
- `-10150917` 版只在最後存一次 CSV（:405）。
- 時間戳順序與功能演進並不單調：02:11 版有階段性存檔，09:17 版沒有。
- 我只用 Grep 比對關鍵行，沒有逐行 diff，所以其他差異未確認。

**建議抽出的共用模組（推測，屬設計建議）：**

1. `pipeai/geometry.py::rel_to_abs_box(coords, w, h) -> (x1,y1,x2,y2)`，統一邊界裁剪。
2. `pipeai/ocr_parse.py`：`parse_distance`、`parse_pipe_diameter`、`parse_region_specific_text`，純函式，不依賴 OCR 引擎。
3. `pipeai/ocr_engine.py`：介面 `read_text(img) -> str`，下面接 EasyOCR、PaddleOCR、pytesseract 三個實作。
4. `pipeai/device.py::select_device(use_gpu)`，同時決定 YOLO 與 OCR 用的裝置。
5. `pipeai/io_utils.py`：`ensure_dir`、`list_videos`（不分大小寫）、`write_csv(df, out_dir)`（固定 `utf-8-sig` 與 `detection_results_YYYYMMDD_HHMMSS.csv`）。

---

## 2. 測試缺口

### 2.1 現有測試清單

**無。**

- 以 Glob 檢查根目錄與 `tests/`，找不到 `test_*.py`、`*_test.py`、`conftest.py`、`pytest.ini`、`pyproject.toml`、`requirements*.txt`。
- 沒有 `requirements.txt`，也就沒有任何依賴版本紀錄。EasyOCR、PaddleOCR、pytesseract、ultralytics、psutil 全是隱含依賴（easyocr:1-11、cloud:11、inference:4）。
- 沒有 CI 設定（`.gitignore` 與目錄清單中未見）。

### 2.2 優先補測清單（依優先序）

**P1. 字幕距離／管徑 OCR 解析**（目標：`parse_distance_flexible`、`parse_pipe_diameter_flexible`、`parse_region_specific_text`）

- 理由：這是報表正確率的核心。目前讀到的邏輯有多個疑點（【事實】）：
  - `parse_distance_flexible` 的「方法 2：任何數字」（easyocr:105）排在「方法 3」（:112）之前。方法 3 實質上到不了，因為只要有數字，方法 2 就先回傳。
  - 方法 2 會把 `坡度-0.5` 之類的字串也當成距離。
  - `parse_pipe_diameter_flexible` 的退路是任何 2–4 位數字都當 `DN`（easyocr:132-134）。例如 `2024` 會變成 `DN2024`。
  - Cloud 版把每個區域的文字都丟進同一個 `parse_text_and_add_to_dict_improved`（cloud:396-401）。後處理的區域文字會覆蓋前面的 Distance，例如坡度區域的數字（【事實】）。
  - Cloud 版管材正則是 `RC` 而非 `RCP`（cloud:170），與主流程不一致（easyocr:159）。
  - Cloud 版的 `RC` 同時也在 Status 正則內（cloud:185），所以 `RC` 會同時變成 PipeMaterial 與 Status（【事實】）。
- 建議測試方式：
  - pytest 參數化，輸入字串對應期望值。例如 `"距離:12.5"→12.5`、`"距12.5m"`、空字串→None、`"DN200PVC"→"DN200"`、`"直徑300"`、`"2024"`（記錄現況行為）。
  - 加 golden-file：從 `processed_images_improved` 少量抽樣（人工挑 10–20 張）搭配人工標準答案。注意不要遞迴掃描該目錄。
  - 抽出純函式後不需要 GPU 或 OCR 套件。
- 這項也是 CLAUDE.md g5-4「人工／CPU／GPU 準確率」的基礎。

**P2. CSV 輸出（`utf-8-sig`、檔名格式）**

- 理由：CLAUDE.md 規定檔名 `detection_results_YYYYMMDD_HHMMSS.csv` 與 `utf-8-sig`。
- 【事實】只有主流程符合（easyocr:441-442、:402、:419）。Cloud 固定檔名 `detection_results_improved.csv`（cloud:461）。舊版固定 `detection_results.csv`（inference:211）。
- 建議測試方式：
  - 用 `tmp_path` 呼叫抽出的 `write_csv`，斷言檔名符合正規式 `^detection_results_\d{8}_\d{6}\.csv$`。
  - 讀取前 3 個 bytes 應為 `EF BB BF`。
  - 欄位集合固定。主流程在有 OCR 區域時會多出 `OCR_Text_*` 欄位（easyocr:365）；舊版是 `DetectedText_Raw`（inference:186）。
  - 空結果不產生檔案（easyocr:425-426）。

**P3. bbox 座標換算**

- 理由：同一公式複製 5 次（見 1.4），任一處改錯都不易察覺。
- 【事實】使用 `int()` 截斷（easyocr:64-67），之後 clamp 到 `[0, w]`、`[0, h]`（:69）。
- 【推測】在極端區域下，clamp 後 `x1 >= x2` 會得到空裁切。`find_text_in_region` 以 `size == 0` 回 `""` 處理（:73-74），但存圖路徑用 `size > 0` 判斷（:329），行為一致。`inference_video.py` 的物件 bbox 裁切沒有 clamp（inference:166），負數座標會產生錯誤切片。
- 建議測試方式：
  - 純函式表格測試：中心點在 (0.1, 0.94)、寬 0.2、高 0.1，解析度 1920×1080 與 640×480。
  - 邊界：超出 1.0、小於 0、寬高為 0。
  - 預期值要人工算出，不要用實作反推。

**P4. 路徑處理**

- 理由：Linux 絕對路徑寫死（train:7、data.yaml:3-4），Windows 無法直接跑。
- 建議測試方式：
  - 抽出 `resolve_paths(root: Path)`，用 `tmp_path` 假目錄驗證相對路徑、中文與空白路徑。
  - 驗證 `list_videos` 不分大小寫。目前是 `endswith(('.mp4', ...))`（easyocr:255），`.MP4` 不會被處理（【事實】）。
  - 驗證不存在的 `video/` 會給明確錯誤。目前只 `print` 後 `return`（easyocr:242-244）。

**P5. data.yaml 與標註類別一致性檢查**

- 理由：CLAUDE.md 已記錄 `nc: 33`、train=val、類別不平衡。目前沒有任何自動檢查。
- 建議測試方式：
  - 讀 `data.yaml` 驗證 `len(names) == nc`（從 data.yaml:7 與 :10 看起來成立，我沒有逐字數）。
  - 掃 `dataset/labels/*.txt`（只讀小檔，不遞迴 images），驗證所有 class id 都在 `[0, nc)`。
  - 驗證 `train != val`。
  - 驗證 `classes.txt` 與 `names` 順序一致。
  - 這項檢查很適合當 g5-2 重編 0–17 之後的回歸測試。

**P6. 無 GPU 時的 fallback**

- 理由：Windows 本機有 4060，但 CPU 測試是 g5-4 的一欄。
- 【事實】主流程的 `use_gpu=False` 或無 CUDA 時，`device='cpu'`（easyocr:199-227）。
- 【事實】但 `easyocr.Reader(..., gpu=use_gpu)`（:235）傳的是參數而不是偵測結果。`ocr_device` 已定義卻沒被使用（:200、:205）。在 `use_gpu=True` 但沒有 CUDA 時，EasyOCR 的行為取決於套件（【推測】多半會警告後退 CPU）。
- 建議測試方式：
  - 用 `monkeypatch` 把 `torch.cuda.is_available` 設成 False，測 `select_device` 回傳 `cpu`。
  - OCR 引擎以 fake 類別注入，不真的載入模型。
  - 另做一個 smoke test，用 `pytest.importorskip` 在有 CUDA 時才跑。

---

## 3. 其他風險

### 3.1 寫死的 Linux／Windows 路徑

- **【事實】** `train_yolov8_local.py:7` 寫死 `/home/docker17de/PipeAI/PipeAI_wmt/dataset`。
- **【事實】** `data.yaml:3-4` 同樣是 Linux 絕對路徑。
- **【事實】** `train_yolov8_local.py:24` 每次執行都用 `open('data.yaml','w')` 覆寫 `data.yaml`，沒有指定 encoding。
  - 所以只改 `data.yaml` 是無效的，下次訓練就會被腳本內容蓋掉。
  - 這與 CLAUDE.md「改之前先跟使用者確認」的 data.yaml 問題直接相關。
- **【事實】** `Auto_run_no_docker.sh:9` 與 `:19` 假設工作目錄是 `/home/docker17de`，且 venv 在 `../venv`。
- **【事實】** `inference_video.py:85-86` 的 tesseract 路徑是註解掉的 Linux／Windows 例子。
- **【事實】** 其餘 Python 腳本用 `./video`、`./best.pt` 這類相對路徑（easyocr:431-432），在 Windows 上沒有問題，但依賴「從專案根目錄啟動」。
- **【事實】** `.gitignore:2-7` 排除 `result/`、`annotated_images/`、`dataset/`、`video/`、`runs/`、`*.pt`，但**沒有**排除 Cloud 版的輸出目錄 `annotated_images_improved/` 與 `processed_images_improved/`（cloud:463-464）。同樣沒有排除 `analyzed_video.mp4` 與 `detection_results.csv`（inference:211-213）。
  - `.gitignore` 的 `annotated_images/` 只比對該名稱的目錄，不涵蓋 `annotated_images_improved/`（【推測】依 gitignore 規則，未實測）。
  - 風險：以 Cloud 版或舊版輸出後，大量圖片會出現在 `git status`。`detection_results*.csv` 有被排除（:8）。
- **【事實】** `dataset/` 整個被排除。標註檔 `dataset/labels`（275 份）因此不在版本控制內。這符合 CLAUDE.md 規定，但標註是最珍貴且體積很小的資產，建議與使用者討論改為只追蹤 `dataset/labels` 與 `classes.txt`（【推測】建議，不是現況問題）。

### 3.2 例外處理

- **【事實】裸 `except:`**：`check_system_resources` 的 `except:`（easyocr:43、cloud:46），會吞掉包含 `KeyboardInterrupt` 的所有例外。`99_bk` 兩版也有（bk:43）。
- **【事實】吞錯誤後 `return`**：模型或 OCR 載入失敗只 `print` 再 `return`（easyocr:238-240、cloud:255-257），結束碼仍是 0，批次或 `.sh` 無法知道失敗。找不到影片資料夾同理（easyocr:242-244）。
- **【事實】OCR 失敗回空字串**：`find_text_in_region` 的 `except Exception` 只 print 警告就回傳 `""`（easyocr:87-89、cloud:96-98）。後果是 CSV 上「OCR 失敗」與「沒有字幕」無法區分。舊版會寫入 `"OCR_FAILED"`（inference:152、:173），三個版本行為不一致。
- **【事實】沒有檢查 `cap.isOpened()`** 或影片是否可讀。若影片打不開，迴圈會直接結束，沒有任何警告（easyocr:264-293）。
- **【事實】除以零風險**：`progress = frame_count / total_frames`（easyocr:301、cloud:320）。當容器回報影格數為 0 時會拋 `ZeroDivisionError`（【推測】實際是否發生取決於影片格式）。
- **【事實】`fixed_ocr_regions=None` 預設值**：`save_ocr_images=True` 時 `for region in fixed_ocr_regions` 會對 `None` 迭代而失敗（easyocr:285、:314）。
- **【事實】`save_annotated_images.py:83-84`** 捕捉所有例外後 `exit()`，不印出實際錯誤原因。

### 3.3 可維護性

- **魔術數字**：
  - OCR 區域座標寫死在 `__main__`（easyocr:465-470）。Cloud 版的 well/pipe 區域與主流程不同，分別是 y=0.03/0.13，高 0.05（cloud:491-492），對照 y=0.03/0.12，高 0.07（easyocr:468-469）。
  - 同一份規格的字幕位置有兩套設定，哪套正確沒有文件。這與 spec.md 待決事項「字幕區域座標是否固定」相關（spec:48）。
  - 其他魔術數字：進度間隔 100（easyocr:298）、管徑 2–4 位數（:132）、管材清單（:159）、`batch_size=1` 未被使用（:188、:453）。
  - `enhancement_method`（:463）與 `csv`、`numpy` 的 import 也沒用到（【事實】本檔內無使用）。
- **全域狀態**：模組層級的 `__main__` 區塊直接設定 `torch.backends.cudnn.benchmark`（easyocr:455-459），沒有 `main()` 函式，無法被 import 測試。主函式 `process_and_save_all_videos_improved` 約 240 行，混合了裝置選擇、IO、推論、OCR、解析、存檔。
- **沒有 CLI 參數**：所有路徑與開關都是 `__main__` 內的變數。要比較 CPU／GPU 需手改 `use_gpu`（easyocr:452）。
- **沒有 logging**：全部用 `print`。Cloud 版還開著 `verbose=True`（cloud:331），每影格印一行推論資訊；主流程為 `verbose=False`（easyocr:310）。
- **標註圖輸出量**：
  - 【事實】對每個框都 `imwrite` 整張標註影格（easyocr:371-379）。同一影格有 N 個框就寫 N 次，且檔名只含類別。同類別多框會彼此覆寫同一檔案。
  - 【事實】OCR 裁切圖在每個有偵測的影格都寫 4 張（easyocr:317-330）。
  - 【推測】這與 CLAUDE.md 所說 `result/` 約 150 萬檔案相符，但我沒有掃描驗證。
- **`.sh` 啟動選單**：
  - 【事實】選單只有 2 個選項（run_choice:10-11），不含 `save_annotated_images.py`、Cloud 版或訓練。
  - 【事實】標示「(預設)」但沒有預設行為，直接按 Enter 會走到「無效的選項」並結束（run_choice:29-32）。
  - 【事實】用 `python` 而非 `python3`，沒有 `set -e`，也不支援非互動模式（`read -p`，:15）。
  - 【事實】Windows 無法直接執行 `.sh`。CLAUDE.md 的指令是 `py -3.10`。
  - 【推測】行尾是否為 CRLF 我沒有檢查，若是則在 Linux 會出現 `\r` 問題。
- **舊版腳本管理**：`inference_video.py`、`save_annotated_images.py`、Cloud 版都沒有在 `99_bk/` 標記為舊版。CLAUDE.md 要求舊版移到 `99_bk/` 並加 `-MMDDHHMM`（CLAUDE.md「重要限制」段），目前只有主流程的兩個備份符合。
- **inference_video.py 的特定問題（事實）**：
  - 多支影片共用同一個 `output_video_path`（inference:108），後一支會覆寫前一支。
  - 註解說「啟用固定區域 OCR 並將 YOLO 關閉」（:216），但程式實際仍執行 YOLO（:118）。註解與實作不符。
  - 呼叫 `model(frame)` 沒有指定 `device`（:118）。

### 3.4 與 CLAUDE.md data.yaml 已知問題的關聯（只引用，不重做）

| CLAUDE.md 已知問題 | 程式中的對應位置 |
|---|---|
| 1. nc=33，0–14 與下水道無關 | `train_yolov8_local.py:17-20` 與 `data.yaml:7-10`。0–14 是 dog、person 等，15–32 才是 sewer 類別。推論時 `model.names[class_id]`（easyocr:343）會輸出模型內的名稱，所以舊權重若誤判成 0–14 的類別，CSV 會出現「dog」之類的列。【推測】此情況是否發生需另行驗證 |
| 2. train 與 val 指向同一資料夾 | `train_yolov8_local.py:13-14` 與 `data.yaml:3-4`。且該腳本每次重寫 data.yaml，所以要改切分必須同時改這支腳本 |
| 3. 類別不平衡 | 程式沒有任何處理，如類別權重或重採樣。`spec.md:21-40` 有統計表 |
| 4. 425 張影像只有 275 份標註 | 訓練腳本沒有檢查。見上方 P5 |

---

## 4. 建議行動順序

| 順序 | 行動 | 風險 | 理由 |
|---|---|---|---|
| 1 | 補 `.gitignore`：加入 `annotated_images_improved/`、`processed_images_improved/`、`*.mp4`、`analyzed_video.mp4`。討論是否追蹤 `dataset/labels` | **低** | 純設定檔，可還原。避免 Cloud 版或舊版輸出灌爆 `git status` |
| 2 | 抽出純函式模組（`ocr_parse`、`geometry`、`io_utils`），再寫 P1–P3 的 pytest，並新增 `requirements.txt`（鎖版本） | **低到中** | 純函式、無 GPU 依賴。先寫「現況行為」測試，再修 `parse_distance` 順序與 Cloud 版覆蓋問題。重構時要避免動到推論行為 |
| 3 | 修 `train_yolov8_local.py`：移除寫死的 Linux 路徑與每次覆寫 data.yaml 的行為，改讀 `pathlib` 相對路徑；輸出到新的 `runs/detect/<名稱>`；加 P5 的 data.yaml／標註一致性檢查 | **中** | 這是 g5-2／g5-3 的前置作業。需先與使用者確認 data.yaml 四個已知問題的處理方式（CLAUDE.md 規定），且不可覆寫 `best.pt`、`runs/` |
| 4 | 加 CLI（`argparse`：`--device cpu/cuda`、`--ocr easyocr/paddle`、`--video-dir`、`--out-dir`）與 `logging`，把裸 `except:` 改為具名例外，失敗時回傳非 0 結束碼，並讓 OCR 失敗在 CSV 內可區分 | **中** | 會改動主流程行為，容易影響現有輸出。需要在 P1–P3 測試就位後再做。同時能直接支援 g5-4 的 CPU／GPU 對照 |
| 5 | 整理舊版：Cloud 版與 `inference_video.py` 決定保留或移到 `99_bk/`（加 `-MMDDHHMM`）。`.sh` 改為可帶參數且支援預設選項；另做 PowerShell 或 `py -3.10` 啟動說明 | **低到中** | 屬整理類工作。Cloud 版是否保留取決於 spec.md 的 OCR 引擎待決事項（spec:48），需使用者決定 |

### 最後備註

- 這份報告的判斷來自靜態閱讀。實際 OCR 正確率、GPU fallback 行為、檔案數量都**沒有**實測。
- 其中標為【推測】的項目，建議在後續任務中以測試或抽樣驗證後再採取行動。
