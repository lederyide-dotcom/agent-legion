---
id: T-0012
title: 實作 report 檢查擴充（--require-refs／--require-tags）
doc_status: 草稿（AI 產生，未經核可）
version: '0.4'
state: WAIT_HUMAN
risk: high
cost_usd: 0.060679
human_touches: 0
approved_by: null
approved_at: null
---

> [!warning] 草稿（AI 產生，未經核可）

# 開發紀錄：實作 report 檢查擴充（--require-refs／--require-tags）（T-0012）

## 1. 文件資訊

| 欄位 | 內容 |
|---|---|
| 編號 | T-0012 |
| 任務 | 實作 report 檢查擴充（--require-refs／--require-tags） |
| 日期 | 2026-11-11 20:55:51 |
| 版本 | 0.4（step 4） |
| 狀態 | WAIT_HUMAN |
| 文件狀態 | 草稿（AI 產生，未經核可） |
| 風險等級 | high |
| 成本（USD，用戶端估算） | 0.0607 |
| 人工介入次數 | 0 |
| 上層任務 | T-0009（深度 2） |

## 2. 目標與範圍

以下引自規格 `specs/T-0012.md`：

> # T-0012 report 檢查擴充（--require-refs／--require-tags）設計與實作提案（唯讀）
>
> ## 前提與限制
> - 目標 repo 是 agent-legion（`D:/202611_agent-legion`），但工作目錄是 `D:\PipeAI_wmt`（與目標無關）。本任務為 readonly，執行者不能寫檔，所以**不會真的改程式**。
> - 交付物是完整報告（放在 `report_md`）：依 T-0009 報告的設計，給出可直接套用的實作提案（含 diff 草稿）。實際改碼要另開 write 任務，目標 repo 為 agent-legion。
> - 執行者只讀 T-0009 報告與 agent-legion 的 `legion/checks`（含 report 子命令）及其測試。不得讀 `.env`、金鑰、憑證。
>
> ## 目標
> 1. 為 `python -m legion.checks report` 設計兩個新選項：
>    - `--require-refs`：要求報告的發現附「檔案:行號」引用。
>    - `--require-tags`：要求報告含指定標籤。
> 2. 補上遷移期限：預設關閉（或僅警告），經過一個遷移期後再升級為強制。需寫明期限日期、警告文字與升級條件。
> 3. 補上 E-008 案例：`file.py:12:34`（含欄號）必須被視為合法引用，並涵蓋 `file.py:12`、`file.py:12-20`、Windows 路徑 `C:\x\file.py:12:34`。
> 4. 保持向後相容：不加旗標時行為與 exit code 不變；警告模式輸出到 stderr 且 exit 0，嚴格模式才 exit 非 0。
>
> ## 範圍
> - 內含：架構（模組、函式、參數流程、regex 草稿、警告／嚴格模式）；測試缺口（現有測試未涵蓋的項目與新增測試清單）；每個發現附檔案:行號。
> - 不含：修改任何檔案、安裝套件、push／merge。
>
> ## 報告必備章節
> 報告須含 `## 架構` 與 `## 測試缺口` 兩個章節（runner 會檢查），另建議含「遷移計畫」「E-008 案例」「風險與開放問題」。
>
> ## 驗收標準
> 1. 報告章節齊全、長度足夠（runner 自動附加的 `legion.checks report` 檢查）。
> 2. 報告中每個發現都附檔案:行號，並指出 T-0009 設計與現況程式碼的差異（由人工審查）。
> 3. 目標 repo 與工作目錄在執行前後 HEAD 與 `git status --porcelain` 相同（未被修改）。
> 4. 報告明確列出預設行為（關閉或警告）、遷移期限日期，以及 E-008 的測試案例。

風險判定理由（程式判定）：

- high: 動作 message
- agent 提議 low，依規則改為 high（不可降級）

## 3. 執行歷程

