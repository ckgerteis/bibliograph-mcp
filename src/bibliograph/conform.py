"""Hold every item and facet to the types tests/response-schema.json declares.

The mutation fuzz of 7 October 2026 fed each source wrong-typed upstream values
- a number where a URL belongs, a boolean year, a list as a page range - and
found them passing straight through make_item into the envelope, which then
failed the family schema. The real services rarely send such values, but an
envelope is the record of a search, so it must validate whatever arrives.

The rule is narrow on purpose: a value already of the declared type is never
touched. Only a value of the wrong type is replaced - an integer becomes its
digits where a string is declared, a four-digit string becomes an integer where
a year is declared, and anything else becomes null. Nothing is invented, and a
null says plainly that the source sent something unusable.

bibliograph's own module, outside mediation.py (which stays byte-identical with
korea-scholarship-mcp's copy).
"""

from __future__ import annotations

import re
from typing import Any

_TITLE = ("ko", "ja", "en", "romanized")
_SOURCE_STR = ("journal_ko", "journal_ja", "journal_en", "volume", "issue", "pages", "holding_org")
_IDS = ("doi", "crid", "naid", "kci_id", "uci", "issn", "oai_id", "url_ko", "url_ja", "url_en", "fulltext_url")
_AUTHOR_STR = ("ko", "ja", "en", "romanized", "name", "name_en", "affiliation", "orcid")


def _str(v: Any) -> Any:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return None


def _int(v: Any) -> Any:
    if v is None or (isinstance(v, int) and not isinstance(v, bool)):
        return v
    if isinstance(v, str) and re.fullmatch(r"\s*\d{1,9}\s*", v):
        return int(v)
    return None


def _year(v: Any) -> Any:
    if v is None or (isinstance(v, int) and not isinstance(v, bool)):
        return v
    if isinstance(v, str) and re.fullmatch(r"\s*\d{4}\s*", v):
        return int(v)
    return None


def _strs(d: Any, keys: tuple) -> None:
    if isinstance(d, dict):
        for k in keys:
            if k in d:
                d[k] = _str(d[k])


def item(it: Any) -> Any:
    if not isinstance(it, dict):
        return it
    _strs(it.get("title"), _TITLE)
    src = it.get("source")
    _strs(src, _SOURCE_STR)
    if isinstance(src, dict) and "year" in src:
        src["year"] = _year(src["year"])
    _strs(it.get("ids"), _IDS)
    authors = it.get("authors")
    if isinstance(authors, list):
        kept = []
        for a in authors:
            if isinstance(a, dict):
                _strs(a, _AUTHOR_STR)
                kept.append(a)
            elif isinstance(a, str):
                kept.append(a)
            elif _str(a) is not None:
                kept.append(_str(a))
        it["authors"] = kept
    elif "authors" in it:
        it["authors"] = []
    if not isinstance(it.get("extra"), dict):
        it["extra"] = {}
    return it


def envelope(env: Any) -> Any:
    if not isinstance(env, dict):
        return env
    for it in env.get("items") or []:
        item(it)
    facets = env.get("facets")
    if isinstance(facets, dict):
        for f in facets.values():
            if not isinstance(f, dict):
                continue
            f["other_count"] = _int(f.get("other_count"))
            for b in f.get("buckets") or []:
                if isinstance(b, dict):
                    b["label"] = _str(b.get("label"))
                    b["count"] = _int(b.get("count"))
    return env
