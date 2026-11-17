# spec：legion scout，找有價值的 GitHub repo（不只看星數）（2026-11-17，David 選 A）

## 最終目標
`legion scout "關鍵字"` 從 GitHub 搜出候選，抓客觀數據，依 6 類指標打分排名，產出可追溯的 JSON 與報告。每個分數都附原始數字。不用 AI、不放寬 agent 權限（agent 仍不能上網）。

## 指標（每類 0～100 分，預設權重可用 `--weights` 覆寫）
| 類別 | 權重 | 數據（來源） | 滿分條件 → 零分條件 |
|---|---|---|---|
| 活躍度 activity | 0.20 | 近 90 天 commit 數、距最後 push 天數、近 365 天 release 數（commits、releases API） | commit ≥100、push ≤30 天、有 release → 一年沒動 |
| 維護 maintenance | 0.20 | 最近 50 個 issue 的關閉比例與關閉天數中位數、最近 50 個已關閉 PR 的合併比例（issues、pulls API） | 關閉 ≥80%、中位數 ≤7 天、合併 ≥70% → 都不處理 |
| 人員 people | 0.15 | 近 90 天不同 commit 作者數、歷來第一大貢獻者佔比（commits、contributors API） | ≥5 人、≤50% → 1 人、100% |
| 採用 adoption | 0.15 | 星數、fork 數（對數刻度） | 星 ≥50k、fork ≥5k |
| 動能 momentum | 0.10 | 近 90 天新增星數（stargazers API 帶時間戳，最近 100 筆） | ≥100 → 0 |
| 成熟度 maturity | 0.20 | 社群健康度 %、有無 CI workflow、授權、OpenSSF Scorecard 分數（community、contents、scorecard API） | 各項齊全 → 都沒有 |

- 已封存（archived）：總分 ×0.2，並標記。
- 取不到的數據記為 null，該項分數依其餘子項計算，並在報告列出「缺資料」。整類都沒資料時該類顯示「—」，不當 0 分，權重按比例分給其他類。
- 實測（2026-11-17）：GitHub 的 stargazers 清單 REST 回 404、GraphQL 回 0 筆，「動能」目前量不到，依上一條處理。
- 未涵蓋：被多少專案依賴（GitHub 的 Used by 沒有 API；deps.dev 要套件名稱），報告註明。

## 候選
同一個查詢跑兩次搜尋（依星數、依相關度），各取前 N（預設 25），合併去重；`--lang`、`--license`（多個用逗號）加進查詢條件；`--top` 決定報告列幾名（預設 10）。

## 輸出
- `02_data/scout/<日期時間>_<關鍵字>.json`：查詢條件、權重、每個 repo 的原始數據、各類分數、總分、名次。
- `vault/AI/scout/<日期時間>_<關鍵字>.md`：排名表＋每個 repo 的分數拆解與數據（手機文件庫可看）。

## 驗收標準
- [ ] `pytest tests/test_scout.py`：評分函式邊界（滿分、零分、缺資料）、封存懲罰、權重覆寫與驗證、兩次搜尋合併去重、報告含原始數字。用假的抓取器，不連網。
- [ ] 對照案例：同樣星數下，停更、單人維護的 repo 排在活躍、多人維護的後面（假資料）。
- [ ] 實跑一次真實關鍵字，產出 JSON 與報告，紀錄 API 用量與耗時。
- [ ] README、覆蓋測試、全套通過；code-reviewer 無 🔴。

## 可以自行決定
子分數的曲線、報告版面、CLI 參數名稱、並行數。

## 必須停下來問我
放寬 agent 上網權限；付費 API；改預設權重以外的評分理念。
