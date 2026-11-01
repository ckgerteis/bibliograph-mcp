"""A 200 body that is not an OpenAlex page or record is an error, not zero.

Stress test, 12 October 2026: a 200 whose body was null, [], a string,
{"error": ...} or {"message": ...} came back from every search tool as
ZERO_RESULTS ("OpenAlex matched nothing"), and from oa_get_work and
oa_get_author as an empty record marked OK with total 1.
"""
import asyncio
import json

import pytest

from bibliograph.sources.openalex import server as S

BAD = [None, [], "x", {}, {"error": "Rate limit exceeded"}, {"message": "Internal error"},
       {"meta": {"count": 94}}, {"results": []}, {"meta": {"count": 1}, "results": "x"}]


@pytest.fixture
def answer(monkeypatch):
    box = {}

    async def fake(endpoint, params=None):
        return box["data"], None
    monkeypatch.setattr(S, "_oa_request", fake)
    return box


def _codes(out):
    env = json.loads(out)
    return env, [d["code"] for d in env["diagnostics"]]


@pytest.mark.parametrize("data", BAD)
def test_search_reports_api_error(answer, data):
    answer["data"] = data
    env, codes = _codes(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="q"))))
    assert codes[0] == "API_ERROR" and "ZERO_RESULTS" not in codes
    assert env["result"]["total"] == 0 and env["items"] == []


@pytest.mark.parametrize("data", BAD)
def test_lookup_reports_api_error(answer, data):
    answer["data"] = data
    env, codes = _codes(asyncio.run(S.oa_get_work(S.WorkLookupInput(work_id="W1"))))
    assert codes[0] == "API_ERROR" and "OK" not in codes
    assert env["result"]["total"] == 0 and env["items"] == []


def test_upstream_message_is_quoted(answer):
    answer["data"] = {"error": "Rate limit exceeded"}
    env, _ = _codes(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="q"))))
    assert "Rate limit exceeded" in env["diagnostics"][0]["message"]


def test_empty_page_is_still_zero_results(answer):
    answer["data"] = {"meta": {"count": 0, "page": 1, "per_page": 10}, "results": []}
    _, codes = _codes(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="q"))))
    assert codes[0] == "ZERO_RESULTS"
