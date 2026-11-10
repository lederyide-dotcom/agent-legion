import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from textkit import slugify  # noqa: E402


def test_slugify_basic() -> None:
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_trims() -> None:
    assert slugify("  --Agent Legion--  ") == "agent-legion"
