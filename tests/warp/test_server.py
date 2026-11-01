"""Offline tests. Fixtures reproduce the shapes WARP returned on 18 Sep 2026.

Since the F1 envelope conversion, each tool returns the family envelope
(mediation.build_envelope): captures/reads are `items[]` (record_type
"web_capture", url in ids.url_ja unless a non-Japanese title routes it to
ids.url_en, capture-specific fields in `extra`), typed `diagnostics[]`
(dicts with `code`), and `result.total`/`result.returned` in place of the
old `total_captures`/`returned` keys.
"""
import json
import os

import httpx
import pytest

from bibliograph.sources.warp import server as S
from bibliograph import ledger

TM = """<https://www.mhlw.go.jp/>; rel="original",
<https://warp.ndl.go.jp/collections/timemap/https://www.mhlw.go.jp/>; rel="self"; type="application/link-format"; from="Wed, 21 Oct 2009 07:47:17 GMT"; until="Sat, 01 Aug 2026 00:05:37 GMT",
<https://warp.ndl.go.jp/collections/https://www.mhlw.go.jp/>; rel="timegate",
<https://warp.ndl.go.jp/web/20091021074717/https://www.mhlw.go.jp/>; rel="first memento"; datetime="Wed, 21 Oct 2009 07:47:17 GMT",
<https://warp.ndl.go.jp/web/20100412040708/https://www.mhlw.go.jp/>; rel="memento"; datetime="Mon, 12 Apr 2010 04:07:08 GMT",
<https://warp.ndl.go.jp/web/20110315000000/https://www.mhlw.go.jp/>; rel="memento"; datetime="Tue, 15 Mar 2011 00:00:00 GMT",
<https://warp.ndl.go.jp/web/20260801000537/https://www.mhlw.go.jp/>; rel="last memento"; datetime="Sat, 01 Aug 2026 00:05:37 GMT",
"""
EMPTY_TM = """<http://example.go.jp/nothing>; rel="original",
<https://warp.ndl.go.jp/collections/timemap/http://example.go.jp/nothing>; rel="self"; type="application/link-format",
<https://warp.ndl.go.jp/collections/http://example.go.jp/nothing>; rel="timegate",
"""


def viewer(inner):
    return f'<!DOCTYPE html><html><head><title>NDL Web Archiving Project (WARP)</title></head><body>' \
           f'<iframe aria-live="polite" id="pywb-frame" class="warp-frame" src="{inner}" seamless="seamless"></iframe></body></html>'


PREMISES = ("<!doctype html><html><head><title>Available only within the facilities of the National Diet "
            "Library, Japan. | NDL Web Archiving Project (WARP)</title></head><body><h1>Available only within "
            "the facilities of the National Diet Library, Japan.</h1></body></html>")

