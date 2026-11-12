"""風險分級（程式判定）。agent 只能提議，最終風險 = max(規則判定, agent 提議)，不能降級。"""
from __future__ import annotations

import fnmatch
import hashlib
import re
import shlex
from pathlib import Path, PureWindowsPath
from typing import Any

from .models import InstallRequest, Risk, max_risk

# 驗收指令白名單：VERIFY 由 runner 親自執行，因此只放行測試與 git 唯讀類指令
ACCEPT_CMD_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(python|py(\s+-3(\.\d+)?)?)\s+-m\s+pytest(\s|$)"),
    re.compile(r"^pytest(\s|$)"),
    re.compile(r"^git\s+(status|diff|log|rev-parse|show)(\s|$)"),
    re.compile(r"^(python|py(\s+-3(\.\d+)?)?)\s+-m\s+legion\.checks(\s|$)"),
)
_SHELL_META = re.compile(r"[&|;<>`]|\$\(")
_ENV_RE = re.compile(r"(^|[\\/\s'\"])\.env(\b|$)|\.env\.", re.IGNORECASE)

HIGH_ACTIONS = {"delete", "network_write", "message"}
MID_ACTIONS = {"merge"}


_PYTEST_FLAGS = {"-q", "-qq", "-x", "-v", "-s", "-rA", "--tb=short", "--tb=no", "--tb=line", "--no-header"}
_PYTEST_VALUE_FLAGS = {"-k", "-m", "--maxfail"}
_GIT_SUBS = {"status", "diff", "log", "rev-parse", "show"}
_GIT_FLAGS = {
    "--porcelain", "--short", "-s", "--stat", "--name-only", "--name-status", "--oneline", "--cached", "--staged",
    "--exit-code", "--quiet", "--untracked-files=all", "--untracked-files=no", "--no-color", "--shortstat",
    "--verify", "--abbrev-ref", "--show-toplevel", "-n",
}
_SAFE_REL = re.compile(r"^[\w.\-/:~^\[\]]+$")


def _safe_rel_path(tok: str) -> bool:
    return (bool(_SAFE_REL.match(tok)) and not tok.startswith(("/", "~")) and ".." not in tok
            and not re.match(r"^[A-Za-z]:", tok))


def accept_cmd_allowed(cmd: str) -> bool:
    """驗收指令由 runner 親自執行，因此逐 token 檢查：只允許白名單旗標與 worktree 內的相對路徑。"""
    c = cmd.strip().replace("\\", "/")
    if _SHELL_META.search(c) or not any(p.match(c) for p in ACCEPT_CMD_PATTERNS):
        return False
    try:
        argv = shlex.split(c, posix=True)
    except ValueError:
        return False
    if argv[0] == "py":
        argv = argv[2:] if len(argv) > 1 and argv[1].startswith("-3") else argv[1:]
        argv = ["python", *argv]
    if argv[0] in {"python", "python3"} and argv[1:3] == ["-m", "pytest"]:
        rest = argv[3:]
    elif argv[0] == "pytest":
        rest = argv[1:]
    elif argv[0] == "git":
        if len(argv) < 2 or argv[1] not in _GIT_SUBS:
            return False
        for i, tok in enumerate(argv[2:], start=2):
            if tok == "--":  # 選項與路徑的分隔符號本身是安全的；後面的路徑照常檢查
                continue
            if tok.startswith("-"):
                if tok not in _GIT_FLAGS and not re.fullmatch(r"-\d{1,3}", tok):
                    return False
            elif argv[i - 1] == "-n":
                if not tok.isdigit():
                    return False
            elif tok != "--" and not _safe_rel_path(tok):
                return False
        return True
    elif argv[0] in {"python", "python3"} and argv[1:3] == ["-m", "legion.checks"]:
        rest = argv[3:]
        if len(rest) < 2 or rest[0] != "report":
            return False
        path = rest[1]
        if "/AI/reports/" not in path or not path.endswith("-report.md") or ".." in path:
            return False
        it = iter(rest[2:])
        for tok in it:
            if tok == "--verify-refs":  # 無參數旗標：只讀核對行號
                continue
            val = next(it, None)
            if val is None:
                return False
            if tok == "--min-refs":
                if not val.isdigit():
                    return False
            elif tok not in {"--section", "--min-chars"}:
                return False
        return True
    else:
        return False
    it = iter(rest)
    for tok in it:
        if tok in _PYTEST_FLAGS:
            continue
        if tok in _PYTEST_VALUE_FLAGS:
            val = next(it, None)
            if val is None or val.startswith("-"):
                return False
            continue
        if tok == "-p":
            if next(it, None) != "no:cacheprovider":
                return False
            continue
        if tok.startswith("-") or not _safe_rel_path(tok):
            return False
    return True


def _outside(path: str, worktree: Path | None) -> bool:
    p = PureWindowsPath(path)
    if p.is_absolute() or p.drive or path.startswith(("/", "\\")):
        if worktree is None:
            return True
        try:
            Path(path).resolve().relative_to(worktree.resolve())
            return False
        except ValueError:
            return True
    return ".." in p.parts


