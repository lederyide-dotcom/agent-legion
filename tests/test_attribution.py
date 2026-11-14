"""作者與原始出處內建在程式與產出裡：clone 後執行也會標示，且與 NOTICE／CITATION.cff 一致。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import legion
from legion.brief import render
from legion.cli import main
from legion.config import PROJECT_ROOT

URL = "https://github.com/lederyide-dotcom/agent-legion"
AUTHOR = "DavidY-tw"


def test_package_metadata_and_version_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert legion.__author__ == AUTHOR and legion.__url__ == URL
    assert AUTHOR in legion.ATTRIBUTION and URL in legion.ATTRIBUTION
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert URL in out and AUTHOR in out and "保留所有權利" in out


def test_notice_citation_license_consistent() -> None:
    root = Path(PROJECT_ROOT)
    for name in ("LICENSE", "NOTICE"):
        text = (root / name).read_text(encoding="utf-8")
        assert URL in text and AUTHOR in text, name
    cff = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    assert cff["repository-code"] == URL and cff["authors"][0]["alias"] == "DavidY-tw"
    assert cff["version"] == legion.__version__
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert URL in readme and "NOTICE" in readme and "CITATION.cff" in readme


def test_author_name_is_unified() -> None:
    """2026-11-14 David 決定作者名統一為 DavidY-tw、不放本名：署名檔不得出現舊寫法。"""
    root = Path(PROJECT_ROOT)
    for name in ("LICENSE", "NOTICE", "CITATION.cff", "README.md", "pyproject.toml",
                 "03_docs/sharing_and_citation.md", "03_docs/public_release_license.md", "src/legion/__init__.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "奕德" not in text and "DavidY " not in text and "DavidY）" not in text, name


def test_brief_footer_carries_attribution() -> None:
    b = {"date": "2026-11-14", "waiting": [], "recent_halts": [], "pending_merge": [], "cleanable": [],
         "missions": [], "cost_yesterday": 0.0, "cost_today": 0.0, "daily_budget": 2.0}
    try:
        text = render(b)
    except KeyError as e:  # 晨報欄位若擴充，這裡補上即可
        pytest.fail(f"晨報欄位缺 {e}")
    assert text.rstrip().endswith(f"_由 {legion.ATTRIBUTION} 產生_")
