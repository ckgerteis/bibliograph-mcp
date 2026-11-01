"""Parser/shape tests against a real jstage_search_articles response.

tests/jstage/fixtures/jstage_search_articles_envelope.json was captured live
on 2026-09-24 (text="反戦青年委員会", count 5) through the receipt-stripping
stdio harness. jstage_search_articles exposes only the finished envelope, not
J-STAGE's raw Atom/XML payload, so this fixture is the envelope itself and
the tests below check its fields directly rather than feeding raw XML
through a parser function.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _load() -> dict:
    return json.loads(
        (FIXTURES / "jstage_search_articles_envelope.json").read_text(encoding="utf-8")
    )


def test_envelope_shape_and_result_count():
    env = _load()
    assert env["server"] == "jstage" and env["operation"] == "search_articles"
    assert env["searched_for"]["term"] == "反戦青年委員会"
    assert env["result"]["returned"] == 5 and len(env["items"]) == 5


def test_titles_present():
    env = _load()
    for it in env["items"]:
        t = it["title"]
        assert t["ja"] or t["en"], it


def test_authors_present():
    env = _load()
    for it in env["items"]:
        assert it["authors"], it
        assert any(a.get("ja") or a.get("en") for a in it["authors"])


def test_year_present_on_every_item():
    env = _load()
    for it in env["items"]:
        assert isinstance(it["source"]["year"], int), it


def test_url_and_doi_present():
    env = _load()
    for it in env["items"]:
        assert it["ids"]["doi"]
        assert it["ids"]["url_ja"] and "jstage.jst.go.jp/article/" in it["ids"]["url_ja"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)
