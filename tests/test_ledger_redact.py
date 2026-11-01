"""Credential redaction in the ledger itself: redact(), record_envelope(),
record_request(). Offline; no network."""
import json
import os

import pytest

from bibliograph import ledger

SECRET = "SECRET-TEST-KEY-123"


def test_redact_strips_known_secret_keys():
    params = {
        "appid": SECRET, "api_key": SECRET, "apikey": SECRET, "key": SECRET,
        "token": SECRET, "access_token": SECRET, "x-api-key": SECRET,
        "mailto": "me@example.com", "email": "me@example.com",
        "password": SECRET, "secret": SECRET,
        "q": "keep me",
    }
    out = ledger.redact(params)
    for k in params:
        if k == "q":
            continue
        assert out[k] == "[redacted]", f"{k} was not redacted"
    assert out["q"] == "keep me"


def test_redact_is_case_and_whitespace_insensitive():
    out = ledger.redact({" API_KEY ": SECRET, "Token": SECRET})
    assert out[" API_KEY "] == "[redacted]"
    assert out["Token"] == "[redacted]"


def test_redact_empty_or_none():
    assert ledger.redact(None) == {}
    assert ledger.redact({}) == {}


def test_record_envelope_never_writes_secret_to_ledger_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_RECEIPT_DIR", str(tmp_path))
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    env = {
        "server": "cinii", "operation": "search_articles",
        "query": {"input_terms": "x", "normalized": "x", "script": "latin",
                   "params": {"q": "x", "appid": SECRET}},
        "matching_mode": "metadata_conjunction",
        "result": {"total": 0, "returned": 0, "start": 1, "breadth": "none"},
        "diagnostics": [],
        "coverage_note": None,
        "receipt": {"issued_at": "2026-01-01T00:00:00+00:00",
                    "query_hash": "sha256:deadbeef", "result_ids": []},
        "attribution": "x",
    }
    written = ledger.record_envelope(env)
    assert written is not None
    path = os.path.join(str(tmp_path), "cinii.jsonl")
    raw = open(path, encoding="utf-8").read()
    assert SECRET not in raw
    line = json.loads(raw.strip().splitlines()[-1])
    assert line["params"]["appid"] == "[redacted]"


def test_record_request_never_writes_secret_to_ledger_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_RECEIPT_DIR", str(tmp_path))
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    written = ledger.record_request(
        server="openalex", operation="search_works", endpoint="works",
        params={"search": "x", "api_key": SECRET, "mailto": "a@b.com"},
        response={"meta": {"count": 0}, "results": []},
    )
    assert written is not None
    path = os.path.join(str(tmp_path), "openalex.jsonl")
    raw = open(path, encoding="utf-8").read()
    assert SECRET not in raw
    line = json.loads(raw.strip().splitlines()[-1])
    assert line["params"]["api_key"] == "[redacted]"
    assert line["params"]["mailto"] == "[redacted]"
