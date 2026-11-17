"""legion scout：評分、權重、候選合併、報告；全部用假抓取器，不連網。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from legion.config import Settings
from legion.scout import (
    ARCHIVED_FACTOR,
    DEFAULT_WEIGHTS,
    NOT_FOUND,
    RepoMetrics,
    candidates,
    collect,
    parse_weights,
    rank,
    score,
    scout,
)

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def full() -> RepoMetrics:
    return RepoMetrics(full_name="a/full", stars=50_000, forks=5_000, pushed_days=1, commits_90d=100, authors_90d=8,
                       releases_365d=4, issue_closed_ratio=0.9, issue_median_close_days=2, pr_merged_ratio=0.9,
                       top_contributor_share=0.3, stars_90d=150, health_pct=100, has_ci=True, license="MIT",
                       scorecard=10.0)


def zero() -> RepoMetrics:
    return RepoMetrics(full_name="a/zero", stars=0, forks=0, pushed_days=400, commits_90d=0, authors_90d=1,
                       releases_365d=0, issue_closed_ratio=0.0, issue_median_close_days=365, pr_merged_ratio=0.0,
                       top_contributor_share=1.0, stars_90d=0, health_pct=0, has_ci=False, license=None,
                       scorecard=0.0)


def test_score_full_and_zero() -> None:
    assert all(v == 100.0 for v in score(full()).values())
    assert all(v == 0.0 for v in score(zero()).values())


def test_missing_data_uses_remaining_subitems() -> None:
    m = full()
    m.issue_median_close_days = None
    m.pr_merged_ratio = None
    m.scorecard = None
    s = score(m)
    assert s["maintenance"] == 100.0 and s["maturity"] == 100.0
    m2 = RepoMetrics(full_name="x/none")  # 幾乎全缺
    s2 = score(m2)
    assert s2["momentum"] is None and s2["people"] is None
    # 整類缺資料不當 0 分：其餘全滿分時總分仍是 100
    m3 = full()
    m3.stars_90d = None
    r = rank([m3], parse_weights(None))[0]
    assert r.scores["momentum"] is None and r.total == 100.0


def test_archived_penalty() -> None:
    a, b = full(), full()
    b.full_name, b.archived = "a/archived", True
    r = rank([a, b], parse_weights(None))
    assert r[0].metrics.full_name == "a/full"
    assert r[1].total == pytest.approx(r[0].total * ARCHIVED_FACTOR, abs=0.1)


def test_weights_override_and_validation() -> None:
    w = parse_weights(None)
    assert w == pytest.approx(DEFAULT_WEIGHTS) and sum(w.values()) == pytest.approx(1.0)
    w2 = parse_weights("adoption=0, momentum=0")
    assert w2["adoption"] == 0 and sum(w2.values()) == pytest.approx(1.0)
    for bad in ("stars=1", "activity", "activity=x", "activity=-1", "activity=nan", "activity=inf",
                ",".join(f"{k}=0" for k in DEFAULT_WEIGHTS)):
        with pytest.raises(ValueError):
            parse_weights(bad)


def test_contrast_stale_solo_ranks_below_active_team() -> None:
    """同樣星數：停更、單人維護的 repo 排在活躍、多人維護的後面（不只看星數）。"""
    active = RepoMetrics(full_name="z/active", stars=3000, forks=300, pushed_days=2, commits_90d=80, authors_90d=6,
                         releases_365d=3, issue_closed_ratio=0.75, issue_median_close_days=5, pr_merged_ratio=0.7,
                         top_contributor_share=0.4, stars_90d=60, health_pct=85, has_ci=True, license="MIT")
    stale = RepoMetrics(full_name="a/stale", stars=3000, forks=300, pushed_days=500, commits_90d=0, authors_90d=0,
                        releases_365d=0, issue_closed_ratio=0.1, issue_median_close_days=200, pr_merged_ratio=0.1,
                        top_contributor_share=0.98, stars_90d=2, health_pct=30, has_ci=False, license="MIT")
    r = rank([stale, active], parse_weights(None))
    assert [x.metrics.full_name for x in r] == ["z/active", "a/stale"]
    assert r[0].scores["adoption"] == r[1].scores["adoption"]


class FakeFetcher:
    def __init__(self, repos: dict[str, dict[str, Any]], search: dict[str | None, list[str]],
                 stars_ok: bool = True, overrides: dict[str, Any] | None = None) -> None:
        self.repos, self.search, self.calls = repos, search, 0
        self.stars_ok, self.overrides = stars_ok, overrides or {}
        self.paths: list[tuple[str, dict[str, str]]] = []

    def _item(self, name: str) -> dict[str, Any]:
        r = self.repos[name]
        return {"full_name": name, "description": r.get("desc", ""), "html_url": f"https://github.com/{name}",
                "language": "Python", "license": {"spdx_id": "MIT"}, "archived": r.get("archived", False),
                "stargazers_count": r["stars"], "forks_count": r.get("forks", 0), "pushed_at": iso(r["pushed"])}

    async def get(self, path: str, params: dict[str, str] | None = None, accept: str | None = None) -> Any:
        self.calls += 1
        params = params or {}
        self.paths.append((path, params))
        if path in self.overrides:
            return self.overrides[path]
        if path == "search/repositories":
            return {"items": [self._item(n) for n in self.search[params.get("sort")]]}
        name = "/".join(path.split("/")[1:3])
        r, tail = self.repos[name], "/".join(path.split("/")[3:])
        if tail == "commits":
            return [{"author": {"login": f"u{i % r['authors']}"}} for i in range(r["commits"])]
        if tail == "releases":
            return [{"published_at": iso(30)}] * r.get("releases", 0)
        if tail == "contributors":
            return [{"contributions": c} for c in r["contrib"]]
        if tail == "issues":  # 依建立時間新到舊；pr_flood 筆 PR 排最前面
            pr = {"state": "closed", "pull_request": {}, "created_at": iso(1), "closed_at": iso(0)}
            allx = ([pr] * r.get("pr_flood", 0)
                    + [{"state": "closed", "created_at": iso(10), "closed_at": iso(7)}] * r["closed"]
                    + [{"state": "open", "created_at": iso(5)}] * r["open"] + [pr])
            n, page = int(params["per_page"]), int(params["page"])
            return allx[(page - 1) * n: page * n]
        if tail == "pulls":
            return [{"merged_at": iso(1)}] * r["merged"] + [{"merged_at": None}] * r["unmerged"]
        if tail == "community/profile":
            return {"health_percentage": r["health"]}
        if tail == "contents/.github/workflows":
            return [{"name": "ci.yml"}] if r.get("ci") else NOT_FOUND
        if tail == "stargazers":
            assert accept == "application/vnd.github.star+json"
            if not self.stars_ok:
                return NOT_FOUND
            if params["per_page"] == "1":  # 整批的可用性探測
                return [{"starred_at": iso(1)}]
            last = max(1, -(-r["stars"] // 100))
            if params["page"] != str(last):  # 前一頁：都是舊的星
                return [{"starred_at": iso(300)}] * 100
            return [{"starred_at": iso(200)}] * 5 + [{"starred_at": iso(10)}] * r["new_stars"]
        raise AssertionError(path)

    async def scorecard(self, full_name: str) -> float | None:
        return self.repos[full_name].get("scorecard")


REPOS: dict[str, dict[str, Any]] = {
    "big/popular-stale": dict(stars=40_000, forks=4000, pushed=600, commits=0, authors=1, contrib=[990, 10],
                              closed=1, open=9, merged=0, unmerged=5, health=40, new_stars=3, desc="很多星但停更"),
    "small/active": dict(stars=800, forks=60, pushed=1, commits=90, authors=6, releases=5, contrib=[40, 30, 30],
                         pr_flood=120, closed=9, open=1, merged=8, unmerged=2, health=100, ci=True, new_stars=50, scorecard=7.5),
    "mid/ok": dict(stars=5000, forks=400, pushed=20, commits=30, authors=3, releases=1, contrib=[60, 40],
                   closed=6, open=4, merged=5, unmerged=5, health=70, ci=True, new_stars=20),
}


def test_candidates_merge_and_dedupe() -> None:
    f = FakeFetcher(REPOS, {"stars": ["big/popular-stale", "mid/ok"], None: ["small/active", "mid/ok"]})
    items = asyncio.run(candidates(f, "agent", 25))
    assert [i["full_name"] for i in items] == ["big/popular-stale", "mid/ok", "small/active"]
    sorts = [p.get("sort") for path, p in f.paths if path == "search/repositories"]
    assert sorts == ["stars", None]


def test_scout_end_to_end_writes_json_and_report(tmp_path: Path) -> None:
    s = Settings(vault=tmp_path / "vault", data_dir=tmp_path / "data")
    f = FakeFetcher(REPOS, {"stars": ["big/popular-stale", "mid/ok"], None: ["small/active"]})
    res = asyncio.run(scout(s, f, "agent orchestration", lang="python", licenses=["mit"], top=2, now=NOW))
    assert res.query == "agent orchestration language:python license:mit"
    assert res.candidates == 3 and res.api_calls == f.calls
    names = [x.metrics.full_name for x in res.ranked]
    assert names[0] == "small/active" and names[-1] == "big/popular-stale"  # 星數最多的排最後
    m = res.ranked[0].metrics
    assert (m.commits_90d, m.authors_90d, m.releases_365d) == (90, 6, 5)
    # 最新 120 筆都是 PR：要往下翻到第 2 頁才拿到真 issue，PR 不算 issue
    assert m.issue_closed_ratio == 0.9 and m.issue_median_close_days == 3.0
    assert [p["page"] for path, p in f.paths if path == "repos/small/active/issues"] == ["1", "2"]
    assert res.stars_available is True
    assert m.pr_merged_ratio == 0.8 and m.top_contributor_share == 0.4 and m.stars_90d == 50
    assert m.has_ci is True and m.scorecard == 7.5 and m.missing == []
    assert "scorecard" in res.ranked[-1].metrics.missing
    star_pages = [p["page"] for path, p in f.paths if path == "repos/small/active/stargazers"]
    assert star_pages == ["8", "7"]  # 800 星 → 最後一頁 8 不滿 100 筆，補第 7 頁

    data = json.loads(Path(res.json_path).read_text(encoding="utf-8"))
    assert data["ranked"][0]["metrics"]["commits_90d"] == 90 and Path(res.json_path).parent.name == "scout"
    md = Path(res.md_path).read_text(encoding="utf-8")
    assert Path(res.md_path).is_relative_to(s.ai_dir / "scout")
    assert "近 90 天 commit 90" in md and "OpenSSF Scorecard 7.5" in md and "small/active" in md
    assert "## 3." not in md  # top=2 只展開前兩名
    assert b"\r\n" not in Path(res.md_path).read_bytes()


def test_scout_rejects_bad_input(tmp_path: Path) -> None:
    s = Settings(vault=tmp_path / "vault", data_dir=tmp_path / "data")
    f = FakeFetcher(REPOS, {"stars": [], None: []})
    with pytest.raises(ValueError):
        asyncio.run(scout(s, f, "  ", now=NOW))
    with pytest.raises(ValueError):
        asyncio.run(scout(s, f, "x", per_query=0, now=NOW))
    with pytest.raises(ValueError):
        asyncio.run(scout(s, f, "x", top=0, now=NOW))


def test_stargazers_unavailable_probed_once_and_weight_redistributed(tmp_path: Path) -> None:
    s = Settings(vault=tmp_path / "vault", data_dir=tmp_path / "data")
    f = FakeFetcher(REPOS, {"stars": ["big/popular-stale", "mid/ok"], None: ["small/active"]}, stars_ok=False)
    res = asyncio.run(scout(s, f, "agent", now=NOW))
    assert res.stars_available is False
    assert len([p for p, _ in f.paths if p.endswith("/stargazers")]) == 1  # 只探測一次，不白打
    assert all(x.scores["momentum"] is None for x in res.ranked)
    md = Path(res.md_path).read_text(encoding="utf-8")
    assert "量不到「動能」" in md and "動能 10%" not in md and "活躍度 22%" in md


def test_ci_404_vs_fetch_error() -> None:
    item = FakeFetcher(REPOS, {})._item("mid/ok")
    wf = "repos/mid/ok/contents/.github/workflows"
    for payload, expect in ((NOT_FOUND, False), (None, None), ({"message": "rate limited"}, None)):
        f = FakeFetcher(REPOS, {}, overrides={wf: payload})
        assert asyncio.run(collect(f, item, NOW)).has_ci is expect


def test_malformed_payloads_do_not_crash() -> None:
    item = FakeFetcher(REPOS, {})._item("mid/ok")
    item["license"] = "MIT"  # 不是 dict
    bad = {
        "repos/mid/ok/commits": ["x", None, {"author": None, "commit": {"author": None}},
                                 {"author": None, "commit": {"author": {"email": "a@b"}}}],
        "repos/mid/ok/releases": [{"published_at": "2026-11-01T00:00:00"}, "x"],  # 沒有時區
        "repos/mid/ok/contributors": [{"contributions": "many"}, {"contributions": 3}],
        "repos/mid/ok/pulls": {"message": "Bad credentials"},
        "repos/mid/ok/community/profile": {"health_percentage": True},
    }
    m = asyncio.run(collect(FakeFetcher(REPOS, {}, overrides=bad), item, NOW))
    assert (m.commits_90d, m.authors_90d, m.releases_365d) == (2, 1, 1)  # 只算 dict 元素；作者只剩 email 那筆
    assert m.top_contributor_share == 1.0 and m.pr_merged_ratio is None and m.health_pct is None
    assert m.license is None


def test_report_escapes_untrusted_text(tmp_path: Path) -> None:
    repos = {k: dict(v) for k, v in REPOS.items()}
    repos["mid/ok"]["desc"] = "好工具\n# 假標題\n---\n[[秘密筆記]] | 表格"
    s = Settings(vault=tmp_path / "vault", data_dir=tmp_path / "data")
    f = FakeFetcher(repos, {"stars": ["mid/ok"], None: []})
    md = Path(asyncio.run(scout(s, f, "# x", now=NOW)).md_path).read_text(encoding="utf-8")
    assert "\n# 假標題" not in md and "\n---\n[[" not in md and "[[秘密筆記]]" not in md
    assert "好工具 # 假標題 --- [\\[秘密筆記]\\] \\| 表格" in md and "# 找 repo：\\# x" in md
