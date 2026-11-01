"""Full-name matching shared by the sources.

First used by jmnedict's find_scholar, now available to cinii, jstage,
openalex and semantic_scholar for deciding whether an author/creator string
on a record is the person a caller is searching for.
"""

from __future__ import annotations

import re

from .sources.names.names import SURNAME_VARIANTS, fold_char
from .sources.names.db import normalize_romaji


# ------------------------------- shared helpers -------------------------------

def _canon_surname_char(ch: str) -> str:
    """Map an interchangeable character (澤/沢, 眞/真 ...) to its representative."""
    return fold_char(ch)


def canonical_name_key(kanji_or_text: str | None) -> str | None:
    """A clustering key for a name: strip separators, fold surname variants.

    斎藤敏一 / 齋藤 敏一 / 斉藤, 敏一 all fold to the same key so the three
    interchangeable surname writings cluster as one person.
    """
    if not kanji_or_text:
        return None
    stripped = re.sub(r"[\s,、・]+", "", kanji_or_text)
    return "".join(_canon_surname_char(c) for c in stripped) or None


def _kanji_needles(variants: dict) -> list[str]:
    """The kanji strings worth matching against author/label fields."""
    needles: list[str] = []
    for k in variants.get("kanji", []):
        if k and k not in needles:
            needles.append(k)
    return needles


def _name_keys(variants: dict) -> list[str]:
    """Search strings for a name, best first: kanji writings; else, for a full
    name, the spaced romaji (never a lone surname token, which searched CiNii
    for "kang" alone); else kana; else any romaji."""
    if variants.get("kanji"):
        return list(variants["kanji"])
    plain = variants.get("hepburn_plain") or []
    spaced = [v for v in plain if " " in v]
    if variants.get("name_shape") == "full" and spaced:
        return spaced
    return list(variants.get("kana") or []) or list(plain)


def _has_kanji(s: str | None) -> bool:
    return bool(s) and any(0x3400 <= ord(c) <= 0x9FFF or 0xF900 <= ord(c) <= 0xFAFF
                           for c in s)


def _is_kana_text(s: str) -> bool:
    t = re.sub(r"[\s,、・＝=]+", "", s or "")
    return bool(t) and all(0x3040 <= ord(c) <= 0x30FF for c in t)


def _romaji_tokens(s: str) -> frozenset:
    return frozenset(normalize_romaji(t) for t in re.split(r"[\s,]+", s or "") if t)


def matches_name(name: str, variants: dict) -> bool:
    """True if an author/creator string is the person being searched for.

    For a full-name query (``name_shape == "full"``) the creator must equal one
    of the full-name writings, surname variants folded -- a shared first
    character is not enough, which is what let every co-author of a
    same-surname stranger into the candidate list. For a surname-only query
    the creator must begin with one of the surname writings. Romaji creators
    ("YOSHIZAWA Seiichiro", "Seiichiro Yoshizawa") match on the token set in
    either order; kana creators on the joined reading.
    """
    if not name:
        return False
    shape = variants.get("name_shape", "single")
    needles = _kanji_needles(variants)
    if _has_kanji(name):
        if not needles:
            # Nothing to check a kanji byline against (a Korean or Chinese name
            # given in romaji, or a name JMnedict lacks). Accepting every kanji
            # author here let "Kang Sang-jung" return 45 strangers; the person is
            # reached instead through the researcher directory and NDL by
            # reading, and then searched under that kanji in the follow-up pass.
            return False
        key = canonical_name_key(name) or ""
        keys = {canonical_name_key(n) for n in needles}
        if shape == "full":
            return key in keys
        return any(k and key.startswith(k) for k in keys)
    if _is_kana_text(name):
        joined = re.sub(r"[\s,、・＝=]+", "", name)
        kana = set(variants.get("kana") or [])
        if not kana:
            return True
        return joined in kana if shape == "full" else any(joined.startswith(k) for k in kana)
    toks = _romaji_tokens(name)
    plain = variants.get("hepburn_plain") or []
    fulls = [v for v in plain if " " in v]
    if shape == "full" and fulls:
        return any(_romaji_tokens(v) == toks for v in fulls)
    singles = {normalize_romaji(v) for v in plain if " " not in v}
    return bool(toks & singles) if singles else True


def matches_surname(name: str, needles: list[str]) -> bool:
    return matches_name(name, {"kanji": needles, "name_shape": "single"})


