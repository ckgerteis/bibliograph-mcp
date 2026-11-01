"""A provider's usage notice is checked per source, from the bibliograph notices folder."""
import json

from bibliograph import notices
from bibliograph.sources.ndl import server as ndl
from bibliograph.sources.ndl_dl import server as ndl_dl


def _env():
    return {"server": "ndl", "operation": "search_books", "diagnostics": [], "items": []}


def test_ndl_note_when_no_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOGRAPH_NOTICES_DIR", str(tmp_path))
    monkeypatch.delenv("BIBLIOGRAPH_NDL_NOTIFICATION_FILE", raising=False)
    for k in ("MCP_RECEIPT_DIR", "MCP_RECEIPT_LOG"):
        monkeypatch.delenv(k, raising=False)
    out = json.loads(ndl._emit(_env()))
    codes = [d["code"] for d in out["diagnostics"]]
    assert "NOTIFICATION_NOT_RECORDED" in codes
    hint = next(d["hint"] for d in out["diagnostics"] if d["code"] == "NOTIFICATION_NOT_RECORDED")
    assert str(tmp_path) in hint


def test_ndl_silent_when_marker_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOGRAPH_NOTICES_DIR", str(tmp_path))
    monkeypatch.delenv("BIBLIOGRAPH_NDL_NOTIFICATION_FILE", raising=False)
    (tmp_path / "NDL-API-NOTIFICATION.txt").write_text("Filed 2026-08-19\n", encoding="utf-8")
    out = json.loads(ndl._emit(_env()))
    assert "NOTIFICATION_NOT_RECORDED" not in [d["code"] for d in out["diagnostics"]]


def test_empty_marker_does_not_count(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOGRAPH_NOTICES_DIR", str(tmp_path))
    (tmp_path / "NDL-API-NOTIFICATION.txt").write_text("", encoding="utf-8")
    assert notices.recorded("ndl") is False

def test_other_sources_have_no_notice():
    assert notices.marker_path("cinii") is None
    assert notices.recorded("cinii") is False
