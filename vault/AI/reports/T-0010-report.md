# T-0010 唯讀審查：PipeAI_wmt 架構與測試缺口

審查範圍：根目錄 `*.py`、`*.sh`、`data.yaml`、`03_docs/spec.md`、`99_bk/`。未讀 `result/`、`annotated_images/`、`dataset/images`、`runs/`、`video/`，也未讀 .env 或金鑰。未修改檔案，未安裝套件，未執行訓練或推論。
`99_bk/` 內的兩個舊版檔案（`99_bk/all_in_one_processing_bbox_easyocr-10150917.py`、`-10150211.py`）只確認存在，沒有逐行審查。

## 一、架構

### 1.1 主流程（影片 → YOLO → OCR → 合併 → CSV／標註影像）
主流程在 `all_in_one_processing_bbox_easyocr.py` 的 `process_and_save_all_videos_improved`（:185）。
- **讀影片：** 用 `os.listdir` 列出 `./video` 下副檔名為 mp4、avi、mov、mkv 的檔案（:255）。副檔名比對區分大小寫，`.MP4` 會被漏掉。
- **逐格處理：** 用 `cv2.VideoCapture` 逐格讀取（:264、:291），沒有跳格或批次，`batch_size` 參數（:188）完全沒用到。
- **YOLO：** `model(frame, device=device, verbose=False)`（:310）。
- **OCR：** 只有在 YOLO 偵測到至少一個框時才做 OCR（:312）。4 個固定相對座標區域（:465-470）：distance、slope、well_info、pipe_info。每個區域交給 `find_text_in_region`（:58，裁切後 `readtext`，再把所有片段串接並移除空白）。
- **合併：** 每個偵測框產生一列（:347-368）。每列帶 `VideoName`、`FrameNumber`、類別、信心度、bbox，以及該影格同一份 OCR 結果解析出的欄位，欄位由 `parse_region_specific_text`（:138）依區域名稱解析。
- **輸出 CSV：** 每處理完一支影片就整份覆寫一次（:398-403），結束時再寫一次（:416-420）。編碼是 `utf-8-sig`，檔名 `detection_results_%Y%m%d_%H%M%S.csv`（:441-445），符合 CLAUDE.md 的慣例。
- **標註影像：** 輸出到 `result/annotated_images_improved/<影片>/<類別>/frame_%05d_<類別>.jpg`（:370-379）。
  - 同一影格若有 N 個框，會把同一張完整標註圖寫 N 次。
  - 這也是 `result/` 與 `annotated_images/` 檔案量極大的原因之一，資料量已約 150 萬與 1.5 萬個檔案（見 CLAUDE.md）。
- **OCR 裁切圖：** 另存裁切圖（:317-330）。
- **合併的是影格編號，不是時間：** 「時間點」目前只有影格編號。程式有讀 fps（:266），但沒有換算成秒，CSV 也沒有時間欄位。spec 流程圖（`03_docs/spec.md:13-17`）寫的是「時間點 × 異常 × 位置」，與實作有落差。

### 1.2 各腳本職責與相依關係
| 檔案 | 職責 | 主要相依 |
|---|---|---|
| `train_yolov8_local.py` | 訓練：寫 `data.yaml` 後呼叫 `YOLO('yolov8n.pt').train(epochs=200, imgsz=640)`（:30-33） | ultralytics |
| `all_in_one_processing_bbox_easyocr.py` | 主流程（EasyOCR） | ultralytics、torch、easyocr（:11）、pandas、psutil、cv2 |
| `all_in_one_processing_bbox_ocr_cloaud.py` | 同主流程，OCR 換成 PaddleOCR | paddleocr（:11）。檔名 `cloaud` 疑似拼錯，且該腳本實際並未使用雲端 |
| `inference_video.py` | 舊版：pytesseract，並輸出標註影片 | pytesseract（:4） |
| `save_annotated_images.py` | 只輸出標註影像，不做 OCR、不輸出 CSV | ultralytics、cv2 |
| `run_choice_no_docker.sh`、`Auto_run_no_docker.sh` | Linux 選單與啟動 | bash、venv |

