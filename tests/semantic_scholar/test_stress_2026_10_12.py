"""Upstream semantic-scholar-mcp 2.2.0 stress-test fixes (12 Oct 2026), ported.

Offline: transport is mocked at httpx level (or _api_request is replaced).
Bibliograph reports an unreadable record as RECORD_SHAPE_UNEXPECTED (its own code),
now naming the record by position and paperId and no longer letting a page of
only unreadable records read as ZERO_RESULTS.
"""
import asyncio
import json
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from bibliograph.sources.semantic_scholar import server as S


def _run(c):
    return asyncio.run(c)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "")
    monkeypatch.setattr(S, "RATE_LIMIT_DELAY", 0)
    monkeypatch.delenv("MCP_RECEIPT_DIR", raising=False)
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)


@pytest.fixture
def wire(monkeypatch):
    """Mock transport; box['text'/'status'] set the reply, urls collects requests."""
    box = {"text": '{"data": []}', "status": 200, "urls": []}

    def handler(req):
        box["urls"].append(req.url)
        return httpx.Response(box["status"], text=box["text"], headers={"content-type": "application/json"})
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    return box


def _codes(env):
    return [d["code"] for d in env["diagnostics"]]


# ------------------------------------------------ 200 that is not the protocol

BAD_BODIES = [None, [], "x", {}, {"error": "Not found"}, {"message": "Too Many Requests"}, {"data": "x"}]
CALLS = [
    lambda: S.s2_search_papers(S.PaperSearchInput(query="q")),
    lambda: S.s2_search_authors(S.AuthorSearchInput(query="q")),
    lambda: S.s2_citations(S.CitationInput(paper_id="abc")),
    lambda: S.s2_author_papers(S.AuthorPapersInput(author_id="1")),
    lambda: S.s2_recommend_single(S.RecommendInput(paper_id="abc")),
    lambda: S.s2_recommend_multi(S.MultiRecommendInput(positive_paper_ids=["abc"])),
    lambda: S.s2_get_paper(S.PaperLookupInput(paper_id="abc")),
    lambda: S.s2_get_author(S.AuthorLookupInput(author_id="1")),
]


@pytest.fixture
def answer(monkeypatch):
    box = {}

    async def fake(method, url, params=None, json_body=None):
        return box["data"], None
    monkeypatch.setattr(S, "_api_request", fake)
    return box


@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("data", BAD_BODIES)
def test_wrong_shape_200_is_api_error_not_zero(answer, call, data):
    answer["data"] = data
    env = json.loads(_run(call()))
    codes = _codes(env)
    assert codes[0] == "API_ERROR", codes
    assert "ZERO_RESULTS" not in codes and "OK" not in codes
    assert env["items"] == [] and env["result"]["total"] == 0


def test_upstream_message_is_quoted(answer):
    answer["data"] = {"message": "Too Many Requests"}
    env = json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="q"))))
    assert "Too Many Requests" in env["diagnostics"][0]["message"]


@pytest.mark.parametrize("data", [{"total": 0, "offset": 0}, {"total": 0, "offset": 0, "data": []}])
def test_empty_search_page_is_still_zero_results(answer, data):
    answer["data"] = data
    codes = _codes(json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="q")))))
    assert "ZERO_RESULTS" in codes and "API_ERROR" not in codes


def test_empty_recommendations_are_still_zero_results(answer):
    answer["data"] = {"recommendedPapers": []}
    codes = _codes(json.loads(_run(S.s2_recommend_single(S.RecommendInput(paper_id="abc")))))
    assert "ZERO_RESULTS" in codes and "API_ERROR" not in codes


# ------------------------------------------------ unreadable records

GOOD = {"paperId": "p1", "title": "ok"}
BADS = [{"paperId": "p2", "externalIds": "x"}, {"paperId": "p2", "journal": "x"},
        {"paperId": "p2", "authors": "x"}, {"paperId": "p2", "openAccessPdf": 5},
        "a string where a record belongs"]


def _page(*recs):
    return json.dumps({"total": len(recs), "offset": 0, "data": list(recs)})


def _shape(env):
    return next(d for d in env["diagnostics"] if d["code"] == "RECORD_SHAPE_UNEXPECTED")


@pytest.mark.parametrize("bad", BADS)
def test_one_bad_record_is_skipped_and_named(wire, bad):
    wire["text"] = _page(GOOD, bad, dict(GOOD, paperId="p3"))
    env = json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="x"))))
    assert env["result"]["returned"] == 2
    d = _shape(env)
    assert "1 of 3" in d["message"] and "#2" in d["message"]
    assert "OK" not in _codes(env) and "RECORD_UNREADABLE" not in _codes(env)


def test_the_bad_record_is_named_by_id(wire):
    wire["text"] = _page(GOOD, BADS[0])
    assert "p2" in _shape(json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="x")))))["message"]


