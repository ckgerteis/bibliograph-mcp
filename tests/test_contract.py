"""tests/test_contract.py -- the bibliograph contract (docs/CONTRACT.md), enforced.

Offline, no network. Three things:

  * The version numbers this test asserts are read out of CONTRACT.md itself
    by regex, so the doc and the code cannot silently drift apart -- whichever
    one is edited first, the test fails until the other catches up.
  * No source under src/bibliograph/sources vendors its own mediation.py/ledger.py:
    everything imports the one copy at src/bibliograph/{mediation,ledger}.py.
  * An outside module built for this test only, registered the way --with
    registers a real one, loads and its tool appears in the suite.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from bibliograph import ledger, mediation, server as S

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "docs" / "CONTRACT.md"
SOURCES_DIR = REPO_ROOT / "src" / "bibliograph" / "sources"


def _contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def _contract_version(field: str) -> str:
    """Pull the version CONTRACT.md states for `field`
    (SCHEMA_VERSION or LEDGER_VERSION) out of its 'currently **`"X.Y.Z"`**' phrasing.
    """
    m = re.search(
        rf'{field}.*?currently \*\*`"(\d+\.\d+\.\d+)"`\*\*',
        _contract_text(),
        re.DOTALL,
    )
    assert m, f"CONTRACT.md does not state a currently-`\"X.Y.Z\"` value for {field}"
    return m.group(1)


def test_contract_doc_exists():
    assert CONTRACT.is_file(), "docs/CONTRACT.md is missing"


def test_schema_version_matches_the_contract():
    assert mediation.SCHEMA_VERSION == _contract_version("SCHEMA_VERSION")


def test_ledger_version_matches_the_contract():
    assert ledger.LEDGER_VERSION == _contract_version("LEDGER_VERSION")


def test_no_stray_mediation_or_ledger_copies_under_sources():
    """Every source imports the one bibliograph.mediation / bibliograph.ledger; none
    vendors its own copy under src/bibliograph/sources/."""
    strays = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in SOURCES_DIR.rglob("*")
        if p.name in ("mediation.py", "ledger.py")
    )
    assert strays == [], f"stray vendored copies found: {strays}"


_FAKE_MODULE_SRC = '''
try:
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer as _MCPServer

__version__ = "0.0.1"

mcp = _MCPServer("fake_outside_source")


@mcp.tool()
def fake_ping() -> str:
    """A single tool, to prove --with copied it in."""
    return "pong"
'''


@pytest.fixture
def fake_outside_module(tmp_path):
    """A tiny outside package on sys.path, built fresh per test and torn down
    after: one FastMCP-or-MCPServer instance at module level, one tool,
    exactly what --with requires and nothing else."""
    mod_name = "bibliograph_test_fake_outside"
    (tmp_path / f"{mod_name}.py").write_text(_FAKE_MODULE_SRC, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        yield mod_name
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(mod_name, None)


def test_with_loads_an_outside_module_and_its_tool_appears(fake_outside_module):
    suite = S.Suite(only=["names"], extra=[fake_outside_module])
    assert suite.skipped == []
    sources = {x["source"]: x for x in suite.loaded}
    assert fake_outside_module in sources
    assert sources[fake_outside_module]["outside"] is True
    assert sources[fake_outside_module]["version"] == "0.0.1"
    assert "fake_ping" in sources[fake_outside_module]["tools"]
    assert "fake_ping" in S._registry(suite.mcp)
