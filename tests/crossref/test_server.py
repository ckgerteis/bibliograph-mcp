"""crossref source: envelope, matching caveats, redaction, rate headers. Offline.

Fixtures are real Crossref responses captured 1 Nov 2026 (polite pool).
"""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from bibliograph.sources.crossref import server as S

FX = Path(__file__).parent / "fixtures"


def _fx(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))["message"]


@pytest.fixture
def answer(monkeypatch):
    box = {}

    async def fake(path, params=None):
        box["path"], box["params"] = path, params
        return box.get("data"), box.get("err")
    monkeypatch.setattr(S, "_cr_request", fake)

    async def no_oa(data, single):
        return None, None
    monkeypatch.setattr(S, "_oa_links", no_oa)
    return box


def _env(out):
    env = json.loads(out)
    return env, [d["code"] for d in env["diagnostics"]]


def test_search_builds_items_and_states_any_term(answer):
    answer["data"] = _fx("works_search_bosozoku.json")
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(query="bosozoku Japan", rows=5))))
    assert codes[0] == "OK" and "TOTAL_IS_ANY_TERM" in codes
    assert env["matching_mode"] == "relevance_ranked_any_term"
    assert env["result"]["total"] == 1184944 and env["result"]["returned"] == 5
    first = env["items"][0]
    assert first["ids"]["doi"] == "10.55156/jjsem.dec2109"
    assert first["ids"]["fulltext_url"] is None
    assert "Crossref" in env["coverage_note"] and "Japanese-language" in env["coverage_note"]
    assert answer["params"]["query.bibliographic"] == "bosozoku Japan"
    assert env["receipt"]["result_ids"][0] == "10.55156/jjsem.dec2109"


def test_markup_and_entities_are_removed(answer):
    answer["data"] = _fx("works_search_bosozoku.json")
    env, _ = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(query="bosozoku Japan", rows=5))))
    titles = [it["extra"]["title"] for it in env["items"]]
    assert any(t.startswith("Bosozoku: flow in Japanese") for t in titles)
    assert not any("<" in (t or "") or "&amp;" in (t or "") for t in titles)


def test_cjk_query_is_warned(answer):
    answer["data"] = _fx("works_search_ja.json")
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(query="暴走族"))))
    assert codes[:2] == ["OK", "CJK_QUERY_WEAK"]
    ja = [it for it in env["items"] if it["title"]["ja"]]
    assert ja, "a kana title should be typed ja"


def test_get_work(answer):
    answer["data"] = json.loads((FX / "work_by_doi.json").read_text(encoding="utf-8"))["message"]
    env, codes = _env(asyncio.run(S.cr_get_work(S.WorkLookupInput(doi="https://doi.org/10.1177/0011128793039003002"))))
    assert answer["path"] == "works/10.1177/0011128793039003002"
    it = env["items"][0]
    assert codes[0] == "OK" and env["coverage_note"] is None
    assert it["source"]["journal_en"] == "Crime & Delinquency"
    assert it["source"]["year"] == 1993 and it["source"]["pages"] == "277-295"
    assert it["authors"][0]["name"] == "Joachim Kersten"
    assert it["extra"]["abstract"].startswith("A number of Western assumptions")
    assert it["record_type"] == "journal-article"


def test_doi_validation():
    for bad in ("not a doi", "10.12/x", "10.1234/../etc"):
        with pytest.raises(Exception):
            S.WorkLookupInput(doi=bad)
    assert S.WorkLookupInput(doi="doi: 10.1515/9781501756337").doi == "10.1515/9781501756337"


def test_match_citation_returns_candidates_not_verdict(answer):
    answer["data"] = _fx("works_resolve_citation.json")
    env, codes = _env(asyncio.run(S.cr_match_citation(
        S.CitationMatchInput(citation="Gerteis Mobilizing Japanese Youth Cornell 2021"))))
    assert codes[:2] == ["OK", "CANDIDATES_NOT_VERDICT"]
    assert env["items"][0]["ids"]["doi"] == "10.1515/9781501756337"
    scores = [it["extra"]["score"] for it in env["items"]]
    assert scores == sorted(scores, reverse=True) and scores[1] > 0.8 * scores[0]


