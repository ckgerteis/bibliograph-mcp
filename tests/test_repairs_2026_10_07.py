"""Regression tests for the repairs of 7 Oct 2026 (live check, mutation fuzz, second-model review).

1. NDL Search put NDLBibID in ids.crid and JPNO in ids.naid - CiNii's slots.
2. NDL Search returned volumes with an embedded newline and indentation.
3. NDL Next Digital Library snippets kept HTML entities (&#x2F; for "/").
4. Receipts from ndl_dl, warp, and DOI-less ndl/openalex/s2 records had an
   empty result_ids, so the ledger did not say what a search returned.
No network is used.
"""
import asyncio
import json
import re
from pathlib import Path

import httpx

from bibliograph import mediation as M
from bibliograph import receipt_ids as R
from bibliograph.sources.ndl import server as NDL
from bibliograph.sources.ndl_dl import server as DL
from bibliograph.sources.warp import server as W

FIX = Path(__file__).parent


def _env(items):
    return M.build_envelope(server="t", operation="t_search", input_terms="x", normalized="x",
                            params={}, matching_mode="exact", total=len(items), start=1,
                            items=items, diagnostics=[], attribution="t")


# ---------------------------------------------------------------- 1 and 2: NDL Search

def test_ndl_identifiers_leave_cinii_slots():
    _, items, _ = NDL._parse_sru((FIX / "ndl/fixtures/sru_book_jpno.xml").read_text(encoding="utf-8"))
    it = items[0]
    assert it["ids"]["crid"] is None and it["ids"]["naid"] is None
    assert it["extra"]["jpno"] == "71009951"


def test_ndl_volume_whitespace_collapsed():
    xml = (FIX / "ndl/fixtures/sru_book_jpno.xml").read_text(encoding="utf-8")
    assert "dcterms:extent" in xml
    assert NDL._squash("第1巻\n            上") == "第1巻 上"
    assert NDL._squash("  12  ") == "12"
    assert NDL._squash("") is None and NDL._squash(None) is None
    assert NDL._squash(" \n ") is None


def test_ndl_receipt_names_ndl_records():
    _, items, _ = NDL._parse_sru((FIX / "ndl/fixtures/sru_article_zassaku.xml").read_text(encoding="utf-8"))
    env = R.complete(_env(items), NDL._receipt_id)
    assert env["receipt"]["result_ids"][0] == "NDLBibID:5173508"
    assert len(env["receipt"]["result_ids"]) == len(items)


# ---------------------------------------------------------------- 3 and 4: Next Digital Library

def test_ndl_dl_snippet_entities_unescaped():
    out = DL._clean_highlights(["明治&#x2F;大正 <em>青年</em> &amp; 団 (0011.jp2)"], "1130482")
    assert "&#x2F;" not in out[0]["snippet"] and "/" in out[0]["snippet"]
    assert "&amp;" not in out[0]["snippet"] and "&" in out[0]["snippet"]
    assert out[0]["image_page"] == 11


def test_ndl_dl_receipt_names_pids(monkeypatch):
    payload = json.loads((FIX / "ndl_dl/fixtures/book_search_seinendan.json").read_text(encoding="utf-8"))

    async def fake(path, params=None):
        return httpx.Response(200, json=payload), []
    monkeypatch.setattr(DL, "_get", fake)
    env = json.loads(asyncio.run(DL.ndl_dl_fulltext_search(DL.FulltextSearchInput(keyword="青年団", size=5))))
    ids = env["receipt"]["result_ids"]
    assert len(ids) == env["result"]["returned"] == 5
    assert all(i.startswith("info:ndljp/pid/") for i in ids)
    assert "info:ndljp/pid/1130482" in ids


# ---------------------------------------------------------------- 4: WARP

def test_warp_receipt_names_the_capture_not_the_site():
    it = M.make_item(url_ja="https://www.mhlw.go.jp/", record_type="web_capture",
                     extra={"capture_timestamp": "20110315000000"})
    rid = W._receipt_id(it)
    assert "20110315000000" in rid and "mhlw.go.jp" in rid
    it2 = M.make_item(url_ja="https://www.mhlw.go.jp/", extra={"viewer_url": "https://warp.ndl.go.jp/x"})
    assert W._receipt_id(it2) == "https://warp.ndl.go.jp/x"