def assess(
    proposed: Risk | None,
    actions: list[dict[str, Any]],
    accept_cmds: list[str],
    kind: str,
    worktree: Path | None,
    install_levels: list[str] | None = None,
) -> tuple[Risk, list[str]]:
    """回傳 (最終風險, 理由)。"""
    reasons: list[str] = []
    rule: Risk = "low"

    def bump(level: Risk, why: str) -> None:
        nonlocal rule
        rule = max_risk(rule, level)
        reasons.append(f"{level}: {why}")

    for a in actions:
        typ = str(a.get("type", "")).lower()
        path = str(a.get("path", "") or "")
        if typ in HIGH_ACTIONS:
            bump("high", f"動作 {typ}")
        if typ == "install":
            bump("high", "安裝須經安裝分級器（PLAN 階段提出即視為高風險）")
        if path and _ENV_RE.search(path):
            bump("high", f"涉及 .env：{path}")
        if typ in {"write", "edit", "delete", "create"}:
            if kind == "readonly":
                bump("high", f"唯讀任務要求寫入：{path}")
            if path and _outside(path, worktree):
                bump("high", f"寫入 worktree 以外：{path}")
            name = Path(path).name.lower()
            if name == "claude.md":
                bump("mid", "修改 CLAUDE.md")
            if "skill" in path.lower().replace("\\", "/").split("/")[:-1] or name == "skill.md":
                bump("mid", "修改 skill")
        if typ in MID_ACTIONS:
            bump("mid", f"動作 {typ}（會合併到主分支）")
        if typ in {"edit_claude_md"}:
            bump("mid", "修改 CLAUDE.md")
        if typ in {"edit_skill"}:
            bump("mid", "修改 skill")
    for cmd in accept_cmds:
        if _ENV_RE.search(cmd):
            bump("high", f"驗收指令涉及 .env：{cmd}")
        elif not accept_cmd_allowed(cmd):
            bump("high", f"驗收指令不在白名單：{cmd}")
    for lvl in install_levels or []:
        if lvl == "ask":
            bump("high", "安裝落在「必須問」等級")
    final = max_risk(rule, proposed)
    if proposed is not None and final != proposed:
        reasons.append(f"agent 提議 {proposed}，依規則改為 {final}（不可降級）")
    return final, reasons


def assess_diff(name_status: str) -> tuple[Risk, list[str]]:
    """依 EXEC 實際產生的變更（git diff --name-status）重新判定風險，不依賴 agent 自報。"""
    rule: Risk = "low"
    reasons: list[str] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code, paths = parts[0], parts[1:]
        for p in paths:
            low = p.lower()
            name = low.rsplit("/", 1)[-1]
            if code.startswith("D"):
                rule = max_risk(rule, "high")
                reasons.append(f"high: 實際變更含刪除：{p}")
            if _ENV_RE.search(p):
                rule = max_risk(rule, "high")
                reasons.append(f"high: 實際變更涉及 .env：{p}")
            if low.startswith(".claude/") or "/.claude/" in low or name == ".mcp.json":
                rule = max_risk(rule, "high")
                reasons.append(f"high: 實際變更修改 agent 設定：{p}")
            if name == "claude.md":
                rule = max_risk(rule, "mid")
                reasons.append(f"mid: 實際變更修改 CLAUDE.md：{p}")
            if name == "skill.md" or "/skills/" in f"/{low}":
                rule = max_risk(rule, "mid")
                reasons.append(f"mid: 實際變更修改 skill：{p}")
    return rule, reasons


# ---------------------------------------------------------------- 硬防線（不經 LLM）
_TEST_PATH = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$|(^|/)pytest\.ini$",
                        re.IGNORECASE)


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path.replace("\\", "/")))


_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.MULTILINE)
_SKIP_MARK = re.compile(r"pytest\.mark\.(skip|skipif|xfail)|pytest\.(skip|xfail)\s*\(|importorskip|"
                        r"^\s*pytestmark\s*=|collect_ignore", re.MULTILINE)
_TEST_CONFIG = re.compile(r"(^|/)(pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|\.gitignore|\.gitattributes)$",
                          re.IGNORECASE)


