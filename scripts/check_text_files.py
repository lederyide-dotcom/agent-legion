"""改檔檢查：換行與語法。給 Claude Code hook（改檔當下）與 git pre-commit（提交前）共用。

檢查項目：
1. 除了 .bat、.cmd、.ps1（規定 CRLF）以外的文字檔不得含 CRLF（.gitattributes 規定 LF）
2. .py 檔要能編譯（抓「字串被斷行」這類改檔事故）
3. --staged 時另外比較 `git diff --cached --numstat` 與忽略行尾差異的版本：
   兩者差很多代表有檔案被整檔改了換行

用法：
  python scripts/check_text_files.py --hook      # Claude Code hook：從 stdin 讀這次工具呼叫的檔；沒有檔名時看工作目錄變動
  python scripts/check_text_files.py --changed   # 工作目錄有變動或未追蹤的檔
  python scripts/check_text_files.py --staged    # 已暫存的內容（pre-commit 用；讀暫存區，不讀工作目錄）
  python scripts/check_text_files.py 檔案 …       # 指定檔案
有問題時 exit 2 並在 stderr 列出（Claude Code hook 會把 stderr 回饋給 Claude）。

路徑一律用 `git -c core.quotepath=false … -z`：中文或含空白的檔名不會被跳脫成找不到的字串。
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRLF_OK = {".bat", ".cmd", ".ps1"}
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".docx", ".xlsx", ".zip", ".ttf", ".ttc", ".woff",
          ".woff2", ".pyc", ".db", ".sqlite"}


def _git_bytes(*args: str) -> bytes:
    out = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=ROOT, capture_output=True, check=False)
    return out.stdout


def _git_paths(*args: str) -> list[str]:
    """執行帶 -z 的 git 指令，回傳以 NUL 分隔的路徑（UTF-8）。"""
    return [p for p in _git_bytes(*args).decode("utf-8").split("\0") if p]


def changed_files() -> list[str]:
    files = _git_paths("diff", "--name-only", "-z", "HEAD")
    files += _git_paths("ls-files", "--others", "--exclude-standard", "-z")
    return sorted(set(files))


def staged_files() -> list[str]:
    return _git_paths("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")


def _from_disk(rel: str) -> bytes | None:
    p = ROOT / rel
    return p.read_bytes() if p.is_file() else None


def _from_index(rel: str) -> bytes | None:
    out = subprocess.run(["git", "show", f":{rel}"], cwd=ROOT, capture_output=True, check=False)
    return out.stdout if out.returncode == 0 else None


def check(paths: list[str], read: Callable[[str], bytes | None] = _from_disk) -> list[str]:
    problems: list[str] = []
    for rel in paths:
        suffix = Path(rel).suffix.lower()
        if suffix in BINARY:
            continue
        data = read(rel)
        if data is None or b"\0" in data[:4096]:
            continue  # 已刪除或二進位
        if suffix not in CRLF_OK and b"\r\n" in data:
            n = data.count(b"\r\n")
            problems.append(f"{rel}：有 {n} 行是 CRLF（本 repo 規定 LF）。用 Write／Edit 工具改檔，Python 寫檔用 "
                            "write_bytes 或 newline=\"\\n\"")
        if suffix == ".py":
            try:
                compile(data.decode("utf-8"), rel, "exec")
            except SyntaxError as e:
                problems.append(f"{rel}:{e.lineno}：語法錯誤（{e.msg}）。常見原因：經 Bash 傳送時 \\n 變成真換行")
            except UnicodeDecodeError:
                problems.append(f"{rel}：不是 UTF-8")
    return problems


def _numstat(*extra: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for row in _git_bytes("diff", "--cached", "--numstat", *extra).decode("utf-8").splitlines():
        parts = row.split("\t")
        if len(parts) >= 3:
            out[parts[2]] = (parts[0], parts[1])
    return out


def staged_eol_churn() -> list[str]:
    """已暫存變更裡，行數差異主要來自換行的檔案（例如 HEAD 是 CRLF、這次整檔轉 LF）。"""
    raw, ign = _numstat(), _numstat("--ignore-cr-at-eol")
    out = []
    for f, (a, d) in raw.items():
        if a == "-" or f not in ign:
            continue
        total, real = int(a) + int(d), sum(int(x) for x in ign[f] if x != "-")
        if total >= 40 and real * 3 < total:
            out.append(f"{f}：變更 {total} 行，其中只有 {real} 行是內容，其餘是換行字元被改。"
                       "若是刻意的換行整理，請獨立 commit 並列入 .git-blame-ignore-revs")
    return out


def hook_files(stdin_text: str) -> list[str] | None:
    """Claude Code hook 的 stdin：有 tool_input.file_path（Write／Edit）就只查那個檔；Bash 等沒有檔名時回傳 None。"""
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        return None
    path = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path")
    if not path:
        return None
    p = Path(path)
    try:
        return [p.resolve().relative_to(ROOT).as_posix()]
    except ValueError:
        return []  # repo 外的檔不歸這裡管


def main(argv: list[str], stdin_text: str = "") -> int:
    if "--staged" in argv:
        problems = check(staged_files(), _from_index) + ([] if "--allow-eol-churn" in argv else staged_eol_churn())
    elif "--hook" in argv:
        files = hook_files(stdin_text)
        problems = check(changed_files() if files is None else files)
    elif "--changed" in argv:
        problems = check(changed_files())
    else:
        problems = check([a for a in argv if not a.startswith("--")])
    if problems:
        print("改檔檢查不通過：", file=sys.stderr)
        for x in problems:
            print(f"  - {x}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], sys.stdin.read() if "--hook" in sys.argv else ""))