SJIS_PAGE = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS">'
             '<title>厚生労働省</title><script>var x=1;</script></head><body>'
             '<div>東日本大震災関連情報</div><p>計画停電について<br>お知らせ</p>'
             '<a href="/20110401/20110315000000/https://www.mhlw.go.jp/stf/houdou/a.pdf">報道発表資料</a>'
             '<a href="https://warp.ndl.go.jp/20110401/20110315000000/https://www.mhlw.go.jp/b.html">b</a>'
             '<a href="#top">top</a></body></html>').encode("cp932")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(S, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(S, "_lock", None)
    monkeypatch.delenv("MCP_RECEIPT_DIR", raising=False)
    monkeypatch.delenv("MCP_RECEIPT_LOG", raising=False)
    yield
    S._TRANSPORT = None


def route(table, seen=None):
    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(str(req.url))
        for prefix, resp in table:
            if str(req.url).startswith(prefix):
                return resp(req) if callable(resp) else resp
        return httpx.Response(404, text="nope")
    S._TRANSPORT = httpx.MockTransport(handler)


def codes(env):
    return [d["code"] for d in env["diagnostics"]]


# ---------------------------------------------------------------- pure helpers

def test_parse_timemap():
    tm = S.parse_timemap(TM)
    ts = [c["timestamp"] for c in tm["captures"]]
    assert ts == ["20091021074717", "20100412040708", "20110315000000", "20260801000537"]
    assert tm["original"] == "https://www.mhlw.go.jp/"
    assert tm["captures"][0]["datetime_utc"] == "2009-10-21T07:47:17Z"


def test_parse_empty_timemap():
    assert S.parse_timemap(EMPTY_TM)["captures"] == []


def test_date_bounds():
    assert S.parse_date_bound("2011") == "20110101000000"
    assert S.parse_date_bound("2011", end=True) == "20111231235959"
    assert S.parse_date_bound("2011-02", end=True) == "20110228235959"
    assert S.parse_date_bound("2012-02", end=True) == "20120229235959"
    assert S.parse_date_bound("2011-03-11") == "20110311000000"
    with pytest.raises(ValueError):
        S.parse_date_bound("11-3")


def test_normalise_rejects_warp_urls():
    with pytest.raises(ValueError):
        S.normalise_url("https://warp.ndl.go.jp/web/20110315000000/https://www.mhlw.go.jp/")
    assert S.normalise_url("www.mhlw.go.jp/") == "http://www.mhlw.go.jp/"


def test_variants():
    v = S.url_variants("https://www.mhlw.go.jp/")
    assert "http://www.mhlw.go.jp/" in v and "https://www.mhlw.go.jp/index.html" in v and "https://mhlw.go.jp/" in v


def test_decode_sjis_without_header():
    text, enc = S.decode_body(SJIS_PAGE, "text/html")
    assert "厚生労働省" in text and enc == "cp932"


def test_links_rewritten_to_original():
    doc, _ = S.decode_body(SJIS_PAGE, None)
    links = S.extract_links(doc, "https://www.mhlw.go.jp/")
    urls = [l["original_url"] for l in links]
    assert urls == ["https://www.mhlw.go.jp/stf/houdou/a.pdf", "https://www.mhlw.go.jp/b.html"]


# ---------------------------------------------------------------- tools

async def test_list_captures_range_and_hist():
    route([(S.TIMEMAP_BASE, httpx.Response(200, text=TM, headers={"content-type": "application/link-format"}))])
    env = await S.list_captures("https://www.mhlw.go.jp/", from_date="2010", to_date="2011")
    assert env["server"] == "warp"
    assert env["operation"] == "warp_list_captures"
    assert env["matching_mode"] == "exact_url"
    assert env["result"]["total"] == 4
    assert env["result"]["returned"] == 2
    ts = [it["extra"]["timestamp"] for it in env["items"]]
    assert ts == ["20100412040708", "20110315000000"]
    for it in env["items"]:
        assert it["record_type"] == "web_capture"
        assert it["ids"]["url_ja"] == "https://www.mhlw.go.jp/"
        assert it["extra"]["captures_by_year"] == {"2009": 1, "2010": 1, "2011": 1, "2026": 1}


async def test_list_captures_empty_is_not_absence():
    route([(S.TIMEMAP_BASE, httpx.Response(200, text=EMPTY_TM))])
    env = await S.list_captures("http://example.go.jp/nothing")
    assert env["items"] == []
    assert env["result"]["total"] == 0
    assert "EMPTY_TIMEMAP" in codes(env)
    assert env.get("suggestions")
    assert any("url" in s for s in env["suggestions"])


async def test_nearest():
    route([(S.TIMEMAP_BASE, httpx.Response(200, text=TM))])
    env = await S.nearest_capture("https://www.mhlw.go.jp/", "2011-03-11")
    it = env["items"][0]
    assert it["extra"]["timestamp"] == "20110315000000"
    assert it["extra"]["at_or_before"]["timestamp"] == "20100412040708"
    assert it["extra"]["after"]["timestamp"] == "20110315000000"
    assert env["result"]["total"] == 4


async def test_timeout_reported_as_throttle():
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)
    route([(S.TIMEMAP_BASE, boom)])
    env = await S.list_captures("https://www.mhlw.go.jp/")
    assert "WARP_UNAVAILABLE" in codes(env)
    msg = next(d["message"] for d in env["diagnostics"] if d["code"] == "WARP_UNAVAILABLE")
    assert "throttling" in msg


async def test_429_reported():
    route([(S.TIMEMAP_BASE, httpx.Response(429))])
    env = await S.nearest_capture("https://www.mhlw.go.jp/", "2011")
    assert "WARP_UNAVAILABLE" in codes(env)


async def test_read_premises_only():
    inner = "/20100417/20100412040708/https://www.mhlw.go.jp/"
    route([
        (S.VIEWER_BASE, httpx.Response(200, text=viewer(inner))),
        (S.BASE + inner, httpx.Response(403, text=PREMISES)),
    ])
    env = await S.read_capture("https://www.mhlw.go.jp/", "20100412040708")
    it = env["items"][0]
    assert it["extra"]["status"] == "ndl_premises_only"
    assert it["extra"]["collection"] == "20100417" and it["extra"]["capture_timestamp"] == "20100412040708"
    assert "NDL_PREMISES_ONLY" in codes(env)


