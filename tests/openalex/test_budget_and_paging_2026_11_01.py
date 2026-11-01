"""A spent daily budget is named as such, and paging at a small size is flagged.

1 Nov 2026: every 429 was reported as "the request rate was exceeded" with
advice to add a key, including when the key was set and the day's $1 budget
was spent. OpenAlex's X-RateLimit-* headers say which limit it was. Separately,
OpenAlex charges a search the same 10 credits at per-page 10 as at 200, so a
sweep paging at 10 pays twenty times over; the envelope now says so.
"""
import asyncio
import json

import httpx
import pytest

from bibliograph.sources.openalex import server as S


def _run_429(monkeypatch, headers, key="k"):
    monkeypatch.setattr(S, "API_KEY", key)

    def handler(request):
        return httpx.Response(429, headers=headers, json={"error": "limit"})
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)
    monkeypatch.setattr(S.httpx, "AsyncClient", client)
    data, err = asyncio.run(S._oa_request("works", {"search": "q"}))
    assert data is None
    return err


BUDGET = {"X-RateLimit-Remaining-USD": "0", "X-RateLimit-Prepaid-Remaining-USD": "0",
          "X-RateLimit-Cost-Required-USD": "0.001", "X-RateLimit-Reset": "7260"}


def test_spent_budget_with_key_is_named(monkeypatch):
    err = _run_429(monkeypatch, BUDGET)
    assert err["code"] == "RATE_LIMITED" and err["level"] == "error"
    assert "$1 daily budget on this API key is spent" in err["message"]
    assert "2 h 1 min" in err["message"]
    assert "openalex.org/pricing" in err["hint"]
    assert "OPENALEX_API_KEY" not in err["hint"]  # the key is set; don't advise adding one
    assert "unknown, not empty" in err["hint"]


def test_spent_budget_without_key_points_to_key(monkeypatch):
    err = _run_429(monkeypatch, BUDGET, key="")
    assert "keyless $0.10 daily budget" in err["message"]
    assert "OPENALEX_API_KEY" in err["hint"]


def test_remaining_below_cost_counts_as_spent(monkeypatch):
    h = dict(BUDGET, **{"X-RateLimit-Remaining-USD": "0.0005"})
    assert "is spent" in _run_429(monkeypatch, h)["message"]


def test_prepaid_balance_means_not_budget(monkeypatch):
    h = dict(BUDGET, **{"X-RateLimit-Prepaid-Remaining-USD": "4.5"})
    err = _run_429(monkeypatch, h)
    assert "per second" in err["message"] and "is spent" not in err["message"]


def test_per_second_limit(monkeypatch):
    err = _run_429(monkeypatch, {"X-RateLimit-Remaining-USD": "0.9", "X-RateLimit-Reset": "100"})
    assert "too many requests per second" in err["message"]
    assert "0.9000 left" in err["message"]
    assert "OPENALEX_API_KEY" not in err["hint"]


def test_no_headers_does_not_guess(monkeypatch):
    err = _run_429(monkeypatch, {}, key="")
    assert "not known which limit" in err["message"]
    assert err["code"] == "RATE_LIMITED"


@pytest.fixture
def page(monkeypatch):
    box = {}

    async def fake(endpoint, params=None):
        box["sent"] = params
        return box["data"], None
    monkeypatch.setattr(S, "_oa_request", fake)
    return box


def _work(i):
    return {"id": f"https://openalex.org/W{i}", "display_name": f"T{i}", "authorships": []}


def _codes(out):
    return [d["code"] for d in json.loads(out)["diagnostics"]]


def test_paging_on_at_small_size_is_flagged_after_ok(page):
    page["data"] = {"meta": {"count": 500, "page": 3, "per_page": 10}, "results": [_work(1)]}
    codes = _codes(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="q", page=3))))
    assert codes[:2] == ["OK", "PAGING_COST"]  # receipt diagnostics may follow