# ---------------------------------------------------------------- the helper itself

def test_contract_slots_still_win_and_order_is_kept():
    a = M.make_item(doi="10.1/a", extra={"openalex_id": "W1"})
    b = M.make_item(extra={"openalex_id": "W2"})
    c = M.make_item()
    env = R.complete(_env([a, b, c]), lambda it: R.prefixed("openalex:", R.extra_of(it).get("openalex_id")))
    assert env["receipt"]["result_ids"] == ["10.1/a", "openalex:W2"]


def test_helper_survives_malformed_items_and_bad_callbacks():
    env = _env([M.make_item()])
    env["items"].append("not a dict")
    env["items"].append({"ids": "nonsense", "extra": None})

    def boom(it):
        raise RuntimeError("x")
    assert R.complete(env, boom)["receipt"]["result_ids"] == []
    assert R.complete(env, lambda it: 42)["receipt"]["result_ids"] == []
    assert R.complete({"items": []}, boom) == {"items": []}  # no receipt: untouched


# ---------------------------------------------------------------- 5: J-STAGE field-restricted zeros
# Reported 7 Oct 2026: 占領期 労働運動 and 労働運動史 returned 0. The receipts show
# both were sent in `keyword` (the authors' own keyword lists); in `text` the same
# strings returned 252 and 815. The fixture is J-STAGE's live answer to
# keyword=労働運動史 that day (ERR_001).

from bibliograph.sources.jstage import server as JS


def test_jstage_keyword_zero_names_the_field_and_points_to_text(monkeypatch):
    body = (FIX / "jstage/fixtures/search_keyword_zero_2026-10-07.xml").read_text(encoding="utf-8")

    async def fake(params):
        return body
    monkeypatch.setattr(JS, "_get", fake)
    env = json.loads(asyncio.run(JS.jstage_search_articles(JS.SearchArticlesInput(keyword="労働運動史"))))
    assert env["result"]["total"] == 0
    assert env["matching_mode"] == "field_restricted"
    d = next(d for d in env["diagnostics"] if d["code"] == "LITERAL_COMPOUND_EMPTY")
    assert "`keyword`" in d["message"]
    assert "`text`" in d["hint"]


def test_jstage_text_search_keeps_full_text_mode(monkeypatch):
    body = (FIX / "jstage/fixtures/search_keyword_zero_2026-10-07.xml").read_text(encoding="utf-8")

    async def fake(params):
        return body
    monkeypatch.setattr(JS, "_get", fake)
    env = json.loads(asyncio.run(JS.jstage_search_articles(JS.SearchArticlesInput(text="労働運動史"))))
    assert env["matching_mode"] == "full_text_broad"
    d = next(d for d in env["diagnostics"] if d["code"] == "LITERAL_COMPOUND_EMPTY")
    assert "emic" in d["hint"]


def test_jstage_keyword_field_description_steers_to_text():
    desc = JS.SearchArticlesInput.model_fields["keyword"].description
    assert "narrowest" in desc and "`text`" in desc


# ---------------------------------------------------------------- 6: found by the mutation fuzz, 7 Oct 2026

def test_warp_timemap_with_unparseable_datetime_skips_the_line():
    tm = ('<https://www.mhlw.go.jp/>; rel="original",\n'
          '<https://warp.ndl.go.jp/x/a>; rel="memento"; datetime="Mon, 12 Apr 20\n,"\n'
          '<https://warp.ndl.go.jp/web/20100412040708/https://www.mhlw.go.jp/>; rel="memento"; '
          'datetime="Mon, 12 Apr 2010 04:07:08 GMT",\n')
    out = W.parse_timemap(tm)
    assert [c["timestamp"] for c in out["captures"]] == ["20100412040708"]


def test_jdcat_non_string_oai_id_is_dropped():
    from bibliograph.sources.jdcat import server as JD
    payload = json.loads((FIX / "jdcat/fixtures/search_kinro_seishonen.json").read_text(encoding="utf-8"))
    hit = payload["hits"]["hits"][0]
    hit["metadata"]["_oai"] = {"id": -1}
    assert JD.item_from_hit(hit)["ids"]["oai_id"] is None