def test_search_needs_something_to_search(answer):
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput())))
    assert codes[0] == "INVALID_INPUT" and "path" not in answer


def test_filters_and_sort_are_built(answer):
    answer["data"] = {"total-results": 0, "items": []}
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(
        author="Gerteis", year_from=2000, year_to=2010, type="journal-article",
        issn="0095-6848", sort="cited"))))
    p = answer["params"]
    assert p["query.author"] == "Gerteis"
    assert p["filter"] == ("from-pub-date:2000-01-01,until-pub-date:2010-12-31,"
                           "type:journal-article,issn:0095-6848")
    assert p["sort"] == "is-referenced-by-count" and p["order"] == "desc"
    assert codes[0] == "ZERO_RESULTS"


def test_filter_values_cannot_add_filters():
    with pytest.raises(Exception):
        S.WorkSearchInput(query="q", type="journal-article,from-pub-date:1900")


def test_error_is_not_zero(answer):
    answer["err"] = S.M.diag("error", "TRANSPORT_ERROR", "x", None)
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(query="q"))))
    assert codes[0] == "TRANSPORT_ERROR" and "ZERO_RESULTS" not in codes and "OK" not in codes


def test_unreadable_record_is_named(answer):
    data = _fx("works_search_bosozoku.json")
    data["items"][1] = {"title": ["no DOI here"]}
    answer["data"] = data
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(query="bosozoku"))))
    assert "RECORD_SHAPE_UNEXPECTED" in codes and env["result"]["returned"] == 4


# ---------------------------------------------------------------- HTTP layer

def _transport(monkeypatch, handler, mailto="me@example.org"):
    monkeypatch.setattr(S, "MAILTO", mailto)

    async def no_oa(data, single):
        return None, None
    monkeypatch.setattr(S, "_oa_links", no_oa)
    monkeypatch.setattr(S, "_spacing", 0.0)
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)
    monkeypatch.setattr(S.httpx, "AsyncClient", client)