**三套 OCR 並存：**
- EasyOCR：`all_in_one_processing_bbox_easyocr.py:11`、`:235`。
- PaddleOCR：`all_in_one_processing_bbox_ocr_cloaud.py:11`、`:252`。
- pytesseract：`inference_video.py:4`、`:148`。
- 專案內沒有 `requirements.txt` 或鎖定檔（根目錄 `*.py`／`*.sh` 之外，我只對 `test_*.py`、`conftest.py` 做 Glob，未確認有無 requirements，建議人工確認）。三套 OCR 互不相同，且 `spec.md:48` 也把「OCR 引擎定案」列為待決事項。

**重複程式碼：**
- 兩支主流程腳本的 `check_system_resources`、`parse_distance_flexible`、`parse_pipe_diameter_flexible`、`find_text_in_region` 幾乎是整段複製（easyocr 版 :13、:91、:121、:58；paddle 版 :13、:100、:133、:65）。
- 兩者的區別：
  - easyocr 版依區域分流解析（`parse_region_specific_text`，:138），而且 Status 是累加。
  - paddle 版對每個區域文字都跑全部解析（`parse_text_and_add_to_dict_improved`，:152），後面區域的文字會覆蓋前面區域的結果。例如 slope 區域的數字會蓋掉 Distance。
  - 兩版的區域座標也不同（easyocr 版 :468-469 對 paddle 版 :491-492）。
  - paddle 版輸出路徑是 `./detection_results_improved.csv`（:461），不符合時間戳記檔名慣例，也不寫入 `result/`。
- paddle 版每格強制 `verbose=True`（:331），輸出會非常多。

**已知小缺陷（會影響結果，供後續參考）：**
- `parse_distance_flexible`（easyocr 版 :91-119）：「方法 2」會抓任何數字，使得「方法 3」永遠不會被執行（死碼）。`slope` 字幕若混入距離區域，會被當成距離。
- `parse_pipe_diameter_flexible`（:121-136）：任何 2–4 位數字都會被當作 DN，例如把坡度或井號數字誤認成管徑。
- `parse_distance_flexible` 的 `[\d.]+` 可能吃到「1.2.3」這類字串，`float()` 失敗後會被吞掉（:98-103）。
- `except:`（:43）為裸 except。
- 影片 `cap.read()` 失敗與 `FRAME_COUNT` 為 0 時，進度除法（:301）會除以零。`total_frames` 為 0 時進度計算會拋例外。
- `fixed_ocr_regions` 預設為 `None`（:188），但 :285 直接迭代，不傳會崩潰。
- `enhancement_method`（:463）與 `batch_size` 皆為未使用的設定。

### 1.3 路徑是否寫死 Linux 絕對路徑
有，且在兩個地方：
- `data.yaml:3-4`：`train`／`val` 為 `/home/docker17de/PipeAI/PipeAI_wmt/dataset/images`。
- `train_yolov8_local.py:7`：`dataset_root_path = '/home/docker17de/PipeAI/PipeAI_wmt/dataset'`。
- `train_yolov8_local.py:24-25` 每次執行會用該路徑**覆寫** `data.yaml`。換句話說，即使手動改了 `data.yaml`，執行訓練腳本後會被還原成 Linux 路徑。
- `Auto_run_no_docker.sh:9`、`:19` 以 `./PipeAI/PipeAI_wmt` 與 `../venv/bin/activate` 為相對路徑，但假設從 `/home/docker17de` 執行（註解於 :8），在 Windows 不可用（`bin/activate` 在 Windows venv 是 `Scripts\activate`）。
- `run_choice_no_docker.sh:40` 使用 `python`，在 Windows 上與 CLAUDE.md 規定的 `py -3.10` 不一致。
- 推論腳本使用 `./video`、`./best.pt`、`./result` 等相對路徑（`all_in_one_processing_bbox_easyocr.py:431-432`、:437），這些是 OK 的，但相對於目前工作目錄，而非腳本所在位置。

