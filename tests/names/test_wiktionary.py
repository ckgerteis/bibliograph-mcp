"""Tests for the Wiktionary archaic-term glossing, against the demo fixture."""
import os
import sys
import tempfile


from bibliograph.sources.names import build_index  # noqa: E402
from bibliograph.sources.names.db import NamesDB  # noqa: E402
from bibliograph.sources.names import wiktionary  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="module")
def db():
    path = os.path.join(tempfile.gettempdir(), "jmnedict_wikt_test.sqlite")
    build_index.build_demo(path)
    d = NamesDB(path)
    yield d
    d.close()


def test_archaic_term_found_with_flag(db):
    res = wiktionary.gloss_archaic(db, "つとめて")
    assert res["found"]
    assert res["archaic_senses_present"]
    assert res["senses"][0]["archaic"] is True
    assert "early morning" in res["senses"][0]["gloss"]
    assert res["etymology"]  # etymology carried through


def test_classical_tag_detected(db):
    res = wiktionary.gloss_archaic(db, "いと")
    assert res["found"] and res["archaic_senses_present"]
    tags = res["senses"][0]["tags"]
    assert "classical" in tags or "archaic" in tags


def test_modern_word_has_no_archaic(db):
    res = wiktionary.gloss_archaic(db, "本")
    assert res["found"]
    assert res["archaic_senses_present"] is False


def test_only_archaic_filter(db):
    res = wiktionary.gloss_archaic(db, "本", only_archaic=True)
    # 本 has no archaic senses, so only_archaic yields nothing
    assert res["found"] is False
    assert res["senses"] == []


def test_caveat_always_present(db):
    res = wiktionary.gloss_archaic(db, "つとめて")
    assert "Nihon Kokugo Daijiten" in res["caveat"]


def test_missing_term_reports_not_found(db):
    res = wiktionary.gloss_archaic(db, "存在しない語")
    assert res["found"] is False
