"""Name order and surname ranking against the real JMnedict index (24 Sep 2026).

Skipped when the index is not built. The cases come from bibliograph's end-to-end
run: "Sato Taro" was read the wrong way round, and for "Uchikoshi Masayuki" the
rarer surname 内越 led the list ahead of 打越.
"""
import os

import pytest

from bibliograph.sources.names import names as N
from bibliograph.sources.names.db import DEFAULT_DB, NamesDB

pytestmark = pytest.mark.skipif(not os.path.exists(DEFAULT_DB), reason="JMnedict index not built")


@pytest.fixture(scope="module")
def db():
    d = NamesDB(DEFAULT_DB)
    yield d
    d.close()


@pytest.mark.parametrize("a,b,sur", [
    ("Sato", "Taro", "Sato"), ("Taro", "Sato", "Sato"), ("Tanaka", "Akira", "Tanaka"),
    ("Hiroshi", "Ito", "Ito"), ("Kishi", "Masahiko", "Kishi"), ("Hanako", "Yamada", "Yamada"),
])
def test_order_from_person_entries(db, a, b, sur):
    r = N.infer_name_order(db, a, b)
    assert r["surname"] == sur
    assert r["basis"] == "person entries"
    assert r["confidence"] == "high"


def test_sato_taro_bundle_leads_with_sato(db):
    assert N.name_query_variants(db, "Sato Taro")["kanji"][0] == "佐藤太郎"


def test_widespread_surname_breaks_the_tie(db):
    k = N.name_query_variants(db, "Uchikoshi Masayuki")["kanji"]
    assert k[0].startswith("打越")
    assert k.index("打越正行") < k.index("内越正行")


def test_attested_names_unchanged(db):
    for name, first in [("Yoshizawa Seiichiro", "吉澤誠一郎"), ("Narita Ryuichi", "成田龍一"),
                        ("Oe Kenzaburo", "大江健三郎"), ("Irokawa Takehiro", "色川武大")]:
        assert N.name_query_variants(db, name)["kanji"][0] == first
