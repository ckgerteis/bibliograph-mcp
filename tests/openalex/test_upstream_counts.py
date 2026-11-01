"""A count that is not a finite, non-negative integer is not a count (stress
test, 12 October 2026).

meta.count of 1e309 parses as infinity: int() raised OverflowError out of the
tool, or the float reached the envelope and json.dumps refused it. A
non-numeric meta.per_page raised ValueError. A negative count was reported as
the corpus size.
"""
import asyncio
import json

import httpx
import pytest

BAD = ["1e309", "-1e309", "-7", "-7.0", "12.5", "true", "\"abc\"", "{}", "[]"]


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


def _total(out):
    env = json.loads(out)
    t = env["result"]["total"]
    assert isinstance(t, int) and not isinstance(t, bool) and t >= 0, t
    return env

from bibliograph.sources.openalex import server as S


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "")
    monkeypatch.setattr(S, "EMAIL", "")


@pytest.mark.parametrize("bad", BAD)
def test_bad_count_is_not_reported_as_a_total(body, bad):
    body["text"] = '{"meta": {"count": %s, "per_page": 1, "page": 1}, "results": [{"id": "https://openalex.org/W1"}, {"id": "https://openalex.org/W2"}]}' % bad
    env = _total(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="x"))))
    assert env["result"]["total"] == 2


@pytest.mark.parametrize("field", ["per_page", "page"])
@pytest.mark.parametrize("bad", BAD)
def test_bad_paging_fields_do_not_crash(body, field, bad):
    meta = {"count": 3, "per_page": 1, "page": 1}
    body["text"] = json.dumps({"meta": meta, "results": [{"id": "https://openalex.org/W1"}]}).replace(
        '"%s": 1' % field, '"%s": %s' % (field, bad))
    env = _total(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="x"))))
    assert env["result"]["start"] >= 1


@pytest.mark.parametrize("good", ["94", '"94"', "94.0"])
def test_a_good_count_passes_through(body, good):
    body["text"] = '{"meta": {"count": %s, "per_page": 1, "page": 1}, "results": [{"id": "https://openalex.org/W1"}]}' % good
    assert _total(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="x"))))["result"]["total"] == 94
