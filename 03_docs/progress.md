# 進度（2026-11-11 07:55）

## 已完成
- 開工查證（02_data/env_check.md）：claude 2.1.319；權限語法（docs＋實測）；排程下訂閱登入可用；Codex 未安裝
- runner 閉環、風險／安裝分級、熔斷、可重入續跑、vault、紀錄文件、證據、docx／pdf 匯出、mock demo
- 實戰 B（T-0005）：DONE，$0.1669，human_touches 0 → 02_data/sandbox_check.txt
- code-reviewer 審查：🔴 8 項已修（見下）；pytest 68 項全過；start.bat 從乾淨狀態實測通過

## 等待 David
- 實戰 A 的目標 repo 路徑（spec 規定必須問）

## 事故紀錄（誠實揭露）
1. demo 想法檔留在共用 INBOX，被正式 tick 以真實 Claude 誤領取（T-0001～T-0004，約 $0.65）。
   已 cancel（HALT: operator_cancel）；修正：demo 結束清除 INBOX、真實 backend 跳過帶 mock 劇本的檔案、領取後封存到 AI/inbox_done/。
2. 第二次從乾淨狀態實測 start.bat 時執行了 `docker compose down -v`，連帶清掉正式 schema 的 DB 紀錄
   （T-0001～T-0005 的 tasks／task_events／agent_runs）。vault 筆記、record.md、證據檔已在 git，不受影響。
   修正：任務編號同時參考 vault 既有筆記，DB 重建不會覆蓋舊紀錄；INBOX 領取後封存，不會被重複領取。
3. 安裝清冊 DEV 列的時間最初是我估填的整點時間，後來改為檔案實際建立時間（事後補記，非安裝當下寫入）。

## 已知限制
- Bash 白名單不是硬邊界；硬邊界由 runner 承擔（VERIFY 親自執行、實際 diff 重判風險、worktree 外狀態比對、證據雜湊）
- 重試次數為 SPEC_REVIEW 退回、VERIFY 失敗、REVIEW 退回的合計
- 「官方發行頁」安裝本輪一律轉人工（比 spec 嚴格）
- 實戰 B 回灌的後續想法 fu-T-0005-1.md 暫放 vault/AI/inbox_hold/，等 David 決定是否放回 INBOX