### 1.4 `data.yaml` 已知問題（皆已在檔案中確認）
1. **`nc: 33`（`data.yaml:7`）：** names 清單（:10）的第 0–14 項是 dog、person、cat、tv、car、meatballs、food、cavity 等非下水道類別，真正的下水道類別是第 15–32（18 類，從 `sewer_HM_RC` 到 `sewer_Pipe_break`）。`spec.md:42` 已說要重編成 0–17，並需同步改標註檔。
2. **train 與 val 相同（`data.yaml:3-4`）：** 兩者都指向 `dataset/images`，所以驗證指標會偏高、不可信。`spec.md:45-46` 的建議是 8:2 且同一支影片的影格不要跨集。
3. **類別不平衡：** `spec.md:21-40` 的標註數：`sewer_Pipe_break` 161、`sewer_scaling` 118，`sewer_bulletin`（:30）與 `sewer_HM_flake`（:39）各只有 1 筆。1 筆的類別在 8:2 切分後必然只出現在其中一側。
4. **標註缺漏：** CLAUDE.md 記載 425 張影像僅 275 份標註，尚待確認是刻意的背景圖還是漏標（我沒有讀 `dataset/images`，此項依 CLAUDE.md，未獨立驗證）。
5. 依 CLAUDE.md，改 `data.yaml` 前要先跟使用者確認，本次審查沒有動它。

## 二、測試缺口

### 2.1 目前有無測試
**沒有。** 在根目錄用 Glob 找 `test_*.py` 與 `conftest.py` 都沒有結果；根目錄 `*.py` 清單只有 `train_yolov8_local.py`、`save_annotated_images.py`、`inference_video.py`、`all_in_one_processing_bbox_ocr_cloaud.py`、`all_in_one_processing_bbox_easyocr.py`。（我沒有再找 `tests/` 子目錄與 pytest 設定檔，因範圍限制只用具體的檔名模式。）因此驗收指令中的 `pytest` 目前沒有東西可跑。

### 2.2 無法自動驗證的環節
1. **OCR 距離解析：** `parse_distance_flexible`（`all_in_one_processing_bbox_easyocr.py:91`）與 `parse_region_specific_text`（:138）都是純函式，卻沒有任何斷言。
   - 現況行為有疑點，例如「方法 3」是死碼（:112），任意數字都被當距離（:105）。
   - `inference_video.py:18` 的 `parse_distance` 與 paddle 版（`all_in_one_processing_bbox_ocr_cloaud.py:100`）各有不同實作，三版行為沒有一致性驗證。
   - 目前無法判斷「正確率 ≥ ＿＿%」（`spec.md:54`）。
2. **管徑解析：** `parse_pipe_diameter_flexible`（:121）會把任何 2–4 位數字視為 DN，容易誤報。
3. **時間點與異常合併：** 合併邏輯內嵌在 :312-368 的大迴圈中，無法單獨呼叫測試。
   - 目前合併的是影格編號，不是時間，沒有 fps 換算。
   - 同一影格多框的 OCR 共用邏輯、無偵測就不輸出（連 OCR 都不跑，:312）的行為都沒有驗證。
   - paddle 版後區域覆蓋前區域的 bug（:396-401）也沒有被任何測試捕捉到。
4. **CSV 編碼與檔名慣例：** `utf-8-sig`（:402、:419）與 `detection_results_YYYYMMDD_HHMMSS.csv`（:441-442）是 CLAUDE.md 的慣例，但只在 `__main__` 內，且 paddle 版（:461）與 `inference_video.py`（:211）違反慣例。目前無法自動確認。
   - 另外：`Distance` 欄位以字串或空字串存放（:149），`inference_video.py:187` 則存 float/None，欄位型別不一致。
