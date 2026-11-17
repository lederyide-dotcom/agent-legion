"""legion scout：找有價值的 GitHub repo（不只看星數）。

不用 AI、不放寬 agent 權限：本機用已登入的 `gh` 抓客觀數據，依 6 類指標打分。
每個分數都附原始數字，可重跑、可追溯。規格見 03_docs/spec_scout.md。
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .config import Settings

DEFAULT_WEIGHTS: dict[str, float] = {
    "activity": 0.20, "maintenance": 0.20, "people": 0.15,
    "adoption": 0.15, "momentum": 0.10, "maturity": 0.20,
}
LABELS = {"activity": "活躍度", "maintenance": "維護", "people": "人員", "adoption": "採用",
          "momentum": "動能", "maturity": "成熟度"}
ARCHIVED_FACTOR = 0.2
ISSUE_SAMPLE = 50
NOT_FOUND: dict[str, Any] = {"_legion_not_found": True}  # HTTP 404：確定不存在，和「抓不到」區分
STAR_PAGE_CAP = 400  # GitHub 的 stargazers 分頁上限（超過拿不到最近的星）


class Fetcher(Protocol):
    async def get(self, path: str, params: dict[str, str] | None = None, accept: str | None = None) -> Any: ...

    async def scorecard(self, full_name: str) -> float | None: ...


class GhFetcher:
    """用本機 `gh api` 讀 GitHub（沿用使用者已登入的帳號）；404 或錯誤回 None，不中斷整批。"""

    def __init__(self, concurrency: int = 6) -> None:
        self.sem = asyncio.Semaphore(concurrency)
        self.calls = 0

    async def get(self, path: str, params: dict[str, str] | None = None, accept: str | None = None) -> Any:
        args = ["gh", "api", "-X", "GET", path]
        for k, v in (params or {}).items():
            args += ["-f", f"{k}={v}"]
        if accept:
            args += ["-H", f"Accept: {accept}"]
        # Windows 上 legion 用 selector 事件迴圈（psycopg 需要），它不支援 asyncio 子行程，所以丟到執行緒跑
        async with self.sem:
            self.calls += 1
            try:
                p = await asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=60)
            except subprocess.TimeoutExpired:
                return None  # 單一呼叫逾時只算缺資料，不丟掉整批
            except OSError as exc:
                raise RuntimeError(f"無法執行 gh（請安裝 GitHub CLI 並 gh auth login）：{exc}") from exc
        if p.returncode != 0:
            return NOT_FOUND if b"HTTP 404" in p.stderr else None
        try:
            return json.loads(p.stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def scorecard(self, full_name: str) -> float | None:
        url = f"https://api.securityscorecards.dev/projects/github.com/{full_name}"

        def fetch() -> float | None:
            try:
                with urllib.request.urlopen(url, timeout=15) as r:  # noqa: S310（固定 https 網址）
                    score = json.loads(r.read().decode("utf-8")).get("score")
                    return float(score) if isinstance(score, (int, float)) else None
            except (urllib.error.URLError, TimeoutError, ValueError, OSError, AttributeError):
                return None

        async with self.sem:
            return await asyncio.to_thread(fetch)


class RepoMetrics(BaseModel):
    full_name: str
    description: str = ""
    url: str = ""
    language: str | None = None
    license: str | None = None
    archived: bool = False
    stars: int = 0
    forks: int = 0
    pushed_days: float | None = None
    commits_90d: int | None = None
    authors_90d: int | None = None
    releases_365d: int | None = None
    issue_closed_ratio: float | None = None
    issue_median_close_days: float | None = None
    pr_merged_ratio: float | None = None
    top_contributor_share: float | None = None
    stars_90d: int | None = None
    health_pct: int | None = None
    has_ci: bool | None = None
    scorecard: float | None = None
    missing: list[str] = Field(default_factory=list)
    error: str | None = None  # 解析失敗時記原因；這類 repo 總分記 0、排在最後


class Scored(BaseModel):
    metrics: RepoMetrics
    scores: dict[str, float | None]
    total: float
    rank: int = 0


# ---------------------------------------------------------------- 評分（純函式）
def _lin(x: float | None, zero: float, full: float) -> float | None:
    """線性內插：x=zero → 0，x=full → 100（zero 可以大於 full，表示越小越好）。"""
    if x is None:
        return None
    t = (x - zero) / (full - zero)
    return round(max(0.0, min(1.0, t)) * 100, 1)


def _log(x: float | None, full: float) -> float | None:
    if x is None:
        return None
    return round(min(1.0, math.log10(1 + max(0.0, x)) / math.log10(1 + full)) * 100, 1)


def _avg(*xs: float | None) -> float | None:
    """子項平均；全部缺資料回 None（該類不計分，權重分給其他類），不當 0 分。"""
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def score(m: RepoMetrics) -> dict[str, float | None]:
    releases = None if m.releases_365d is None else (100.0 if m.releases_365d >= 1 else 0.0)
    license_ok = 100.0 if m.license and m.license not in ("NOASSERTION", "other") else 0.0
    ci = None if m.has_ci is None else (100.0 if m.has_ci else 0.0)
    return {
        "activity": _avg(_log(m.commits_90d, 100), _lin(m.pushed_days, 365, 30), releases),
        "maintenance": _avg(_lin(m.issue_closed_ratio, 0.0, 0.8), _lin(m.issue_median_close_days, 180, 7),
                            _lin(m.pr_merged_ratio, 0.0, 0.7)),
        "people": _avg(_lin(m.authors_90d, 1, 5), _lin(m.top_contributor_share, 1.0, 0.5)),
        "adoption": _avg(_log(m.stars, 50_000), _log(m.forks, 5_000)),
        "momentum": _avg(_log(m.stars_90d, 100)),
        "maturity": _avg(None if m.health_pct is None else float(m.health_pct), ci, license_ok,
                         None if m.scorecard is None else m.scorecard * 10),
    }


def parse_weights(spec: str | None) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    if spec:
        for part in spec.split(","):
            k, sep, v = part.partition("=")
            k = k.strip()
            if not sep or k not in w:
                raise ValueError(f"權重格式是 類別=數字，類別只能是 {'、'.join(w)}：{part!r}")
            try:
                w[k] = float(v)
            except ValueError as exc:
                raise ValueError(f"權重必須是數字：{part!r}") from exc
            if not math.isfinite(w[k]) or w[k] < 0:
                raise ValueError(f"權重必須是非負的有限數字：{part!r}")
    total = sum(w.values())
    if total <= 0:
        raise ValueError("權重總和必須大於 0")
    return {k: v / total for k, v in w.items()}


def rank(metrics: list[RepoMetrics], weights: dict[str, float]) -> list[Scored]:
    out = []
    for m in metrics:
        s = score(m)
        avail = {k: w for k, w in weights.items() if s[k] is not None}
        wsum = sum(avail.values())
        total = sum((s[k] or 0.0) * w for k, w in avail.items()) / wsum if wsum else 0.0
        if m.error:
            total = 0.0
        if m.archived:
            total *= ARCHIVED_FACTOR
        out.append(Scored(metrics=m, scores=s, total=round(total, 1)))
    out.sort(key=lambda x: (-x.total, x.metrics.full_name))
    for i, x in enumerate(out, 1):
        x.rank = i
    return out


# ---------------------------------------------------------------- 蒐集
def build_query(keywords: str, lang: str | None, licenses: list[str]) -> str:
    q = keywords.strip()
    if lang:
        q += f" language:{lang}"
    for lic in licenses:
        q += f" license:{lic}"
    return q


async def candidates(f: Fetcher, query: str, per_query: int) -> list[dict[str, Any]]:
    """依星數與依相關度各搜一次，合併去重（只依星數會漏掉新興好專案）。"""
    seen: dict[str, dict[str, Any]] = {}
    for sort in ("stars", None):
        params = {"q": query, "per_page": str(per_query)}
        if sort:
            params["sort"] = sort
        res = await f.get("search/repositories", params)
        for it in (res or {}).get("items", []) if isinstance(res, dict) else []:
            name = it.get("full_name")
            if isinstance(name, str) and name not in seen:
                seen[name] = it
    return list(seen.values())


def _dt(iso: Any) -> datetime | None:
    if not isinstance(iso, str) or not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _days_since(iso: Any, now: datetime) -> float | None:
    d = _dt(iso)
    return None if d is None else round((now - d).total_seconds() / 86400, 1)


def _dicts(x: Any) -> list[dict[str, Any]] | None:
    """API 回傳的 list 只留 dict 元素；不是 list（錯誤、None、404）回 None。"""
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else None


def _int(x: Any) -> int:
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def _author(c: dict[str, Any]) -> str | None:
    a = c.get("author")
    if isinstance(a, dict) and a.get("login"):
        return str(a["login"])
    cm = c.get("commit")
    ca = cm.get("author") if isinstance(cm, dict) else None
    return str(ca["email"]) if isinstance(ca, dict) and ca.get("email") else None


def _base(item: dict[str, Any], now: datetime) -> RepoMetrics:
    r = str(item["full_name"])
    lic = item.get("license")
    lang = item.get("language")
    return RepoMetrics(full_name=r, description=str(item.get("description") or "")[:200],
                       url=str(item.get("html_url") or f"https://github.com/{r}"),
                       language=lang if isinstance(lang, str) else None,
                       license=str(lic.get("spdx_id")) if isinstance(lic, dict) and lic.get("spdx_id") else None,
                       archived=item.get("archived") is True, stars=_int(item.get("stargazers_count")),
                       forks=_int(item.get("forks_count")), pushed_days=_days_since(item.get("pushed_at"), now))


async def _issues(f: Fetcher, r: str) -> list[dict[str, Any]] | None:
    """最近 50 個真正的 issue。issues API 會連 PR 一起回，PR 多的 repo 要往下翻（最多 3 頁）。"""
    real: list[dict[str, Any]] = []
    for page in (1, 2, 3):
        res = _dicts(await f.get(f"repos/{r}/issues", {"state": "all", "per_page": "100", "sort": "created",
                                                         "direction": "desc", "page": str(page)}))
        if res is None:
            return real or None
        real += [i for i in res if "pull_request" not in i]
        if len(real) >= ISSUE_SAMPLE or len(res) < 100:
            break
    return real[:ISSUE_SAMPLE]


async def stars_available(f: Fetcher, items: list[dict[str, Any]]) -> bool:
    """GitHub 目前可能不提供 stargazers 清單：整批只探測一次，不行就全部略過，不白打 API。"""
    probe = next((it for it in items if _int(it.get("stargazers_count")) > 0), None)
    if probe is None:
        return False
    res = await f.get(f"repos/{probe['full_name']}/stargazers", {"per_page": "1", "page": "1"},
                      accept="application/vnd.github.star+json")
    return isinstance(res, list) and bool(res)


async def collect(f: Fetcher, item: dict[str, Any], now: datetime, want_stars: bool = True) -> RepoMetrics:
    m = _base(item, now)
    r = m.full_name
    since90 = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    star_page = max(1, math.ceil(m.stars / 100))
    fetch_stars = want_stars and 0 < m.stars <= STAR_PAGE_CAP * 100
    commits, releases, contributors, issues, pulls, community, workflows, stars, sc = await asyncio.gather(
        f.get(f"repos/{r}/commits", {"since": since90, "per_page": "100"}),
        f.get(f"repos/{r}/releases", {"per_page": "30"}),
        f.get(f"repos/{r}/contributors", {"per_page": "100"}),
        _issues(f, r),
        f.get(f"repos/{r}/pulls", {"state": "closed", "per_page": "50", "sort": "created", "direction": "desc"}),
        f.get(f"repos/{r}/community/profile"),
        f.get(f"repos/{r}/contents/.github/workflows"),
        f.get(f"repos/{r}/stargazers", {"per_page": "100", "page": str(star_page)},
              accept="application/vnd.github.star+json") if fetch_stars else _none(),
        f.scorecard(r),
    )
    if (cs := _dicts(commits)) is not None:
        m.commits_90d = len(cs)
        m.authors_90d = len({_author(c) for c in cs} - {None})
    if (rs := _dicts(releases)) is not None:
        m.releases_365d = sum(1 for x in rs if (d := _days_since(x.get("published_at"), now)) is not None
                              and d <= 365)
    if ct := _dicts(contributors):
        counts = [_int(c.get("contributions")) for c in ct]
        if sum(counts):
            m.top_contributor_share = round(max(counts) / sum(counts), 3)
    if issues:
        closed = [i for i in issues if i.get("state") == "closed" and i.get("closed_at")]
        m.issue_closed_ratio = round(len(closed) / len(issues), 3)
        days = [d for i in closed if (d := _gap_days(i.get("created_at"), i.get("closed_at"))) is not None]
        if days:
            m.issue_median_close_days = round(statistics.median(days), 1)
    if ps := _dicts(pulls):
        m.pr_merged_ratio = round(sum(1 for p in ps if p.get("merged_at")) / len(ps), 3)
    if isinstance(community, dict) and type(community.get("health_percentage")) is int:
        m.health_pct = community["health_percentage"]
    if workflows == NOT_FOUND:
        m.has_ci = False  # 確定沒有 .github/workflows
    elif (ws := _dicts(workflows)) is not None:
        m.has_ci = any(str(w.get("name", "")).endswith((".yml", ".yaml")) for w in ws)
    if m.stars == 0:
        m.stars_90d = 0
    elif fetch_stars and (st := _dicts(stars)) is not None:
        if star_page > 1 and len(st) < 100:  # 最後一頁不滿 100 筆：補前一頁，湊足最近 100 筆以上
            prev = _dicts(await f.get(f"repos/{r}/stargazers", {"per_page": "100", "page": str(star_page - 1)},
                                      accept="application/vnd.github.star+json"))
            st = (prev or []) + st
        m.stars_90d = sum(1 for s in st if (d := _days_since(s.get("starred_at"), now)) is not None and d <= 90)
    m.scorecard = float(sc) if isinstance(sc, (int, float)) and not isinstance(sc, bool) else None
    m.missing = [k for k in ("commits_90d", "releases_365d", "top_contributor_share", "issue_closed_ratio",
                             "pr_merged_ratio", "health_pct", "stars_90d", "scorecard") if getattr(m, k) is None]
    return m


async def _none() -> None:
    return None


def _gap_days(a: Any, b: Any) -> float | None:
    da, db = _dt(a), _dt(b)
    return None if da is None or db is None else (db - da).total_seconds() / 86400


# ---------------------------------------------------------------- 報告
def _slug(text: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", text.strip(), flags=re.UNICODE).strip("-")
    return (s or "scout")[:40]


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _inline(text: str) -> str:
    """外來文字（repo 描述、查詢）壓成一行並跳脫，不能在報告裡插標題、分隔線、表格或 Obsidian 連結。"""
    s = " ".join(text.split()).replace("|", "\\|").replace("[[", "[\\[").replace("]]", "]\\]")
    return "\\" + s if s[:1] in tuple("#>-+*=[`~_<") else s


def effective_weights(weights: dict[str, float], ranked: list[Scored]) -> dict[str, float]:
    """這次實際生效的權重：所有 repo 都沒資料的類別不列入，其餘按比例放大。"""
    live = {k: w for k, w in weights.items() if any(x.scores.get(k) is not None for x in ranked)}
    total = sum(live.values())
    return {k: w / total for k, w in live.items()} if total else dict(weights)


def render_md(query: str, weights: dict[str, float], ranked: list[Scored], top: int, when: datetime) -> str:
    eff = effective_weights(weights, ranked)
    w = "、".join(f"{LABELS[k]} {v:.0%}" for k, v in eff.items())
    dropped = "、".join(LABELS[k] for k in weights if k not in eff)
    note = f"這次所有候選都量不到「{dropped}」，該類權重已按比例分給其他類。" if dropped else ""
    lines = [
        "---", f"query: {json.dumps(query, ensure_ascii=False)}", f"created: {when.isoformat(timespec='seconds')}",
        f"candidates: {len(ranked)}", "---",
        f"# 找 repo：{_inline(query)}", "",
        f"候選 {len(ranked)} 個（依星數、依相關度各搜一次後合併），列前 {min(top, len(ranked))} 名。"
        f"實際權重：{w}。{note}",
        "已封存的 repo 總分 ×0.2；解析失敗的 repo 記 0 分。個別 repo 某類完全沒資料時顯示「—」，不當 0 分，"
        "該類權重按比例分給其他類。未涵蓋：被多少專案依賴（GitHub 的 Used by 沒有 API）。", "",
        "| 名次 | repo | 總分 | " + " | ".join(LABELS.values()) + " | 星 |",
        "|---|---|---|" + "---|" * len(LABELS) + "---|",
    ]
    for x in ranked[:top]:
        m = x.metrics
        flag = "（已封存）" if m.archived else ("（解析失敗）" if m.error else "")
        lines.append(f"| {x.rank} | [{m.full_name}]({m.url}){flag} | **{x.total:g}** | "
                     + " | ".join(_fmt(x.scores[k]) for k in LABELS) + f" | {m.stars:,} |")
    lines.append("")
    for x in ranked[:top]:
        m = x.metrics
        lines += [
            f"## {x.rank}. {m.full_name}（{x.total:g} 分）", "",
            _inline(m.description) or "（沒有描述）", "",
            f"- 活躍度：近 90 天 commit {_fmt(m.commits_90d)}（最多計 100）、距最後 push {_fmt(m.pushed_days)} 天、"
            f"近一年 release {_fmt(m.releases_365d)} 次",
            f"- 維護：最近 issue 關閉比例 {_fmt(m.issue_closed_ratio)}、關閉天數中位數 {_fmt(m.issue_median_close_days)}、"
            f"已關閉 PR 合併比例 {_fmt(m.pr_merged_ratio)}",
            f"- 人員：近 90 天 commit 作者 {_fmt(m.authors_90d)} 人、第一大貢獻者佔 {_fmt(m.top_contributor_share)}",
            f"- 採用：星 {m.stars:,}、fork {m.forks:,}；動能：近 90 天新增星 {_fmt(m.stars_90d)}（最多計 100）",
            f"- 成熟度：社群健康度 {_fmt(m.health_pct)}%、CI {_fmt(m.has_ci)}、授權 {_fmt(m.license)}、"
            f"OpenSSF Scorecard {_fmt(m.scorecard)}",
        ]
        if m.missing:
            lines.append(f"- 缺資料（該項以其餘子項計分）：{'、'.join(m.missing)}")
        if m.error:
            lines.append(f"- 解析失敗（總分記 0）：{_inline(m.error)}")
        lines.append("")
    return "\n".join(lines)


class ScoutResult(BaseModel):
    query: str
    weights: dict[str, float]
    created: str
    candidates: int
    stars_available: bool
    api_calls: int | None = None  # gh 呼叫次數；另有每個候選一次 OpenSSF Scorecard（不算 GitHub 額度）
    wall_s: float
    ranked: list[Scored]
    json_path: str
    md_path: str


async def scout(settings: Settings, fetcher: Fetcher, keywords: str, lang: str | None = None,
                licenses: list[str] | None = None, per_query: int = 25, top: int = 10,
                weights: dict[str, float] | None = None, now: datetime | None = None) -> ScoutResult:
    if not keywords.strip():
        raise ValueError("請給關鍵字")
    if not 1 <= per_query <= 100:
        raise ValueError("--per-query 必須在 1～100")
    if top < 1:
        raise ValueError("--top 必須 ≥ 1")
    weights = weights or parse_weights(None)
    now = now or datetime.now(timezone.utc)
    t0 = asyncio.get_running_loop().time()
    query = build_query(keywords, lang, licenses or [])
    items = await candidates(fetcher, query, per_query)
    want_stars = await stars_available(fetcher, items)

    async def safe(it: dict[str, Any]) -> RepoMetrics:
        try:
            return await collect(fetcher, it, now, want_stars)
        except (AttributeError, TypeError, ValueError, KeyError) as exc:  # 單一 repo 資料異常不丟掉整批
            m = _base(it, now)
            m.error = f"{type(exc).__name__}: {exc}"[:200]
            return m

    metrics = await asyncio.gather(*(safe(it) for it in items))
    ranked = rank(list(metrics), weights)
    wall = round(asyncio.get_running_loop().time() - t0, 1)
    stamp = now.astimezone().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}_{_slug(keywords)}"
    jp = settings.data_dir / "scout" / f"{name}.json"
    mp = settings.ai_dir / "scout" / f"{name}.md"
    res = ScoutResult(query=query, weights=weights, created=now.isoformat(timespec="seconds"), candidates=len(items),
                      stars_available=want_stars, api_calls=getattr(fetcher, "calls", None), wall_s=wall, ranked=ranked,
                      json_path=str(jp), md_path=str(mp))
    for p, body in ((jp, res.model_dump_json(indent=2) + "\n"), (mp, render_md(query, weights, ranked, top, now))):
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_bytes(body.encode("utf-8") if body.endswith("\n") else (body + "\n").encode("utf-8"))
    return res
