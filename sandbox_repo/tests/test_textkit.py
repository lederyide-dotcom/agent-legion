import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from textkit import char_count, slugify  # noqa: E402


def test_slugify_basic() -> None:
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_trims() -> None:
    assert slugify("  --Agent Legion--  ") == "agent-legion"


def test_char_count_basic() -> None:
    assert char_count("a b c") == 3


def test_char_count_tab_newline() -> None:
    assert char_count("a\tb\nc") == 3


def test_char_count_empty() -> None:
    assert char_count("") == 0


def test_char_count_all_whitespace() -> None:
    assert char_count(" \t\n") == 0


def test_char_count_fullwidth_space() -> None:
    assert char_count("你　好") == 2
