"""Regression tests for the 23 Sep 2026 fixes (hermetic: demo index, no network).

1. romaji full names were exploded into an unpaired pool of part-kanji, so
   the matcher searched on whichever part sorted first and matched strangers;
2. any creator sharing a first kanji with any needle was accepted;
3. the NDL SPARQL GET overflowed (HTTP 414) on ~130 OR-terms;
4. (subject-hint fixes lived in the now-removed cross-service scholar finder);
5. kanji_by_radical rejected radical forms (氵) that RADKFILE files under
   stand-ins (汁);
6. JMnedict's short tags (masc/fem/unclass) were not counted as person types.
"""
import os
import tempfile

import pytest

from bibliograph.sources.names import build_index
from bibliograph.sources.names import names, refdata, authorities
from bibliograph.sources.names.db import NamesDB
from bibliograph.sources.names.db import PERSON_TYPES, apostrophe_forms
from bibliograph import namematch


@pytest.fixture(scope="module")
def db():
    path = os.path.join(tempfile.gettempdir(), "jmnedict_test_fixes.sqlite")
    build_index.build_demo(path)
    d = NamesDB(path)
    yield d
    d.close()


def test_two_token_romaji_pairs_into_full_names(db):
    b = names.name_query_variants(db, "Saito Shinichi")
    assert b["name_shape"] == "full"
    assert "斎藤慎一" in b["kanji"] and "斉藤慎一" in b["kanji"]
    assert "斎藤" not in b["kanji"]            # parts are no longer pooled in
    assert b["surname_kanji"][:2] == ["斎藤", "斉藤"] or set(b["surname_kanji"]) >= {"斎藤", "斉藤"}
    assert "saitō shin'ichi" in b["hepburn_macron"]


def test_short_person_tags_accepted():
    assert {"masc", "fem", "unclass"} <= PERSON_TYPES


def test_reading_fit_respects_marked_vowel_length():
    assert names._reading_fit("さとう", "Satō") == 2
    assert names._reading_fit("さと", "Satō") == 1
    assert names._reading_fit("さとう", "satou") == 2
    assert names._reading_fit("さと", "satou") == 1
    # unmarked input cannot discriminate: both fit
    assert names._reading_fit("せいいちろう", "Seiichiro") == 2
    assert names._reading_fit("せいいちろ", "Seiichiro") == 2
    assert names._reading_fit("せいいちろ", "Seiichirō") == 1


def _bundle(**kw):
    b = {"kanji": [], "kana": [], "hepburn_plain": [], "name_shape": "full"}
    b.update(kw)
    return b


def test_full_name_match_rejects_coauthors_and_same_surname_strangers():
    v = _bundle(kanji=["吉澤誠一郎", "吉沢誠一郎"],
                hepburn_plain=["yoshizawa", "seiichiro", "yoshizawa seiichiro"])
    assert namematch.matches_name("吉澤 誠一郎", v)
    assert namematch.matches_name("吉沢誠一郎", v)
    assert not namematch.matches_name("吉田 伸之", v)       # shares 吉 only
    assert not namematch.matches_name("吉澤 太郎", v)       # shares surname only
    assert namematch.matches_name("YOSHIZAWA Seiichiro", v)
    assert namematch.matches_name("Seiichiro Yoshizawa", v)
    assert not namematch.matches_name("Yoshizawa Taro", v)


def test_surname_only_query_keeps_prefix_matching():
    v = _bundle(kanji=["斎藤"], name_shape="single")
    assert namematch.matches_name("齋藤 敏一", v)
    assert not namematch.matches_name("田中 太郎", v)


def test_ndl_query_is_capped(monkeypatch):
    seen = {}

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": {"bindings": []}}

    def fake_get(url, params=None, **kw):
        seen["query"] = params["query"]
        return R()

    monkeypatch.setattr(authorities.requests, "get", fake_get)
    v = _bundle(kanji=[f"名前{i:03d}" for i in range(130)],
                kana_split=[["な", f"か{i}"] for i in range(50)])
    authorities.search_ndl_authorities(v)
    n_terms = seen["query"].count("CONTAINS(STR(?label)") + seen["query"].count("CONTAINS(STR(?yomi)")
    assert n_terms == authorities.NDL_MAX_KANJI_TERMS + authorities.NDL_MAX_KANA_TERMS


def test_radical_forms_map_to_radkfile_stand_ins():
    assert refdata._canon_component("氵") == "汁"
    assert refdata._canon_component("亻") == "化"
    assert refdata._canon_component("辶") == "込"
    assert refdata._canon_component("⽔") == "水"      # Kangxi block, via NFKC
    assert refdata._canon_component("阝") == "阝"      # ambiguous: expanded later


def test_syllabic_n_apostrophe_forms():
    assert "shin'ichi" in apostrophe_forms("shinichi")
    assert apostrophe_forms("tanaka")[0] == "tanaka"
    assert "tan'aka" in apostrophe_forms("tanaka")  # harmless: no such row


