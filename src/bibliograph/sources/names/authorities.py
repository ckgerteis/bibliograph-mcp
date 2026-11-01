"""Web NDL Authorities lookup for personal names.

Queries the National Diet Library's Web NDL Authorities SPARQL endpoint for
personal-name authority records: the established heading, its katakana
transcription, life dates and NDLA identifier. This is catalogue-verified
metadata that no sibling source (cinii, jstage, openalex, ndl) provides, so
it stays live here after the cross-service scholar-finder fan-out (CiNii,
KAKEN, NRID, J-STAGE) was removed as redundant with those sibling sources.

Schema confirmed against the live endpoint (NDLA SPARQL JSON) on 2026-06-30.
"""

from __future__ import annotations

import re
import time

import requests

_UA = "bibliograph-mcp (names; +https://github.com/ckgerteis/bibliograph-mcp)"
_TIMEOUT = 30

NDL_SPARQL_ENDPOINT = "https://id.ndl.go.jp/auth/ndla/sparql"
NDL_PERSONAL_SCHEME = "http://id.ndl.go.jp/auth#personalNames"


def _get(url: str, **kw):
    """requests.get with ONE retry on a dropped connection (J-STAGE reset one
    mid-search on 23 Sep 2026). Never retries a refusal, a timeout or an HTTP
    error status: a throttling service must not be pressed (NDL stalls rather
    than answering 429)."""
    try:
        return requests.get(url, **kw)
    except (requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError) as exc:
        if isinstance(exc, requests.exceptions.ConnectTimeout):
            raise
        time.sleep(1.0)
        return requests.get(url, **kw)


def _error_marker(source: str, exc: Exception) -> dict:
    return {"source": source, "error": f"{type(exc).__name__}: {exc}"}


# ------------------------------ Web NDL Authorities ------------------------------

NDL_MAX_KANJI_TERMS = 6
NDL_MAX_KANA_TERMS = 3

_NDL_DATE_RE = re.compile(r",\s*(\d{3,4})\s*-\s*(\d{3,4})?\s*$")


def _ndl_query(needles: list[str], kana: list[str], limit: int) -> str:
    """Build a SPARQL query: personal-name authorities whose label or reading
    contains one of the kanji needles (or kana readings)."""
    terms = []
    for n in needles:
        safe = n.replace('"', "")
        terms.append(f'CONTAINS(STR(?label), "{safe}")')
    for k in kana:
        safe = k.replace('"', "")
        terms.append(f'CONTAINS(STR(?yomi), "{safe}")')
    filt = " || ".join(terms) if terms else "false"
    return f"""
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX xl: <http://www.w3.org/2008/05/skos-xl#>
PREFIX ndl: <http://ndl.go.jp/dcndl/terms/>
SELECT DISTINCT ?uri ?label ?yomi ?viaf WHERE {{
  ?uri skos:inScheme <{NDL_PERSONAL_SCHEME}> ;
       rdfs:label ?label .
  OPTIONAL {{ ?uri xl:prefLabel ?pl . ?pl ndl:transcription ?yomi . }}
  OPTIONAL {{ ?uri skos:exactMatch ?viaf . FILTER(CONTAINS(STR(?viaf), "viaf.org")) }}
  FILTER ( {filt} )
}} LIMIT {limit}
"""


def _to_katakana(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if 0x3041 <= ord(c) <= 0x3096 else c for c in s)


def _ndl_forms(variants: dict) -> tuple[list[str], list[str]]:
    """Needles shaped the way NDL Authorities writes a personal name.

    NDLA labels are "姓, 名, 生年-" and transcriptions "セイ, メイ" in
    katakana, so a joined full name ("吉澤誠一郎", "よしざわせいいちろう") never
    matches by CONTAINS. For full names, split on a known surname writing and
    use the comma form; for a surname-only query the bare surname is already a
    substring of the label. Capped: the query travels in a GET URL.
    """
    kanji = list(variants.get("kanji") or [])
    surnames = sorted(variants.get("surname_kanji") or [], key=len, reverse=True)
    needles: list[str] = []
    if variants.get("name_shape") == "full":
        for k in kanji:
            s = next((x for x in surnames if k.startswith(x) and len(k) > len(x)), None)
            if s is None and len(k) >= 3:
                s = k[:2]  # most surnames are two characters; a lead, not a fact
            if s:
                form = f"{s}, {k[len(s):]}"
                if form not in needles:
                    needles.append(form)
    else:
        needles = list(kanji)
    kana: list[str] = []
    for pair in variants.get("kana_split") or []:
        if len(pair) == 2:
            form = f"{_to_katakana(pair[0])}, {_to_katakana(pair[1])}"
            if form not in kana:
                kana.append(form)
    if variants.get("name_shape") != "full":
        kana = [_to_katakana(k) for k in (variants.get("kana") or [])]
    return needles[:NDL_MAX_KANJI_TERMS], kana[:NDL_MAX_KANA_TERMS]


def search_ndl_authorities(variants: dict, max_results: int = 40) -> list[dict]:
    """Query Web NDL Authorities (SPARQL) for matching personal-name records.

    Reads the established label (which embeds birth/death years), the kana
    transcription, the NDLA id, and any VIAF exactMatch.
    """
    # Cap the OR-terms: the query travels in a GET URL, and ~130 percent-encoded
    # CJK terms overflowed it (HTTP 414). The bundle's lists are ranked, so the
    # head is what matters.
    needles, kana = _ndl_forms(variants)
    if not needles and not kana:
        return []

    query = _ndl_query(needles, kana, max(1, min(max_results, 200)))
    try:
        r = _get(NDL_SPARQL_ENDPOINT,
                 params={"query": query, "output": "json"},
                 timeout=_TIMEOUT + 15, headers={"User-Agent": _UA})
        r.raise_for_status()
        bindings = r.json().get("results", {}).get("bindings", [])
    except Exception as exc:  # noqa: BLE001
        return [_error_marker("ndl", exc)]

    by_uri: dict[str, dict] = {}
    for b in bindings:
        uri = b.get("uri", {}).get("value")
        if not uri:
            continue
        label = b.get("label", {}).get("value")
        cand = by_uri.get(uri)
        if cand is None:
            birth = death = None
            m = _NDL_DATE_RE.search(label or "")
            if m:
                birth, death = m.group(1), m.group(2)
            ndla_id = uri.rstrip("/").rsplit("/", 1)[-1]
            cand = {
                "source": "ndl",
                "kanji_name": re.sub(r",\s*(\d{3,4})\s*-\s*(\d{3,4})?\s*$", "",
                                     label or "").strip() if label else None,
                "reading": b.get("yomi", {}).get("value"),
                "affiliation": None,
                "field": None,
                "birth": birth,
                "death": death,
                "works": [],
                "ids": {"ndla": ndla_id,
                        "viaf": b.get("viaf", {}).get("value"),
                        "doi": []},
                "match_basis": {
                    "source": "ndl",
                    "key": "authority-label",
                    "value": label,
                    "confidence": "high" if (birth or death) else "moderate",
                },
            }
            by_uri[uri] = cand
        else:
            if not cand["reading"] and b.get("yomi", {}).get("value"):
                cand["reading"] = b["yomi"]["value"]
            if not cand["ids"]["viaf"] and b.get("viaf", {}).get("value"):
                cand["ids"]["viaf"] = b["viaf"]["value"]
    return list(by_uri.values())
