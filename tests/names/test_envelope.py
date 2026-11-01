"""Every tool answers in the family envelope and deposits a verifiable receipt."""
import json
import os
import tempfile

import pytest

from bibliograph.sources.names import build_index
from bibliograph import ledger
from bibliograph.sources.names import server
from bibliograph.sources.names.db import NamesDB

FAMILY_KEYS = {"server", "schema_version", "operation", "query", "matching_mode",
               "result", "items", "diagnostics", "coverage_note", "receipt", "attribution"}


@pytest.fixture()
def demo(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "demo.sqlite")
    build_index.build_demo(path)
    db = NamesDB(path)
    monkeypatch.setattr(server, "_DB", db)
    for k in ("MCP_RECEIPT_DIR", "MCP_RECEIPT_LOG"):
        monkeypatch.delenv(k, raising=False)
    yield db
    db.close()


def _call(fn, *a, **kw):
    return json.loads(fn(*a, **kw))


def test_dictionary_tool_is_enveloped(demo):
    env = _call(server.name_query_variants, "Saito Shinichi")
    assert FAMILY_KEYS <= set(env)
    assert env["server"] == "jmnedict" and env["operation"] == "name_query_variants"
    assert env["query"]["input_terms"] == "Saito Shinichi"
    assert env["result"]["returned"] == 1
    item = env["items"][0]
    assert item["record_type"] == "name_forms"
    assert "kanji" in item["extra"] and "hepburn_macron" in item["extra"]
    codes = [d["code"] for d in env["diagnostics"]]
    assert codes[0] == "OK"
    assert "RECEIPT_NOT_DEPOSITED" in codes          # no receipts folder set
    assert "EDRDG" in env["attribution"]


def test_absent_headword_is_zero_not_error(demo):
    env = _call(server.gloss_term, "存在しない語彙XYZ")
    assert env["items"] == [] and env["result"]["total"] == 0
    assert any(d["code"] == "ZERO_RESULTS" for d in env["diagnostics"])
    assert not any(d["level"] == "error" for d in env["diagnostics"])


def test_missing_index_is_a_typed_error(monkeypatch):
    def boom():
        raise FileNotFoundError("names.sqlite not found")
    monkeypatch.setattr(server, "_db", boom)
    env = _call(server.kanji_info, "漢")
    assert env["items"] == []
    assert [d["code"] for d in env["diagnostics"]][0] == "INDEX_MISSING"


def test_name_authority_records_are_items_and_plan_stays_visible(demo, monkeypatch):
    fake = [{"kanji_name": "打越正行", "reading": "ウチコシマサユキ",
             "ids": {"ndla": "00312345"}}]
    monkeypatch.setattr(server.authorities, "search_ndl_authorities", lambda v: fake)
    env = _call(server.name_authority, "Uchikoshi Masayuki")
    assert env["query"]["input_terms"] == "Uchikoshi Masayuki"
    assert "query_forms" in env["plan"]
    assert env["items"][0]["record_type"] == "authority"
    assert env["items"][0]["authors"][0]["ja"] == "打越正行"
    assert env["items"][0]["extra"]["ids"]["ndla"] == "00312345"
    codes = [d["code"] for d in env["diagnostics"]]
    assert "OK" in codes


def test_receipt_is_deposited_and_chain_verifies(demo, monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("MCP_RECEIPT_DIR", d)
    monkeypatch.setenv("MCP_RECEIPT_SESSION", "test")
    server.name_query_variants("Saito Shinichi")
    env = _call(server.resolve_name_kanji, "Satō")
    assert not any(x["code"].startswith("RECEIPT_") for x in env["diagnostics"])
    path = os.path.join(d, "jmnedict.jsonl")
    assert os.path.exists(path)
    assert ledger.verify_chain(path)["ok"] is True


def test_internal_fault_is_server_error_not_index_missing():
    # 1 Nov 2026: only FileNotFoundError was caught; the 31 Oct thread fault
    # reached the client as a bare "Error executing tool".
    import json as _json
    from bibliograph.sources.names import envelope as _E

    def boom():
        raise RuntimeError("SQLite objects created in a thread can only be used in that same thread")
    env = _json.loads(_E.respond("kanji_info", {"kanji": "書"}, boom))
    d = env["diagnostics"][0]
    assert d["code"] == "SERVER_ERROR" and d["level"] == "error"
    assert "RuntimeError" in d["message"] and "same thread" in d["message"]
    assert "INDEX_MISSING" not in [x["code"] for x in env["diagnostics"]]
