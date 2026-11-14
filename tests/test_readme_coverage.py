"""README 覆蓋檢查：程式裡有的角色、狀態、子命令，README 對應段落都要寫到。

背景：T-0022 之後 README 雖然有「軍師」一節，主流程圖與角色表卻漏掉軍師（2026-11-14）。
整份文件搜字串抓不到這種漏，所以這裡逐段比對：新增角色、狀態或子命令卻沒更新 README，測試就失敗。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from legion.cli import ROLE_LABELS, build_parser
from legion.config import DEFAULT_ROLE_MODELS
from legion.models import State

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

# 只在戰役中出場、不在單一任務主流程圖裡的角色
NOT_IN_MAIN_CHART = {"strategist"}


def _section(start: str) -> str:
    """從標題切到下一個同級或更高級標題（不寫死下一節名稱，調整順序也不會吞進別節）。"""
    i = README.index(start)
    level = len(start.split(" ")[0])
    m = re.compile(r"\n#{1,%d} " % level).search(README, i + len(start))
    return README[i:m.start() if m else len(README)]


def _short(label: str) -> str:
    return label.split("（")[0]


def _model_row_name(label: str) -> str:
    """只給模型分配表用：指揮官分規劃／執行兩列，保留括號；其他角色取短名。"""
    return label if label.startswith("指揮官") else _short(label)


MAIN = _section("## 閉環流程")
_start = MAIN.index("```mermaid")
MAIN_CHART = MAIN[_start:MAIN.index("```", _start + 3)]
ROLE_TABLE = MAIN[MAIN.index("| 角色 |"):]
MODELS = _section("### 模型分配")


@pytest.mark.parametrize("state", list(State), ids=lambda s: s.value)
def test_main_chart_has_every_state(state: State) -> None:
    assert re.search(rf"\b{state.value}\b", MAIN_CHART), f"主流程圖缺少 {state.value}"


@pytest.mark.parametrize("role", sorted(ROLE_LABELS))
def test_role_table_has_every_role(role: str) -> None:
    assert _short(ROLE_LABELS[role]) in ROLE_TABLE, f"閉環流程的角色表缺少 {ROLE_LABELS[role]}"


@pytest.mark.parametrize("role", sorted(set(ROLE_LABELS) - NOT_IN_MAIN_CHART))
def test_main_chart_has_every_role(role: str) -> None:
    assert _short(ROLE_LABELS[role]) in MAIN_CHART, f"主流程圖缺少 {ROLE_LABELS[role]}"


def test_role_table_has_both_commanders() -> None:
    row = next(line for line in ROLE_TABLE.splitlines() if line.startswith("| 指揮官"))
    assert "規劃" in row and "執行" in row


def test_main_chart_has_both_commanders() -> None:
    assert "PLAN<br/>指揮官" in MAIN_CHART and "EXEC<br/>指揮官" in MAIN_CHART


@pytest.mark.parametrize("role", sorted(ROLE_LABELS))
def test_models_table_has_every_role(role: str) -> None:
    name = _model_row_name(ROLE_LABELS[role])
    assert f"| {name} |" in MODELS, f"模型分配表缺少 {name}"


def _subcommands() -> list[str]:
    # argparse 沒有列出子命令的公開 API；_actions／_SubParsersAction 自 3.2 起未變
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return sorted(sub.choices)


@pytest.mark.parametrize("cmd", _subcommands())
def test_readme_mentions_every_subcommand(cmd: str) -> None:
    assert re.search(rf"legion {re.escape(cmd)}(?![\w-])", README), f"README 沒提到 legion {cmd}"


# ---- 環境變數：程式讀到的每個 LEGION_* 都要寫進 README 的變數表與 .env.example ----
ROOT = Path(__file__).resolve().parents[1]
SETTINGS = _section("## 設定")
# 只看「主要變數」那張表：其他小節順帶提到不算數
_vt = SETTINGS.index("| 變數 |")
_vt_end = SETTINGS.find("\n\n", _vt)
ENV_TABLE = SETTINGS[_vt:_vt_end if _vt_end != -1 else len(SETTINGS)]
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
# 只給測試用的掛鉤，不必出現在 .env.example（README 仍要寫明用途）
TEST_ONLY_ENV = {"LEGION_CRASH_AT"}


def _env_vars() -> list[str]:
    """掃 src/legion 下所有 .py（含子目錄）的完整變數名。

    - 結尾是底線的字首（例如 f"LEGION_MODEL_{role}"）不算，另由逐角色測試檢查。
    - 註解與 docstring 裡的名稱也會被掃到：寫範例名就要在文件列出，或改寫成 `LEGION_MODEL_<角色>`。
    - 執行時拼出來的名稱（"LEGION_" + x）掃不到。
    """
    found: set[str] = set()
    for f in (ROOT / "src" / "legion").rglob("*.py"):
        found |= set(re.findall(r"(?<![A-Za-z0-9_])LEGION_[A-Z0-9_]*[A-Z0-9](?![A-Za-z0-9_])",
                                f.read_text(encoding="utf-8")))
    return sorted(found)


def test_env_scan_finds_known_vars() -> None:
    assert {"LEGION_DB_PORT", "LEGION_ADVISOR", "LEGION_SCHEMA"} <= set(_env_vars())


@pytest.mark.parametrize("var", _env_vars())
def test_readme_settings_has_every_env_var(var: str) -> None:
    assert re.search(rf"`{var}`", ENV_TABLE), f"README 主要變數表沒寫 {var}"


@pytest.mark.parametrize("var", sorted(set(_env_vars()) - TEST_ONLY_ENV))
def test_env_example_has_every_env_var(var: str) -> None:
    assert re.search(rf"^#?\s*{var}=", ENV_EXAMPLE, re.M), f".env.example 沒有 {var}"


def test_role_lists_agree() -> None:
    """README 檢查用 cli 的 ROLE_LABELS；實際讀環境變數的是 config 的 DEFAULT_ROLE_MODELS，兩者要一致。"""
    assert set(ROLE_LABELS) == set(DEFAULT_ROLE_MODELS)


@pytest.mark.parametrize("role", sorted(DEFAULT_ROLE_MODELS))
def test_settings_lists_every_role_override(role: str) -> None:
    row = next(line for line in ENV_TABLE.splitlines() if "LEGION_MODEL_<角色>" in line)
    assert f"`{role.upper()}`" in row, f"逐角色覆寫沒列 {role.upper()}"