def test_an_all_unreadable_page_is_not_an_absence(wire):
    wire["text"] = _page(BADS[0], BADS[1])
    codes = _codes(json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="x")))))
    assert "ZERO_RESULTS" not in codes and "RECORD_SHAPE_UNEXPECTED" in codes


def test_an_unreadable_single_record_is_reported(wire):
    wire["text"] = json.dumps(BADS[0])
    env = json.loads(_run(S.s2_get_paper(S.PaperLookupInput(paper_id="p2"))))
    assert "RECORD_SHAPE_UNEXPECTED" in _codes(env) and env["result"]["returned"] == 0


def test_citation_wrapper_without_a_paper_is_counted_not_dropped(wire):
    wire["text"] = json.dumps({"offset": 0, "data": [{"citingPaper": GOOD}, {"citingPaper": None}, "junk"]})
    env = json.loads(_run(S.s2_citations(S.CitationInput(paper_id="abc"))))
    assert env["result"]["returned"] == 1
    assert "2 of 3" in _shape(env)["message"]


# ------------------------------------------------ counts

BAD_TOTALS = ["1e309", "-1e309", "-7", "-7.0", "12.5", "true", "\"abc\"", "{}", "[]"]


@pytest.mark.parametrize("bad", BAD_TOTALS)
def test_bad_total_is_reported_as_not_reported(wire, bad):
    wire["text"] = '{"total": %s, "offset": 0, "data": [{"paperId": "p1"}, {"paperId": "p2"}]}' % bad
    env = json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="x"))))
    t = env["result"]["total"]
    assert t == 2 and isinstance(t, int) and "TOTAL_NOT_REPORTED" in _codes(env)


@pytest.mark.parametrize("good", ["94", '"94"', "94.0"])
def test_a_good_total_passes_through(wire, good):
    wire["text"] = '{"total": %s, "offset": 0, "data": [{"paperId": "p1", "title": "x"}]}' % good
    assert json.loads(_run(S.s2_search_papers(S.PaperSearchInput(query="x"))))["result"]["total"] == 94


# ------------------------------------------------ identifiers, key, queries

ID_MODELS = [(S.PaperLookupInput, "paper_id"), (S.CitationInput, "paper_id"),
             (S.AuthorLookupInput, "author_id"), (S.AuthorPapersInput, "author_id"),
             (S.RecommendInput, "paper_id")]


@pytest.mark.parametrize("model,field", ID_MODELS)
@pytest.mark.parametrize("bad", ["../../author/1", "1/../../paper/zzz", "./x", "a\x00b", "a\nb"])
def test_id_cannot_walk_the_path(model, field, bad):
    with pytest.raises(ValidationError):
        model(**{field: bad})


@pytest.mark.parametrize("model,field", ID_MODELS)
def test_real_id_forms_are_accepted(model, field):
    for ok in ("649def34f8be52c8b66281af98ae884c09aef38b", "DOI:10.1093/mind/LIX.236.433",
               "ARXIV:2106.15928", "CorpusId:215416146", "URL:https://arxiv.org/abs/2106.15928v1"):
        model(**{field: ok})


@pytest.mark.parametrize("pid", ["abc?x=1", "abc#", "DOI:10.1002/a#b"])
def test_citations_keep_their_suffix(wire, pid):
    _run(S.s2_citations(S.CitationInput(paper_id=pid)))
    path = wire["urls"][0].raw_path.decode().split("?")[0]
    assert path.endswith(quote(pid, safe=":/") + "/citations"), path


def test_overlong_query_is_refused_before_sending():
    with pytest.raises(ValidationError):
        S.PaperSearchInput(query="x" * 70_000)
    with pytest.raises(ValidationError):
        S.AuthorSearchInput(query="x" * 70_000)
    S.PaperSearchInput(query="x" * S.QUERY_MAX)


def test_unsendable_request_is_a_diagnostic_not_a_crash(wire):
    data, err = _run(S._api_request("GET", f"{S.API_BASE}/paper/a\x00b"))
    assert data is None and err["code"] == "TRANSPORT_ERROR"


def test_key_straddling_the_cut_is_not_leaked(wire, monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "SENTINELKEY123")
    wire.update(status=400, text="x" * 290 + "SENTINELKEY123")
    _, err = _run(S._api_request("GET", f"{S.API_BASE}/paper/search", params={"query": "q"}))
    assert "SENTIN" not in err["message"]


@pytest.mark.parametrize("form", [quote("k/y+z=", safe=""), "k/y%2Bz%3D", "k%2Fy%2Bz%3D"])
def test_key_is_redacted_in_encoded_forms(monkeypatch, form):
    monkeypatch.setattr(S, "API_KEY", "k/y+z=")
    out = S._redact(f"url?key={form}&x")
    assert "[redacted]" in out and form not in out
