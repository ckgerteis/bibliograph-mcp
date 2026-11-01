"""Parser/shape tests against a real cinii_search_books response.

tests/cinii/fixtures/cinii_search_books_envelope.json was captured live on
2026-09-24 (query "大江健三郎 水死", count 5) through the receipt-stripping
stdio harness. The `cinii_search_books` MCP tool exposes only the finished
envelope, not CiNii's raw OpenSearch/JSON-LD payload, so this fixture is the
envelope itself, not a service payload to feed through a parser function --
the test below checks the envelope's fields directly instead.

This capture is evidence of the Fix 2 bug in the wild, from the server as it
stood before this fix: item 0's `source.journal_ja` holds "人民文学出版社"
(a publisher, Random House's PRC affiliate) with `extra` empty. Fix 2 itself
is unit-tested against a raw record built from this capture's own fields in
tests/cinii/test_parse.py (test_search_result_book_publisher_goes_to_extra_not_journal).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _load() -> dict:
    return json.loads((FIXTURES / "cinii_search_books_envelope.json").read_text(encoding="utf-8"))


def test_envelope_shape_and_result_count():
    env = _load()
    assert env["server"] == "cinii" and env["operation"] == "search_books"
    assert env["searched_for"]["term"] == "大江健三郎 水死"
    assert env["result"]["returned"] == 5 and len(env["items"]) == 5


def test_titles_present():
    env = _load()
    for it in env["items"]:
        t = it["title"]
        assert t["ja"] or t["en"], it


def test_authors_present_and_include_oe_kenzaburo():
    env = _load()
    for it in env["items"]:
        assert it["authors"], it
    ja_names = {a["ja"] for it in env["items"] for a in it["authors"] if a.get("ja")}
    assert "大江, 健三郎" in ja_names


def test_year_present_on_every_item():
    env = _load()
    for it in env["items"]:
        assert isinstance(it["source"]["year"], int), it


def test_url_and_crid_present():
    env = _load()
    for it in env["items"]:
        assert it["ids"]["crid"]
        assert it["ids"]["url_ja"] and "cir.nii.ac.jp/crid/" in it["ids"]["url_ja"]


def test_captured_bug_book_publisher_was_in_journal_ja_before_fix_2():
    # Documents what the live server returned before Fix 2: the publisher of
    # the first item's record sat in source.journal_ja and extra was empty.
    # The fix itself (extra.publisher, journal_ja None for record_type book)
    # is exercised against live-shaped input in test_parse.py, since this
    # fixture is the finished envelope, not raw input to a parser.
    env = _load()
    first = env["items"][0]
    assert first["record_type"] == "book"
    assert first["source"]["journal_ja"] == "人民文学出版社"
    assert first["extra"] == {}


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok  ", name)
    sys.exit(0)
