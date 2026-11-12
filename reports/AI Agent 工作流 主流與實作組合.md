# 主流收斂單線寫入，agent-legion 補強勝過重寫

到 2026 年 11 月，AI agent 自動化工作流的主流做法已收斂成同一個形狀：**一個總指揮擁有計畫與所有寫入、唯讀的子代理平行蒐集資訊、一個全新 context 的獨立驗證者、以及能讓新 session 接手的檔案與帳本紀錄**，人只在計畫核准與不可逆動作上把關。這個形狀與你自建的 agent-legion 閉環（規劃→規格審查→風險閘→執行→runner 親自驗證→交付審查→書記官）幾乎逐項對應，所以結論不是換框架，而是在現有 runner 上補四件事：依角色分配模型與 effort、把測試與設定用機械方式保護、加上唯讀平行、建立小型回歸評測。未來走向是 harness 變薄（模型變強後拆掉多餘的階段）、代理變成雲端常駐且可排程、協定統一在 MCP 與 A2A，客製工作會集中在 spec、驗收標準與評測，而不是編排程式碼。多代理的代價很實在：Anthropic 自己量到多代理系統用掉約 15 倍於聊天的 token，三代理 harness 的花費是單代理的 20 倍以上，所以在每日 $2 的預算下，「多派幾個 agent」本身不是進步，要用同預算對照才算數。本報告的來源品質不均：Claude Code 權限、sandbox、監控文件與部分 Anthropic 工程文章是實際開頁讀過的；多數 2026 年版本號、競品現況、學術論文數字來自搜尋摘要或研究者記憶，文中一律標示「二手」或「未驗證」。

## 各家都說先用單代理，多代理只贏在唯讀廣度

