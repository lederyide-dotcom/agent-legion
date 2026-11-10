---
title: demo：為 calc 新增 multiply
kind: write
repo: D:\202611_agent-legion\.legion_tmp\demo_repo
mock:
  risk_proposed: low
  accept_cmds:
  - python -m pytest -q
  actions:
  - type: write
    path: calc.py
  exec:
  - claim: passed
    write_files: {}
  - claim: passed
    write_files:
      calc.py: "def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return\
        \ a * b\n"
---
低風險：在 worktree 內新增 multiply 並通過測試。
