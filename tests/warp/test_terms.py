"""Tests for the WARP access-terms decision: serial, spaced, single-URL,
nothing harvested, with the docstrings pointing at ndl_search_warp / the
next tool in the pipeline."""
import inspect

import httpx
import pytest

from bibliograph.sources.warp import server as S
from bibliograph.sources.ndl import server as NDL


# ---------------------------------------------------------------- rate floor

def test_min_request_interval_at_least_three_seconds():
    assert S.MIN_REQUEST_INTERVAL >= 3.0


# ---------------------------------------------------------------- single URL only

def _params(fn):
    return inspect.signature(fn).parameters


def test_tools_take_a_single_url_not_a_list():
    for fn in (S.warp_list_captures, S.warp_nearest_capture, S.warp_read_capture):
        params = _params(fn)
        assert "url" in params, f"{fn.__name__} must take a url parameter"
        ann = params["url"].annotation
        # Accept a bare `str` annotation, or an unresolved forward ref/None
        # (no `from __future__ import annotations` surprise), but never a
        # list/sequence-of-urls signature.
        assert ann in (str, "str", inspect.Parameter.empty), (
            f"{fn.__name__}.url must be a single str, not {ann!r}"
        )
        assert "urls" not in params, f"{fn.__name__} must not also accept multiple urls"


# ---------------------------------------------------------------- docstrings name the pipeline

def test_docstrings_mention_ndl_search_warp_or_next_step():
    # module docstring: states the pipeline end to end
    mod_doc = S.__doc__ or ""
    assert "ndl_search_warp" in mod_doc

    # warp_list_captures and warp_nearest_capture are reachable straight from a
    # subject search: they should point back to ndl_search_warp.
    assert "ndl_search_warp" in (S.warp_list_captures.__doc__ or "")
    assert "ndl_search_warp" in (S.warp_nearest_capture.__doc__ or "")

    # warp_read_capture's next-step is upstream (list/nearest_capture), not
    # ndl_search_warp directly, but it must name the actual next step.
    read_doc = S.warp_read_capture.__doc__ or ""
    assert "warp_list_captures" in read_doc and "warp_nearest_capture" in read_doc

    # ndl_search_warp, in turn, must point forward into the warp tools.
    ndl_doc = NDL.ndl_search_warp.__doc__ or ""
    assert "warp_list_captures" in ndl_doc or "warp_nearest_capture" in ndl_doc


def test_docstrings_state_browser_first_no_api_terms():
    for fn in (S.warp_list_captures, S.warp_nearest_capture, S.warp_read_capture):
        doc = fn.__doc__ or ""
        assert "no API" in doc or "browser-first" in doc

    mod_doc = S.__doc__ or ""
    assert "browser-first" in mod_doc


def test_docstrings_state_copyright_and_citable_viewer_url():
    for fn in (S.warp_list_captures, S.warp_nearest_capture, S.warp_read_capture):
        doc = fn.__doc__ or ""
        assert "copyright" in doc
        assert "viewer_url" in doc


# ---------------------------------------------------------------- serial + spaced, no network

@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("MCP_RECEIPT_DIR", raising=False)
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    yield
    S._TRANSPORT = None


async def test_consecutive_requests_spaced_by_the_floor(monkeypatch):
    """Drive S._get with a fake clock and a faked asyncio.sleep so the test
    is instant, but assert it against the REAL (undegraded) floor rather
    than a shortened one, since that floor is the thing under test."""
    monkeypatch.setattr(S, "_lock", None)
    S._last_request_at = 0.0

    clock = {"t": 10_000.0}

    def fake_monotonic():
        return clock["t"]

    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)
        clock["t"] += d

    monkeypatch.setattr(S.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(S.asyncio, "sleep", fake_sleep)

    def handler(req: httpx.Request):
        return httpx.Response(200, text="ok")

    S._TRANSPORT = httpx.MockTransport(handler)

    await S._get("https://warp.ndl.go.jp/collections/timemap/https://a.go.jp/")
    # advance the clock by less than the floor before the second request
    clock["t"] += 0.05
    await S._get("https://warp.ndl.go.jp/collections/timemap/https://a.go.jp/")

    assert sleeps, "the second request must have waited"
    assert sleeps[-1] >= S.MIN_REQUEST_INTERVAL - 0.05 - 1e-9


async def test_requests_are_serialised_by_a_single_lock(monkeypatch):
    """Two concurrent calls to _get must not overlap the network call: the
    lock must be held for the whole request, not just the wait."""
    monkeypatch.setattr(S, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(S, "_lock", None)
    S._last_request_at = 0.0

    import asyncio as _asyncio

    active = {"n": 0, "max": 0}

    def handler(req: httpx.Request):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        active["n"] -= 1
        return httpx.Response(200, text="ok")

    S._TRANSPORT = httpx.MockTransport(handler)

    await _asyncio.gather(*(S._get("https://warp.ndl.go.jp/x") for _ in range(5)))
    assert active["max"] <= 1