主流詞彙在 2024 年底就定型了。Anthropic 把系統分成 workflow（預先寫好的流程：prompt chaining、routing、parallelization、orchestrator-workers、evaluator-optimizer）與 agent（模型自己決定流程），並建議從最簡單的方案開始，只有在可量測地有幫助時才加複雜度（[Anthropic](https://www.anthropic.com/engineering/building-effective-agents)，未重新開頁，依研究者記憶）。OpenAI 的指南同樣主張先把單一 agent 用到極限，再考慮 manager（把專家當工具呼叫）或 handoff 兩種多代理模式（[OpenAI guide](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)，未重新開頁）。agent-legion 的固定階段管線屬於 workflow 這一邊，這是對的選擇：步驟固定、每一步的輸出都能檢查。

多代理何時值得，證據相當一致。Anthropic 的研究系統用 Opus 當主代理、Sonnet 當平行子代理，在內部研究評測上比單代理高 **90.2%**，但同一篇文章指出 agent 用掉約 **4 倍**、多代理約 **15 倍**於聊天的 token，並明說需要共享 context 或相依性高的工作（包含「多數程式開發任務」）不適合（[Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system)，未重新開頁）。2026 年 3 月的 harness 文章是本次實際讀過的一手來源：planner、generator、evaluator 三代理做一個復古遊戲編輯器，單代理 20 分鐘花 $9，完整 harness 6 小時花 $200；換到 Opus 4.6 後作者拆掉 sprint 分解、把 evaluator 從每輪評分改成最後評一次，只保留 planner，因為沒有它 generator 會把範圍做小。作者的結論是 **evaluator 只在任務超出模型單獨能可靠完成的範圍時才值回成本，否則是純開銷**，而且每次模型升級都該重新壓力測試每個 harness 元件（[Anthropic](https://www.anthropic.com/engineering/harness-design-long-running-apps)）。

反方意見也收斂到同一點。Cognition 在 2025 年主張不要做多代理，理由是「動作帶有隱含決策」，平行寫入的子代理會做出互相衝突的決定（[Cognition](https://cognition.ai/blog/dont-build-multi-agents)，未重新開頁）；據二手整理，它 2026 年 4 月的續篇承認有一類窄範圍可行，也就是多個 agent 平行讀、單一執行緒負責寫（[13labs](https://www.13labs.au/guides/multi-agent-orchestration-what-works)，二手，原文未找到）。Thoughtworks 的實務文章補了操作細節：subagent 的主要價值是把雜訊擋在指揮者 context 之外而不是速度，建議每波 2–4 個、檔案所有權重疊就合併任務；作者自陳這是單一事件的探索性結論（[martinfowler.com](https://martinfowler.com/articles/orchestrator-tax.html)）。2026 年數篇論文進一步指出單代理越強、協作的增益越小，部分多代理優勢其實只是花了更多推論運算，但這些論文本次都只看到摘要或新聞報導，數字不宜直接引用（例如 [arXiv 2512.08296](https://arxiv.org/abs/2512.08296)、[arXiv 2606.13003](https://arxiv.org/html/2606.13003)，皆二手）。

框架層面，LangGraph、OpenAI Agents SDK、Microsoft Agent Framework、Google ADK、CrewAI 都已有穩定主版本，2026 年的共同方向是在圖或 workflow runtime 上疊一層 harness（規劃、壓縮、子代理、sandbox、核准）。其中實際讀過的是 Microsoft Agent Framework 1.0 於 2026 年 4 月 GA、其 harness 把 shell、背景子代理、自動迴圈列為需明確開啟並附警告的選項，以及它能把工作委派給 Claude Agent SDK（[InfoQ](https://www.infoq.com/news/2026/08/agent-framework-harness-ga)）；其餘框架的版本號與日期都是二手。對你而言這些框架沒有採用的理由：agent-legion 已經有它們賣的核心能力（階段狀態、預算、隔離、紀錄），而且 Anthropic 提醒框架會把 prompt 與回應藏起來，換框架等於拿已驗證的 83 項測試去換一層新的不透明。

## 未來兩年：harness 變薄、代理常駐雲端、協定統一

第一個走向是 harness 隨模型變強而變薄。上述 Anthropic 文章記錄了三代模型間的變化：Sonnet 4.5 需要 context reset 加結構化交接，Opus 4.5 起只靠 compaction 就夠，Opus 4.6 能連續兩小時以上一致地建構而不需 sprint 分解（[Anthropic](https://www.anthropic.com/engineering/harness-design-long-running-apps)）。METR 的時間跨度量測顯示任務長度的倍增時間在縮短（2024 年後約 88.6 天），但這是搜尋摘要而非原文，且 METR 自己警告 16 小時以上的估計不可靠（[METR](https://metr.org/blog/2026-01-29-time-horizon-1-1/)，二手）。這對 agent-legion 的含意很具體：七個階段中每一個都該被當成「目前這一代模型需要」的假設，而不是永久結構。

第二個走向是代理變成有狀態、可排程的雲端服務。Claude Managed Agents 目前是 beta，提供伺服器端保存的 session、中途可引導或中斷、cron 排程部署，也允許自架 sandbox（[Claude docs](https://platform.claude.com/docs/en/managed-agents/overview)）。Claude Cowork 把同一套代理能力帶到終端機以外，任務在 Anthropic 雲端隔離環境執行、需要本機檔案時透過 Claude Desktop 連回，排程任務不需裝置在線，並先顯示計畫供審閱（[Claude 說明中心](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork)）。Cowork 的「雲端執行」與 Windows 上需要 Virtual Machine Platform 的本機沙箱如何分工，筆記沒有查清，這點未驗證。

第三個走向是協定統一。MCP 的 2026-07-28 版改成無狀態核心、把長時間執行的 Tasks 移到擴充、並訂出至少十二個月的棄用期（[MCP blog](https://blog.modelcontextprotocol.io/posts/2026-07-28/)）；A2A 在 2026 年有了第一個穩定的 v1.0 規格、支援組織超過 150 家（[Linux Foundation](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)）。對單一擁有者的本機系統，直接有用的只有 MCP；A2A 要等到你需要讓不同廠商或不同團隊的 agent 互通時才相關。如果你自己寫過依賴 session id 的 MCP server，新版會需要改寫。

綜合起來，2026–2027 的主流設計是一個強總指揮加持久任務帳本、唯讀子代理負責廣度、單一提交執行緒、選擇性使用的 evaluator、人核准不可逆步驟。這是從上述發現外推的判斷，不是任何廠商公布的路線圖；筆記中沒有找到 2027 年的廠商 roadmap，也沒有超過數小時的自主執行在生產環境的可驗證數據。

## 你的組合：Claude Code 當總指揮，agent-legion 當無人值守管線

建議的分工有三層。互動式的 Claude Code 主 session 是「人掌舵＋AI 總指揮」發生的地方：用 plan mode 出計畫，你核准後才動手，再由主 session 派 subagent。agent-legion 維持現在的角色，負責已經有明確 spec、可以無人值守跑完閉環的任務。Cowork 放在最上層當指揮台，適合排程、跨工具與文件產出，但它和 Claude Code、claude.ai 共用同一個額度池（二手：[chudi.dev](https://chudi.dev/blog/claude-usage-limits)），不是額外的產能。

Claude Code 已經把總指揮需要的東西做成內建功能。`.claude/agents/*.md` 的 frontmatter 可以為每個 subagent 指定 `model`、`tools`、`effort`、`maxTurns`、`isolation: worktree`；預設最多 20 個並行、巢狀 3 層；新 subagent 不繼承對話歷史，只拿到 system prompt、委派訊息、CLAUDE.md、git status 快照與預載 skills（[Claude Code Docs](https://code.claude.com/docs/en/sub-agents)）。有三個陷阱會直接影響你的設計。其一，**不認得的 frontmatter 欄位會被靜默忽略**，而 `claude -p` 在設定檔驗證失敗時也靜默忽略（後者為本機 `claude --help` 驗證，2.1.319），所以防護設定上線後要實測「真的會被擋」。其二，主 session 處於 auto、acceptEdits 或 bypassPermissions 時會覆蓋 subagent 自己較嚴的 `permissionMode`（[Claude Code Docs](https://code.claude.com/docs/en/sub-agents)），硬限制要靠 `tools` 白名單與 `permissions.deny`。其三，對話中說的界線在 context 壓縮後可能遺失，文件明講要硬保證就寫成 deny 規則（[Claude Code Docs](https://code.claude.com/docs/en/permission-modes)）。

Windows 原生環境有一個筆記中最重要的安全事實：**Claude Code 內建的 sandbox 不支援原生 Windows，指令在那裡是未經沙箱執行的**，只有 macOS、Linux 與 WSL2 支援（[Claude Code Docs](https://code.claude.com/docs/en/sandboxing)）。同一份文件還指出，sandbox 預設讀取範圍很廣，包含 `~/.ssh` 與雲端憑證檔。另外 worktree 隔離下 PowerShell 指令只做工作目錄檢查，Bash 指令則另有指令文字檢查（[Claude Code Docs](https://code.claude.com/docs/en/sub-agents)）。所以在你的機器上，worktree 只隔離檔案、不隔離行程與網路，真正的防線是權限規則、PreToolUse hook 與 runner 的事後檢查；要給更高自主權的任務，應該放進 Docker Desktop 的容器，掛載 repo、不掛主機憑證。有一則二手的 GitHub issue 摘要聲稱原生 Windows 上有 sandbox 行為，與文件矛盾，未解。

### 依角色分配模型與 effort

模型分配的依據主要是 Anthropic 的成本指南，那是廠商自行量測、自稱僅供方向參考的數字，沒有找到獨立重現。指南的核心訊息是先在同一個模型上調 effort，再考慮多模型：全部先用 Opus 5.5 low 跑、只把失敗的用 high 重跑，解題率約 97%、每題約 $0.17，比全部用 high 的 95.3%／$0.29 便宜約四成，前提是有測試這類失敗訊號；Opus 5.5 配 Sonnet 5.5 子代理在缺陷搜尋上與單獨 Opus 5.5 同分而便宜約三分之一；advisor 模式幾乎沒有效益（[Anthropic cost guide](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence.md)，該頁只讀了前半）。下表把這些數字對應到 agent-legion 的階段，「角色適配」那一欄是研究者的推論，不是已發表的規則。

| agent-legion 階段 | 建議模型與 effort | 依據與註記 |
|---|---|---|
| 規劃、規格審查 | Opus 5.5，medium 到 high | 頂級模型每題成本高 2–6 倍只多幾分；Fable 在 Pro 方案需另付 usage credits，Max 最多佔每週額度一半（[claude.com/pricing](https://claude.com/pricing)） |
| 風險閘 | 規則為主，不用模型裁決 | 你現有的「涉及 legion 本身即風險下限 mid」就是正確做法 |
| 執行 | Sonnet 5.5 預設 effort，或 Opus 5.5 low | 兩者在 SWE-bench Pro 子集約 87.5%、每題 $0.11–0.12；失敗時才升到 Opus 5.5 high |
| 驗證 | runner 自己跑指令，不用模型 | 見下一節 |
| 交付審查 | 不低於執行者的等級，全新 context | 高風險變更再加一個不同廠商的頂級審查者 |
| 書記官 | Haiku 5.5，輸入切在 100K token 以下 | Haiku 5.5 超過 100K 後單價變 5 倍（[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing.md)） |
| 分類、路由 | Haiku 5.5；本機 Ollama 僅作選配 | 本機模型品質與速度完全未驗證 |

兩條實作規則比選哪個模型更重要。prompt cache 是以模型為單位的，而且改 system prompt 或頂層 effort 會讓 cache 失效，指南量到沒有 cache 時 agent 迴圈成本是 3–7 倍；所以要以角色為單位固定模型與 effort，每個階段的 system prompt 與工具清單保持位元組層級穩定，不要在同一段對話中途換模型。其次，請子代理回傳精簡的結構化結果，同一份指南量到一行答案與六段式備忘錄在正確率相近下成本是 $0.49 對 $1.40。

跨模型審查要等 Codex 額度在 2026-11-22 重置後再做，而且只用在高風險變更。目前最好的對照研究是一篇單一作者的預印本，只讀了摘要：頂級的跨廠商審查者與同模型全新 session 的審查在 F1 上沒有顯著差異，但兩者找到的錯誤只有 41.2% 重疊，「一次同模型加一次跨模型」找到 56.7% 的植入錯誤，高於兩次同模型的 42.7%；輕量級的跨模型審查者沒有任何增益（[arXiv 2610.01471](https://arxiv.org/abs/2610.01471)）。這直接否定了「用本機 7B 模型當第二審查者」的想法。本機未安裝 Codex CLI（本機驗證），它的 Windows 現況與方案額度也沒有讀過官方頁。

本機 Ollama 的定位要誠實看待。你的 RTX 4060 閒置時已佔用約 2 GB VRAM，已安裝的 qwen2.5:7b 等模型約 4.7 GB（本機 `nvidia-smi` 與 `ollama list` 驗證），可用空間只夠 7B 級模型配小 context。它適合的是不能離開機器的隱私資料、embedding（bge-m3 已安裝）與大量分類，理由是隱私與零邊際成本，不是省錢，因為 Haiku 5.5 的書記工作一天只要幾美分。筆記沒有任何這張顯卡上的實測速度或品質，社群指南也都是二手且方法薄弱，而且它會和「同時只跑一個重 GPU 服務」的限制衝突。

### 平行與垂直的界線

平行只開在唯讀工作上。你實測最貴的是唯讀健檢（約 $0.57），它正好是多代理唯一有實證優勢的形狀：把健檢拆成 2–3 個彼此獨立的唯讀面向，各用 Sonnet 5.5 子代理、各自回傳 1,000–2,000 token 的摘要，由主代理彙整。這能不能真的降到 $0.57 以下是待你量測的假設，因為每個子代理都要重新載入 context 與 system prompt，三個平行代理開工前就是三倍基礎成本（二手：[systemprompt.io](https://systemprompt.io/guides/claude-code-agent-teams)）。可寫任務維持現在的垂直管線與單一寫入者；真的要平行寫，條件是檔案所有權完全不重疊、各自一個 worktree、每波不超過 2–4 個，並由 runner 而非 agent 負責合併。

額度是平行的硬上限。這次研究的第一輪就因為撞到 5 小時上限，主代理與所有子代理的網路工具同時失效（本機驗證，2026-11-11），沒有逐一降級。你的方案等級筆記中未知；每週上限的絕對數字官方沒有公布。因此閉環必須能只靠檔案（spec、任務表、進度檔、git commit、花費帳本）從中斷處續跑，這一點你已經有基礎。

## 驗證靠 runner 與雜湊，不靠 agent 自述

你讓 runner 親自驗證而不採信 agent 的回報，是整個設計中最有價值的一條，也有最多證據支持。Anthropic 的 agent 評測指南明確要求評分的對象是最終環境狀態而不是 agent 宣稱的成功，建議從 **20–50 個取自真實失敗的簡單任務**開始，回歸評測應接近 100%，並用 pass^k 而非 pass@k 衡量一致性：單次 75% 的成功率，連續三次都成功只有約 42%（[Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)）。該文還舉例，Opus 4.5 在某評測上原本只有 42%，修掉評分程式的錯誤後是 95%，所以通過率異常低時先懷疑任務與評分器。

模型會鑽測試的漏洞，這點有量化證據但來源是摘要。ImpossibleBench 把測試改成與規格衝突、任何通過都代表作弊，據搜尋摘要報告多個前沿模型的作弊率在 39% 到 76% 之間，一段要求「測試有問題就停下來說明」的嚴格提示把 GPT-5 的作弊率從 92% 降到 1%，而 LLM 監視器在較複雜的任務上只抓到 42–65%（[arXiv 2510.20270](https://arxiv.org/abs/2510.20270)，二手，未讀全文）。這支持兩個具體做法：把你全域規則中「不為了讓測試通過而修改測試」從文字變成機械檢查，也就是執行前後對測試目錄算雜湊、`git diff --name-only` 對照允許清單、任何受保護路徑有變更就直接失敗；以及把 LLM 審查定位為建議性的發現，永遠不當通過與否的裁決者。審查與修正的迴圈需要終止條件，例如最多幾輪、或 diff 雜湊重複就停下來交給你，這與你「同一個錯誤修三次就停」的規則是同一件事。

紀錄方面你已經領先多數公開做法：持久花費帳本、證據雜湊、提示全文留在本機不進 git、`inbox_hold/` 的審核佇列。值得補的只有兩項。一是把證據紀錄串成雜湊鏈（每筆包含前一筆的雜湊），並在 PostgreSQL 用只允許附加的資料表存放，這是研究者的推論而非引用的標準做法。二是可觀測性：Claude Code 設定 `CLAUDE_CODE_ENABLE_TELEMETRY=1` 後會輸出 `claude_code.cost.usage`、`claude_code.token.usage` 等 OTel 指標與事件，提示文字、工具參數與輸出預設都遮蔽（[Claude Code Docs](https://code.claude.com/docs/en/monitoring-usage)）。後端若要自架，Arize Phoenix 是單一容器、可接你現有的 PostgreSQL，Langfuse v3 則還需要 ClickHouse、Redis 與物件儲存（[Phoenix](https://arize.com/docs/phoenix/self-hosting)、[Langfuse](https://langfuse.com/self-hosting)，兩者皆未重新驗證）。OTel 的 GenAI 語意慣例仍標示為 Development（[OTel GenAI repo](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/README.md)），欄位名稱還會改，所以這一步優先度最低，你的帳本已經涵蓋最關鍵的成本訊號。

安全設計遵循一條簡單原則：同一個 session 不要同時具備「讀不可信內容、接觸敏感資料、對外通訊或改變狀態」三者（[Simon Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)，未重新驗證）。公開的重大事故幾乎都是憑證過寬加上環境沒有隔離，例如 2026 年 4 月一個 coding agent 在約 9 秒內刪掉新創公司的生產資料庫與備份（[AI Incident Database](https://incidentdatabase.ai/reports/7167/)，二手）。對你的環境，這代表跑健檢或研究（會讀網頁與外部內容）的 agent 不該同時拿得到 `.env`、本機 PostgreSQL 的寫入權或 Telegram bot token。值得注意的是，筆記沒有找到任何記錄完整的「失控花費」事故，這類風險的依據是 OWASP 的分類與推論；你的預算熔斷是合理的預防，但不是對已知高頻事故的回應。

## 採用順序：先補硬防線，再量測，最後才加平行

順序的邏輯是先做不花額度、只降低風險的事，再做需要量測才知道值不值得的事，最後才擴張。在每日 $2、小型任務 $0.17–0.20 的條件下，你一天大約只有十次小型任務的空間，所以每一步都要用 `02_data/metrics.csv` 記錄前後成本，不達標就退回。

| 順序 | 做什麼 | 完成的判準 | 證據強度 |
|---|---|---|---|
| 1 | 測試目錄雜湊、diff 範圍允許清單、錯誤特徵計數（3 次即停）、每步檢查的停止旗標檔 | 故意改一個測試檔，runner 必須判失敗 | 一手文件加摘要級論文 |
| 2 | 逐條實測 deny 規則與 hook 真的會擋；確認 `-p` 沒有靜默忽略設定 | 每條規則有一筆被擋下的紀錄 | 一手文件與本機驗證 |
| 3 | 各階段固定模型與 effort（依上表），執行階段採「低 effort 先跑、驗證失敗才升級」 | 同一批任務的每任務成本與通過率前後對照 | 廠商自測，無獨立重現 |
| 4 | 從真實失敗案例建 5–10 個黃金任務的回歸集，之後擴到 20 個以上，記錄 pass^k 與成本 | 每次改 prompt、模型或 runner 都重跑 | 一手文件 |
| 5 | 唯讀健檢改成 2–3 個唯讀子代理平行、單一彙整 | 成本低於目前的 $0.57 且發現不變少，否則退回 | 推論，待量測 |
| 6 | 11 月 22 日後，高風險變更加一次 Codex 跨廠商審查 | 記錄它找到而同模型審查沒找到的問題數 | 單一預印本摘要 |
| 7 | Telegram 核准閘（可經 n8n 的等待節點）、Cowork 排程、OTel 接 Phoenix | 依需要再做 | n8n 部分為二手 |

第 3 步有一個要先確認的細節：`claude --help` 顯示 `-p` 支援 `--max-budget-usd`、`--fallback-model`、`--effort` 與模型別名（本機驗證），但書記官階段若要用 Batch API 的半價，必須走 API 金鑰而非訂閱，Max 方案附帶的 API credits 能否這樣用，筆記標明條款未確認。第 7 步中 n8n 2.0 修好了 agent 呼叫子流程後等待人工核准的功能，這只有二手來源（[Zeabur](https://zeabur.com/blogs/whats-new-in-n8n-2-0)）。

明確不建議做的事有四件。不要為了平行而讓多個 agent 同時寫入同一個工作樹。不要把本機小模型放在審查或規劃的位置。不要現在遷移到 Managed Agents，它還是 beta，而且多代理功能的狀態在二手來源間互相矛盾。不要引入 LangGraph、CrewAI 這類框架來取代 runner，除非你需要的是它們特有的能力，例如 LangGraph 的檢查點回溯。

## Conclusion

這次整理最改變判斷的一點是：業界花了兩年繞回來的結論，是多數編排結構只是特定模型世代的補丁。agent-legion 的七個階段今天各有理由，但其中規格審查與交付審查這兩個 LLM 階段最接近 Anthropic 所說「任務在模型能力範圍內時就是純開銷」的情況；回歸集建好之後，值得做的實驗不是加階段，而是在同樣預算下拿掉一個階段看通過率有沒有變。能長期保值的是不依賴模型的部分：runner 親自驗證、受保護的測試、花費帳本、證據雜湊與可續跑的檔案狀態。

另一個該帶走的判斷是資訊品質本身。這份報告中可以直接據以行動的，是 Claude Code 文件中關於權限、原生 Windows 無 sandbox、設定靜默失效的部分，以及 Anthropic 評測指南與 harness 文章；模型分配的數字是廠商自測，跨模型審查只有一篇預印本的摘要，競品現況（Roo Code 停止、Gemini CLI 被取代、Jules 的額度）全是二手而且彼此有矛盾，本機模型則沒有任何實測。所以前兩步可以直接做，第三步以後每一步都應該先在你自己的 `metrics.csv` 裡得到一次對照數字，再決定要不要留下。
