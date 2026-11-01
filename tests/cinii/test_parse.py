"""Parsing of CiNii Research single-record JSON-LD, from records captured on
2026-09-04. Until 3.0.1 an untagged Japanese title was reported as its own
English title, the `creator` nodes were not read (no authors), and NAID and
ISSN were dropped. Run with pytest, or directly."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bibliograph.sources.cinii.server import _envelope, _item_from_cinii, _item_from_record

FIXTURES = Path(__file__).parent / "fixtures"


def _load(crid: str) -> dict:
    return _item_from_record(json.loads((FIXTURES / f"crid_{crid}.json").read_text(encoding="utf-8")))


def test_untagged_japanese_title_is_japanese_only():
    item = _load("1050002213762702720")
    assert item["title"]["ja"] == "鈴木文治と大正勞働運動 (中)"
    assert item["title"]["en"] is None
    assert item["source"]["journal_ja"] == "法學研究 : 法律・政治・社会"
    assert item["source"]["journal_en"] is None
    assert item["source"]["volume"] == "32" and item["source"]["issue"] == "2/3"
    assert item["source"]["pages"] == "21-45" and item["source"]["year"] == 1959


def test_creator_nodes_and_identifiers_are_read():
    item = _load("1050002213762702720")
    assert item["authors"] == [{"ja": "中村, 勝範", "en": None}]
    assert item["ids"]["naid"] == "120006816768"
    assert item["ids"]["issn"] == "03890538"
    assert item["ids"]["crid"] == "1050002213762702720"


def test_english_tagged_record_without_title():
    item = _load("1571135649335369984")
    assert item["title"] == {"ko": None, "ja": None, "en": None, "romanized": None}
    assert item["authors"] == [{"ja": None, "en": "Japan-Vitnam Friendship Association."}]
    assert item["source"]["journal_en"] == "Socialist R. of Vietnam."
    assert item["source"]["journal_ja"] is None
    assert item["ids"]["naid"] == "10005672599"


# ---------------------- book publisher (source.journal_ja -> extra.publisher) ----------------------
# Synthetic fixture (crid_book_synthetic.json), shaped like a CiNii Books
# JSON-LD record: dcterms:publisher carries the publisher, and until this fix
# it was merged into source.journal_ja, mislabelling a publisher as a journal.

def test_get_record_book_publisher_goes_to_extra_not_journal():
    item = _load("book_synthetic")
    assert item["record_type"] == "book"
    assert item["source"]["journal_ja"] is None
    assert item["source"]["journal_en"] is None
    assert item["extra"]["publisher"] == "人民文学出版社"


def test_search_result_book_publisher_goes_to_extra_not_journal():
    # _item_from_cinii is what cinii_search_books actually parses; CiNii's
    # OpenSearch item schema puts the publisher in prism:publicationName /
    # dc:publisher, same field an article's journal name occupies.
    raw = {
        "title": "水死",
        "dc:creator": ["大江健三郎"],
        "dc:publisher": "人民文学出版社",
        "dc:date": "2010",
        "@id": "https://cir.nii.ac.jp/crid/1130282271234567890",
    }
    item = _item_from_cinii(raw, "book")
    assert item["source"]["journal_ja"] is None
    assert item["source"]["journal_en"] is None
    assert item["extra"]["publisher"] == "人民文学出版社"


def test_search_result_article_journal_is_unaffected():
    raw = {
        "title": "テスト論文",
        "dc:creator": ["山田太郎"],
        "prism:publicationName": "日本研究",
        "dc:date": "2020",
    }
    item = _item_from_cinii(raw, "article")
    assert item["source"]["journal_ja"] == "日本研究"
    assert "publisher" not in item["extra"]


# ---------------------- F3: Researcher Number (NRID) ----------------------
# crid_researcher_synthetic.json is a synthetic Researcher-type JSON-LD
# record, shaped per the Researcher node schema directly observed nested
# under an article's `creator` in crid_1050002213762702720.json (a live
# capture, personIdentifier @type "NRID"): foaf:name for the name,
# personIdentifier for the identifier list. cinii_get_record previously
# returned every field null for a standalone Researcher CRID because
# _item_from_record only read dc:title/creator, which a Researcher record
# does not have.

def test_get_record_researcher_number_and_identifiers():
    item = _load("researcher_synthetic")
    assert item["record_type"] == "researcher"
    assert item["title"]["ja"] == "姜 尚中" and item["title"]["en"] == "Kang, Sangjung"
    assert item["extra"]["researcher_number"] == "9000408628758"
    assert {"type": "NRID", "value": "9000408628758"} in item["extra"]["identifiers"]
    assert {"type": "e-Rad", "value": "10204794"} in item["extra"]["identifiers"]
    # Bibliographic identifiers are untouched: this is person data.
    assert item["ids"]["doi"] is None and item["ids"]["naid"] is None


def test_search_researchers_does_not_fabricate_a_number():
    # _item_from_cinii is what cinii_search_researchers actually parses.
    # CiNii's OpenSearch researcher item schema carries no personIdentifier
    # field (checked live, 2026-09-24, query "姜尚中"): extraction must
    # degrade to nothing found, never invent a number.
    raw = {
        "title": "姜 尚中",
        "@id": "https://cir.nii.ac.jp/crid/1030003658443272706",
    }
    item = _item_from_cinii(raw, "researcher")
    assert "researcher_number" not in item["extra"]
    assert "identifiers" not in item["extra"]

    data = {"opensearch:totalResults": "1", "items": [raw]}
    env_json = _envelope(operation="search_researchers", record_type="researcher",
                         query_str="姜尚中", qp={"q": "姜尚中"}, data=data, error_diag=None,
                         author_query="姜尚中")
    env = json.loads(env_json)
    codes = [d["code"] for d in env["diagnostics"]]
    assert "NRID_NOT_IN_SEARCH_RESULT" in codes


def test_search_researchers_reads_identifier_if_cinii_ever_adds_one():
    # Defensive path: if a future OpenSearch payload does carry
    # personIdentifier, it is read the same way cinii_get_record reads it.
    raw = {
        "title": "姜 尚中",
        "@id": "https://cir.nii.ac.jp/crid/1030003658443272706",
        "personIdentifier": [{"@type": "NRID", "@value": "9000408628758"}],
    }
    item = _item_from_cinii(raw, "researcher")
    assert item["extra"]["researcher_number"] == "9000408628758"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)
