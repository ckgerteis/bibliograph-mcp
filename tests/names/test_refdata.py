"""Tests for JMdict / KANJIDIC2 / KRAD-RADK lookups, against the demo fixture."""
import os
import sys
import tempfile


from bibliograph.sources.names import build_index  # noqa: E402
from bibliograph.sources.names.db import NamesDB  # noqa: E402
from bibliograph.sources.names import refdata  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="module")
def db():
    path = os.path.join(tempfile.gettempdir(), "jmnedict_refdata_test.sqlite")
    build_index.build_demo(path)
    d = NamesDB(path)
    yield d
    d.close()


def test_gloss_term(db):
    r = refdata.gloss_term(db, "和")
    assert r["found"]
    assert "harmony" in r["senses"][0]["gloss"]
    assert "n" in r["senses"][0]["pos"]
    assert r["senses"][0]["common"] is True


def test_gloss_term_kana_form(db):
    assert refdata.gloss_term(db, "せいふ")["found"]  # kana form resolves too


def test_kanji_info(db):
    r = refdata.kanji_info(db, "漢")
    assert r["found"]
    assert r["stroke_count"] == 13
    assert r["radical"] == 85
    assert "カン" in r["on"]
    assert any("China" in m or "Sino" in m for m in r["meanings"])
    assert r["jlpt"] == 2
    assert r["sh_desc"] == "3a10.11"
    assert r["skip"] == "1-3-10"
    assert set(r["components"]) == {"氵", "廿", "口", "夫"}


def test_kanji_info_rejects_multichar(db):
    assert refdata.kanji_info(db, "漢字")["found"] is False


def test_kanji_by_radical_intersection(db):
    r = refdata.kanji_by_radical(db, "氵 口")
    assert r["found"] and r["kanji"] == ["漢"]


def test_kanji_by_radical_single(db):
    assert set(refdata.kanji_by_radical(db, "口")["kanji"]) == {"漢", "和"}


def test_kanji_by_radical_unknown_flagged(db):
    r = refdata.kanji_by_radical(db, "口 z")
    assert "z" in r["unknown_components"]
    assert r["found"] is False   # nothing has both 口 and z


def test_components_of(db):
    assert set(refdata.components_of(db, "和")["components"]) == {"禾", "口"}