def test_ndl_dl_malformed_body_and_records_are_typed(monkeypatch):
    async def not_an_object(path, params=None):
        return httpx.Response(200, json=["x"]), []
    monkeypatch.setattr(DL, "_get", not_an_object)
    env = json.loads(asyncio.run(DL.ndl_dl_fulltext_search(DL.FulltextSearchInput(keyword="青年", size=1))))
    assert "API_ERROR" in [d["code"] for d in env["diagnostics"]] and env["items"] == []

    async def odd_records(path, params=None):
        return httpx.Response(200, json={"hit": 2, "list": [{"id": "1", "title": 7, "volume": None}, 3.5, {"id": {}}]}), []
    monkeypatch.setattr(DL, "_get", odd_records)
    env = json.loads(asyncio.run(DL.ndl_dl_fulltext_search(DL.FulltextSearchInput(keyword="青年", size=3))))
    assert env["items"][0]["title"]["ja"] == "7"
    assert any(d["code"] == "RECORD_SHAPE_UNEXPECTED" for d in env["diagnostics"])


def test_cinii_malformed_records_are_counted_not_raised():
    from bibliograph.sources.cinii import server as CI
    out = json.loads(CI._envelope(operation="search_articles", record_type="article", query_str="青年",
                                  qp={}, data={"items": [{"title": 1.5, "dc:creator": 3}, "junk"],
                                               "opensearch:totalResults": 2}, error_diag=None))
    codes = [d["code"] for d in out["diagnostics"]]
    assert "RECORD_SHAPE_UNEXPECTED" in codes
    assert len(out["items"]) + int(re.search(r"(\d+) record", next(
        d["message"] for d in out["diagnostics"] if d["code"] == "RECORD_SHAPE_UNEXPECTED")).group(1)) == 2


# ---------------------------------------------------------------- 7: found by the live stress run, 7 Oct 2026

def test_ndl_dl_page_image_caps_and_drops_page_zero():
    env = json.loads(asyncio.run(DL.ndl_dl_page_image(DL.PageImageInput(item_id="1130482", pages="0-999999"))))
    imgs = env["items"][0]["extra"]["page_images"]
    assert len(imgs) == DL.MAX_PAGE_IMAGES and imgs[0]["image_page"] == 1
    assert "PAGE_LIST_CAPPED" in [d["code"] for d in env["diagnostics"]]


def test_warp_refuses_non_http_schemes_and_bad_ports():
    import pytest
    for bad in ("javascript:alert(1)", "mailto:a@b.jp", "file:///etc/passwd", "http://a.go.jp:99999999/"):
        with pytest.raises(ValueError):
            W.normalise_url(bad)
    for ok in ("www.mhlw.go.jp", "www.mhlw.go.jp:8080/x", "localhost:8080/", "https://www.mhlw.go.jp/"):
        assert W.normalise_url(ok).startswith(("http://", "https://"))


def test_s2_whitespace_in_pages_collapsed():
    from bibliograph.sources.semantic_scholar import server as S2
    assert S2._ws("\n          10519815261449251\n        ") == "10519815261449251"
    assert S2._ws("  ") is None and S2._ws(None) is None and S2._ws(12) == "12"


# ---------------------------------------------------------------- 8: conform - wrong types never reach the envelope

def test_conform_replaces_only_wrong_types():
    from bibliograph import conform as C
    it = M.make_item(title_ja="青年", volume="12", year=1960, doi="10.1/x", url_en=None,
                     authors=[{"ja": "田中", "en": 3}, "編集部", 7, None, 1.5])
    it["source"]["pages"] = 41
    it["source"]["year"] = 1960
    before = json.dumps(it, ensure_ascii=False)
    C.item(it)
    assert it["title"]["ja"] == "青年" and it["source"]["volume"] == "12" and it["ids"]["doi"] == "10.1/x"
    assert it["source"]["pages"] == "41" and it["source"]["year"] == 1960
    assert it["authors"] == [{"ja": "田中", "en": "3"}, "編集部", "7"]
    assert before != json.dumps(it, ensure_ascii=False)
    bad = M.make_item(url_ja=True, year=True)
    bad["source"]["year"] = "1960"
    C.item(bad)
    assert bad["ids"]["url_ja"] is None and bad["source"]["year"] == 1960


