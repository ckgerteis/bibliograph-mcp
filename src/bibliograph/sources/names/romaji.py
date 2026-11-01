"""Deterministic kana -> romaji conversion.

Produces three search-useful renderings of a kana reading:

  - ``hepburn_macron``  Modified Hepburn with macrons (Satō, Yūki, Tarō)
  - ``hepburn_plain``   Hepburn consonants, macrons dropped (Sato, Yuki, Taro)
  - ``kunrei``          Kunrei-shiki consonants, diacritics dropped (Sato, Saito;
                        si/ti/tu/hu/zi where Hepburn has shi/chi/tsu/fu/ji)

Why three: Japanese bibliographic databases key romanised author fields
inconsistently — some Hepburn, some kunrei, some with macrons stripped. A
single rendering silently misses records. These three cover the common cases.

Pure and dependency-free so it can be unit-tested and run at index time
without a model call.

Honest limits (documented, not hidden):
  - Long-vowel handling collapses ``ou``/``oo`` and ``uu`` only. It does NOT
    collapse ``aa``/``ii``/``ee`` or ``ei``, which in names are usually two
    genuine morae (Niijima, Eiichi). A deliberate bias toward under-collapsing
    rather than mangling names.
  - In plain/kunrei the long vowel reduces to a single short vowel (Satō ->
    Sato), matching macron-stripped library romanisation. The circumflex
    kunrei form (Tô) is not produced.
"""

from __future__ import annotations

SMALL_Y = {"ゃ": "ya", "ゅ": "yu", "ょ": "yo"}
SMALL_V = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}
SOKUON = "っ"
PROLONG = "ー"

_HEPBURN = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "wi", "ゑ": "we", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ゔ": "vu",
}

_HEPBURN_YOUON = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo",
    "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho",
    "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo",
    "ぢゃ": "ja", "ぢゅ": "ju", "ぢょ": "jo",
    "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
}

_KUNREI_MORA = {
    "し": "si", "ち": "ti", "つ": "tu", "ふ": "hu",
    "じ": "zi", "ぢ": "zi", "づ": "zu", "を": "o", "ゔ": "vu",
}
_KUNREI_YOUON = {
    "しゃ": "sya", "しゅ": "syu", "しょ": "syo",
    "ちゃ": "tya", "ちゅ": "tyu", "ちょ": "tyo",
    "じゃ": "zya", "じゅ": "zyu", "じょ": "zyo",
    "ぢゃ": "zya", "ぢゅ": "zyu", "ぢょ": "zyo",
}

_MACRON = {"a": "ā", "i": "ī", "u": "ū", "e": "ē", "o": "ō"}


def _kata_to_hira(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _tokenize(hira: str):
    i, n = 0, len(hira)
    while i < n:
        ch = hira[i]
        if ch == SOKUON:
            yield ("sokuon", None)
            i += 1
            continue
        if ch == PROLONG:
            yield ("prolong", None)
            i += 1
            continue
        if i + 1 < n and hira[i + 1] in SMALL_Y:
            yield ("syl", ch + hira[i + 1])
            i += 2
            continue
        yield ("syl", ch)
        i += 1


def _syl_romaji(kana: str, style: str) -> str:
    if style == "kunrei":
        if kana in _KUNREI_YOUON:
            return _KUNREI_YOUON[kana]
        if kana in _KUNREI_MORA:
            return _KUNREI_MORA[kana]
    if kana in _HEPBURN_YOUON:
        return _HEPBURN_YOUON[kana]
    if kana in _HEPBURN:
        return _HEPBURN[kana]
    if kana in SMALL_V:
        return SMALL_V[kana]
    return kana


def _apply_n_apostrophe(syllables):
    out = []
    for idx, syl in enumerate(syllables):
        out.append(syl)
        if syl == "n" and idx + 1 < len(syllables):
            nxt = syllables[idx + 1]
            if nxt and nxt[0] in "aiueoy":
                out.append("'")
    return out


def _join(tokens, style: str) -> str:
    syllables = []
    geminate = False
    for kind, val in tokens:
        if kind == "sokuon":
            geminate = True
            continue
        if kind == "prolong":
            if syllables:
                prev = syllables[-1]
                if prev and prev[-1] in "aiueo" and style == "hepburn_macron":
                    syllables[-1] = prev[:-1] + _MACRON[prev[-1]]
            continue
        rom = _syl_romaji(val, style)
        if geminate and rom:
            if rom.startswith("ch"):
                rom = "t" + rom
            elif rom[0] not in "aiueo":
                rom = rom[0] + rom
            geminate = False
        syllables.append(rom)
    syllables = _apply_n_apostrophe(syllables)
    return _collapse_long_vowels("".join(syllables), style)


def _collapse_long_vowels(text: str, style: str) -> str:
    long_o = "ō" if style == "hepburn_macron" else "o"
    long_u = "ū" if style == "hepburn_macron" else "u"
    out = []
    i, n = 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two in ("ou", "oo"):
            out.append(long_o)
            i += 2
            continue
        if two == "uu":
            out.append(long_u)
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def to_romaji(kana: str, style: str = "hepburn_macron") -> str:
    """Convert a kana string to romaji. style in
    {hepburn_macron, hepburn_plain, kunrei}."""
    if style not in ("hepburn_macron", "hepburn_plain", "kunrei"):
        raise ValueError(f"unknown style: {style}")
    hira = _kata_to_hira(kana.strip())
    if not hira:
        return ""
    return _join(list(_tokenize(hira)), style)


def romaji_variants(kana: str) -> dict:
    """Return all three renderings plus a deduplicated query list."""
    macron = to_romaji(kana, "hepburn_macron")
    plain = to_romaji(kana, "hepburn_plain")
    kunrei = to_romaji(kana, "kunrei")
    ordered = []
    for v in (macron, plain, kunrei):
        if v and v not in ordered:
            ordered.append(v)
    return {
        "hepburn_macron": macron,
        "hepburn_plain": plain,
        "kunrei": kunrei,
        "all": ordered,
    }
