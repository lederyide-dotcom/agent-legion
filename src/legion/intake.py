"""想法入口：`legion idea "一句話"` 把想法寫成 vault/INBOX 的 .md，下一輪 tick 就會領取。

使用者不用自己寫 frontmatter，也不用記得填 repo；不清楚的地方交給規劃者在需求釐清時提問。

安全：目標是 legion 自己時，必須明確用 --repo 或 LEGION_DEFAULT_REPO 指定（在 legion 資料夾裡忘了加 --repo
不會默默變成「改 legion 自己」的任務）；明確指定時，比照後續想法加上風險下限 mid。
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from .config import PROJECT_ROOT, Settings

TITLE_MAX = 40
SELF_RISK_FLOOR = "mid"


def git_toplevel(cwd: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True,
                             encoding="utf-8", check=False)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 and out.stdout.strip() else None


def is_legion_itself(repo: Path) -> bool:
    return repo.resolve() == Path(PROJECT_ROOT).resolve()


def resolve_repo(arg: str | None, settings: Settings, cwd: Path) -> Path | None:
    """目標 repo：--repo → LEGION_DEFAULT_REPO → 目前所在的 git repo；都沒有回傳 None。路徑必須是 git repo。
    只靠「目前所在位置」推斷到 legion 自己時拋 ValueError，要求明確指定。"""
    for cand in (arg, settings.default_repo):
        if cand:
            top = git_toplevel(Path(cand))
            if top is None:
                raise ValueError(f"{cand} 不是 git repo")
            return top
    top = git_toplevel(cwd)
    if top is not None and is_legion_itself(top):
        raise ValueError("目前在 legion 自己的資料夾：要改哪個專案請加 --repo <路徑>"
                         "（真的要改 legion 本身也請明確寫 --repo，會加上風險下限 mid）")
    return top


def validate_subdir(repo: str | Path, subdir: object, kind: str = "write") -> str:
    """任務的 subdir 唯一的檢查（`legion idea` 與讀進想法檔共用）：白名單，不合格就拋 ValueError。

    - 必須是非空字串、相對路徑（不能有磁碟代號、開頭的 / 或 \\、網路路徑）
    - 解析後（含 ..、捷徑連結）仍在 repo 裡，而且不是 repo 本身
    - write 任務：資料夾必須已進 git（worktree 從 HEAD 建立）；readonly：資料夾必須存在
    回傳正規化後的相對路徑（/ 分隔）。
    """
    if not isinstance(subdir, str) or not subdir.strip():
        raise ValueError(f"subdir 必須是非空字串：{subdir!r}")
    raw = subdir.strip()
    if PureWindowsPath(raw).anchor or PurePosixPath(raw).anchor:
        raise ValueError(f"subdir 必須是相對路徑：{raw!r}")
    top = Path(repo).resolve()
    if not top.is_dir():  # 壞檔要變成 ValueError 進 bad_inbox，不能讓 OSError 讓整個 tick 崩潰
        raise ValueError(f"repo 不是資料夾：{repo}")
    p = (top / raw).resolve()
    if p == top or not p.is_relative_to(top):
        raise ValueError(f"subdir 跑出 repo 範圍：{raw!r}")
    rel = p.relative_to(top).as_posix()
    if ".git" in rel.split("/"):
        raise ValueError(f"subdir 不能是 .git 內部：{rel}")
    if not p.is_dir():
        raise ValueError(f"subdir 資料夾不存在：{rel}")
    if kind == "write":
        def git(*a: str) -> subprocess.CompletedProcess[str]:
            try:  # --literal-pathspecs：`:(top)` 這類 pathspec 語法一律當成字面路徑
                return subprocess.run(["git", "--literal-pathspecs", *a], cwd=top, capture_output=True,
                                      text=True, encoding="utf-8", check=False)
            except OSError as exc:
                raise ValueError(f"無法執行 git：{exc}") from exc

        if git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            raise ValueError(f"{top} 不是 git repo，或還沒有任何 commit")
        out = git("ls-tree", "-d", "HEAD", "--", rel)
        if out.returncode != 0 or not out.stdout.strip():
            raise ValueError(f"{rel} 還沒進 git（或被 .gitignore 排除）：任務的 worktree 從 HEAD 建立，看不到這個資料夾")
    return rel


def subdir_for(arg: str | None, settings: Settings, top: Path, kind: str = "write") -> str | None:
    """--repo（或 LEGION_DEFAULT_REPO）指到 repo 裡的子資料夾時，回傳相對路徑，讓任務只改那個子資料夾。
    例：--repo sandbox_repo → repo 是 legion 根目錄、subdir 是 sandbox_repo（不會默默放大成整個 repo）。"""
    cand = arg or settings.default_repo
    if not cand:
        return None
    p = Path(cand).resolve()
    if p == top or not p.is_relative_to(top):
        return None
    return validate_subdir(top, p.relative_to(top).as_posix(), kind)


def _title(text: str) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    first = re.sub(r"\s+", " ", first)
    return first if len(first) <= TITLE_MAX else first[: TITLE_MAX - 1] + "…"


def write_idea(settings: Settings, text: str, repo: Path, kind: str = "write", now: datetime | None = None,
               subdir: str | None = None) -> Path:
    text = text.strip()
    if not text:
        raise ValueError("想法是空的")
    now = now or datetime.now()
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    base = f"idea-{now:%Y%m%d-%H%M%S}"
    path = settings.inbox_dir / f"{base}.md"
    n = 1
    while path.exists():
        n += 1
        path = settings.inbox_dir / f"{base}-{n}.md"
    fm: dict[str, str] = {"title": _title(text), "kind": kind, "repo": repo.as_posix()}
    if subdir:
        fm["subdir"] = subdir
    if is_legion_itself(repo):
        fm["risk_floor"] = SELF_RISK_FLOOR  # 改 legion 本身：至少 mid（與後續想法涉及 legion 時的規則一致）
    path.write_text(f"---\n{yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)}---\n{text}\n",
                    encoding="utf-8", newline="\n")
    return path