def test_mailto_sent_but_never_in_envelope(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["ua"] = str(request.url), request.headers["user-agent"]
        return httpx.Response(200, headers={"x-rate-limit-limit": "3", "x-rate-limit-interval": "1s"},
                              json={"status": "ok", "message": {"total-results": 0, "items": []}})
    _transport(monkeypatch, handler)
    out = asyncio.run(S.cr_search_works(S.WorkSearchInput(query="q")))
    assert "mailto=me%40example.org" in seen["url"] and "me@example.org" in seen["ua"]
    assert "me@example.org" not in out and "example.org" not in out
    assert abs(S._spacing - 1 / 3) < 1e-9


def test_429_names_the_pool(monkeypatch):
    _transport(monkeypatch, lambda r: httpx.Response(
        429, headers={"x-rate-limit-limit": "3", "x-rate-limit-interval": "1s"}))
    data, err = asyncio.run(S._cr_request("works", {}))
    assert err["code"] == "RATE_LIMITED" and "polite pool" in err["message"]
    assert "CROSSREF_MAILTO" not in err["hint"]


def test_400_quotes_crossref(monkeypatch):
    _transport(monkeypatch, lambda r: httpx.Response(400, json={
        "status": "failed", "message": [{"type": "x", "message": "Filter 'bad' specified but there is no such filter"}]}))
    data, err = asyncio.run(S._cr_request("works", {}))
    assert err["code"] == "API_ERROR" and "no such filter" in err["message"]


def test_404_is_not_found(monkeypatch):
    _transport(monkeypatch, lambda r: httpx.Response(404, text="Resource not found."))
    env, codes = _env(asyncio.run(S.cr_get_work(S.WorkLookupInput(doi="10.9999/nonexistent.bibliograph"))))
    assert codes[0] == "NOT_FOUND" and env["items"] == []


@pytest.mark.parametrize("v,expect", [("1s", 1.0), ("500ms", 0.5), ("2", 2.0), ("", None), ("x", None)])
def test_interval_parsing(v, expect):
    assert S._seconds(v) == expect


def test_select_names_only_fields_crossref_accepts():
    # Valid selects for /works, from Crossref's own 400 message of 1 Nov 2026.
    # `language` is not among them and once broke every list request.
    assert "language" not in S.SELECT.split(",")


def test_review_beside_its_book_is_named(answer):
    # Shape of the live answer of 1 Nov 2026 for Gordon 1985: review first.
    answer["data"] = {"total-results": 3, "items": [
        {"DOI": "10.1/rev", "type": "journal-article", "score": 60.1,
         "title": ["The Evolution of Labor Relations in Japan: Heavy Industry, 1853-1955"]},
        {"DOI": "10.1/book", "type": "monograph", "score": 58.0,
         "title": ["The Evolution of Labor Relations in Japan"]},
        {"DOI": "10.1/other", "type": "journal-article", "score": 20.0, "title": ["Something else entirely"]},
    ]}
    env, codes = _env(asyncio.run(S.cr_match_citation(S.CitationMatchInput(
        citation="Gordon 1985 The Evolution of Labor Relations in Japan"))))
    same = [d for d in env["diagnostics"] if d["code"] == "SAME_TITLE_DIFFERENT_TYPE"]
    assert len(same) == 1 and "Candidates 1 (journal-article) and 2 (monograph)" in same[0]["message"]
    assert codes[0] == "OK"


def test_same_type_same_title_is_not_flagged(answer):
    answer["data"] = {"total-results": 2, "items": [
        {"DOI": "10.1/a", "type": "journal-article", "title": ["Mobilizing Japanese Youth: The Cold War"]},
        {"DOI": "10.1/b", "type": "journal-article", "title": ["Mobilizing Japanese youth: the cold war"]},
    ]}
    _, codes = _env(asyncio.run(S.cr_match_citation(S.CitationMatchInput(citation="Mobilizing Japanese Youth"))))
    assert "SAME_TITLE_DIFFERENT_TYPE" not in codes


# ---------------------------------------------------------------- agency and open access (1 Nov 2026)

@pytest.mark.parametrize("agency,failure,code,phrase", [
    ("JaLC", None, "NOT_FOUND", "registered with JaLC"),
    ("DataCite", None, "NOT_FOUND", "registered with DataCite"),
    (None, None, "DOI_NOT_REGISTERED", "No registration agency has the DOI"),
    (None, "ConnectError", "NOT_FOUND", "lookup failed (ConnectError)"),
    ("Crossref", None, "NOT_FOUND", "Crossref registered this DOI"),
])
def test_not_found_names_the_agency(answer, monkeypatch, agency, failure, code, phrase):
    answer["err"] = S.M.diag("warning", "NOT_FOUND", "Crossref has no record for this DOI.", None)

    async def ra(doi):
        return agency, failure
    monkeypatch.setattr(S, "_doi_agency", ra)
    env, codes = _env(asyncio.run(S.cr_get_work(S.WorkLookupInput(doi="10.11501/1234567"))))
    assert codes[0] == code and phrase in env["diagnostics"][0]["message"]
    if agency == "JaLC":
        assert "jstage_get_article_by_doi" in env["diagnostics"][0]["hint"]


@pytest.mark.parametrize("body,expect", [
    ([{"DOI": "10.11501/1234567", "RA": "JaLC"}], ("JaLC", None)),
    ([{"DOI": "10.1515/x", "status": "DOI does not exist"}], (None, None)),
])
def test_agency_lookup_reads_doi_org(monkeypatch, body, expect):
    # Answer shapes as doi.org gave them on 1 Nov 2026.
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=body)
    _transport(monkeypatch, handler)
    assert asyncio.run(S._doi_agency("10.11501/1234567")) == expect
    assert seen["url"] == "https://doi.org/ra/10.11501/1234567"


def test_agency_lookup_failure_is_reported(monkeypatch):
    _transport(monkeypatch, lambda r: httpx.Response(502, text="bad gateway"))
    agency, failure = asyncio.run(S._doi_agency("10.1/x"))
    assert agency is None and failure


