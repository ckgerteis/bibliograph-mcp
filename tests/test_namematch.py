"""Tests for bibliograph.namematch, the full-name matching shared by the sources.

Moved out of tests/names/test_fixes_2026_09.py when the matching functions
moved from bibliograph.sources.names.services (deleted) to bibliograph.namematch, for
reuse by cinii, jstage, openalex and semantic_scholar.
"""
from bibliograph import namematch


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


def test_kanji_creator_rejected_when_nothing_to_match_against():
    v = _bundle(kanji=[], hepburn_plain=["kang", "sangjung", "kang sangjung"])
    assert not namematch.matches_name("土田 孝", v)
    assert namematch.matches_name("Kang Sangjung", v)


def test_full_name_search_key_is_the_spaced_romaji():
    v = _bundle(kanji=[], hepburn_plain=["kang", "sangjung", "kang sangjung"])
    assert namematch._name_keys(v)[0] == "kang sangjung"


def test_old_and_new_forms_fold_to_one_person():
    assert namematch.canonical_name_key("丸山眞男") == namematch.canonical_name_key("丸山真男")
    assert namematch.canonical_name_key("柳田國男") == namematch.canonical_name_key("柳田国男")
    # distinct name choices must NOT fold
    assert namematch.canonical_name_key("成田龍一") != namematch.canonical_name_key("成田竜一")


def test_matches_surname_wraps_matches_name():
    assert namematch.matches_surname("齋藤 敏一", ["斎藤"])
    assert not namematch.matches_surname("田中 太郎", ["斎藤"])


# ------------------------------- author_match -------------------------------

def test_author_match_kanji_partial_substring():
    assert namematch.author_match("田中明", "田中明彦") == "partial"
    assert namematch.author_match("田中明彦", "田中明") == "partial"


def test_author_match_kanji_exact_old_new_forms_fold():
    assert namematch.author_match("丸山眞男", "丸山真男") == "exact"


def test_author_match_kanji_whitespace_ignored():
    assert namematch.author_match("田中　太郎", "田中太郎") == "exact"
    assert namematch.author_match("田中 太郎", "田中太郎") == "exact"


def test_author_match_kanji_unrelated_is_none():
    assert namematch.author_match("田中太郎", "鈴木一郎") == "none"


def test_author_match_latin_exact_ignores_order_case_comma_macron():
    assert namematch.author_match("Yoshizawa Seiichiro", "YOSHIZAWA, Seiichirō") == "exact"
    assert namematch.author_match("Tanaka Akira", "Akira Tanaka") == "exact"


def test_author_match_latin_hyphen_ignored():
    assert namematch.author_match("Kang Sangjung", "Kang Sang-jung") == "exact"


def test_author_match_latin_surname_only_overlap_is_partial():
    # Decision: a shared surname with a different given name is graded
    # "partial", not "none" -- see author_match's docstring.
    assert namematch.author_match("Tanaka Akira", "Tanaka Akihiko") == "partial"


def test_author_match_latin_subset_is_partial():
    assert namematch.author_match("Tanaka", "Tanaka Akira") == "partial"
    assert namematch.author_match("Tanaka Akira", "Tanaka") == "partial"


def test_author_match_latin_no_overlap_is_none():
    assert namematch.author_match("Tanaka Akira", "Suzuki Ichiro") == "none"


def test_author_match_mixed_script_is_none():
    assert namematch.author_match("田中明", "Tanaka Akira") == "none"
    assert namematch.author_match("Tanaka Akira", "田中明") == "none"


def test_author_match_empty_is_none():
    assert namematch.author_match("", "田中明") == "none"
    assert namematch.author_match("田中明", "") == "none"
    assert namematch.author_match(None, "田中明") == "none"


def test_best_author_match_ranks_candidates():
    assert namematch.best_author_match("田中明", ["鈴木一郎", "田中明彦"]) == "partial"
    assert namematch.best_author_match("田中明", ["鈴木一郎", "田中明", "田中明彦"]) == "exact"
    assert namematch.best_author_match("田中明", []) == "none"
    assert namematch.best_author_match("田中明", [None, ""]) == "none"
