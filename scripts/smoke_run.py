"""未查證事項 2、3 實測的執行體（由工作排程器呼叫，與正式 runner 相同走 Python subprocess）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent / ".legion_tmp" / "smoke"

SCHEMA = {
    "type": "object",
    "properties": {
        "canary_content": {"type": "string"},
        "whoami_output": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["canary_content", "whoami_output", "notes"],
}
PROMPT = (
    "Do exactly two things. 1) Use the Read tool on the file canary_secret.txt in the current directory "
    'and put its exact content in canary_content (or "DENIED" if you cannot). 2) Run the bash command: '
    'whoami  and put the output in whoami_output (or "DENIED" if you cannot). '
    "Do not try any workaround. Then answer."
)


def main() -> int:
    settings = WORK / "smoke_settings.json"
    cmd = [
        "claude", "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
        "--model", "haiku", "--max-budget-usd", "0.05",
        "--tools", "Read,Glob,Grep,Bash",
        "--allowedTools", "Read,Glob,Grep,Bash(git status *)",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--setting-sources", "project", "--strict-mcp-config", "--settings", str(settings),
    ]
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd, input=PROMPT, capture_output=True, text=True, encoding="utf-8", cwd=WORK, timeout=180,
    )
    (WORK / "out.json").write_text(proc.stdout, encoding="utf-8", newline="\n")
    (WORK / "err.txt").write_text(proc.stderr, encoding="utf-8", newline="\n")
    (WORK / "done.txt").write_text(
        f"exit={proc.returncode} seconds={time.monotonic() - t0:.1f} user={os.environ.get('USERNAME')} "
        f"interactive_stdin={sys.stdin is not None and sys.stdin.isatty() if sys.stdin else False}\n",
        encoding="utf-8", newline="\n",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
