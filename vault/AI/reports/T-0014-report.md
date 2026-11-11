# T-0014 補查 PipeAI_wmt 測試檔案（唯讀）

查詢日期：2026-11-11。範圍：`D:\PipeAI_wmt` 根目錄 Glob、`99_bk/*`、`03_docs/*`、`02_data/*`，以及對 `*.py` 內容的 Grep。**未**遞迴讀取 `result/`、`annotated_images/`、`dataset/images`。未寫檔、未安裝、未讀 `.env` 或金鑰。

## 架構

根目錄的 Python 腳本共 5 支（Glob `*.py` 的結果，路徑相對於 `D:\PipeAI_wmt`）：

| 檔案 | 用途（依 CLAUDE.md 描述，本次未開檔核對內容） |
|---|---|
| `train_yolov8_local.py` | YOLO 訓練 |
| `all_in_one_processing_bbox_easyocr.py` | 影片批次推論加 EasyOCR，為主流程 |
| `all_in_one_processing_bbox_ocr_cloaud.py` | 同上，OCR 改用 PaddleOCR |
| `inference_video.py` | 舊版推論加 pytesseract |
| `save_annotated_images.py` | 輸出標註影像 |

資料夾與其他檔案：
- `99_bk/` 有 2 支舊版備份：`99_bk\all_in_one_processing_bbox_easyocr-10150917.py` 和 `99_bk\all_in_one_processing_bbox_easyocr-10150211.py`。檔名時間戳格式 `-MMDDHHMM` 符合 CLAUDE.md 慣例。
- `03_docs/` 只有 `03_docs\spec.md`。
- `02_data/` 查無任何檔案（Glob `02_data/*` 無結果）。
- 依 CLAUDE.md，另有 `result/`、`annotated_images/`、`dataset/`、`video/`、`runs/` 和 `best.pt` 等。這些本次均未遞迴讀取。

依賴宣告方式：根目錄沒有 `requirements.txt`、`pyproject.toml`、`setup.cfg`、`tox.ini`、`setup.py`、`Pipfile`、`environment.yml`（見下方 Glob 結果）。依賴只靠各腳本的 import，以及 CLAUDE.md 文字說明（`py -3.10` 加專案 venv、對應 CUDA 的 PyTorch）。環境無法由檔案重現。

## 測試缺口

### 查詢紀錄

| # | 指令／pattern | 範圍 | 結果 |
|---|---|---|---|
| 1 | Glob `*_test.py` | 根目錄 | 無 |
| 2 | Glob `test_*.py` | 根目錄 | 無 |
| 3 | Glob `{pytest.ini,pyproject.toml,requirements*.txt,setup.cfg,setup.py,tox.ini,conftest.py,Pipfile,environment.yml}` | 根目錄 | 無 |
| 4 | Glob `tests/*` | 根目錄 | 無 |
| 5 | Glob `*.py` | 根目錄（結果也列出 `99_bk` 內 2 支） | 共 7 支，皆非測試檔名（5 支主腳本加 99_bk 2 支） |
| 6 | Glob `99_bk/*` | `99_bk` | 只有 2 支舊版 `.py`，無測試相關檔 |
| 7 | Glob `03_docs/*` | `03_docs` | 只有 `03_docs\spec.md` |
| 8 | Glob `02_data/*` | `02_data` | 無 |
| 9 | Grep `import pytest\|unittest\|def test_`，glob `*.py`，路徑 `D:\PipeAI_wmt` | 所有 `.py` | No matches found（無任何檔案:行號命中） |

### 結論

**專案沒有測試。** 在上述範圍內，沒有測試檔、測試目錄、測試框架設定（pytest、tox、conftest）或依賴宣告檔，各腳本內也沒有內嵌的 `pytest`、`unittest` 或 `def test_`。T-0010 的結論成立。

限制：結論僅限根目錄、`99_bk`、`03_docs`、`02_data` 與 `*.py` 內容。其他子資料夾，如 `runs/`、`video/`，以及非 `.py` 的檔案（例如 `.sh`）沒有逐一查驗。`result/`、`annotated_images/`、`dataset/images` 依規定排除。Grep 以專案根目錄為路徑、限 `*.py`，理論上可能涵蓋 `result/` 等目錄中的 `.py`。這些目錄預期只含影像與 CSV，但本次沒有另外確認。

### 缺口

1. **完全沒有自動化測試**：推論、OCR 解析、CSV 輸出（`utf-8-sig`、檔名 `detection_results_YYYYMMDD_HHMMSS.csv`）全靠人工執行驗證。
2. **沒有依賴宣告檔**：無 `requirements.txt` 或 `pyproject.toml`，環境無法重現，也無法在 CI 或另一台機器建立測試環境。
3. **沒有測試設定**：無 `pytest.ini` 或 `conftest.py`。
4. **主流程難以單元測試的風險**：腳本是 all-in-one 結構，邏輯與 I/O、模型載入耦合。這是依檔名與 CLAUDE.md 的推測，本次未開檔驗證。

### 建議

以下為建議，本任務未執行：
- 新增 `requirements.txt`，鎖定 ultralytics、easyocr、paddleocr 等版本。
- 新增 `tests/`，先抽出可純函式測試的部分：OCR 字幕解析（距離、管徑）、類別對應、CSV 欄位與檔名格式。
- 加入小型 fixture，例如單張影像或短片，不依賴 `result/` 的大量資料。
- 加入 smoke test：模型載入加單張推論，GPU 不可用時自動 skip。
- 在 `data.yaml` 類別重編（g5-2）之前，先為類別對應寫測試，避免重編後回歸。
- 這些變更需另開任務，並遵守 CLAUDE.md 對 `best.pt`、`runs/`、`result/` 不得覆寫的限制。
