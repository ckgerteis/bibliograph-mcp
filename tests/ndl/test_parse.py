"""Parsing of NDL's two record layouts, from responses captured on 2026-09-04.

The periodicals index (zassaku) states the host periodical as
dcndl:publicationName, the issue as dcndl:issue, the pages as dcndl:pageRange,
and the material type only in the attributes of an empty dcndl:materialType.
Until 1.1.2 every one of those was missed: an article came back typed "book"
with no journal, no issue and no pages. Run with pytest, or directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

from bibliograph.sources.ndl.server import _parse_sru

FIXTURES = Path(__file__).parent / "fixtures"


def _one(name: str) -> dict:
    total, items, err = _parse_sru((FIXTURES / name).read_text(encoding="utf-8"))
    assert err is None, err
    assert total >= 1 and items, (total, items)
    return items[0]


def test_article_index_record_is_typed_and_sourced():
    item = _one("sru_article_zassaku.xml")
    assert item["record_type"] == "article"
    assert item["title"]["ja"] == "愛国的労働運動の波紋"
    assert item["source"]["journal_ja"] == "社会運動通信"
    assert item["source"]["issue"] == "285"
    assert item["source"]["pages"] == "1～2"
    assert item["source"]["year"] == 1951
    assert item["ids"]["crid"] is None  # NDLBibID is not a CiNii CRID (7 Oct 2026)
    assert item["extra"]["ndl_bib_id"] == "5173508"


def test_book_record_keeps_its_layout():
    item = _one("sru_book_jpno.xml")
    assert item["record_type"] == "book"
    assert item["ids"]["naid"] is None  # JPNO is not a CiNii NAID (7 Oct 2026)
    assert item["extra"]["jpno"] == "71009951"
    assert item["source"]["pages"] and "p" in item["source"]["pages"]
    assert item["source"]["journal_ja"] is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)
