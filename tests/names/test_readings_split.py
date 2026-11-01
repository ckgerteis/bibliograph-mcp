"""resolve_name_readings spaces a full-name listing at its surname boundary."""
from bibliograph.sources.names import names


class StubDB:
    """Rows shaped like NamesDB.by_kanji, copied from the real index."""
    ROWS = {
        "成田龍一": [{"kana": "なりたりゅういち", "name_types": "person"}],
        "成田": [{"kana": "なりた", "name_types": "surname"}],
        "龍一": [{"kana": "りゅういち", "name_types": "masc"}],
        "成": [{"kana": "なり", "name_types": "surname"}],
        "佐藤": [{"kana": "さとう", "name_types": "surname"}],
        "佐": [{"kana": "さ", "name_types": "surname"}],
        "藤": [{"kana": "とう", "name_types": "given"}],
    }

    def by_kanji(self, k):
        return list(self.ROWS.get(k, []))


def test_boundary_from_the_listing_reading():
    s = names._split_by_reading(StubDB(), "成田龍一", "なりたりゅういち")
    assert s == ("成田", "なりた", "龍一", "りゅういち")   # 成 + 田龍一 is unconfirmed, loses


def test_spaced_romaji_for_the_split():
    sp = names._spaced_romaji("なりた", "りゅういち")
    assert sp["hepburn_macron"] == "narita ryūichi"


def test_bare_surname_is_never_cut(monkeypatch):
    # 佐 + 藤 would "fit" the reading さ+とう; only person listings are split.
    class R:
        def attestation(self, *a):
            return 0

        def reading_popularity(self, *a):
            return 0
    monkeypatch.setattr(names, "_FreqRanker", lambda db: R())
    out = names.resolve_name_readings(StubDB(), "佐藤")
    assert out["readings"][0]["hepburn_macron"] == "satō"
    assert "split" not in out["readings"][0]
