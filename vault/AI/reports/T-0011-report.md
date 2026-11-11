# T-0011 legion.checks 實際來源位置查證報告

## 結論摘要
- **推定的 `legion.checks.__file__`：`D:\202611_agent-legion\src\legion\checks.py`**。這是靜態推論的結果。我沒有 shell 工具，無法執行 `python -c "import legion.checks as m; print(m.__file__)"`，所以不是 runtime 輸出。
- 型態是 **editable install**，用 setuptools 的 `.pth` 方式，指向 `src` 目錄。它不是 site-packages 裡的複本，不是 pyc-only，不是 zip／egg，也不是 namespace package。
- 目標 repo `D:\PipeAI_wmt` 內沒有 legion 原始碼。E-004 能執行、E-008 說找不到，兩者並不矛盾（見「E-008 差異解釋」）。

## 架構

### 1. 實際路徑與安裝方式
- `D:\202611_agent-legion\.venv\Lib\site-packages\__editable__.legion-0.4.0.pth:1` 的內容只有一行：`D:\202611_agent-legion\src`。
  - Python 啟動時 site 模組會讀取 `.pth`，把這個目錄加進 `sys.path`，所以 `import legion` 會解析到 `src\legion`。
  - 檔名 `legion-0.4.0` 顯示安裝的版本是 0.4.0。
- `D:\202611_agent-legion\pyproject.toml:6` 是 `name = "legion"`，`:7` 是 `version = "0.4.0"`，與上述 `.pth` 檔名一致。
- `D:\202611_agent-legion\pyproject.toml:35-36` 的 `[tool.setuptools.packages.find] where = ["src"]` 表示套件根目錄是 `src`。
- `D:\202611_agent-legion\.venv\pyvenv.cfg:1-3`：
  - `home = C:\Program Files\Python310`
  - `include-system-site-packages = false`
  - `version = 3.10.11`
  - 所以直譯器是 venv 內的 `D:\202611_agent-legion\.venv\Scripts\python.exe`（Glob 已確認此檔存在），不會看到系統 site-packages。
- `.venv\Lib\site-packages` 下用 `*legion*` 搜尋只找到上面那個 `.pth`。用 `**/legion/**` 搜尋沒有結果，所以 site-packages 內沒有 legion 的已安裝複本。

### 2. import 解析鏈（推定）
1. 用 venv 的 python 啟動，`sys.executable` 應為 `D:\202611_agent-legion\.venv\Scripts\python.exe`。
2. site 處理 `__editable__.legion-0.4.0.pth`，把 `D:\202611_agent-legion\src` 加進 `sys.path`。
3. `import legion` 解析到 `D:\202611_agent-legion\src\legion\__init__.py`（Glob 已確認存在）。因為有 `__init__.py`，它是一般套件，不是 namespace package。
4. `legion.checks` 解析到 `D:\202611_agent-legion\src\legion\checks.py`，origin 是 `.py` 原始碼。
5. `python -m legion.checks` 會執行 `checks.py:216-217` 的 `if __name__ == "__main__": sys.exit(main())`。

### 3. 重要但未驗證的前提
驗收指令是在 runner 的工作目錄 `D:\PipeAI_wmt` 執行 `python`。若那裡的 `python` 不是 `.venv` 的直譯器，import 就不會成功。E-004 能執行，暗示 runner 用的是 legion 的 venv，但我沒辦法從這裡證實。

### 4. 模組結構與 checks 入口
`D:\202611_agent-legion\src\legion\` 下有這些模組（Glob 結果）：`models`、`evidence`、`record`、`export`、`config`、`checks`、`risk`、`installs`、`cli`、`db`、`demo`、`agents`、`runner`、`vault`、`prompts`、`__main__`、`__init__`。

`checks.py` 的結構：
- `checks.py:18` 從 `.record` 匯入 `CHAPTERS`，所以 checks 依賴 record。`checks.py:16` 依賴 pydantic。
- `checks.py:25-42` 定義 `RecordCheck`（pydantic model）和 `ok` 屬性。
- `checks.py:45` `_sections`、`:61` `parse_ledger`、`:72` `narrative_violations`、`:103` `check_record`、`:150` `append_csv`。
- `checks.py:166` `check_report(path, sections, min_chars)`。這是唯讀任務驗收用的函式：
  - 報告不存在回 1（`:167-169`）。
  - 缺章節或字元數不足回 1（`:176-181`）。
  - 通過印 `OK` 並回 0（`:182-183`）。
  - 章節比對方式：標題行（以 `#` 開頭）是否含該字串（`:171-172`）。
- `checks.py:186` `main()`，有兩個子指令：
  - `record`（`:189-193`），參數有 `--criteria-json`、`--criterion`、`--csv`。
  - `report`（`:194-197`），參數有 `path`、`--section`（可重複）、`--min-chars`（預設 800）。
- 模組 docstring（`checks.py:3`）只寫了 `record` 的用法，沒提 `report`。
- `D:\202611_agent-legion\src\legion\__main__.py` 存在，是 `python -m legion` 的入口。它與 `python -m legion.checks` 是分開的路徑，後者由 `checks.py` 自己的 `__main__` 判斷處理。

