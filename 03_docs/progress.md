# 進度（2026-11-11）

## 已完成
- 開工查證：claude 2.1.319；權限語法（docs＋實測）；排程下訂閱登入可用；Codex 未安裝 → 02_data/env_check.md
- 骨架、鎖版本 venv、mermaid-cli（借用 Edge）、Docker PostgreSQL 16.6（埠 55432）
- runner 閉環、風險／安裝分級、熔斷、可重入續跑、vault 匯出、紀錄文件、證據、docx／pdf 匯出、mock demo
- pytest 全數通過；start.bat 從乾淨狀態實測通過；verify_artifacts.py 通過

## 進行中
- 實戰 B（sandbox_repo 新增 word_count，真實 claude -p）

## 下一步
- 實戰 A：等 David 提供目標 repo 路徑（spec 規定必須問）
- code-reviewer 審查 → 修 🔴 → 02_data/verify_20261111.md

## 已知問題
- Bash 白名單不是硬邊界（內建唯讀指令如 whoami 會自動放行）；由 runner 事後檢查承擔
- 真實任務的回灌想法會留在 INBOX，下一次 tick 會被領取並花費額度
