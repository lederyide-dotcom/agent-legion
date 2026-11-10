---
title: 實戰 B：textkit 新增 word_count
kind: write
repo: D:/202611_agent-legion
subdir: sandbox_repo
---
在 sandbox_repo 的 textkit.py 新增 `word_count(text: str) -> int`：以空白切分計算字數，空字串或只有空白時回傳 0。
在 sandbox_repo/tests/test_textkit.py 補上對應測試，`python -m pytest -q` 全數通過。只改 sandbox_repo 內的檔案。