def _ns_entries(name_status: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append((parts[0], parts[-1].replace("\\", "/").strip('"')))
    return out


def protected_test_violations(name_status: str, numstat: str, added: dict[str, str] | None = None,
                              base_src: dict[str, str] | None = None) -> list[str]:
    """既有測試只能新增、不能削弱。違規＝驗收失敗（agent 要自己改回來）。

    - 刪除既有測試檔、型別變更（例如換成 symlink）
    - 修改既有測試時刪改任何一行；無法計算行數（二進位、`-diff` 屬性）也算
    - 在既有測試檔新增跳過標記（skip／xfail／importorskip／pytestmark／collect_ignore）
    - 在既有測試檔重新定義已存在的同名測試（用空殼覆蓋原測試）

    輸入應以 `--no-renames` 與 `core.quotepath=false` 取得：改名會呈現為「刪除＋新增」，中文檔名不被加引號。
    新增的測試檔不受限（全新測試）。純新增的測試案例允許。
    """
    added = added or {}
    base_src = base_src or {}
    deleted_lines: dict[str, str] = {}
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            deleted_lines[parts[2].replace("\\", "/").strip('"')] = parts[1]
    out: list[str] = []
    for code, path in _ns_entries(name_status):
        if not is_test_path(path):
            continue
        if code.startswith("D"):
            out.append(f"刪除了既有測試檔：{path}")
        elif code.startswith("T"):
            out.append(f"變更了既有測試檔的型別（例如換成連結）：{path}")
        elif code.startswith("M"):
            d = deleted_lines.get(path, "0")
            if not d.isdigit():
                out.append(f"既有測試檔的變更無法逐行比對（二進位或 -diff 屬性）：{path}")
            elif int(d) > 0:
                out.append(f"修改既有測試時刪改了 {d} 行（只允許新增）：{path}")
            new_text = added.get(path, "")
            if _SKIP_MARK.search(new_text):
                out.append(f"在既有測試檔新增了跳過標記：{path}")
            redefined = set(_TEST_DEF.findall(new_text)) & set(_TEST_DEF.findall(base_src.get(path, "")))
            if redefined:
                out.append(f"在既有測試檔重新定義了已存在的測試 {sorted(redefined)}：{path}")
    return out


def collection_risks(name_status: str, base_files: list[str], index_flags: list[str]) -> list[str]:
    """會改變「哪些測試被收集、怎麼執行」的環境變更。可能是正當需要，所以判 high、交給人核准，而不是直接失敗。"""
    out: list[str] = []
    base_tests = [f.replace("\\", "/") for f in base_files if is_test_path(f)]
    for code, path in _ns_entries(name_status):
        if code.startswith("D"):
            continue  # 刪除已由 assess_diff 判為 high
        name = path.rsplit("/", 1)[-1].lower()
        if _TEST_CONFIG.search(path):
            out.append(f"修改了會影響測試執行的設定檔：{path}")
        elif name == "conftest.py":
            folder = path.rsplit("/", 1)[0] if "/" in path else ""
            if any(folder == "" or t.startswith(folder + "/") for t in base_tests):
                out.append(f"conftest.py 會作用到既有測試：{path}")
    for line in index_flags:
        if line and (line[0] == "S" or line[0].islower()):
            out.append(f"git 索引旗標會讓檔案變更不出現在 diff（skip-worktree／assume-unchanged）：{line[2:]}")
    return out


def added_lines_by_file(unified_diff: str) -> dict[str, str]:
    """從 `git diff -U0` 取出每個檔案新增的行（不含 +++ 標頭）。"""
    out: dict[str, list[str]] = {}
    current = ""
    for line in unified_diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip().strip('"')
            current = p[2:] if p.startswith("b/") else p
            out.setdefault(current, [])
        elif line.startswith("+") and current:
            out[current].append(line[1:])
    return {k: "\n".join(v) for k, v in out.items()}


def _path_allowed(path: str, pattern: str) -> bool:
    pat = pattern.replace("\\", "/").strip("/")
    if pat.endswith("/**"):
        prefix = pat[:-3]
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pat)


def out_of_scope(name_status: str, allowed: list[str]) -> list[str]:
    """實際變更中，不在允許清單（glob；`dir/**` 代表整個子目錄）內的路徑。allowed 為空表示不限制。"""
    if not allowed:
        return []
    out: list[str] = []
    for line in name_status.splitlines():
        parts = line.split("\t")
        for p in parts[1:]:
            path = p.replace("\\", "/").strip('"')
            if path and not any(_path_allowed(path, a) for a in allowed) and path not in out:
                out.append(path)
    return out


def failure_signature(failures: list[str]) -> str:
    """把一次驗收失敗正規化成特徵：保留失敗的測試名稱與 exit code，去掉其餘數字（耗時、行號、位址）。

    同一特徵反覆出現代表 agent 在原地打轉，不必等到重試上限。
    """
    keys: list[str] = []
    for f in failures:
        lines = f.splitlines()
        first = lines[0] if lines else ""
        code = re.search(r"\(exit (-?\d+)\)", first)
        head = re.sub(r"\d+(\.\d+)?", "#", first) + (f"|exit={code.group(1)}" if code else "")
        named = sorted({m.group(0) for m in re.finditer(r"^(FAILED|ERROR) \S+", f, re.MULTILINE)})
        if named:
            keys.append(head + "|" + "|".join(named))
        else:
            tail = [ln for ln in lines[1:] if ln.strip()][-5:]
            keys.append(head + "|" + "|".join(re.sub(r"\d+(\.\d+)?", "#", ln.strip()) for ln in tail))
    return hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()[:16]


def install_levels(reqs: list[InstallRequest]) -> list[str]:
    from .installs import classify

    return [classify(r).level for r in reqs]
