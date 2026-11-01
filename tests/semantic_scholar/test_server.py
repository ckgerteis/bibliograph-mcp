"""Fixture-driven tests for semantic-scholar-mcp.

The fixtures under tests/fixtures/ are real Semantic Scholar responses captured
on 2026-09-04 with curl and no key. Nothing here touches the network. The live
test at the bottom is gated on RUN_LIVE=1.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from bibliograph import mediation as M
from bibliograph.sources.semantic_scholar import server as S

FIX = Path(__file__).parent / "fixtures"
SCHEMA = json.loads((Path(__file__).parent.parent / "response-schema.json").read_text(encoding="utf-8"))


def _fixture(name: str):
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
    calls = []
    table: dict[str, tuple] = {}

    async def fake(method, url, params=None, json_body=None):
        calls.append((method, url, params, json_body))
        for key, val in table.items():
            if key in url:
                return val
        raise AssertionError(f"no fixture for {url}")

    monkeypatch.setattr(S, "_api_request", fake)
    table["_calls"] = calls  # type: ignore[assignment]
    return table


# ---------------------------------------------------------------- envelope shape

def test_search_papers_envelope(patched):
    patched["paper/search"] = (_fixture("paper_search_ja.json"), None)
    out = _run(S.s2_search_papers(S.PaperSearchInput(query="暴走族", limit=2)))
    env = json.loads(out)
    _validate(env)
    assert env["server"] == "semantic_scholar" and env["operation"] == "search_papers"
    assert env["searched_for"] == {"term": "暴走族", "script": "han", "matching": "relevance_ranked"}
    assert env["result"] == {"total": 291, "returned": 2, "start": 1, "breadth": "broad"}
    assert env["diagnostics"][0]["code"] == "OK"
    ja, zh = env["items"]
    assert ja["title"]["ja"] and ja["title"]["en"] is None          # kana present
    assert zh["title"] == {"ko": None, "ja": None, "en": None, "romanized": None}  # han-only: untyped
    assert zh["extra"]["title"].startswith("《东京暴走族》")
    assert ja["extra"]["s2_paper_id"] and ja["extra"]["corpus_id"]
    assert "fields" not in env["query"]["params"]


def test_get_paper_single(patched):
    patched["paper/DOI"] = (_fixture("paper_by_doi.json"), None)
    env = json.loads(_run(S.s2_get_paper(S.PaperLookupInput(paper_id="DOI:10.1017/S0026749X10000156"))))
    _validate(env)
    assert "searched_for" not in env and env["matching_mode"] == "identifier_lookup"
    it = env["items"][0]
    assert it["ids"]["doi"] == "10.1017/S0026749X10000156"
    assert it["source"]["journal_en"] == "Modern Asian Studies"
    assert it["ids"]["issn"] == "0026-749X"
    assert env["receipt"]["result_ids"] == ["10.1017/S0026749X10000156"]


def test_citations_total_not_reported(patched):
    patched["/citations"] = (_fixture("paper_citations.json"), None)
    env = json.loads(_run(S.s2_citations(S.CitationInput(paper_id="X", direction="citations", limit=2))))
    _validate(env)
    assert "searched_for" not in env and env["operation"] == "citations"
    codes = [d["code"] for d in env["diagnostics"]]
    assert codes[0] == "TOTAL_NOT_REPORTED"
    assert "further page" in env["diagnostics"][0]["message"]
    assert env["result"]["total"] == env["result"]["returned"] == 2
    assert env["items"][0]["ids"]["doi"] == "10.1215/1089201x-12354745"
    assert env["items"][0]["ids"]["fulltext_url"] is None   # empty openAccessPdf.url is not a URL


def test_author_papers_and_recommendations(patched):
    patched["/papers"] = (_fixture("author_papers.json"), None)
    env = json.loads(_run(S.s2_author_papers(S.AuthorPapersInput(author_id="2262347", limit=2, offset=4))))
    _validate(env)
    assert env["matching_mode"] == "filter_exact" and env["result"]["start"] == 5

    patched.clear()
    patched["forpaper"] = (_fixture("recommend_single.json"), None)
    env = json.loads(_run(S.s2_recommend_single(S.RecommendInput(paper_id="X", limit=2))))
    _validate(env)
    assert env["matching_mode"] == "similarity_ranked"
    assert [d["code"] for d in env["diagnostics"]] == ["TOTAL_NOT_REPORTED", "RECEIPT_NOT_DEPOSITED"]


def test_batch_partial_not_found_and_ids_in_receipt(patched):
    paper = _fixture("paper_by_doi.json")
    patched["paper/batch"] = ([paper, None], None)
    ids = ["DOI:10.1017/S0026749X10000156", "DOI:10.0000/none"]
    env = json.loads(_run(S.s2_batch_papers(S.BatchPaperInput(paper_ids=ids))))
    _validate(env)
    codes = [d["code"] for d in env["diagnostics"]]
    assert "PARTIAL_NOT_FOUND" in codes and "ZERO_RESULTS" not in codes
    assert env["coverage_note"].startswith("Unresolved: DOI:10.0000/none")
    assert env["query"]["params"]["ids"] == ids
    assert env["result"]["total"] == 1


def test_recommend_multi_seed_ids_in_params(patched):
    patched["papers/"] = ({"recommendedPapers": []}, None)
    env = json.loads(_run(S.s2_recommend_multi(S.MultiRecommendInput(positive_paper_ids=["a", "b"], negative_paper_ids=["c"]))))
    _validate(env)
    assert env["query"]["params"]["positive_paper_ids"] == ["a", "b"]
    assert "ZERO_RESULTS" in [d["code"] for d in env["diagnostics"]]
    _, url, _, body = patched["_calls"][0]
    assert body == {"positivePaperIds": ["a", "b"], "negativePaperIds": ["c"]}


# ---------------------------------------------------------------- diagnostics

def test_error_diag_passes_through(patched):
    patched["paper/search"] = (None, M.diag("error", "RATE_LIMITED", "429", None))
    env = json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="q"))))
    _validate(env)
    codes = [d["code"] for d in env["diagnostics"]]
    assert codes[0] == "RATE_LIMITED" and "ZERO_RESULTS" not in codes and "TOTAL_NOT_REPORTED" not in codes


def test_search_authors(patched):
    patched["author/search"] = ({"total": 1, "offset": 0, "data": [{"authorId": "1", "name": "Christopher Gerteis", "affiliations": ["SOAS"], "paperCount": 3, "hIndex": 1}]}, None)
    env = json.loads(_run(S.s2_search_authors(S.AuthorSearchInput(query="Christopher Gerteis"))))
    _validate(env)
    a = env["items"][0]
    assert a["record_type"] == "author" and a["extra"]["s2_author_id"] == "1" and a["title"]["en"] == "Christopher Gerteis"
    assert a["extra"]["name_match"] == "exact"


def test_search_authors_loose_match_reported_not_filtered(patched):
    # S2 author search returns loose matches and duplicate people; the exact
    # namesake and a same-surname stranger both come back, and the server
    # grades each rather than dropping or reordering either.
    patched["author/search"] = ({"total": 2, "offset": 0, "data": [
        {"authorId": "1", "name": "Christopher Gerteis", "aliases": ["C. Gerteis"], "paperCount": 3, "hIndex": 1},
        {"authorId": "2", "name": "John Gerteis", "paperCount": 1, "hIndex": 0},
    ]}, None)
    env = json.loads(_run(S.s2_search_authors(S.AuthorSearchInput(query="Christopher Gerteis"))))
    _validate(env)
    matches = [i["extra"]["name_match"] for i in env["items"]]
    assert matches == ["exact", "partial"]
    assert len(env["items"]) == 2  # both kept -- not filtered
    codes = [d["code"] for d in env["diagnostics"]]
    assert "LOOSE_NAME_MATCH" in codes
    diag = next(d for d in env["diagnostics"] if d["code"] == "LOOSE_NAME_MATCH")
    assert diag["level"] == "info" and "1 partial" in diag["message"]


def test_search_authors_matches_on_alias_too(patched):
    patched["author/search"] = ({"total": 1, "offset": 0, "data": [
        {"authorId": "1", "name": "C. Gerteis", "aliases": ["Christopher Gerteis"], "paperCount": 1, "hIndex": 0},
    ]}, None)
    env = json.loads(_run(S.s2_search_authors(S.AuthorSearchInput(query="Christopher Gerteis"))))
    _validate(env)
    assert env["items"][0]["extra"]["name_match"] == "exact"


# ---------------------------------------------------------------- record_type (S2 publicationTypes)

def test_record_type_mapped_from_publication_types(patched):
    paper = _fixture("paper_by_doi.json")
    for pub_types, expected in (
        (["JournalArticle"], "article"),
        (["Review"], "review"),
        (["Book"], "book"),
        (["BookSection"], "chapter"),
        (["Conference"], "conference paper"),
        (None, "article"),
        ([], "article"),
        (["SomethingS2InventsLater"], "article"),  # unrecognised type falls back, not crashes
    ):
        p = dict(paper)
        p["publicationTypes"] = pub_types
        patched["paper/DOI"] = (p, None)
        env = json.loads(_run(S.s2_get_paper(S.PaperLookupInput(paper_id="DOI:x"))))
        _validate(env)
        item = env["items"][0]
        assert item["record_type"] == expected, (pub_types, item["record_type"])
        assert item["extra"]["publication_types"] == pub_types


def test_record_type_first_recognised_type_wins(patched):
    paper = dict(_fixture("paper_by_doi.json"))
    paper["publicationTypes"] = ["JunkNotInVocabulary", "Book", "JournalArticle"]
    patched["paper/DOI"] = (paper, None)
    env = json.loads(_run(S.s2_get_paper(S.PaperLookupInput(paper_id="DOI:x"))))
    _validate(env)
    assert env["items"][0]["record_type"] == "book"


# ---------------------------------------------------------------- rate limit and secrets

def test_rate_limiter_serialises_concurrent_calls(monkeypatch):
    times = []

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"data": []}

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None):
            times.append(asyncio.get_event_loop().time())
            assert headers.get("x-api-key") == "SECRET"
            assert not params or "SECRET" not in json.dumps(params)
            return _Resp()

    monkeypatch.setattr(S.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(S, "API_KEY", "SECRET")
    monkeypatch.setattr(S, "RATE_LIMIT_DELAY", 0.05)
    monkeypatch.setattr(S, "_rate_lock", None)
    monkeypatch.setattr(S, "_last_request_time", 0.0)

    async def go():
        await asyncio.gather(*[S._api_request("GET", "u", params={"q": "x"}) for _ in range(4)])

    _run(go())
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(times) == 4 and all(g >= 0.045 for g in gaps), gaps


def test_non_json_200_is_api_error(monkeypatch):
    class _Resp:
        status_code = 200
        text = "<html>"
        def json(self):
            raise ValueError("no")

    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()

    monkeypatch.setattr(S.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(S, "RATE_LIMIT_DELAY", 0)
    data, err = _run(S._api_request("GET", "u"))
    assert data is None and err["code"] == "API_ERROR"


# ---------------------------------------------------------------- live (opt-in)

@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit api.semanticscholar.org")
def test_live_get_paper():
    env = json.loads(_run(S.s2_get_paper(S.PaperLookupInput(paper_id="DOI:10.1017/S0026749X10000156"))))
    _validate(env)
    assert env["diagnostics"][0]["code"] in ("OK", "RATE_LIMITED")
