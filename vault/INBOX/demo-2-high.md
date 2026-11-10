---
title: demo：清掉舊的測試檔
kind: write
repo: D:\202611_agent-legion\.legion_tmp\demo_repo
mock:
  risk_proposed: low
  accept_cmds:
  - python -m pytest -q
  actions:
  - type: delete
    path: test_calc.py
---
高風險：agent 提議 low，但動作含刪除，規則判定 high → WAIT_HUMAN。