def test_conform_facets_and_valid_envelopes_untouched():
    from bibliograph import conform as C
    env = _env([M.make_item(title_en="t", doi="10.1/a")])
    env["facets"] = {"Topic": {"buckets": [{"label": "a", "count": True}, {"label": 3, "count": "5"}], "other_count": 2}}
    C.envelope(env)
    assert env["facets"]["Topic"]["buckets"] == [{"label": "a", "count": None}, {"label": "3", "count": 5}]
    clean = _env([M.make_item(title_en="t", doi="10.1/a", year=2001)])
    snapshot = json.dumps(clean, sort_keys=True)
    C.envelope(clean)
    assert json.dumps(clean, sort_keys=True) == snapshot


def test_jstage_double_escaped_titles_unescaped():
    import xml.etree.ElementTree as ET
    el = ET.fromstring("<t>労働史研究への示唆に関する覚書(&amp;lt;書評特集&amp;gt;二村一夫)</t>")
    assert JS._text(el) == "労働史研究への示唆に関する覚書(<書評特集>二村一夫)"


# ---------------------------------------------------------------- 9: second-model review, 7 Oct 2026

def test_unescape_needs_a_semicolon():
    assert JS._unescape("https://x/?a=1&region=2&para=3") == "https://x/?a=1&region=2&para=3"
    assert JS._unescape("(&lt;書評特集&gt;) &amp; &#x2F; &#47;") == "(<書評特集>) & / /"
    assert DL._unescape("R&D &sect3 &amp;") == "R&D &sect3 &"


def test_warp_scheme_guard_closes_digit_loophole_keeps_userinfo():
    import pytest
    for bad in ("javascript:1", "tel:5551234", "http://a.go.jp:0/"):
        with pytest.raises(ValueError):
            W.normalise_url(bad)
    for ok in ("user:pass@host.jp/x", "localhost:8080/", "[::1]:8080/x", "HTTP://Example.com/"):
        W.normalise_url(ok)


async def test_warp_unparseable_mementos_reported(monkeypatch):
    tm = ('<https://www.mhlw.go.jp/>; rel="original",\n'
          '<https://warp.ndl.go.jp/x/a>; rel="memento"; datetime="garbage",\n')
    monkeypatch.setattr(W, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(W, "_lock", None)
    W._TRANSPORT = httpx.MockTransport(lambda req: httpx.Response(200, text=tm))
    try:
        env = await W.list_captures("https://www.mhlw.go.jp/")
    finally:
        W._TRANSPORT = None
    codes = [d["code"] for d in env["diagnostics"]]
    assert "EMPTY_TIMEMAP" in codes and "MEMENTO_DATE_UNPARSEABLE" in codes


def test_non_list_results_are_reported():
    items, bad = R.build_items({"oops": 1}, lambda r, m: r, "m")
    assert items == [] and bad == 1
    items, bad = R.build_items(None, lambda r, m: r, "m")
    assert items == [] and bad == 0


def test_whitespace_slot_does_not_suppress_fallback():
    it = M.make_item(oai_id="   ", extra={"openalex_id": "W9"})
    env = R.complete(_env([it]), lambda i: R.prefixed("openalex:", R.extra_of(i).get("openalex_id")))
    assert env["receipt"]["result_ids"] == ["openalex:W9"]


def test_openalex_single_record_that_will_not_build_is_an_error():
    from bibliograph.sources.openalex import server as OA

    def boom(r, m):
        raise TypeError("x")
    out = json.loads(OA._envelope(operation="get_work", term="W1", params={}, matching_mode="identifier",
                                  data={"id": "W1"}, err=None, build=boom, matched_in="identifier", single=True))
    assert "API_ERROR" in [d["code"] for d in out["diagnostics"]]


def test_ndl_dl_page_zero_never_resolved():
    env = json.loads(asyncio.run(DL.ndl_dl_page_image(DL.PageImageInput(item_id="1130482", pages="0-3"))))
    assert [p["image_page"] for p in env["items"][0]["extra"]["page_images"]] == [1, 2, 3]
    assert DL._parse_page_range("0-3", 99999)[0] >= 1  # the parser never yields page 0
