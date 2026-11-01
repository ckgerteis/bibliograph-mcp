"""Fixture-driven tests for openalex-mcp.

The fixtures under tests/fixtures/ are real OpenAlex responses captured on
2026-09-04 with curl. Nothing here touches the network, so the suite runs
without an API key and without spending the per-IP daily budget. The live
tests at the bottom are gated on RUN_LIVE=1.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from bibliograph import mediation as M
from bibliograph.sources.openalex import server as S

FIX = Path(__file__).parent / "fixtures"
SCHEMA = json.loads((Path(__file__).parent.parent / "response-schema.json").read_text(encoding="utf-8"))


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _validate(env: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(env, SCHEMA)


def _run(coro):
    # asyncio.run, not get_event_loop(): since 3.14 there is no implicit loop
    # in the main thread, and get_event_loop() raises instead of creating one.
    return asyncio.run(coro)


@pytest.fixture
def patched(monkeypatch):
    """Route _oa_request to a fixture chosen by endpoint substring."""
    table: dict[str, tuple] = {}

    async def fake(endpoint, params=None):
        for key, val in table.items():
            if key in endpoint:
                return val
        raise AssertionError(f"no fixture for {endpoint}")

    monkeypatch.setattr(S, "_oa_request", fake)
    monkeypatch.setattr(S, "API_KEY", "TESTKEY-SHOULD-NOT-LEAK")
    return table


# ---------------------------------------------------------------- envelope shape

def test_search_works_envelope_validates(patched):
    patched["works"] = (_fixture("works_search_bosozoku.json"), None)
    out = _run(S.oa_search_works(S.WorkSearchInput(query="bosozoku", per_page=3)))
    env = json.loads(out)
    _validate(env)
    assert env["server"] == "openalex"
    assert env["schema_version"] == M.SCHEMA_VERSION
    assert env["operation"] == "search_works"
    assert env["searched_for"] == {"term": "bosozoku", "script": "latin", "matching": S.MODE_SEARCH}
    assert env["matching_mode"] == "full_text_stemmed"
    assert env["result"] == {"total": 94, "returned": 3, "start": 1, "breadth": "broad"}
    assert [d["code"] for d in env["diagnostics"]][0] == "OK"
    assert env["attribution"].startswith("Data via OpenAlex")
    assert env["receipt"]["query_hash"].startswith("sha256:")
    item = env["items"][0]
    assert item["record_type"] in ("article", "book", "book-chapter", "dissertation", "review", "other", "preprint")
    assert item["extra"]["openalex_id"].startswith("W")
    assert "TESTKEY" not in out


def test_japanese_titles_are_typed_by_openalex_language(patched):
    patched["works"] = (_fixture("works_search_ja.json"), None)
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="暴走族", per_page=3))))
    _validate(env)
    assert env["searched_for"]["script"] == "han"
    langs = [i["extra"]["language"] for i in env["items"]]
    assert langs == ["ja", "ja", "zh"]
    ja, ja2, zh = env["items"]
    assert ja["title"]["ja"] and ja["title"]["en"] is None and ja["title"]["ko"] is None
    # A work OpenAlex marks zh goes to no typed slot: it is neither Japanese,
    # Korean, nor Latin-script. extra.title still carries it.
    assert zh["title"] == {"ko": None, "ja": None, "en": None, "romanized": None}
    assert zh["extra"]["title"].startswith("暴走族")


def test_place_title_without_language_does_not_guess_han():
    assert S._place_title("暴走族の実態", None)["title_ja"] == "暴走族の実態"       # kana present
    assert S._place_title("暴走族", None) == {"title_ja": None, "title_ko": None, "title_en": None}  # han only: no guess
    assert S._place_title("폭주족 연구", None)["title_ko"] == "폭주족 연구"
    assert S._place_title("Bosozoku", None)["title_en"] == "Bosozoku"


def test_get_work_single_item_no_searched_for(patched):
    patched["works/"] = (_fixture("work_by_doi.json"), None)
    env = json.loads(_run(S.oa_get_work(S.WorkLookupInput(work_id="10.1215/9780822392194"))))
    _validate(env)
    assert "searched_for" not in env
    assert env["matching_mode"] == "identifier_lookup"
    assert env["result"]["total"] == 1 and env["result"]["returned"] == 1
    it = env["items"][0]
    assert it["ids"]["doi"] == "10.1215/9780822392194"
    assert it["matched_in"] == "identifier"
    assert env["receipt"]["result_ids"] == ["10.1215/9780822392194"]


def test_cited_by_is_filter_not_search(patched):
    patched["works"] = (_fixture("works_cited_by.json"), None)
    env = json.loads(_run(S.oa_cited_by(S.CitedByInput(work_id="W2041565646", per_page=2))))
    _validate(env)
    assert "searched_for" not in env
    assert env["matching_mode"] == "filter_exact"
    assert env["query"]["params"]["filter"] == "cites:W2041565646"
    assert env["result"]["total"] == 27


def test_author_source_institution_records(patched):
    patched["authors"] = (_fixture("authors_search.json"), None)
    env = json.loads(_run(S.oa_search_authors(S.AuthorSearchInput(query="Christopher Gerteis", per_page=2))))
    _validate(env)
    a = env["items"][0]
    assert a["record_type"] == "author" and a["extra"]["openalex_id"].startswith("A")
    assert isinstance(a["extra"]["affiliations"], list)

    patched.clear()
    patched["sources"] = (_fixture("sources_search.json"), None)
    env = json.loads(_run(S.oa_search_sources(S.SourceSearchInput(query="Japan Forum", per_page=2))))
    _validate(env)
    s = env["items"][0]
    assert s["record_type"] == "source" and s["ids"]["issn"]

    patched.clear()
    patched["institutions"] = (_fixture("institutions_search.json"), None)
    env = json.loads(_run(S.oa_search_institutions(S.InstitutionSearchInput(query="SOAS", per_page=1))))
    _validate(env)
    i = env["items"][0]
    assert i["record_type"] == "institution" and i["extra"]["ror"]


def test_author_search_name_match_exact(patched):
    patched["authors"] = (_fixture("authors_search.json"), None)
    env = json.loads(_run(S.oa_search_authors(S.AuthorSearchInput(query="Christopher Gerteis", per_page=2))))
    _validate(env)
    # Both records are "Christopher Gerteis" up to case -> both exact, so no
    # LOOSE_NAME_MATCH diagnostic is raised.
    assert [i["extra"]["name_match"] for i in env["items"]] == ["exact", "exact"]
    assert "LOOSE_NAME_MATCH" not in [d["code"] for d in env["diagnostics"]]


def test_author_search_name_match_partial_raises_loose_name_match(patched):
    patched["authors"] = (_fixture("authors_search.json"), None)
    env = json.loads(_run(S.oa_search_authors(S.AuthorSearchInput(query="Gerteis", per_page=2))))
    _validate(env)
    # A surname-only query is a proper subset of each full display name.
    assert [i["extra"]["name_match"] for i in env["items"]] == ["partial", "partial"]
    codes = [d["code"] for d in env["diagnostics"]]
    assert "LOOSE_NAME_MATCH" in codes
    diag = next(d for d in env["diagnostics"] if d["code"] == "LOOSE_NAME_MATCH")
    assert diag["level"] == "info" and "2 partial" in diag["message"]


def test_non_author_search_has_no_name_match(patched):
    patched["works"] = (_fixture("works_search_bosozoku.json"), None)
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="bosozoku", per_page=3))))
    _validate(env)
    assert "name_match" not in env["items"][0]["extra"]


def test_pagination_start(patched):
    data = _fixture("works_search_bosozoku.json")
    data["meta"]["page"] = 3
    patched["works"] = (data, None)
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="bosozoku", per_page=3, page=3))))
    assert env["result"]["start"] == 7


# ---------------------------------------------------------------- diagnostics

def test_zero_results_diagnostic(patched):
    patched["works"] = ({"meta": {"count": 0, "page": 1, "per_page": 10}, "results": []}, None)
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="xyzzy-nothing"))))
    _validate(env)
    assert env["result"]["breadth"] == "none"
    assert [d["code"] for d in env["diagnostics"]][0] == "ZERO_RESULTS"


def test_error_diag_passes_through_and_total_is_zero(patched):
    err = M.diag("error", "RATE_LIMITED", "OpenAlex answered 429", None)
    patched["works"] = (None, err)
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="bosozoku"))))
    _validate(env)
    codes = [d["code"] for d in env["diagnostics"]]
    assert codes[0] == "RATE_LIMITED" and "ZERO_RESULTS" not in codes
    assert env["items"] == [] and env["result"]["total"] == 0


def test_malformed_page_does_not_crash(patched):
    patched["works"] = ({"meta": {"count": "not-a-number"}, "results": [None, {"id": "https://openalex.org/W1"}]}, None)
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="q"))))
    _validate(env)
    assert env["result"]["returned"] == 1


# ---------------------------------------------------------------- secrets

def test_key_never_enters_params_or_receipt(patched):
    patched["works"] = (_fixture("works_search_bosozoku.json"), None)
    out = _run(S.oa_search_works(S.WorkSearchInput(query="bosozoku")))
    assert "TESTKEY" not in out
    env = json.loads(out)
    assert "api_key" not in env["query"]["params"] and "mailto" not in env["query"]["params"]


def test_request_copies_params(monkeypatch):
    """_oa_request must not write the credential into the caller's dict."""
    seen = {}

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"meta": {}, "results": []}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None):
            seen.update(params or {})
            return _Resp()

    monkeypatch.setattr(S.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(S, "API_KEY", "SECRET")
    qp = {"search": "x"}
    data, err = _run(S._oa_request("works", qp))
    assert err is None and seen["api_key"] == "SECRET"
    assert "api_key" not in qp


def test_redact_strips_key_from_error_text(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "SECRET")
    assert S._redact("bad SECRET here") == "bad [redacted] here"


# ---------------------------------------------------------------- live (opt-in)

@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit api.openalex.org")
def test_live_search():
    env = json.loads(_run(S.oa_search_works(S.WorkSearchInput(query="bosozoku", per_page=2))))
    _validate(env)
    assert env["diagnostics"][0]["code"] in ("OK", "RATE_LIMITED")
