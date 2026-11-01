"""Credential redaction for openalex-mcp: OPENALEX_API_KEY / OPENALEX_EMAIL
(mailto) must never appear in the envelope, the receipt, a deposited ledger
line, an error diagnostic built from a simulated HTTP failure, or captured log
output. Offline; transport mocked."""
import asyncio
import io
import json
import logging
import os

import httpx
import pytest

from bibliograph.sources.openalex import server as S

SECRET = "SECRET-TEST-KEY-123"

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before any monkeypatching


def _client_factory(transport):
    def make(*args, **kwargs):
        kwargs["transport"] = transport
        return _REAL_ASYNC_CLIENT(*args, **kwargs)
    return make


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(S, "API_KEY", SECRET)
    monkeypatch.setattr(S, "EMAIL", "")
    monkeypatch.delenv("MCP_RECEIPT_DIR", raising=False)
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    yield


def _ok_transport():
    def handler(req: httpx.Request):
        assert SECRET in str(req.url)  # sanity: key really is on the wire
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
    return httpx.MockTransport(handler)


def _search():
    return S.oa_search_works(S.WorkSearchInput(query="test query"))


def test_api_key_absent_from_envelope_and_receipt(monkeypatch):
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_ok_transport()))
    out = _run(_search())
    assert SECRET not in out
    env = json.loads(out)
    assert "api_key" not in env["query"]["params"]
    assert SECRET not in json.dumps(env["receipt"])


def test_api_key_absent_from_deposited_ledger_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_RECEIPT_DIR", str(tmp_path))
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_ok_transport()))
    _run(_search())
    path = os.path.join(str(tmp_path), "openalex.jsonl")
    assert os.path.exists(path)
    assert SECRET not in open(path, encoding="utf-8").read()


def test_api_key_absent_from_captured_log_output(monkeypatch):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_ok_transport()))
        _run(_search())
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert SECRET not in buf.getvalue()


def test_httpx_logger_is_actually_muted():
    """httpx.MockTransport does not emit httpx/httpcore's own request-URL INFO
    log line, so the previous test cannot exercise _silence_http_logging()'s
    level/propagate settings on its own. This emits the record directly."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        logging.getLogger("httpx").info(
            f"HTTP Request: GET https://api.openalex.org/works?search=test&api_key={SECRET} "
            "\"HTTP/1.1 200 OK\""
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert SECRET not in buf.getvalue()


def _error_transport(body: str, status: int = 500):
    def handler(req: httpx.Request):
        return httpx.Response(status, text=body)
    return httpx.MockTransport(handler)


def test_api_key_absent_from_api_error_diagnostic(monkeypatch):
    """OpenAlex's own _redact() strips the literal key from error text; this
    proves the control holds against an error body that echoes the key back."""
    echoed = f"error: bad api_key={SECRET} in request"
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(_error_transport(echoed, 400)))
    out = _run(_search())
    assert SECRET not in out


def test_api_key_absent_from_transport_error_diagnostic(monkeypatch):
    def handler(req: httpx.Request):
        raise httpx.ConnectError(f"could not connect to {req.url}")
    monkeypatch.setattr(S.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler)))
    out = _run(_search())
    assert SECRET not in out


def test_redact_helper_strips_key_from_arbitrary_text():
    assert S._redact(f"prefix {SECRET} suffix") == "prefix [redacted] suffix"