| # | 狀態 | 開始 | 結束 | 負責角色 | 模型 | agent 耗時（秒） |
|---|---|---|---|---|---|---|
| 1 | INBOX | 2026-11-11 20:55:51 | 2026-11-11 20:55:51 | Runner | — | — |
| 2 | PLAN | 2026-11-11 20:55:51 | 2026-11-11 20:56:41 | 指揮官（planner） | sonnet | 15.3 |
| 3 | SPEC_REVIEW | 2026-11-11 20:56:41 | 2026-11-11 20:57:57 | 規格審查者 | sonnet | 7.3 |
| 4 | GATE | 2026-11-11 20:57:57 | 2026-11-11 20:58:16 | Runner | — | — |
| 5 | WAIT_HUMAN | 2026-11-11 20:58:16 | — | David | — | — |

## 4. 設計與變更說明

### 4.1 流程圖（Mermaid）

```mermaid
flowchart LR
    INBOX([INBOX]) --> PLAN([PLAN])
    PLAN([PLAN]) --> SPEC_REVIEW([SPEC_REVIEW])
    SPEC_REVIEW([SPEC_REVIEW]) --> GATE([GATE])
    GATE([GATE]) --> WAIT_HUMAN([WAIT_HUMAN])
```

### 4.3 變更檔案與 diff 統計

（尚無）

## 5. 驗證證據

### 5.1 驗收標準 1：`git status --porcelain`

（尚未執行驗證）

### 5.2 驗收標準 2：`git rev-parse HEAD`

（尚未執行驗證）

### 5.3 驗收標準 3：`python -m legion.checks report "D:/202611_agent-legion/vault/AI/reports/T-0012-report.md" --section 架構 --section 測試缺口`

（尚未執行驗證）

## 6. 審查紀錄

### 6.1 規格審查

- 第 1 次結論：pass（E-001）
- 發現：建議：驗收指令 `git status --porcelain` 與 `git rev-parse HEAD` 在工作目錄 D:\PipeAI_wmt 執行，無法驗證目標 repo（agent-legion）未被修改；請明示 runner 會對目標 repo 另行比對（-C 或 cwd），或規格註明規劃者指令僅針對工作目錄。；建議：驗收標準 4（預設行為、遷移期限日期、E-008 測試案例）與標準 2（每個發現附檔案:行號）只靠人工審查，runner 檢查只驗 `## 架構`、`## 測試缺口` 章節。可加 `--section 遷移計畫 --section E-008 案例`，但這條由 runner 附加，故僅作建議。；建議：遷移期限只寫「需寫明日期」，未給基準。今天是 2026-11-11，建議指定例如警告期至 2027-01-31、之後升級為強制，或寫明由執行者提議並說明理由。；建議：`--require-tags` 的標籤來源（CLI 參數值、清單格式、是否可重複）未定義，請要求報告明確設計，並涵蓋缺標籤時的警告與嚴格行為。；建議：規格說明工作目錄與目標無關，且執行者要讀 D:/202611_agent-legion 的檔案；請確認該路徑在唯讀權限內，並再次強調不得讀 `.env`、金鑰與憑證（規格已提到）。；建議：E-008 的 regex 草稿需區分 Windows 磁碟機代號 `C:` 與行號冒號；請要求測試清單含 `C:\x\file.py:12:34`、`file.py:12-20`、無行號的負面案例。（E-001）
- 處置：放行（E-001）

### 6.2 交付審查

（尚未進行）

## 7. 問題與教訓

- 重試次數：0
- HALT 原因：無

## 8. 附錄：證據清冊

| 證據編號 | 檔名 | SHA-256 | 產生時間 | 產生者 |
|---|---|---|---|---|
| E-001 | evidence/E-001_spec_review.json | 87d16876093ad3fd62e44e20bc4356b405fcaa388bcef7cfc55f1042fa3b0ac6 | 2026-11-11 20:57:57 | runner（記錄 spec_review session dcad6063-24cb-4b6d-83cb-8070e23465b2） |
