@echo off
chcp 65001 >nul
REM 一鍵啟動：啟動 DB、建表、建 vault 骨架、跑 mock demo（零成本）
setlocal
cd /d "%~dp0.."

echo [1/5] 啟動 PostgreSQL（Docker）
docker compose up -d db || exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\wait_db.ps1 || exit /b 1

echo [2/5] 檢查 Python 與 Node 環境
if not exist .venv\Scripts\python.exe (
  py -3.10 -m venv .venv || exit /b 1
  .venv\Scripts\python.exe -m pip install -r requirements.lock || exit /b 1
  .venv\Scripts\python.exe -m pip install -e . --no-build-isolation --no-deps || exit /b 1
)
if not exist tools\mermaid\node_modules (
  set PUPPETEER_SKIP_DOWNLOAD=1
  call npm ci --prefix tools\mermaid || exit /b 1
)

echo [3/5] 建表
.venv\Scripts\python.exe -m legion init-db || exit /b 1
.venv\Scripts\python.exe -m legion --schema demo init-db || exit /b 1

echo [4/5] 建 vault 骨架
.venv\Scripts\python.exe -m legion init-vault || exit /b 1

echo [5/5] 跑 mock demo
.venv\Scripts\python.exe -m legion demo --mock || exit /b 1
echo 完成。用 Obsidian 開啟 vault 資料夾即可看到 AI\儀表.base、AI\流程.canvas 與 AI\records\
endlocal
