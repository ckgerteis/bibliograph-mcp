# Ported from openalex-mcp 2.2.0; bibliograph keeps its own code RECORD_SHAPE_UNEXPECTED.
"""One malformed record no longer takes the page with it (stress test,
12 October 2026).

A record with a field of the wrong type (a string where an object belongs)
raised out of the item builder, so the caller got an exception instead of an
envelope and the other records on the page were lost. Such a record is now
skipped and named in a RECORD_SHAPE_UNEXPECTED warning; the rest are returned, and an
all-unreadable page is not reported as an absence.
"""
import asyncio
import json

import httpx
import pytest


@pytest.fixture
def body(monkeypatch):
    box = {"text": ""}

    def handler(req):
        return httpx.Response(200, text=box["text"], headers={"content-type": "application/json"})
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    return box


def _codes(env):
    return [d["code"] for d in env["diagnostics"]]


def _skipped(env):
    return next(d for d in env["diagnostics"] if d["code"] == "RECORD_SHAPE_UNEXPECTED")

from bibliograph.sources.openalex import server as S

GOOD = {"id": "https://openalex.org/W1", "display_name": "ok"}
BADS = [{"id": "https://openalex.org/W2", "authorships": "x"},
        {"id": "https://openalex.org/W2", "primary_location": "x"},
        {"id": "https://openalex.org/W2", "biblio": "x"},
        {"id": 2},
        "a string where a record belongs"]


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "")
    monkeypatch.setattr(S, "EMAIL", "")


def _page(*recs):
    return json.dumps({"meta": {"count": len(recs), "per_page": 25, "page": 1}, "results": list(recs)})


@pytest.mark.parametrize("bad", BADS)
def test_one_bad_record_is_skipped_and_named(body, bad):
    body["text"] = _page(GOOD, bad, dict(GOOD, id="https://openalex.org/W3"))
    env = json.loads(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="x"))))
    assert env["result"]["returned"] == 2
    d = _skipped(env)
    assert "1 of 3" in d["message"] and "#2" in d["message"]
    assert "OK" not in _codes(env)


def test_the_bad_record_is_named_by_id(body):
    body["text"] = _page(GOOD, BADS[0])
    assert "W2" in _skipped(json.loads(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="x")))))["message"]


def test_an_all_skipped_page_is_not_an_absence(body):
    body["text"] = _page(BADS[0], BADS[1])
    env = json.loads(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="x"))))
    assert "ZERO_RESULTS" not in _codes(env) and "RECORD_SHAPE_UNEXPECTED" in _codes(env)


def test_an_skipped_single_record_is_reported(body):
    body["text"] = json.dumps(BADS[0])
    env = json.loads(asyncio.run(S.oa_get_work(S.WorkLookupInput(work_id="W2"))))
    assert _codes(env)[0] == "API_ERROR" and env["result"]["returned"] == 0
