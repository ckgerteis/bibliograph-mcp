"""Credential redaction for cinii-mcp: CINII_APPID must never appear in the
envelope, the receipt, a deposited ledger line, an error diagnostic built from
a simulated HTTP failure, or captured log output. Offline; transport mocked."""
import io
import json
import logging
import os

import httpx
import pytest

from bibliograph.sources.cinii import server as S

SECRET = "SECRET-TEST-KEY-123"

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before any monkeypatching


def _client_factory(transport):
    def make(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(*args, **kwargs)
    return make


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(S, "CINII_APPID", SECRET)
    monkeypatch.delenv("MCP_RECEIPT_DIR", raising=False)
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    yield


def _ok_transport():
    def handler(req: httpx.Request):
        assert SECRET in str(req.url)  # sanity: appid really is on the wire
        return httpx.Response(200, json={"opensearch:totalResults": "0", "items": []})
    return httpx.MockTransport(handler)


async def _run(params=None):
    inp = S.ArticleSearchInput(query="test query")
    return await S.cinii_search_articles(inp)


def test_appid_absent_from_envelope_and_receipt(monkeypatch):
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_ok_transport()))
    out = asyncio_run(_run())
    assert SECRET not in out
    env = json.loads(out)
    assert "appid" not in env["query"]["params"]
    assert SECRET not in json.dumps(env["receipt"])


def test_appid_absent_from_deposited_ledger_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_RECEIPT_DIR", str(tmp_path))
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_ok_transport()))
    asyncio_run(_run())
    path = os.path.join(str(tmp_path), "cinii.jsonl")
    assert os.path.exists(path)
    raw = open(path, encoding="utf-8").read()
    assert SECRET not in raw


def test_appid_absent_from_captured_log_output(monkeypatch):
    """_silence_http_logging() mutes httpx/httpcore and stops propagation, so
    even a DEBUG-level root handler must not see the request URL (and its
    appid). This exercises the control as configured at import time; a
    mutation copy that removes the mute is expected to fail this test."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_ok_transport()))
        asyncio_run(_run())
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert SECRET not in buf.getvalue()


def test_httpx_logger_is_actually_muted(monkeypatch):
    """The previous test drives a real search, but httpx.MockTransport does
    not emit httpx/httpcore's own request-URL INFO log line (that line comes
    from httpcore's real connection-pool code, which a mock transport never
    reaches), so it cannot exercise _silence_http_logging()'s level/propagate
    settings on its own. This test emits the log record directly through the
    httpx logger, as a real connection would, and checks the mute actually
    stops it from reaching a DEBUG root handler."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        logging.getLogger("httpx").info(
            "HTTP Request: GET https://cir.nii.ac.jp/opensearch/v2/articles"
            f"?q=test&appid={SECRET}&format=json \"HTTP/1.1 200 OK\""
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert SECRET not in buf.getvalue()


def _error_transport(body: str, status: int = 500):
    def handler(req: httpx.Request):
        return httpx.Response(status, text=body)
    return httpx.MockTransport(handler)


def test_appid_absent_from_api_error_diagnostic(monkeypatch):
    """A CiNii error response that echoes the failed request URL (as many APIs'
    error pages do) must not leak the appid into the diagnostic message."""
    echoed = f"Bad request for /opensearch/v2/articles?q=test&appid={SECRET}&format=json"
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_error_transport(echoed, 400)))
    out = asyncio_run(_run())
    assert SECRET not in out


def test_appid_absent_from_transport_error_diagnostic(monkeypatch):
    """A network-layer failure (e.g. a proxy or DNS error) can embed the failed
    URL in its exception message; that must not leak the appid either."""
    def handler(req: httpx.Request):
        raise httpx.ConnectError(f"could not connect to {req.url}")
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))
    out = asyncio_run(_run())
    assert SECRET not in out


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
