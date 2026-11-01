"""ndl-dl-mcp: parser and envelope tests against real captured fixtures
(tests/ndl_dl/fixtures/, captured live 2026-09-24, keyword 青年団 and
反戦青年委員会, size 5) plus offline synthetic cases for paths the two live
fixtures did not happen to exercise (book fulltext, the notification gate,
the bulk refusal). No network is used by any test in this file."""
import asyncio
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from bibliograph.sources.ndl_dl import server as S

FIX = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    yield
    S._last_request_at = 0.0


def _mock_get_returning(payload: dict):
    async def fake(path, params=None):
        return httpx.Response(200, json=payload), []
    return fake


# ---------------------------------------------------------------- hits / titles / pages

def test_search_reports_hits_titles_and_located_pages(monkeypatch):
    """The real 青年団 fixture: hit is at the service's 10,000 window ceiling,
    and the facet total (17,764, from isClassic false+true) is recovered and
    used as result.total, matching the ceiling case documented in the module
    docstring."""
    payload = _fixture("book_search_seinendan.json")
    monkeypatch.setattr(S, "_get", _mock_get_returning(payload))
    out = _run(S.ndl_dl_fulltext_search(S.FulltextSearchInput(keyword="青年団", size=5)))
    env = json.loads(out)
    assert env["server"] == "ndl-dl-mcp"
    assert env["result"]["total"] == 17764
    assert env["result"]["returned"] == 5
    codes = [d["code"] for d in env["diagnostics"]]
    assert "HIT_COUNT_CAPPED" in codes
    assert "NOTIFICATION_NOT_RECORDED" not in codes
    titles = [it["title"]["ja"] for it in env["items"]]
    assert "青年団叢書" in titles
    first = env["items"][0]
    assert first["authors"] == ["大日本聯合青年団 編"]
    assert first["source"]["year"] == 1935
    snippets = first["extra"]["located_snippets"]
    assert snippets, "expected located snippets from highlights"
    assert snippets[0]["image_page"] == 11
    assert snippets[0]["page_image_url"].endswith("/1130482/R0000011/full/full/0/default.jpg")
    assert "｢青年團｣" in snippets[0]["snippet"]


def test_zero_hit_search_is_zero_not_error(monkeypatch):
    """The real 反戦青年委員会 fixture: a postwar term against a pre-1945-heavy
    public-domain corpus returns zero hits, cleanly (no error diagnostic)."""
    payload = _fixture("book_search_hansen_seinen_iinkai.json")
    monkeypatch.setattr(S, "_get", _mock_get_returning(payload))
    out = _run(S.ndl_dl_fulltext_search(S.FulltextSearchInput(keyword="反戦青年委員会", size=5)))
    env = json.loads(out)
    assert env["items"] == []
    assert env["result"]["total"] == 0
    assert not any(d["level"] == "error" for d in env["diagnostics"])


# ---------------------------------------------------------------- no gate (0.2.0)
# NDL Lab asks for no application for non-commercial use, so there is no
# notice diagnostic and no refusal above 20 records.

def test_no_notification_diagnostic(monkeypatch):
    payload = _fixture("book_search_hansen_seinen_iinkai.json")
    monkeypatch.setattr(S, "_get", _mock_get_returning(payload))
    out = _run(S.ndl_dl_fulltext_search(S.FulltextSearchInput(keyword="x", size=1)))
    codes = [d["code"] for d in json.loads(out)["diagnostics"]]
    assert "NOTIFICATION_NOT_RECORDED" not in codes


def test_request_above_twenty_is_sent(monkeypatch):
    """size=21 reaches the transport and is not refused in process."""
    calls = []

    async def fake(path, params=None):
        calls.append(params)
        return httpx.Response(200, json=_fixture("book_search_hansen_seinen_iinkai.json")), []
    monkeypatch.setattr(S, "_get", fake)
    out = _run(S.ndl_dl_fulltext_search(S.FulltextSearchInput(keyword="青年団", size=21)))
    codes = [d["code"] for d in json.loads(out)["diagnostics"]]
    assert "BULK_REFUSED" not in codes
    assert calls and calls[0]["size"] == 21


def test_size_still_capped_at_max_records():
    with pytest.raises(Exception):
        S.FulltextSearchInput(keyword="x", size=S.MAX_RECORDS + 1)


# ---------------------------------------------------------------- distribution mode

def test_distribution_mode_with_no_year_facet_is_a_typed_diagnostic(monkeypatch):
    """The real fixture carries only an isClassic facet, no publishyear facet,
    so distribution mode must report NO_YEAR_FACET rather than silently
    returning an empty distribution."""
    payload = _fixture("book_search_seinendan.json")
    monkeypatch.setattr(S, "_get", _mock_get_returning(payload))
    out = _run(S.ndl_dl_fulltext_search(
        S.FulltextSearchInput(keyword="青年団", size=5, mode="distribution")))
    env = json.loads(out)
    assert env["items"] == []
    codes = [d["code"] for d in env["diagnostics"]]
    assert "NO_YEAR_FACET" in codes
    assert env["year_distribution"] == {}


# ---------------------------------------------------------------- book fulltext (synthetic; offline)

def _zip_with_pages(pages: dict[int, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for page, text in pages.items():
            zf.writestr(f"item_{page:04d}.txt", text)
    return buf.getvalue()


def test_book_fulltext_returns_pages_with_image_urls(monkeypatch):
    body = _zip_with_pages({1: "扉", 11: "四、男女青年團等との關係", 12: "青年學校と青年團との關係"})

    async def fake_get(path, params=None):
        assert path == "/api/book/fulltext/1130482"
        return httpx.Response(200, content=body), []
    monkeypatch.setattr(S, "_get", fake_get)

    out = _run(S.ndl_dl_book_fulltext(S.BookFulltextInput(item_id="1130482", pages="11-12")))
    env = json.loads(out)
    item = env["items"][0]
    assert item["extra"]["pages_returned"] == [11, 12]
    pages = {p["image_page"]: p for p in item["extra"]["pages"]}
    assert pages[11]["text"] == "四、男女青年團等との關係"
    assert pages[11]["page_image_url"] == "https://dl.ndl.go.jp/api/iiif/1130482/R0000011/full/full/0/default.jpg"
    assert env["result"]["total"] == 3  # text pages in archive


def test_book_fulltext_missing_pages_reported(monkeypatch):
    body = _zip_with_pages({1: "扉"})

    async def fake_get(path, params=None):
        return httpx.Response(200, content=body), []
    monkeypatch.setattr(S, "_get", fake_get)

    out = _run(S.ndl_dl_book_fulltext(S.BookFulltextInput(item_id="1130482", pages="1,99")))
    env = json.loads(out)
    codes = [d["code"] for d in env["diagnostics"]]
    assert "PAGES_NOT_IN_ARCHIVE" in codes
