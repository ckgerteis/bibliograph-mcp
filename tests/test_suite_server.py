"""The gathered server: --only, skip-and-report, status, version, tool names kept."""
import json
import sys
import types

import pytest

from bibliograph import __version__, server as S

# Tool names each source must keep: skills and prompts name them directly.
KEPT = {
    "ndl": {"ndl_search_books", "ndl_get_record"},
    "cinii": {"cinii_search_articles", "cinii_search_books", "cinii_search_researchers"},
    "jstage": {"jstage_search_articles"},
    "openalex": {"oa_search_works", "oa_search_authors"},
    "semantic_scholar": {"s2_search_papers"},
    "crossref": {"cr_search_works", "cr_get_work", "cr_match_citation"},
    "warp": {"warp_list_captures", "warp_read_capture"},
    "ndl_dl": {"ndl_dl_fulltext_search"},
    "jdcat": {"jdcat_search", "jdcat_get_record"},
    "fetch": {"fetch_pdf", "fetch_pdf_text"},
    "names": {"name_query_variants", "resolve_name_readings", "name_authority"},
}


def tools(suite):
    return set(S._registry(suite.mcp))


def test_all_sources_load_and_keep_their_tool_names():
    suite = S.Suite()
    assert suite.skipped == []
    assert [x["source"] for x in suite.loaded] == list(S.SOURCES)
    names = tools(suite)
    for src, expected in KEPT.items():
        assert expected <= names, (src, expected - names)
    assert "bibliograph_status" in names


def test_only_restricts_the_tool_list():
    suite = S.Suite(only=["cinii"])
    names = tools(suite)
    assert KEPT["cinii"] <= names
    assert not (KEPT["ndl"] & names) and not (KEPT["names"] & names)
    assert names - {"bibliograph_status"} == set(suite.loaded[0]["tools"])


def test_unknown_key_is_reported_not_fatal():
    suite = S.Suite(only=["cinii", "nosuch"])
    assert [x["source"] for x in suite.loaded] == ["cinii"]
    assert suite.skipped[0]["source"] == "nosuch"


def test_a_failing_source_is_skipped_and_the_rest_load(monkeypatch):
    monkeypatch.setitem(S.SOURCES, "broken", "bibliograph_test_broken_module")
    mod = types.ModuleType("bibliograph_test_broken_module")

    def boom(name, *a, **k):
        if name == "bibliograph_test_broken_module":
            raise ImportError("simulated failure")
        return real(name, *a, **k)
    real = S.importlib.import_module
    monkeypatch.setattr(S.importlib, "import_module", boom)
    suite = S.Suite(only=["cinii", "broken"])
    assert [x["source"] for x in suite.loaded] == ["cinii"]
    assert suite.skipped[0]["source"] == "broken"
    assert "simulated failure" in suite.skipped[0]["reason"]


def test_status_reports_versions():
    suite = S.Suite(only=["ndl", "names"])
    st = suite.status()
    assert st["bibliograph"] == __version__
    by = {x["source"]: x for x in st["loaded"]}
    assert by["ndl"]["version"] and by["names"]["version"]
    fn = S._registry(suite.mcp)["bibliograph_status"].fn
    assert json.loads(fn())["loaded"][0]["source"] == "ndl"


def test_env_only_and_cli_only(monkeypatch):
    monkeypatch.setenv("BIBLIOGRAPH_ONLY", "jstage")
    assert [x["source"] for x in S.build([]).loaded] == ["jstage"]
    assert [x["source"] for x in S.build(["--only", "warp"]).loaded] == ["warp"]


def test_server_reports_its_own_version():
    srv = S._new_server()
    low = getattr(srv, "_mcp_server", None)
    if low is not None and hasattr(low, "version"):
        assert low.version == __version__


def test_status_reports_openalex_budget(monkeypatch):
    from bibliograph.sources.openalex import server as OA
    monkeypatch.setattr(OA, "budget_snapshot", lambda: {"daily_remaining_usd": 0.5})
    st = S.Suite(only=["openalex"]).status()
    assert st["budgets"]["openalex"] == {"daily_remaining_usd": 0.5}


def test_status_survives_a_failing_budget(monkeypatch):
    from bibliograph.sources.openalex import server as OA

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(OA, "budget_snapshot", boom)
    st = S.Suite(only=["openalex"]).status()
    assert "RuntimeError" in st["budgets"]["openalex"]["error"]