async def test_read_follows_archived_redirect_and_decodes():
    inner = "/20260723/20260705001243/https://www.mhlw.go.jp/"
    inner2 = "/20260723/20260705001243/https://www.mhlw.go.jp/index.html"
    seen = []
    route([
        (S.VIEWER_BASE + "20260705001243/https://www.mhlw.go.jp/index.html", httpx.Response(200, text=viewer(inner2))),
        (S.VIEWER_BASE, httpx.Response(200, text=viewer(inner))),
        (S.BASE + inner2, httpx.Response(200, content=SJIS_PAGE, headers={"content-type": "text/html"})),
        (S.BASE + inner, httpx.Response(301, headers={"location": inner2})),
    ], seen)
    env = await S.read_capture("https://www.mhlw.go.jp/", "20260801000537", include_links=True)
    it = env["items"][0]
    assert it["extra"]["status"] == "ok", it["extra"]
    assert it["extra"]["capture_timestamp"] == "20260705001243"
    assert it["extra"]["original_url"] == "https://www.mhlw.go.jp/index.html"
    assert it["extra"]["viewer_url"] == S.VIEWER_BASE + "20260705001243/https://www.mhlw.go.jp/index.html"
    assert "東日本大震災関連情報" in it["extra"]["text"] and "var x" not in it["extra"]["text"]
    assert it["title"]["ja"] == "厚生労働省"
    assert "CAPTURE_TIMESTAMP_DIFFERS_FROM_REQUEST" in codes(env)
    assert len(it["extra"]["redirects"]) == 1 and len(seen) == 4
    assert it["extra"]["redirects"][0]["to_original_url"] == "https://www.mhlw.go.jp/index.html"
    assert it["extra"]["links"][0]["original_url"].endswith("a.pdf")


async def test_read_redirect_loop_capped():
    inner = "/1/20200101000000/https://a.go.jp/"
    route([
        (S.VIEWER_BASE, httpx.Response(200, text=viewer(inner))),
        (S.BASE + inner, httpx.Response(302, headers={"location": inner})),
    ])
    env = await S.read_capture("https://a.go.jp/", "20200101000000")
    assert "REDIRECT_HOP_LIMIT" in codes(env)
    assert len(env["items"][0]["extra"]["redirects"]) == S.MAX_REDIRECT_HOPS


async def test_read_non_html():
    inner = "/1/20200101000000/https://a.go.jp/x.pdf"
    route([
        (S.VIEWER_BASE, httpx.Response(200, text=viewer(inner))),
        (S.BASE + inner, httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})),
    ])
    env = await S.read_capture("https://a.go.jp/x.pdf", "20200101000000")
    assert env["items"][0]["extra"]["status"] == "non_html"


async def test_read_pagination():
    inner = "/1/20200101000000/https://a.go.jp/"
    body = "<html><body><p>" + ("あ" * 5000) + "</p></body></html>"
    route([
        (S.VIEWER_BASE, httpx.Response(200, text=viewer(inner))),
        (S.BASE + inner, httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})),
    ])
    env = await S.read_capture("https://a.go.jp/", "20200101000000", max_chars=1000, offset=4500)
    extra = env["items"][0]["extra"]
    assert extra["total_chars"] == 5000 and extra["returned_chars"] == 500 and extra["truncated"] is False


async def test_invalid_timestamp():
    env = await S.read_capture("https://a.go.jp/", "2020")
    assert env["items"] == []
    assert "INVALID_INPUT" in codes(env)


async def test_serialised_and_spaced(monkeypatch):
    import asyncio, time
    monkeypatch.setattr(S, "MIN_REQUEST_INTERVAL", 0.2)
    route([(S.TIMEMAP_BASE, httpx.Response(200, text=TM))])
    t0 = time.monotonic()
    S._last_request_at = 0.0
    await asyncio.gather(*(S.list_captures("https://www.mhlw.go.jp/") for _ in range(3)))
    assert time.monotonic() - t0 >= 0.4  # three requests, two enforced gaps


async def test_receipt_written(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_RECEIPT_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_RECEIPT_SESSION", "test")
    route([(S.TIMEMAP_BASE, httpx.Response(200, text=TM))])
    await S.list_captures("https://www.mhlw.go.jp/", limit=2)
    p = tmp_path / "warp.jsonl"
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["server"] == "warp" and lines[0]["total"] == 4
    assert lines[0]["term"] == "https://www.mhlw.go.jp/"
    assert ledger.verify_chain(str(p))["ok"] is True


def test_ledger_is_family_copy():
    import hashlib, pathlib
    h = hashlib.sha256(pathlib.Path(ledger.__file__).read_bytes()).hexdigest()
    assert h == "d0bf4175edbc5bc143b08635ef1a3ca80f19b4183ba45239dcd43d1b3eca1bc1"
