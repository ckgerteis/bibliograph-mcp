"""Unit tests for the deterministic romanisation core.

Run from the project root:  python -m pytest tests/ -q
"""
import os
import sys


from bibliograph.sources.names.romaji import to_romaji, romaji_variants  # noqa: E402


def test_plain_names():
    assert to_romaji("やまだ", "hepburn_macron") == "yamada"
    assert to_romaji("すずき", "hepburn_macron") == "suzuki"
    assert to_romaji("なかむら", "hepburn_macron") == "nakamura"


def test_long_o_macron_and_plain():
    # さとう -> Satō / Sato
    assert to_romaji("さとう", "hepburn_macron") == "satō"
    assert to_romaji("さとう", "hepburn_plain") == "sato"
    # たろう -> Tarō / Taro
    assert to_romaji("たろう", "hepburn_macron") == "tarō"
    assert to_romaji("たろう", "hepburn_plain") == "taro"
    # こうの -> Kōno / Kono
    assert to_romaji("こうの", "hepburn_macron") == "kōno"
    assert to_romaji("こうの", "hepburn_plain") == "kono"


def test_long_u_macron():
    assert to_romaji("ゆうき", "hepburn_macron") == "yūki"
    assert to_romaji("ゆうき", "hepburn_plain") == "yuki"


def test_hepburn_vs_kunrei_consonants():
    # さいとう
    assert to_romaji("さいとう", "hepburn_macron") == "saitō"
    assert to_romaji("さいとう", "hepburn_plain") == "saito"
    assert to_romaji("さいとう", "kunrei") == "saito"
    # ちば -> Chiba / Tiba
    assert to_romaji("ちば", "hepburn_macron") == "chiba"
    assert to_romaji("ちば", "kunrei") == "tiba"
    # ふじ -> Fuji / Huzi
    assert to_romaji("ふじ", "hepburn_macron") == "fuji"
    assert to_romaji("ふじ", "kunrei") == "huzi"


def test_syllabic_n_apostrophe():
    # 慎一 しんいち -> shin'ichi ; kunrei sin'iti
    assert to_romaji("しんいち", "hepburn_macron") == "shin'ichi"
    assert to_romaji("しんいち", "kunrei") == "sin'iti"


def test_gemination():
    # 服部 はっとり -> Hattori
    assert to_romaji("はっとり", "hepburn_macron") == "hattori"
    # 吉川 きっかわ -> Kikkawa
    assert to_romaji("きっかわ", "hepburn_macron") == "kikkawa"


def test_youon():
    # じろう -> Jirō / Ziro
    assert to_romaji("じろう", "hepburn_macron") == "jirō"
    assert to_romaji("じろう", "kunrei") == "ziro"
    # とうきょう -> Tōkyō / Tokyo
    assert to_romaji("とうきょう", "hepburn_macron") == "tōkyō"
    assert to_romaji("とうきょう", "hepburn_plain") == "tokyo"


def test_katakana_input():
    # katakana should romanise identically to hiragana
    assert to_romaji("サトウ", "hepburn_macron") == "satō"


def test_variants_bundle():
    v = romaji_variants("さいとう")
    assert v["hepburn_macron"] == "saitō"
    assert "saito" in v["all"]
    # macron and plain/kunrei are distinct entries
    assert "saitō" in v["all"]


def test_conservative_double_vowels():
    # ii is NOT collapsed: 新島 にいじま -> Niijima, not Nījima
    assert to_romaji("にいじま", "hepburn_macron") == "niijima"
