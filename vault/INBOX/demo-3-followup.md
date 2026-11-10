---
title: demo：為 calc 補 docstring
kind: write
repo: D:\202611_agent-legion\.legion_tmp\demo_repo
mock:
  risk_proposed: low
  accept_cmds: &id001
  - python -m pytest -q
  actions:
  - type: write
    path: calc.py
  exec:
  - claim: passed
    write_files:
      calc.py: "\"\"\"小計算機。\"\"\"\n\n\ndef add(a, b):\n    \"\"\"相加。\"\"\"\n    return\
        \ a + b\n\n\ndef multiply(a, b):\n    \"\"\"相乘。\"\"\"\n    return a * b\n"
  followups:
  - title: demo：新增 power 函式
    body: 書記官回灌的後續想法。
  child:
    risk_proposed: low
    accept_cmds: *id001
    actions:
    - type: write
      path: calc.py
    exec:
    - claim: passed
      write_files:
        calc.py: "\"\"\"小計算機。\"\"\"\n\n\ndef add(a, b):\n    \"\"\"相加。\"\"\"\n   \
          \ return a + b\n\n\ndef multiply(a, b):\n    \"\"\"相乘。\"\"\"\n    return\
          \ a * b\n\n\ndef power(a, b):\n    \"\"\"次方。\"\"\"\n    return a ** b\n"
---
會回灌：結案時書記官提出 1 個後續想法寫回 INBOX。
