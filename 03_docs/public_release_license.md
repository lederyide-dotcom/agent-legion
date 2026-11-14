# 公開版授權方案

> **2026-11-14 作者決定採方案 A**（inbox D12）：程式碼 PolyForm Noncommercial 1.0.0、文件 CC BY-NC-SA 4.0。目前版本仍保留所有權利，**公開時才切換**。不是法律意見。
>
> 已先做：`NOTICE` 加上 PolyForm 要求的 `Required Notice:` 行（現在加不影響保留所有權利）。
> 公開時再做：放入兩份授權全文（從官方取得：https://polyformproject.org/licenses/noncommercial/1.0.0/ 、https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode ），並完成下方「公開前都要做」清單。

## 先釐清：CC 授權不適合程式碼

Creative Commons 官方建議**不要**把 CC 授權用在軟體上，因為 CC 沒有處理原始碼散布、專利等軟體特有的問題。比較常見的做法是分開授權：

- **程式碼**（`src/`、`scripts/`、`tests/`）：使用軟體授權。
- **文件、圖表、說明**（`README.md`、`03_docs/`、圖片）：使用 CC 授權。

## 候選方案

| 方案 | 程式碼 | 文件 | 別人可以商業使用嗎 | 保護作者署名的方式 | 適合的情況 |
|---|---|---|---|---|---|
| A. 署名＋非商業（推薦） | PolyForm Noncommercial 1.0.0 | CC BY-NC-SA 4.0 | 不行，商業使用要另外向作者取得授權 | PolyForm 只強制轉發授權條款與以 `Required Notice:` 開頭的行，所以 NOTICE 要寫成 `Required Notice: Copyright 2026 DavidY-tw (https://github.com/lederyide-dotcom/agent-legion)`；CC BY-NC-SA 要求依 TASL 標示 | 想公開展示、讓人學習，但保留商業價值 |
| B. 開源＋署名 | Apache-2.0 | CC BY 4.0 | 可以 | Apache-2.0 第 4 條要求散布時保留 `NOTICE` 檔；CC BY 要求依 TASL 標示 | 想要更多人採用、累積作品集聲量 |
| C. 只公開文件 | 不公開 | CC BY-NC-ND 4.0 | 不行，也不得改作 | 只能原樣轉載並標示 | 只想展示設計與成果，程式碼不公開 |

說明：

- **PolyForm Noncommercial** 是為軟體寫的非商業授權，允許個人學習、研究、非營利使用，禁止商業使用。它不是 OSI 認可的開源授權。
- **Apache-2.0** 是開源授權。散布衍生作品時必須附上 `NOTICE` 檔中相關的標示，作者與出處因此會跟著散布的副本走（但不涵蓋程式執行的輸出，NOTICE 裡的附加要求也只供參考）；缺點是別人可以合法商業使用。
- **CC BY-NC-SA 4.0**：署名、非商業、改作須以相同條款分享。**CC BY-NC-ND 4.0**：署名、非商業、禁止改作。

## 不管選哪個，公開前都要做

1. 把 `LICENSE` 換成選定的授權全文（程式碼與文件分開時，加上 `LICENSE-docs`），依選定的授權改寫 `NOTICE`（方案 A 要用 `Required Notice:` 格式），保留 `CITATION.cff` 並更新版本與日期。
2. 改寫 `03_docs/sharing_and_citation.md` 與 `LICENSE` 裡「看得到或 clone 不代表授權」等只適用私人版本的文字：repo 公開後，依 GitHub 服務條款，其他使用者可以在 GitHub 上檢視與 fork。
3. 重新檢查公開範圍：`02_data/`、`03_docs/progress.md`、`vault/` 裡可能有目標 repo 名稱、路徑、花費等資訊，公開前要另外去敏感化。
4. 確認第三方套件的授權與選定方案相容（目前的相依套件都是寬鬆授權，例如 MIT、BSD、Apache，但 matplotlib、pillow 等要再核對一次）。
5. 檢查 git 歷史有沒有不適合公開的內容；必要時以乾淨的歷史建立公開 repo，不直接把私人 repo 改成公開。
6. 在 README 開頭寫明授權與署名要求，並保留 `legion --version` 等內建標示。
