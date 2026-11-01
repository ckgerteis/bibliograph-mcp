"""Tests for the names core, run against the demo fixture index.

Run from the project root:  python -m pytest tests/ -q
"""
import os
import sys
import tempfile


from bibliograph.sources.names import build_index  # noqa: E402
from bibliograph.sources.names.db import NamesDB  # noqa: E402
from bibliograph.sources.names import names  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="module")
def db():
    path = os.path.join(tempfile.gettempdir(), "jmnedict_test.sqlite")
    build_index.build_demo(path)
    d = NamesDB(path)
    yield d
    d.close()


def test_reverse_romaji_to_kanji(db):
    res = names.resolve_name_kanji(db, "Saito")
    kanji = [c["kanji"] for c in res["candidates"]]
    assert "斎藤" in kanji and "斉藤" in kanji


def test_reverse_handles_macron_and_wapuro(db):
    # Satō and Satou both resolve to 佐藤
    assert any(c["kanji"] == "佐藤" for c in names.resolve_name_kanji(db, "Satō")["candidates"])
    assert any(c["kanji"] == "佐藤" for c in names.resolve_name_kanji(db, "Satou")["candidates"])


def test_readings_from_kanji(db):
    res = names.resolve_name_readings(db, "佐藤")
    assert res["found"]
    assert res["readings"][0]["kana"] == "さとう"
    assert res["readings"][0]["hepburn_macron"] == "satō"


def test_query_variants_expands_surname_kanji(db):
    bundle = names.name_query_variants(db, "斎藤")
    # interchangeable surname characters are generated even if not all are in the index
    assert "斎藤" in bundle["kanji"]
    assert "斉藤" in bundle["kanji"]
    assert "齋藤" in bundle["kanji"]
    assert "さいとう" in bundle["kana"]
    assert "saitō" in bundle["hepburn_macron"]


def test_infer_name_order(db):
    order = names.infer_name_order(db, "Tanaka", "Hiroshi")
    assert order["surname"] == "Tanaka"
    assert order["given"] == "Hiroshi"


def test_query_variants_two_token_romaji(db):
    bundle = names.name_query_variants(db, "Saito Shinichi")
    # full names are paired now; the surname parts live in surname_kanji
    assert "斎藤慎一" in bundle["kanji"]
    assert "斎藤" in bundle["surname_kanji"]
    # inverted order string present
    # built from the reading, so the macron survives
    assert bundle["inverted"] == ["Shin'ichi Saitō"]