### 5. 其他模組如何使用 checks
- `D:\202611_agent-legion\src\legion\runner.py:26` 匯入 `narrative_violations`。
- `runner.py:347-348` 會移除規劃者自己抄的 `legion.checks report` 驗收指令，再附加 runner 版本：`python -m legion.checks report "{rp}" --section 架構 --section 測試缺口`。
- `D:\202611_agent-legion\src\legion\risk.py:16` 用正規表示式把 `python -m legion.checks` 加進白名單，`:70` 在 argv 判斷中也有對應處理。
- `D:\202611_agent-legion\src\legion\prompts.py:91` 與 `:106` 在提示詞中說明這條指令，`:150` 針對 readonly 任務挑出 runner 版指令。
- `D:\202611_agent-legion\src\legion\record.py:4` 的註解提到 `checks.narrative_violations`。

## E-008 差異解釋
- **主因（高度可能）：搜尋範圍只涵蓋目標 repo。** `D:\PipeAI_wmt` 內完全沒有 "legion" 字樣，而原始碼在另一個專案 `D:\202611_agent-legion\src`。editable install 讓 import 成功，但在目標 repo 裡搜不到。
- 次因：因為是 editable install，`site-packages` 內只有一個 `.pth`（`__editable__.legion-0.4.0.pth:1`），沒有 `legion` 目錄。若 E-008 去 site-packages 找套件目錄，也會找不到。
- 排除：不是 pyc-only，也不是 zip。`src\legion\checks.py` 是明文 `.py`。

## 測試缺口

### 現有測試（D:\202611_agent-legion\tests\）
- `test_vault_record.py:14` 匯入 `check_record`、`narrative_violations`。`:82` 的 `test_record_checker_detects_untraceable_and_uncited` 覆蓋 record 檢查（證據不可追溯、段落未引用）。
- `test_loop.py:227` `test_readonly_task_reports_and_leaves_repo_untouched`：
  - `:232` 斷言 `accept_cmds` 含 `legion.checks report`。
  - `:233` 讀取 verify_runs 的 checks。
- `test_loop.py:256-257`：規劃者抄的 report 指令不重複，且只有一條。
- `test_loop.py:260` `test_readonly_task_without_proper_report_is_not_accepted`：間接覆蓋報告不合格的情況。
- 其餘測試檔：`conftest.py`、`test_resume.py`、`test_installs.py`。
- pytest 設定在 `pyproject.toml:38-39`，`testpaths = ["tests"]`。

### 缺口
1. **沒有 `check_report` 的直接單元測試。** Grep 在 tests 內沒有找到直接呼叫 `check_report` 的測試。它只被 `test_loop.py` 在整合層間接涵蓋。以下情況沒有被獨立驗證：
   - 報告檔不存在。
   - 字元數低於 `--min-chars`。
   - 缺少章節。
   - 多個 `--section` 同時使用。
   - 章節比對是子字串比對，所以「架構」出現在任何標題中就算通過（`checks.py:172`）。
2. **沒有 `main()` 與 `python -m legion.checks` 的 CLI 測試。** 以下情況沒有測試：
   - 子指令解析（`checks.py:186-198`）。
   - 回傳碼。
   - `record` 分支多檔、`--csv`、`--criterion` 與 `--criteria-json` 優先序（`:201`）。
3. **`append_csv`（`checks.py:150`）沒有直接測試**，包含新建表頭與附加寫入。
4. **沒有 import 來源或安裝方式的測試**（例如確認 `legion.checks.__file__` 在 `src` 下）。這正是 E-004 與 E-008 不一致的根源。
5. `min_chars` 用 `len(text)` 計算字元數（`checks.py:176`），中文與英文都算一個字元，沒有針對中文報告的邊界測試。

### 實作任務前置條件建議
- 先確認 runner 實際使用的 `python` 是 `D:\202611_agent-legion\.venv\Scripts\python.exe`，並在有 shell 的環境補跑：
  - `python -c "import legion.checks as m; print(m.__file__)"`
  - `python -c "import legion,sys; print(legion.__file__, list(legion.__path__), sys.executable, sys.path)"`
  - `python -c "import importlib.util as u; s=u.find_spec('legion.checks'); print(s.origin, s.submodule_search_locations)"`
  - `pip show -f legion`
- 若後續要改 `checks.py`，應先為 `check_report` 與 `main` 補測試，再改程式。
- 改 legion 屬於另一個 repo（`D:\202611_agent-legion`），任務規格要明確寫出這點，並與 `D:\PipeAI_wmt` 的工作範圍分開。

## 未能確認之處
- **沒有任何 runtime 輸出。** 本次執行環境只有 Read／Glob／Grep，沒有 shell，所以以下都沒有實測：`legion.checks.__file__`、`legion.__file__`、`legion.__path__`、`sys.executable`、`sys.path`、`find_spec` 的 origin 與 submodule_search_locations、`pip show -f legion` 的 Location。以上數值都是由 `.pth`、`pyproject.toml`、目錄結構推定。
- 沒有確認 `.venv` 之外是否還有另一份 legion（例如全域 site-packages）。`C:\Users\User\AppData\Local\Programs\Python` 不存在；`C:\Program Files\Python310` 我沒有搜尋。
- 沒有確認是否有 `.pyc` 快取，也沒有確認 `.pth` 指向的原始碼與已載入的版本一致。
- 沒有開 `__init__.py`、`__main__.py` 讀內容，所以沒有確認版本字串，也不知道 `legion.__path__` 是否有其他內容。
- 沒有讀 `D:\202611_agent-legion\03_docs\spec.md`，沒有確認它對 E-004、E-008 的描述。
- 沒有掃描 `D:\PipeAI_wmt` 內的 `result/`、`annotated_images/`、`dataset/images`，也沒有遞迴掃描任何大型資料夾。所有搜尋都限定在 legion 專案的 `src`、`tests` 與 `.venv\Lib\site-packages` 的檔名。