# ------------------------- author_match: is this the same person? -------------------------
#
# matches_name() above answers a yes/no question for the jmnedict-backed name
# machinery, which always has a resolved bundle of kanji/kana/romaji variants
# to check against. The sources this function serves (jstage author search,
# cinii_search_researchers and cinii article/book search when an author is
# given, oa_search_authors, s2_search_authors) have no such bundle: the
# caller supplied one plain string and the source's own author/person search
# is loose (substring, fuzzy, or both), so the tool must grade *how well* the
# candidate matches the query, not just admit or reject it. The server does
# not filter or reorder on this grade — mediation.py's rule that a tool "may
# show its choices; it may not make them on the scholar's behalf" — it is
# reported on each item as extra.name_match for the caller to read.

import unicodedata

_ZENKAKU_SPACE = "　"


def _has_cjk_char(s: str) -> bool:
    return any(
        0x3040 <= ord(c) <= 0x30FF  # kana
        or 0x3400 <= ord(c) <= 0x9FFF  # kanji (incl. ext. A)
        or 0xF900 <= ord(c) <= 0xFAFF  # kanji compatibility
        for c in s
    )


def _has_latin_letter(s: str) -> bool:
    return any(("a" <= c.lower() <= "z") for c in s)


def _script_bucket(s: str) -> str:
    """'cjk', 'latin', 'mixed' or 'none' (nothing to classify) for one string."""
    if not s or not s.strip():
        return "none"
    cjk = _has_cjk_char(s)
    latin = _has_latin_letter(s)
    if cjk and latin:
        return "mixed"
    if cjk:
        return "cjk"
    if latin:
        return "latin"
    return "none"


def _cjk_norm(s: str) -> str:
    """Whitespace (ASCII and U+3000) stripped, old/new kanji forms folded."""
    stripped = re.sub(rf"[\s{_ZENKAKU_SPACE}]+", "", s)
    return "".join(fold_char(c) for c in stripped)


def _latin_token_set(s: str) -> frozenset:
    """Case-insensitive token set: commas are separators, hyphens are joins
    (Sang-jung -> sangjung, not two tokens), macrons fold to base vowels."""
    t = s.replace(",", " ").replace("-", "")
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # drop macrons/diacritics
    return frozenset(tok.lower() for tok in re.split(r"\s+", t.strip()) if tok)


def author_match(query: str, author: str) -> str:
    """Grade how well an author/creator string matches a person the caller
    named, without ever admitting or excluding it -- "exact", "partial" or
    "none".

    Kanji/kana (either string, or both): compared after stripping all
    whitespace and folding old/new character forms with fold_char. "exact" is
    equality; "partial" is one string containing the other (吉田 vs 吉田太郎).

    Latin script (both strings): compared as case-insensitive token sets,
    order-independent, with commas and hyphens ignored and macrons folded to
    their base vowel (Seiichirō == Seiichiro). "exact" is the same set;
    "partial" is one set a proper subset of the other, or any nonempty
    overlap short of that ("surname-only overlap") -- e.g. "Tanaka Akira" vs
    "Tanaka Jiro" share only "tanaka". Decision, documented here because the
    task that added this function asked for one: "Tanaka Akira" vs "Tanaka
    Akihiko" is graded "partial", not "none" -- the shared surname token is a
    real, if weak, signal that the source's loose author search may have
    found a relative or a near-miss transliteration rather than a stranger,
    and "none" is reserved for candidates sharing no token at all.

    Mixed scripts, or one string kanji/kana and the other Latin: "none". A
    romaji query cannot confirm a kanji name (or vice versa) by string
    comparison alone -- that confirmation needs the jmnedict-backed name
    machinery in matches_name(), not this function.
    """
    if not query or not author:
        return "none"
    qb, ab = _script_bucket(query), _script_bucket(author)
    if qb == "none" or ab == "none" or qb == "mixed" or ab == "mixed" or qb != ab:
        return "none"
    if qb == "cjk":
        qn, an = _cjk_norm(query), _cjk_norm(author)
        if not qn or not an:
            return "none"
        if qn == an:
            return "exact"
        if qn in an or an in qn:
            return "partial"
        return "none"
    # qb == ab == "latin"
    qt, at = _latin_token_set(query), _latin_token_set(author)
    if not qt or not at:
        return "none"
    if qt == at:
        return "exact"
    if qt & at:
        return "partial"
    return "none"


_MATCH_RANK = {"none": 0, "partial": 1, "exact": 2}


def best_author_match(query: str, candidates: list) -> str:
    """The best (highest-ranked) author_match over several candidate strings,
    e.g. an item's several authors, or a person record's display name plus
    its alternate names. "none" if there are no non-empty candidates."""
    best = "none"
    for c in candidates or []:
        if not c:
            continue
        m = author_match(query, c)
        if _MATCH_RANK[m] > _MATCH_RANK[best]:
            best = m
        if best == "exact":
            break
    return best
