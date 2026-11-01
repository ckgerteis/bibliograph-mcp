"""The set declared on 18 September 2026: six providers, two credit conditions.

Fixtures are live SRU responses captured on 2026-09-18, one request per
provider. They pin the record shapes the new tools read: WARP's start URL in a
dcterms:description, the Digital Collections' access statement and viewer link,
the digitised copy clustered as an item under a holdings record, and the
journal-title records of the ISSN register. Run with pytest, or directly.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from bibliograph.sources.ndl import server as S

FIXTURES = Path(__file__).parent / "fixtures"


def _items(name: str) -> list[dict]:
    total, items, err = S._parse_sru((FIXTURES / name).read_text(encoding="utf-8"))
    assert err is None, err
    assert total >= 1 and items, (total, items)
    return items


def test_declared_set_is_twelve_and_excludes_article_online():
    assert len(S.DECLARED_DPIDS) == 12
    for dpid in ("ndl-boj", "warp", "iss-ndl-opac-inprocess", "issn-online", "ndl-dl", "ndl-dl-online",
                 "iss-ndl-opac-bib"):
        assert dpid in S.PROVIDERS
    assert S.PROVIDERS["iss-ndl-opac-bib"]["licence"] == "pdl"
    for dpid in ("ndl-article-online", "ndl-dl-doi"):
        assert dpid not in S.PROVIDERS


def test_search_all_leaves_out_warp_inprocess_and_the_redundant_subset():
    for dpid in ("warp", "iss-ndl-opac-inprocess", "ndl-boj", "iss-ndl-opac-bib"):
        assert dpid not in S.ALL_DPIDS
    assert "ndl-dl" in S.ALL_DPIDS and "issn-online" in S.ALL_DPIDS


def test_credit_keeps_display_only_providers_apart():
    open_only = S.provider_credit(S.BOOK_DPIDS)
    assert "Display only" not in open_only and "PDL1.0" in open_only
    mixed = S.provider_credit(S.ALL_DPIDS)
    head, _, tail = mixed.partition("Display only:")
    assert "国立国会図書館デジタルコレクション（電子書籍・電子雑誌）" in tail
    assert "国立国会図書館デジタルコレクション（電子書籍・電子雑誌）" not in head
    assert "not to be redistributed" in tail
    # the open-data digital set is PDL1.0 and stays in the open clause
    assert "（オープンデータ）" in head


def test_undeclared_dpid_is_refused_without_a_request():
    out = json.loads(asyncio.run(S._search("t", S.SearchInput(title="x"), ["ndl-article-online"])))
    assert out["diagnostics"][0]["code"] == "DPID_NOT_PERMITTED"


def test_get_record_query_stays_inside_the_declared_set():
    cql = S.build_cql({"anywhere": "000002727275"}, S.ALL_DPIDS)
    assert cql.startswith('anywhere="000002727275"')
    assert cql.count("dpid=") == len(S.ALL_DPIDS)


def test_warp_record_is_a_website_with_its_start_url():
    item = _items("sru_warp.xml")[0]
    assert item["record_type"] == "website"
    assert item["extra"]["warp_start_url"].startswith("http")
    assert "warp.ndl.go.jp" in item["extra"]["warp_url"]
    assert item["extra"]["warp_collection"]


def test_e_publication_states_access_and_viewer():
    items = _items("sru_ndl_dl_online.xml")
    rights = [r for it in items for r in it["extra"].get("access_rights", [])]
    assert "インターネット公開" in rights and "国立国会図書館内限定公開" in rights
    assert all(it["extra"]["viewer_url"].startswith("https://dl.ndl.go.jp/pid/") for it in items)


def test_digitised_copy_is_read_from_its_item_and_nothing_else_is():
    raw = (FIXTURES / "sru_ndl_dl_items.xml").read_text(encoding="utf-8")
    assert "東京都立中央図書館" in raw  # the response does carry other libraries' holdings
    items = _items("sru_ndl_dl_items.xml")
    first = items[0]
    assert first["title"]["ja"] == "嗚呼青年団"
    assert first["extra"]["viewer_url"] == "https://dl.ndl.go.jp/pid/13937109"
    assert first["ids"]["doi"] == "10.11501/13937109"
    assert "access_rights" not in first["extra"]  # the Search API does not state it here
    shown = json.dumps(items, ensure_ascii=False)
    for other in ("東京都立中央図書館", "神奈川県立図書館", "catalog.library.metro.tokyo.lg.jp", "ci.nii.ac.jp"):
        assert other not in shown, other


def test_issn_register_record_is_a_serial():
    item = _items("sru_issn_online.xml")[0]
    assert item["record_type"] == "serial"
    assert item["ids"]["issn"] == "2433-992X"
    assert item["extra"]["issn_l"] == "2433-992X"


def test_in_process_record_parses():
    item = _items("sru_inprocess.xml")[0]
    assert item["title"]["ja"]
    assert item["record_type"] == "book"


def test_books_input_flags_route_and_warn(monkeypatch=None):
    seen = {}

    async def fake(op, params, dpids, *, only_bib=True, notes=None):
        seen.update(dpids=dpids, notes=[n["code"] for n in (notes or [])], params=params)
        return "{}"

    real = S._search
    S._search = fake
    try:
        asyncio.run(S.ndl_search_books(S.BooksInput(title="x", include_in_process=True)))
        assert seen["dpids"] == ["iss-ndl-opac-bib", "iss-ndl-opac-inprocess"]
        assert seen["notes"] == ["PROVISIONAL_RECORDS"]
        assert type(seen["params"]) is S.SearchInput
        asyncio.run(S.ndl_search_books(S.BooksInput(title="x", japan_related_foreign_language_only=True)))
        assert seen["dpids"] == ["ndl-boj"] and seen["notes"] == []
        asyncio.run(S.ndl_search_books(S.BooksInput(title="x")))
        assert seen["dpids"] == ["iss-ndl-opac-bib"]
        asyncio.run(S.ndl_search_books(S.BooksInput(title="x", exclude_serial_issues=False)))
        assert seen["dpids"] == ["iss-ndl-opac"]
        assert "exclude_serial_issues" not in seen["params"].model_dump()
    finally:
        S._search = real


def test_digital_record_found_elsewhere_gets_the_display_only_credit():
    """A cluster's representative can come from the Digital Collections even when
    another set was searched (seen live on the ISSN register, 18 Sep 2026)."""
    xml = (FIXTURES / "sru_ndl_dl_online.xml").read_text(encoding="utf-8")

    async def fake_request(_params):
        return xml

    real = S._sru_request
    S._sru_request = fake_request
    try:
        out = json.loads(asyncio.run(S._search("t", S.SearchInput(title="x"), S.ONLINE_JOURNAL_DPIDS)))
        assert "Display only:" in out["attribution"]
        assert "DISPLAY_ONLY_METADATA" in [d["code"] for d in out["diagnostics"]]
        out = json.loads(asyncio.run(S._search("t", S.SearchInput(title="x"), S.DIGITAL_OPEN_DPIDS)))
        assert "Display only:" not in out["attribution"]
    finally:
        S._sru_request = real


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)


_NUMBER_WORDS = {10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen"}


def test_coverage_note_counts_the_declared_set():
    """The coverage note goes out in every response; its count must be the table's.

    bibliograph 1.4.0 declared twelve sets and told every user it queried eleven.
    """
    word = _NUMBER_WORDS[len(S.DECLARED_DPIDS)]
    assert f"the {word} NDL-created sets it declares" in S.COVERAGE_NOTE
    others = [w for n, w in _NUMBER_WORDS.items() if n != len(S.DECLARED_DPIDS)]
    assert not any(f" {w} " in S.COVERAGE_NOTE for w in others)
