"""Ported from ndl-mcp 1.2.3 (stress test, 12 October 2026), adapted to bibliograph.

Offline: httpx is mocked. Identifiers live in extra.ndl_bib_id / extra.jpno here.
Covers: a 200 that is not SRU is an error; get_record returns only the record
asked for, inside the declared set; identifiers are validated; no more records
shown than asked for; Retry-After honoured only if finite and non-negative.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from bibliograph.sources.ndl import server as S

FIXTURES = Path(__file__).parent / "fixtures"
BOOK = (FIXTURES / "sru_book_jpno.xml").read_text(encoding="utf-8")


@pytest.fixture
def ndl(monkeypatch):
    box = {"body": BOOK, "sent": [], "handler": None}

    def handler(req):
        box["sent"].append(parse_qs(req.url.query.decode()))
        if box["handler"]:
            return box["handler"](req)
        return httpx.Response(200, text=box["body"])
    orig = httpx.AsyncClient.__init__

    def init(self, *a, **k):
        k["transport"] = httpx.MockTransport(handler)
        orig(self, *a, **k)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    monkeypatch.setattr(S, "MIN_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(S, "_last_request_at", 0.0)
    return box


# ---- a 200 that is not the protocol -----------------------------------------

@pytest.mark.parametrize("body", [
    "<html><body><h1>503 Service Unavailable</h1></body></html>",
    "<error>rate limited</error>",
    "<response/>",
    '<searchRetrieveResponse xmlns="http://example.org/not-srw"><numberOfRecords>3'
    "</numberOfRecords></searchRetrieveResponse>",
    '<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/"><version>1.2</version>'
    "</searchRetrieveResponse>",
])
def test_non_sru_body_is_an_error_not_zero(body):
    total, items, diag = S._parse_sru(body)
    assert diag is not None and diag["level"] == "error" and diag["code"] == "API_ERROR"
    assert (total, items) == (0, [])


def test_non_sru_body_through_a_search_is_not_zero_conjunction(ndl):
    ndl["body"] = "<html><body>maintenance</body></html>"
    env = json.loads(asyncio.run(S.ndl_search_books(S.BooksInput(title="x"))))
    codes = [d["code"] for d in env["diagnostics"]]
    assert "API_ERROR" in codes and "ZERO_CONJUNCTION" not in codes


@pytest.mark.parametrize("name", ["sru_book_jpno.xml", "sru_article_zassaku.xml"])
def test_real_responses_still_parse(name):
    total, items, diag = S._parse_sru((FIXTURES / name).read_text(encoding="utf-8"))
    assert diag is None and total >= 1 and items


def test_record_does_not_exist_is_still_zero():
    body = ('<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
            "<version>1.2</version><numberOfRecords>0</numberOfRecords>"
            '<diagnostics><diagnostic xmlns="http://www.loc.gov/zing/srw/diagnostic/">'
            "<message>Record does not exist</message></diagnostic></diagnostics>"
            "</searchRetrieveResponse>")
    assert S._parse_sru(body) == (0, [], None)


# ---- ndl_get_record ----------------------------------------------------------

def _get(**kw):
    return json.loads(asyncio.run(S.ndl_get_record(S.GetRecordInput(**kw))))


@pytest.mark.parametrize("kw", [{"jpno": "71009951"}, {"ndl_bib_id": "000001185032"}])
def test_get_record_query_is_scoped_to_the_declared_providers(ndl, kw):
    _get(**kw)
    assert len(ndl["sent"]) == 1
    cql = ndl["sent"][0]["query"][0]
    dpids = {c.split("=", 1)[1].strip('"') for c in cql.split(" AND ") if c.startswith("dpid=")}
    assert dpids == set(S.ALL_DPIDS)
    assert dpids <= set(S.DECLARED_DPIDS)


@pytest.mark.parametrize("kw", [{"jpno": "71009951"}, {"ndl_bib_id": "000001185032"}])
def test_the_matching_record_is_returned(ndl, kw):
    env = _get(**kw)
    assert env["result"]["returned"] == 1 and env["diagnostics"][0]["code"] == "OK"
    ex = env["items"][0]["extra"]
    assert ex.get("jpno") == "71009951" or ex.get("ndl_bib_id") == "000001185032"


@pytest.mark.parametrize("kw,other", [({"jpno": "99999999"}, "71009951"),
                                      ({"ndl_bib_id": "999999999"}, "000001185032")])
def test_a_different_record_is_not_returned_as_the_one_asked_for(ndl, kw, other):
    env = _get(**kw)
    assert env["result"]["returned"] == 0 and env["result"]["total"] == 0
    assert env["items"] == []
    d = env["diagnostics"][0]
    assert d["code"] == "ZERO_CONJUNCTION" and other in d["message"]


@pytest.mark.parametrize("kw", [{"ndl_bib_id": "a and b"}, {"jpno": '7" or dpid="ndl-article-online'},
                                {"jpno": "1" * 40}])
def test_an_identifier_that_is_not_one_is_refused(kw):
    with pytest.raises(ValidationError):
        S.GetRecordInput(**kw)


def test_an_empty_second_identifier_counts_as_absent(ndl):
    env = _get(jpno="71009951", ndl_bib_id=" ")
    assert env["result"]["returned"] == 1


# ---- the 100-record cap on what is shown -------------------------------------

def _many(n):
    rec = re.search(r"    <record>.*?</record>\n", BOOK, re.S).group(0)
    body = BOOK.replace(rec, rec * n)
    return body.replace("<numberOfRecords>1</numberOfRecords>", f"<numberOfRecords>{n}</numberOfRecords>")


@pytest.mark.parametrize("count,sent,shown", [(100, 500, 100), (5, 40, 5), (20, 3, 3)])
def test_items_are_capped_at_the_count_asked_for(ndl, count, sent, shown):
    ndl["body"] = _many(sent)
    env = json.loads(asyncio.run(S.ndl_search_books(S.BooksInput(title="x", count=count))))
    assert env["result"]["returned"] == shown and len(env["items"]) == shown


# ---- Retry-After -------------------------------------------------------------

@pytest.mark.parametrize("value", ["nan", "-nan", "inf", "-5", "1e309",
                                   "Wed, 21 Oct 2026 07:28:00 GMT", ""])
def test_unusable_retry_after_falls_back_and_retries_once(ndl, monkeypatch, value):
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": value})
        return httpx.Response(200, text="<ok/>")
    ndl["handler"] = handler
    slept = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s, *a):
        slept.append(s)
        await real_sleep(0)
    monkeypatch.setattr(S.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(S, "BACKOFF_SECONDS", 10.0)
    body = asyncio.run(asyncio.wait_for(S._sru_request({"query": "x"}), 5))
    assert body == "<ok/>" and len(calls) == 2
    assert slept and all(s == s and 0 <= s <= 10.0 for s in slept), slept


def test_usable_retry_after_is_honoured_and_capped(ndl, monkeypatch):
    for value, want in (("3", 3.0), ("999", 30.0)):
        calls = []

        def handler(req, calls=calls, value=value):
            calls.append(req)
            return httpx.Response(429, headers={"Retry-After": value}) if len(calls) == 1 \
                else httpx.Response(200, text="<ok/>")
        ndl["handler"] = handler
        slept = []

        async def fake_sleep(s, *a, slept=slept):
            slept.append(s)
        monkeypatch.setattr(S.asyncio, "sleep", fake_sleep)
        asyncio.run(S._sru_request({"query": "x"}))
        assert want in slept, (value, slept)