def _oa_stub(monkeypatch, result, err=None):
    calls = []

    async def fake(endpoint, params=None):
        calls.append((endpoint, params))
        return result, err
    monkeypatch.setattr(S._OA, "_oa_request", fake)
    return calls


OA_PAGE = {"results": [  # shape of OpenAlex's answer of 1 Nov 2026
    {"doi": "https://doi.org/10.1515/9781501756337",
     "open_access": {"is_oa": True, "oa_status": "green", "oa_url": "https://soas-repository.worktribe.com/output/338422"},
     "best_oa_location": {"pdf_url": None, "license": "cc-by"}},
    {"doi": "https://doi.org/10.1177/0011128793039003002",
     "open_access": {"is_oa": False, "oa_status": "closed", "oa_url": None}, "best_oa_location": None},
]}


def test_page_gets_one_list_call_and_links(monkeypatch):
    calls = _oa_stub(monkeypatch, OA_PAGE)
    data = {"total-results": 3, "items": [
        {"DOI": "10.1515/9781501756337", "type": "monograph", "title": ["Mobilizing Japanese Youth"]},
        {"DOI": "10.1177/0011128793039003002", "type": "journal-article", "title": ["Street Youths"]},
        {"DOI": "10.1/a|b", "type": "journal-article", "title": ["Pipe in DOI"]},
    ]}
    oa, d = asyncio.run(S._oa_links(data, single=False))
    assert len(calls) == 1 and calls[0][0] == "works"
    assert calls[0][1]["filter"] == "doi:10.1515/9781501756337|10.1177/0011128793039003002"
    assert oa["10.1515/9781501756337"]["url"].startswith("https://soas-repository")
    assert oa["10.1177/0011128793039003002"]["url"] is None
    assert d["code"] == "OA_FROM_OPENALEX" and "1 of 2" in d["message"] and "$0.0001" in d["message"]


def test_single_doi_uses_the_free_lookup(monkeypatch):
    calls = _oa_stub(monkeypatch, OA_PAGE["results"][0])
    oa, d = asyncio.run(S._oa_links({"DOI": "10.1515/9781501756337"}, single=True))
    assert calls[0][0] == "works/doi:10.1515/9781501756337" and "free" in d["message"]


def test_oa_failure_leaves_crossref_answer(monkeypatch):
    _oa_stub(monkeypatch, None, S.M.diag("error", "RATE_LIMITED", "OpenAlex answered 429", None))

    async def fake(path, params=None):
        return _fx("works_search_bosozoku.json"), None
    monkeypatch.setattr(S, "_cr_request", fake)
    env, codes = _env(asyncio.run(S.cr_search_works(S.WorkSearchInput(query="bosozoku"))))
    assert codes[0] == "OK" and "OA_LOOKUP_FAILED" in codes and env["result"]["returned"] == 5


def test_links_reach_the_item(monkeypatch):
    _oa_stub(monkeypatch, OA_PAGE["results"][0])

    async def fake(path, params=None):
        return {"DOI": "10.1515/9781501756337", "type": "monograph",
                "title": ["Mobilizing Japanese Youth"]}, None
    monkeypatch.setattr(S, "_cr_request", fake)
    env, codes = _env(asyncio.run(S.cr_get_work(S.WorkLookupInput(doi="10.1515/9781501756337"))))
    it = env["items"][0]
    assert it["ids"]["fulltext_url"].startswith("https://soas-repository")
    assert it["extra"]["oa_status"] == "green" and it["extra"]["oa_via"] == "openalex"
    assert codes[:2] == ["OK", "OA_FROM_OPENALEX"]


def test_oa_links_can_be_switched_off(monkeypatch):
    calls = _oa_stub(monkeypatch, OA_PAGE)

    async def fake(path, params=None):
        return _fx("works_search_bosozoku.json"), None
    monkeypatch.setattr(S, "_cr_request", fake)
    asyncio.run(S.cr_search_works(S.WorkSearchInput(query="bosozoku", oa_links=False)))
    assert calls == []