def test_two_token_with_unresolved_given_falls_back_to_surname(db):
    b = names.name_query_variants(db, "Saito Zzzz")
    assert "斎藤" in b["kanji"] and b["name_shape"] == "single"


def test_ndl_forms_use_authority_label_shape():
    v = _bundle(kanji=["吉澤誠一郎", "吉沢誠一郎"], surname_kanji=["吉澤", "吉沢"],
                kana_split=[["よしざわ", "せいいちろう"]])
    needles, kana = authorities._ndl_forms(v)
    assert needles[:2] == ["吉澤, 誠一郎", "吉沢, 誠一郎"]
    assert kana == ["ヨシザワ, セイイチロウ"]


def test_attested_kanji_name_is_split_into_parts(db):
    b = names.name_query_variants(db, "斎藤慎一")
    assert b["surname_kanji"] == ["斎藤"] and b["given_kanji"] == ["慎一"]
    assert ["さいとう", "しんいち"] in b["kana_split"]


def test_kanji_full_name_gets_spaced_romaji_and_inverted_order(db):
    # 色川武大 used to come back as one joined string with no inverted order
    b = names.name_query_variants(db, "斎藤慎一")
    assert "saitō shin'ichi" in b["hepburn_macron"]
    assert all(" " in v for v in b["hepburn_macron"])
    assert "Shin'ichi Saitō" in b["inverted"]          # not Shin'Ichi


def test_spaced_kanji_input_records_the_split(db):
    b = names.name_query_variants(db, "斎藤 慎一")
    assert ["さいとう", "しんいち"] in b["kana_split"]
    assert "Shin'ichi Saitō" in b["inverted"]


def test_readings_put_the_established_reading_first(db):
    # demo 佐藤 has only さとう; the ordering key must not crash and keep it
    r = names.resolve_name_readings(db, "佐藤")
    assert r["readings"][0]["kana"] == "さとう"


def test_extra_unknown_token_is_dropped_and_pair_kept(db):
    b = names.name_query_variants(db, "Saito Shinichi Jr")
    assert b["name_shape"] == "full" and "斎藤慎一" in b["kanji"]
    assert any("Jr" in n for n in b["notes"])


def test_kana_two_token_inverted_is_romaji(db):
    b = names.name_query_variants(db, "さいとう しんいち")
    assert b["inverted"] == ["Shin'ichi Saitō"]


def test_old_and_new_forms_fold_to_one_person():
    assert namematch.canonical_name_key("丸山眞男") == namematch.canonical_name_key("丸山真男")
    assert namematch.canonical_name_key("柳田國男") == namematch.canonical_name_key("柳田国男")
    # distinct name choices must NOT fold
    assert namematch.canonical_name_key("成田龍一") != namematch.canonical_name_key("成田竜一")
    v = names._kanji_variants("丸山眞男")
    assert v[0] == "丸山眞男" and "丸山真男" in v and len(v) <= names._MAX_KANJI_VARIANTS


def test_kanji_creator_rejected_when_nothing_to_match_against():
    v = _bundle(kanji=[], hepburn_plain=["kang", "sangjung", "kang sangjung"])
    assert not namematch.matches_name("土田 孝", v)
    assert namematch.matches_name("Kang Sangjung", v)


def test_full_name_search_key_is_the_spaced_romaji():
    v = _bundle(kanji=[], hepburn_plain=["kang", "sangjung", "kang sangjung"])
    assert namematch._name_keys(v)[0] == "kang sangjung"


# ---- Phase 1 (J4-J7) --------------------------------------------------------

def test_romaji_inverted_order_keeps_macron(db):
    b = names.name_query_variants(db, "Saito Shinichi")
    assert b["inverted"] == ["Shin'ichi Saitō"]


def test_one_retry_on_dropped_connection(monkeypatch):
    calls = []

    def flaky(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise authorities.requests.exceptions.ChunkedEncodingError("reset")
        return "ok"
    monkeypatch.setattr(authorities.requests, "get", flaky)
    monkeypatch.setattr(authorities.time, "sleep", lambda s: None)
    assert authorities._get("https://example.org") == "ok" and len(calls) == 2


def test_no_retry_on_timeout(monkeypatch):
    calls = []

    def slow(url, **kw):
        calls.append(url)
        raise authorities.requests.exceptions.ReadTimeout("throttled")
    monkeypatch.setattr(authorities.requests, "get", slow)
    with pytest.raises(authorities.requests.exceptions.ReadTimeout):
        authorities._get("https://example.org")
    assert len(calls) == 1


def test_tool_descriptions_state_the_rules():
    from bibliograph.sources.names import server
    assert "catalogue-verified" in server.name_authority.__doc__
    assert "query_forms" in server.name_authority.__doc__
    assert "lead, not an" in server.name_query_variants.__doc__
    assert "soft signal" in server.gloss_term.__doc__


def test_non_japanese_surname_list_excludes_common_japanese_surnames():
    for ch in "林高安原森佐田":
        assert ch not in names.LIKELY_NON_JAPANESE_SURNAMES
    assert "姜" in names.LIKELY_NON_JAPANESE_SURNAMES