5. **類別重編：** 目前不存在重編腳本（G5 的 g5-2 尚未做）。需要驗證的項目：(a) 15–32 對映到 0–17，(b) 所有標註檔的 class id 同步改寫，(c) `data.yaml` 的 nc 與 names 一致，(d) 切分時不可有同一支影片的影格跨 train／val。這些都還沒有可測試的程式。
6. **路徑可攜性：** `data.yaml:3-4` 與 `train_yolov8_local.py:7` 的 Linux 絕對路徑沒有任何檢查，Windows 上才會在訓練時失敗。
7. **OCR 區域裁切：** 裁切邊界計算（:64-71）在 :321-327 又重複一份，沒有單元測試；越界、零面積的處理沒有驗證。

### 2.3 建議的最小測試清單（依優先順序）
| 優先 | 測試 | 目標 | 說明 |
|---|---|---|---|
| P0 | 路徑檢查：`data.yaml` 與訓練腳本不得含 `/home/`，train 與 val 不得相同 | `data.yaml:3-4`、`train_yolov8_local.py:7,24` | 純文字檢查，不需 GPU，立即可寫 |
| P0 | 距離解析表驅動測試（「距離:12.5」、「距12.5m」、「12.5」、「」、亂碼、「1.2.3」） | `all_in_one_processing_bbox_easyocr.py:91` | 先釘住現況，再修；並與 paddle 版／舊版做一致性比較 |
| P0 | 管徑與管材解析（「DN300」、「PVC DN200」、「坡度-1.5」不應被判成管徑） | :121、:138 | 會暴露誤報 |
| P1 | CSV 輸出：`utf-8-sig` BOM、檔名正則 `detection_results_\d{8}_\d{6}\.csv`、欄位清單 | :398-420、:441 | 需把輸出邏輯抽成函式；以 `tmp_path` 檢查 |
| P1 | 合併邏輯：以假的 YOLO result 物件驗證「每框一列、OCR 欄位正確帶入、無框不輸出」 | :312-368 | 需把迴圈內合併抽成函式；加上 fps → 秒的欄位後再測 |
| P1 | 類別重編：給定舊 id，輸出新 id；非下水道類別不會出現在標註中 | 尚未實作（`spec.md:42`） | 隨 g5-2 一起交付 |
| P2 | 影片切分：同一影片不跨 train／val、比例約 8:2、稀有類別處理 | 尚未實作（`spec.md:45`） | 隨 g5-2 |
| P2 | OCR 區域裁切邊界（越界、零面積） | :58-74 | 純 numpy 陣列即可 |
| P2 | 冒煙測試：用 1 張合成圖與 1 秒測試影片跑一輪（可用 CPU） | 整條主流程 | 需模型與 OCR 套件，放在 CI 以外手動跑 |

### 2.4 前置重構建議（讓以上測試可寫）
- 把解析函式抽到一個共用模組（例如 `ocr_parsing.py`），兩支主流程腳本共用，消除 paddle 版與 easyocr 版的重複。
- 兩個主流程腳本在 import 時就載入 `easyocr`／`paddleocr`（:11），所以在沒有該套件的環境下，連匯入純函式都會失敗；抽出模組後可避免這個問題。
- 在 `tests/` 底下加 pytest，並在專案根目錄加 `requirements.txt` 或 `pyproject.toml`，把測試依賴與 OCR 依賴分開。
- 以上建議都應先與使用者確認；舊版腳本依 CLAUDE.md 移到 `99_bk/` 並加 `-MMDDHHMM` 後綴。

## 三、結論
- 主流程單一而清楚，但邏輯集中在一個超長函式，OCR 解析規則存在已知誤判（任意數字當距離、任意 2–4 位數當 DN）。
- Linux 絕對路徑集中在 `data.yaml:3-4` 與 `train_yolov8_local.py:7,24`，且訓練腳本會覆寫 `data.yaml`，這是 Windows 本機訓練前必須先處理的第一個阻礙。
- 目前零測試。最划算的起點是 P0 三項：路徑／train-val 檢查、距離解析、管徑解析，都是純函式或純文字，不需 GPU。
- 本報告所有判斷都以上列檔案行號為依據；未讀取被禁止的目錄，標註數與 425／275 的數字來自 `spec.md` 與 CLAUDE.md，未獨立驗證。