def test_first_page_and_large_pages_are_not_flagged(page):
    page["data"] = {"meta": {"count": 500, "page": 1, "per_page": 10}, "results": [_work(1)]}
    assert "PAGING_COST" not in _codes(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="q"))))
    page["data"] = {"meta": {"count": 500, "page": 2, "per_page": 200}, "results": [_work(1)]}
    assert "PAGING_COST" not in _codes(asyncio.run(
        S.oa_search_works(S.WorkSearchInput(query="q", page=2, per_page=200))))


def test_paging_hint_does_not_displace_zero_results(page):
    page["data"] = {"meta": {"count": 5, "page": 4, "per_page": 10}, "results": []}
    codes = _codes(asyncio.run(S.oa_search_works(S.WorkSearchInput(query="q", page=4))))
    assert codes[:2] == ["ZERO_RESULTS", "PAGING_COST"]


def test_cap_and_default_unchanged():
    assert S.WorkSearchInput(query="q").per_page == 10
    S.WorkSearchInput(query="q", per_page=200)
    with pytest.raises(Exception):
        S.WorkSearchInput(query="q", per_page=201)
    assert "per call, not per result" in S.WorkSearchInput.model_fields["per_page"].description


# Headers of a real spent-budget 429, captured keyless 1 Nov 2026.
REAL_SPENT = {"retry-after": "80687", "x-ratelimit-cost-required-usd": "0.0001",
              "x-ratelimit-credits-required": "1", "x-ratelimit-limit": "1000",
              "x-ratelimit-limit-usd": "0.1", "x-ratelimit-onetime-remaining": "0",
              "x-ratelimit-prepaid-remaining-usd": "0", "x-ratelimit-remaining": "0",
              "x-ratelimit-remaining-usd": "0", "x-ratelimit-reset": "80687"}


def test_real_spent_budget_429(monkeypatch):
    err = _run_429(monkeypatch, REAL_SPENT, key="")
    assert "keyless $0.10 daily budget" in err["message"] and "is spent" in err["message"]
    assert "22 h 24 min" in err["message"]


def test_load_throttle_429_quotes_openalex(monkeypatch):
    # Also seen live 1 Nov 2026: only Retry-After and a message.
    monkeypatch.setattr(S, "API_KEY", "")
    msg = ("Anonymous search is temporarily rate-limited while the search cluster is "
           "under elevated load. Please retry in 15s")
    err = S._rate_limit_diag(httpx.Headers({"retry-after": "15"}), json.dumps({"error": "x", "message": msg}))
    assert "elevated load" in err["message"] and "retry in 15 s" in err["hint"]


def test_budget_snapshot_without_key_sends_nothing(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "")
    monkeypatch.setattr(S.httpx, "get", lambda *a, **k: pytest.fail("network used"))
    assert "no OPENALEX_API_KEY" in S.budget_snapshot()["note"]


def test_budget_snapshot_reports_and_redacts(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", "SECRETKEY")

    class R:
        status_code = 200

        def json(self):
            return {"api_key": "SEC...KEY", "rate_limit": {
                "daily_budget_usd": 1, "daily_used_usd": 0.0161, "daily_remaining_usd": 0.9839,
                "prepaid_remaining_usd": 0, "prepaid_expires_at": None,
                "resets_at": "2026-11-02T00:00:00.000Z",
                "endpoint_costs_usd": {"singleton": 0, "list": 0.0001, "search": 0.001}}}
    monkeypatch.setattr(S.httpx, "get", lambda *a, **k: R())
    snap = S.budget_snapshot()
    assert snap["daily_remaining_usd"] == 0.9839 and snap["endpoint_costs_usd"]["singleton"] == 0
    assert "SECRET" not in json.dumps(snap)

    def boom(*a, **k):
        raise httpx.ConnectError("no route to SECRETKEY")
    monkeypatch.setattr(S.httpx, "get", boom)
    assert "SECRETKEY" not in S.budget_snapshot()["error"]
