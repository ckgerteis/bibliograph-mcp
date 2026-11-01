"""Identifiers cannot rewrite the request; credentials do not survive into
diagnostics in any encoding (stress test, 12 October 2026).

- A comma in an ID or enum field added filters the caller never asked for:
  author_id="A1,is_oa:true,publication_year:1900".
- '../', '?' and '#' in a lookup ID reached another endpoint, or cut a DOI.
- A query over ~65,000 characters raised httpx.InvalidURL out of the tool.
- _redact() matched the raw key only, never the URL-encoded form nor the
  contact email, and ran after a 300-character cut, so a key straddling the
  cut leaked a prefix.
"""
import asyncio
from urllib.parse import quote, quote_plus

import httpx
import pytest
from pydantic import ValidationError

from bibliograph.sources.openalex import server as S


@pytest.mark.parametrize("model,field", [
    (S.WorkSearchInput, "author_id"), (S.WorkSearchInput, "institution_id"),
    (S.WorkSearchInput, "source_id"), (S.WorkSearchInput, "sort_by"),
    (S.AuthorSearchInput, "institution_id"), (S.SourceSearchInput, "type"),
    (S.InstitutionSearchInput, "country_code"), (S.CitedByInput, "work_id"),
    (S.AuthorWorksInput, "author_id"), (S.AuthorWorksInput, "sort_by"),
])
def test_comma_cannot_add_a_filter(model, field):
    base = {"query": "q"} if "query" in model.model_fields else {}
    if "work_id" in model.model_fields and field != "work_id":
        base["work_id"] = "W1"
    if "author_id" in model.model_fields and field != "author_id" and model is S.AuthorWorksInput:
        base["author_id"] = "A1"
    with pytest.raises(ValidationError):
        model(**base, **{field: "A1,is_oa:true"})


def test_or_within_one_filter_is_still_allowed():
    assert S.WorkSearchInput(query="q", author_id="A1|A2").author_id == "A1|A2"


@pytest.mark.parametrize("bad", ["../authors/A5", "W1/../../authors", "./W1", "W1\x00", "W1\nW2"])
def test_lookup_id_cannot_walk_the_path(bad):
    with pytest.raises(ValidationError):
        S.WorkLookupInput(work_id=bad)
    with pytest.raises(ValidationError):
        S.AuthorLookupInput(author_id=bad)


@pytest.fixture
def requested(monkeypatch):
    urls, box = [], {"status": 200, "body": '{"id": "https://openalex.org/W1"}'}

    def handler(req):
        urls.append(req.url)
        return httpx.Response(box["status"], text=box["body"])
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    monkeypatch.setattr(S, "API_KEY", "")
    monkeypatch.setattr(S, "EMAIL", "")
    return urls, box


@pytest.mark.parametrize("doi", ["10.1002/a#b", "10.1002/a?b=c"])
def test_doi_with_reserved_characters_is_sent_whole(requested, doi):
    urls, _ = requested
    asyncio.run(S.oa_get_work(S.WorkLookupInput(work_id=doi)))
    assert urls[0].raw_path.decode().endswith(quote(doi, safe=":/"))
    assert urls[0].fragment == ""


def test_overlong_query_is_refused_before_sending():
    with pytest.raises(ValidationError):
        S.WorkSearchInput(query="x" * 70_000)


def test_unsendable_request_is_a_diagnostic_not_a_crash(requested):
    data, err = asyncio.run(S._oa_request("works/W1\x00"))
    assert data is None and err["code"] == "TRANSPORT_ERROR"


@pytest.mark.parametrize("key", ["SENT+INEL/KEY=1&2", "SENTINELKEY123"])
def test_key_is_redacted_in_every_encoding(requested, monkeypatch, key):
    urls, box = requested
    monkeypatch.setattr(S, "API_KEY", key)
    box.update(status=400, body=f"bad: raw={key} q={quote(key, safe='')} p={quote_plus(key)}")
    _, err = asyncio.run(S._oa_request("works", {"search": "q"}))
    for form in (key, quote(key, safe=""), quote_plus(key)):
        assert form not in err["message"]


def test_email_is_redacted(requested, monkeypatch):
    urls, box = requested
    monkeypatch.setattr(S, "EMAIL", "sentinel@example.invalid")
    box.update(status=400, body="bad: mailto=sentinel%40example.invalid and sentinel@example.invalid")
    _, err = asyncio.run(S._oa_request("works", {"search": "q"}))
    assert "sentinel" not in err["message"]


def test_key_straddling_the_cut_is_not_leaked(requested, monkeypatch):
    urls, box = requested
    monkeypatch.setattr(S, "API_KEY", "SENTINELKEY123")
    box.update(status=400, body="x" * 290 + "SENTINELKEY123")
    _, err = asyncio.run(S._oa_request("works", {"search": "q"}))
    assert "SENTIN" not in err["message"]
