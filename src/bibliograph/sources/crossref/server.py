"""
Crossref source for bibliograph (v0.1.0)
===================================
Metadata that publishers deposit when they register DOIs with Crossref, read
through the public REST API (https://api.crossref.org). No key is needed.

Why it is here (1 Nov 2026): OpenAlex now charges per call beyond a free daily
dollar and Semantic Scholar allows one request a second on a key, so DOI
lookups and citation matching are routed here instead, at no cost.

Access. Crossref sorts callers into pools. Without identification a caller is
in the public pool; with a contact address (`mailto`) it is in the polite pool;
a Metadata Plus token buys a third. Limits are set by Crossref and change with
load, and each response states them in `x-rate-limit-limit` and
`x-rate-limit-interval` (measured 1 Nov 2026: public 1 request per second, one
at a time; polite 3 per second, three at a time). This module serialises its
requests and spaces them by the interval those headers last gave.

    CROSSREF_MAILTO       contact address for the polite pool (falls back to
                          OPENALEX_EMAIL when unset)
    CROSSREF_PLUS_TOKEN   optional Metadata Plus token

What it holds, and what it does not. Crossref has what publishers deposited
with a Crossref DOI: most English-language journals and many university and
commercial presses. It does not have most Japanese-language scholarship, which
has no DOI or a JaLC DOI, nor books from presses that register none. An absence
here is not an absence from the literature.

How it matches. A multi-word query matches records containing ANY of its
words, ranked by relevance, so `total-results` for "bosozoku Japan" was
1,184,944 while "bosozoku" alone was 4 (1 Nov 2026). The count is the union,
not a literature; only the top of the ranking means anything. Crossref also
tokenises Chinese, Japanese and Korean text poorly.

Two lookups beyond Crossref. A DOI Crossref does not hold is put to doi.org's
registration-agency lookup (free, no key), which says whether the DOI belongs
to another agency (JaLC, DataCite, ...) or to none: a DOI no agency has is a
finding in citation checking, while "not in Crossref" is not. And Crossref's
links point to publishers, not to open copies, so open-access locations are
filled from OpenAlex: a free single-record lookup for one DOI, or one list
call ($0.0001, 1 Nov 2026) for a page of results. Either lookup failing leaves
the Crossref answer intact and says so.

Licence: Crossref says almost none of the metadata is under copyright and it
may be used for any purpose; some abstracts may be the publisher's or author's.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import sys
import time
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids
from ..openalex import server as _OA

__version__ = "0.1.0"

# ==============================================================================
# Configuration
# ==============================================================================

API_BASE = "https://api.crossref.org"
MAILTO = os.environ.get("CROSSREF_MAILTO", "") or os.environ.get("OPENALEX_EMAIL", "")
PLUS_TOKEN = os.environ.get("CROSSREF_PLUS_TOKEN", "")
TIMEOUT = 30.0
ATTRIBUTION = ("Metadata via the Crossref REST API (https://www.crossref.org), as deposited "
               "by publishers. Crossref states the metadata may be used for any purpose; "
               "some abstracts may be under the publisher's or author's copyright.")
COVERAGE_NOTE = ("Crossref holds what publishers deposited with a Crossref DOI. Most "
                 "Japanese-language scholarship (no DOI, or a JaLC DOI) and books from presses "
                 "that register none are absent: an absence here is not an absence from the "
                 "literature. Use CiNii, J-STAGE and NDL for Japanese-language work.")

MODE_SEARCH = "relevance_ranked_any_term"
MODE_LOOKUP = "identifier_lookup"
QUERY_MAX = 2000
ROWS_MAX = 100          # Crossref allows 1,000; each record is text the client must read
OFFSET_MAX = 10000      # Crossref refuses a deeper offset with 400 (checked 1 Nov 2026)

# Fields asked for in list requests. `select` keeps the response small; every
# name here was accepted by /works on 1 Nov 2026 (tests/crossref pins the list). Lookups by DOI return the whole record.
SELECT = ",".join((
    "DOI", "title", "subtitle", "author", "editor", "container-title", "volume", "issue",
    "page", "issued", "published", "ISSN", "ISBN", "URL", "type", "publisher",
    "abstract", "is-referenced-by-count", "score", "license",
))  # `language` is not selectable on /works (400, 1 Nov 2026); lookups by DOI still carry it
SORTS = {"relevance": "score", "published": "published", "cited": "is-referenced-by-count"}
_SECRET_PARAMS = ("mailto",)
RA_BASE = "https://doi.org/ra"
OA_SELECT = "doi,open_access,best_oa_location"
_OA_UNSAFE = re.compile(r"[|,]")  # would split OpenAlex's OR-filter


def _silence_http_logging() -> None:
    """stdout carries JSON-RPC; httpx logs every URL at INFO, mailto included."""
    for name in ("httpx", "httpcore", "httpx._client"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "stream", None) is sys.stdout:
            root.removeHandler(h)
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stderr))


_silence_http_logging()

try:
    mcp = _MCPServer("crossref_mcp", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("crossref_mcp")


# ==============================================================================
# HTTP client: serialised, spaced by the interval Crossref last stated
# ==============================================================================

_lock: Optional[asyncio.Lock] = None
_lock_loop: Any = None
_last_call = 0.0
_spacing = 1.0  # seconds between requests; replaced from response headers


def _get_lock() -> asyncio.Lock:
    """One lock per event loop: FastMCP runs one loop, tests run several."""
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


def _seconds(v: Optional[str]) -> Optional[float]:
    """'1s' -> 1.0, '500ms' -> 0.5, '2' -> 2.0; anything else None."""
    if not v:
        return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s|m)?\s*", v)
    if not m:
        return None
    n = float(m.group(1))
    return n / 1000 if m.group(2) == "ms" else n * 60 if m.group(2) == "m" else n


def _learn_spacing(headers) -> None:
    global _spacing
    try:
        limit = float(headers.get("x-rate-limit-limit"))
    except (TypeError, ValueError):
        return
    interval = _seconds(headers.get("x-rate-limit-interval"))
    if limit > 0 and interval:
        _spacing = min(max(interval / limit, 0.05), 10.0)


def _redact(text: str) -> str:
    for secret in (MAILTO, PLUS_TOKEN):
        if secret:
            for form in {secret, quote(secret, safe=""), quote(secret, safe="@")}:
                text = text.replace(form, "[redacted]")
    return text


def _headers() -> dict:
    ua = f"bibliograph-mcp crossref/{__version__} (https://github.com/ckgerteis)"
    if MAILTO:
        ua += f" mailto:{MAILTO}"
    h = {"User-Agent": ua, "Accept": "application/json"}
    if PLUS_TOKEN:
        h["Crossref-Plus-API-Token"] = f"Bearer {PLUS_TOKEN}"
    return h


async def _cr_request(path: str, params: Optional[Dict[str, Any]] = None
                      ) -> tuple[Optional[Any], Optional[dict]]:
    """Call one endpoint. Returns (message, error_diag); exactly one is non-None.
    The caller's `params` is never mutated and never carries the contact address."""
    global _last_call
    sent: Dict[str, Any] = dict(params or {})
    if MAILTO:
        sent["mailto"] = MAILTO
    async with _get_lock():
        wait = _spacing - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                         headers=_headers()) as client:
                resp = await client.get(f"{API_BASE}/{path}", params=sent)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            return None, M.diag(
                "error", "TRANSPORT_ERROR",
                f"Could not reach Crossref: {_redact(type(exc).__name__ + ': ' + str(exc))[:300]}",
                "The result of this search is unknown, not empty. Retry before "
                "concluding anything about the literature.",
            )
        finally:
            _last_call = time.monotonic()
        _learn_spacing(resp.headers)

    if resp.status_code == 404:
        return None, M.diag("warning", "NOT_FOUND",
                            "Crossref has no record for this DOI.",
                            "Check the DOI. A DOI registered with another agency (JaLC, "
                            "DataCite, KISTI, CNKI) is not in Crossref; try CiNii or J-STAGE "
                            "for a JaLC DOI.")
    if resp.status_code == 429:
        pool = ("Metadata Plus" if PLUS_TOKEN else "polite" if MAILTO else "public")
        return None, M.diag(
            "error", "RATE_LIMITED",
            f"Crossref answered 429: the {pool} pool's limit of "
            f"{resp.headers.get('x-rate-limit-limit', '?')} request(s) per "
            f"{resp.headers.get('x-rate-limit-interval', '?')} was exceeded.",
            "The result of this search is unknown, not empty. Wait and retry."
            + ("" if MAILTO else " Setting CROSSREF_MAILTO moves requests to the faster polite pool."),
        )
    if resp.status_code == 403:
        return None, M.diag("error", "API_ERROR",
                            "Crossref answered 403: requests from this address are blocked.",
                            "Crossref blocks callers that ignore its limits; contact "
                            "support@crossref.org. The result is unknown, not empty.")
    try:
        body = resp.json()
    except ValueError:
        body = None
    if resp.status_code >= 400:
        said = ""
        if isinstance(body, dict) and isinstance(body.get("message"), list):
            said = "; ".join(str(m.get("message", m)) if isinstance(m, dict) else str(m)
                             for m in body["message"][:2])
        else:
            said = resp.text
        return None, M.diag("error", "API_ERROR",
                            f"Crossref answered {resp.status_code}: {_redact(said)[:300]}", None)
    if not (isinstance(body, dict) and body.get("status") == "ok" and "message" in body):
        return None, M.diag(
            "error", "API_ERROR",
            "Crossref answered 200 with a body that is not an ok message.",
            "The result of this search is unknown, not empty. Retry.",
        )
    return body["message"], None


# ==============================================================================
# Record builder
# ==============================================================================

_TAG = re.compile(r"<[^>]+>")


def _clean(s: Any) -> Optional[str]:
    """Crossref titles carry markup (<i>, <jats:p>) and HTML entities (&amp;)."""
    if not isinstance(s, str):
        return None
    out = re.sub(r"\s+", " ", html.unescape(_TAG.sub("", s))).strip()
    return out or None


def _first(v: Any) -> Optional[str]:
    if isinstance(v, list):
        for x in v:
            c = _clean(x)
            if c:
                return c
        return None
    return _clean(v)


def _year(w: dict) -> Optional[int]:
    for key in ("issued", "published", "published-print", "published-online"):
        try:
            y = (w.get(key) or {})["date-parts"][0][0]
        except (KeyError, IndexError, TypeError):
            continue
        if isinstance(y, int) and not isinstance(y, bool) and 1000 <= y <= 2100:
            return y
    return None


def _place_title(text: Optional[str], language: Optional[str]) -> dict:
    """Same rule as the openalex source: a declared language decides; otherwise
    kana or hangul decide ja or ko, Latin goes to `en`, and a han-only title is
    left untyped (extra.title keeps it) rather than guessed."""
    out = {"title_ja": None, "title_ko": None, "title_en": None}
    if not text:
        return out
    script = M.detect_script(text)
    if language == "ja" or (not language and script in ("kana", "han_kana")):
        out["title_ja"] = text
    elif language == "ko" or (not language and script in ("hangul", "han_hangul")):
        out["title_ko"] = text
    elif script == "latin":
        out["title_en"] = text
    return out


def _person(p: dict) -> dict:
    given, family = _clean(p.get("given")), _clean(p.get("family"))
    if family and given:
        cjk = M.detect_script(family + given) != "latin"
        name = f"{family}{given}" if cjk else f"{given} {family}"
    else:
        name = family or given or _clean(p.get("name"))
    affs = [_clean(a.get("name")) for a in (p.get("affiliation") or []) if isinstance(a, dict)]
    orcid = p.get("ORCID")
    return {
        "name": name,
        "family": family,
        "given": given,
        "orcid": orcid if isinstance(orcid, str) else None,
        "affiliation": "; ".join(a for a in affs if a) or None,
    }


def _abstract(w: dict) -> Optional[str]:
    text = _clean(w.get("abstract"))
    if not text:
        return None
    text = re.sub(r"^(Abstract|ABSTRACT)\s*", "", text)
    return text[:400] + "…" if len(text) > 400 else text


def _item_from_work(w: dict, matched_in: str) -> dict:
    title = _first(w.get("title"))
    language = w.get("language") if isinstance(w.get("language"), str) else None
    people = [p for p in (w.get("author") or []) if isinstance(p, dict)]
    editors = [p for p in (w.get("editor") or []) if isinstance(p, dict)]
    issns = [i for i in (w.get("ISSN") or []) if isinstance(i, str)]
    isbns = [i for i in (w.get("ISBN") or []) if isinstance(i, str)]
    doi = w.get("DOI")
    if not isinstance(doi, str) or not doi.strip():
        raise ValueError("record has no DOI")
    licences = [lc.get("URL") for lc in (w.get("license") or [])
                if isinstance(lc, dict) and isinstance(lc.get("URL"), str)]
    return M.make_item(
        **_place_title(title, language),
        authors=[_person(p) for p in people[:12]],
        journal_en=_first(w.get("container-title")),
        volume=_clean(w.get("volume")),
        issue=_clean(w.get("issue")),
        pages=_clean(w.get("page")),
        year=_year(w),
        doi=doi.strip().lower(),
        issn=issns[0] if issns else None,
        url_en=w.get("URL") if isinstance(w.get("URL"), str) else f"https://doi.org/{doi}",
        fulltext_url=None,  # Crossref links are publisher links, not open full text
        matched_in=matched_in,
        record_type=w.get("type") if isinstance(w.get("type"), str) else "unknown",
        extra={
            "title": title,
            "subtitle": _first(w.get("subtitle")),
            "language": language,
            "publisher": _clean(w.get("publisher")),
            "issns": issns,
            "isbns": isbns,
            "editors": [_person(p)["name"] for p in editors[:6]],
            "authors_total": len(people),
            "cited_by_count": w.get("is-referenced-by-count"),
            "score": w.get("score"),
            "license_urls": licences[:3],
            "abstract": _abstract(w),
        },
    )


# ==============================================================================
# Envelope assembly
# ==============================================================================

def _count(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, str) and v.strip().isdecimal():
        return int(v.strip())
    return None


def _build_all(records: list, matched_in: str) -> tuple[list[dict], list[str]]:
    items, bad = [], []
    for pos, rec in enumerate(records, 1):
        try:
            if not isinstance(rec, dict):
                raise TypeError("record is not an object")
            items.append(_item_from_work(rec, matched_in))
        except Exception:  # noqa: BLE001
            rid = rec.get("DOI") if isinstance(rec, dict) else None
            bad.append(f"#{pos}" + (f" ({rid[:100]})" if isinstance(rid, str) and rid else ""))
    return items, bad


def _envelope(*, operation: str, term: str, params: dict, matching_mode: str,
              data: Optional[Any], err: Optional[dict], matched_in: str,
              single: bool = False, extra_diags: Optional[list] = None,
              oa: Optional[dict] = None) -> str:
    items: list[dict] = []
    bad: list[str] = []
    total, start, n = 0, 1, 0
    ds: list[dict] = [err] if err else []
    if err:
        pass
    elif single:
        if isinstance(data, dict) and isinstance(data.get("DOI"), str):
            n = 1
            items, bad = _build_all([data], matched_in)
            total = len(items)
        else:
            ds.append(M.diag("error", "API_ERROR",
                             "Crossref answered with something other than a work record.",
                             "Do not treat the DOI as absent; retry."))
    elif not (isinstance(data, dict) and isinstance(data.get("items"), list)):
        ds.append(M.diag("error", "API_ERROR",
                         "Crossref answered with something other than a list of works.",
                         "The result of this search is unknown, not empty. Retry."))
    else:
        n = len(data["items"])
        items, bad = _build_all(data["items"], matched_in)
        total = _count(data.get("total-results"))
        if total is None:
            total = len(items)
        start = (_count(params.get("offset")) or 0) + 1

    if oa:
        for it in items:
            hit = oa.get(it["ids"]["doi"] or "")
            if hit:
                it["ids"]["fulltext_url"] = hit.get("url")
                it["extra"]["oa_status"] = hit.get("status")
                it["extra"]["oa_license"] = hit.get("license")
                it["extra"]["oa_via"] = "openalex"
    if bad and single:
        ds.append(M.diag("error", "API_ERROR",
                         f"Crossref returned this record in a shape that could not be read ({bad[0]}).",
                         "Do not treat the record as absent; report the DOI."))
    elif bad:
        ds.append(M.diag(
            "warning", "RECORD_SHAPE_UNEXPECTED",
            f"{len(bad)} of {n} record(s) could not be read and were left out: "
            + "; ".join(bad[:10]) + ("; and more" if len(bad) > 10 else "") + ".",
            "The upstream record is malformed, not absent; look it up by DOI."))
    if not ds and not items:
        ds.append(M.diag(
            "warning", "ZERO_RESULTS",
            "No records. Crossref matched nothing for this query and filter set.",
            "Crossref holds only DOI-registered work; most Japanese-language scholarship "
            "is not in it. Try CiNii, J-STAGE or NDL."))
    if not ds:
        ds.append(M.diag("info", "OK", f"{total} record(s) reported by Crossref.", None))
    if not err and items:
        # After OK or ZERO_RESULTS is decided, so a caveat never displaces either.
        ds.extend(extra_diags or [])

    clean = {k: v for k, v in params.items() if k not in _SECRET_PARAMS and v is not None}
    env = M.build_envelope(
        server="crossref", operation=operation, input_terms=term, normalized=term,
        params=clean, matching_mode=matching_mode, total=total, start=start,
        items=items, diagnostics=ds, attribution=ATTRIBUTION,
        coverage_note=None if single else COVERAGE_NOTE,
    )
    return M.emit(_rids.finish(env))


_NORM = re.compile(r"[^0-9a-z\u3040-\u9fff\uac00-\ud7af]+")


def _same_title_diags(env_items: list[dict]) -> list[dict]:
    """Name candidates that share a title but not a type.

    A review carries the title of the book it reviews, so in Crossref it ranks
    beside the book: for Gordon's *The Evolution of Labor Relations in Japan*
    (1985) a 1986 review ranked first and the monograph second (1 Nov 2026).
    """
    def key(it):
        t = (it.get("extra") or {}).get("title") or ""
        return _NORM.sub(" ", t.lower()).strip()[:40]
    out, seen = [], {}
    for pos, it in enumerate(env_items, 1):
        k = key(it)
        if len(k) < 12:
            continue
        for k2, (pos2, typ2) in seen.items():
            if (k.startswith(k2) or k2.startswith(k)) and typ2 != it.get("record_type"):
                out.append(M.diag(
                    "warning", "SAME_TITLE_DIFFERENT_TYPE",
                    f"Candidates {pos2} ({typ2}) and {pos} ({it.get('record_type')}) share a "
                    "title but not a type; one is probably a review of the other.",
                    "Take the candidate whose type, authors and year match the reference; "
                    "a journal-article bearing a book's title is usually its review."))
                break
        seen.setdefault(k, (pos, it.get("record_type")))
    return out[:3]


def _search_diags(query: str, total: int = 0) -> list[dict]:
    """What the count means, and when the query script will match badly."""
    out = []
    if len(query.split()) > 1:
        out.append(M.diag(
            "info", "TOTAL_IS_ANY_TERM",
            "Crossref matches records containing ANY of the query's words and ranks them; "
            "result.total is that union, not a literature.",
            "Read the top of the ranking only. Narrow with author, container, year or "
            "type filters rather than by adding words."))
    if M.detect_script(query) != "latin":
        out.append(M.diag(
            "warning", "CJK_QUERY_WEAK",
            "Crossref tokenises Chinese, Japanese and Korean text poorly; a CJK query "
            "returns loosely related records.",
            "Search the Japanese title in CiNii, J-STAGE or NDL, or search Crossref by "
            "the romanised or English title, author or DOI."))
    return out


# ==============================================================================
# Beyond Crossref: the DOI's registration agency, and open-access locations
# ==============================================================================

_RA_HINTS = {
    "JaLC": "It is a Japan Link Center DOI: try jstage_get_article_by_doi for a J-STAGE "
            "article, or search CiNii or NDL by its title.",
    "DataCite": "It is a DataCite DOI (data, software, repository deposits such as Zenodo); "
                "try oa_get_work.",
}


async def _doi_agency(doi: str) -> tuple[Optional[str], Optional[str]]:
    """Ask doi.org which agency registered a DOI. Returns (agency, None),
    (None, None) when no agency has it, or (None, reason) when the lookup failed."""
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_headers()) as client:
            resp = await client.get(f"{RA_BASE}/{quote(doi, safe='/:;()')}")
        body = resp.json()
        rec = body[0] if isinstance(body, list) and body else {}
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        return None, type(exc).__name__
    if not isinstance(rec, dict):
        return None, "unreadable answer"
    if isinstance(rec.get("RA"), str) and rec["RA"].strip():
        return rec["RA"].strip(), None
    if "not exist" in str(rec.get("status", "")).lower():
        return None, None
    return None, f"unexpected answer: {str(rec)[:120]}"


def _agency_diag(doi: str, agency: Optional[str], failure: Optional[str]) -> dict:
    if failure:
        return M.diag("warning", "NOT_FOUND",
                      "Crossref has no record for this DOI, and doi.org's agency lookup "
                      f"failed ({failure}), so which agency registered it is unknown.",
                      "Check the DOI; a DOI from another agency (JaLC, DataCite, KISTI, "
                      "CNKI) is not in Crossref.")
    if agency is None:
        return M.diag("warning", "DOI_NOT_REGISTERED",
                      f"No registration agency has the DOI {doi} (doi.org: \"DOI does not exist\").",
                      "The DOI as written does not exist: check it for a typing or copying "
                      "error, and treat a reference that depends on it as unverified.")
    if agency == "Crossref":
        return M.diag("warning", "NOT_FOUND",
                      "doi.org says Crossref registered this DOI, but Crossref's API has no "
                      "record of it.",
                      "The record may be withdrawn or not yet indexed; retry later, or try "
                      "oa_get_work.")
    return M.diag("warning", "NOT_FOUND",
                  f"Crossref has no record for this DOI because it is registered with {agency}, "
                  "not Crossref. The work may well exist.",
                  _RA_HINTS.get(agency, f"Look it up through {agency} or by its title."))


def _oa_parse(rec: Any) -> Optional[tuple[str, dict]]:
    if not isinstance(rec, dict):
        return None
    doi = rec.get("doi")
    if not isinstance(doi, str):
        return None
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I).lower()
    oa = rec.get("open_access") or {}
    best = rec.get("best_oa_location") or {}
    url = oa.get("oa_url") or best.get("pdf_url") or best.get("landing_page_url")
    if not (oa.get("is_oa") and isinstance(url, str)):
        return doi, {"url": None, "status": oa.get("oa_status"), "license": None}
    return doi, {"url": url, "status": oa.get("oa_status"), "license": best.get("license")}


async def _oa_links(data: Any, single: bool) -> tuple[Optional[dict], Optional[dict]]:
    """Open-access locations for the DOIs in a Crossref answer, from OpenAlex.
    Returns (doi -> {url, status, license}, diagnostic)."""
    recs = [data] if single else (data.get("items") if isinstance(data, dict) else None)
    dois = []
    for r in recs or []:
        d = r.get("DOI") if isinstance(r, dict) else None
        if isinstance(d, str) and d.strip() and not _OA_UNSAFE.search(d):
            dois.append(d.strip().lower())
    dois = list(dict.fromkeys(dois))[:100]
    if not dois:
        return None, None
    if len(dois) == 1:
        got, err = await _OA._oa_request(f"works/doi:{quote(dois[0], safe='/:;()')}",
                                         {"select": OA_SELECT})
        found = [got] if got else []
        how = "one free single-record lookup"
    else:
        got, err = await _OA._oa_request("works", {"filter": "doi:" + "|".join(dois),
                                                   "select": OA_SELECT, "per-page": 100})
        found = got.get("results", []) if isinstance(got, dict) else []
        how = "one OpenAlex list call ($0.0001)"
    if err and err.get("code") != "NOT_FOUND":
        return None, M.diag("info", "OA_LOOKUP_FAILED",
                            "Open-access locations could not be looked up in OpenAlex: "
                            f"{err.get('message', '')[:200]}",
                            "The Crossref records are complete; ids.fulltext_url is empty because "
                            "the lookup failed, not because no open copy exists.")
    oa = dict(p for p in map(_oa_parse, found) if p)
    n_open = sum(1 for v in oa.values() if v["url"])
    return oa, M.diag("info", "OA_FROM_OPENALEX",
                      f"Open-access locations from OpenAlex ({how}): {n_open} of {len(dois)} "
                      "record(s) have an open copy, in ids.fulltext_url.",
                      "An empty fulltext_url means OpenAlex knows no open copy, or does not "
                      "hold the DOI; it is not proof that none exists.")


# ==============================================================================
# Input models
# ==============================================================================

_FILTER_BAD = re.compile(r"[,:\x00-\x1f]")


def _filter_value(v: Optional[str]) -> Optional[str]:
    """A filter value cannot carry a comma or colon: it would add a filter."""
    if v is None:
        return v
    if _FILTER_BAD.search(v):
        raise ValueError("must not contain commas, colons or control characters")
    return v


def _bare_doi(v: str) -> str:
    v = re.sub(r"^\s*(https?://(dx\.)?doi\.org/|doi:\s*)", "", v.strip(), flags=re.I)
    if not re.match(r"^10\.\d{4,9}/\S+$", v):
        raise ValueError("not a DOI (expected 10.xxxx/...)")
    if any(seg in (".", "..") for seg in v.split("/")):
        raise ValueError("DOI path segments '.' and '..' are refused")
    return v


class WorkSearchInput(BaseModel):
    """Search Crossref for DOI-registered works."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: Optional[str] = Field(default=None, max_length=QUERY_MAX,
                                 description="Words to match in titles, authors, container, year "
                                             "(Crossref's query.bibliographic). Any word matches.")
    author: Optional[str] = Field(default=None, max_length=300, description="Author name to match")
    container: Optional[str] = Field(default=None, max_length=300,
                                     description="Journal or book-series title to match")
    year_from: Optional[int] = Field(default=None, ge=1000, le=2100, description="Earliest publication year")
    year_to: Optional[int] = Field(default=None, ge=1000, le=2100, description="Latest publication year")
    type: Optional[str] = Field(default=None, description="Crossref type, e.g. 'journal-article', "
                                                          "'book-chapter', 'monograph', 'edited-book', "
                                                          "'book'. Presses type a single-author book "
                                                          "'monograph' as often as 'book'.")
    issn: Optional[str] = Field(default=None, description="Restrict to one journal by ISSN (e.g. '0095-6848')")
    sort: str = Field(default="relevance", description="'relevance', 'published' (newest first) or 'cited'")
    rows: int = Field(default=10, ge=1, le=ROWS_MAX, description="Results to return (1-100)")
    offset: int = Field(default=0, ge=0, le=OFFSET_MAX, description="Results to skip (Crossref allows up to 10,000)")
    oa_links: bool = Field(default=True, description="Fill ids.fulltext_url with open-access "
                                                    "locations from OpenAlex (free for one DOI, "
                                                    "$0.0001 for a page)")

    _filters = field_validator("type", "issn")(_filter_value)

    @field_validator("sort")
    @classmethod
    def _sort(cls, v: str) -> str:
        if v not in SORTS:
            raise ValueError(f"sort must be one of {sorted(SORTS)}")
        return v


class WorkLookupInput(BaseModel):
    """Look up one work by DOI."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    doi: str = Field(..., min_length=4, max_length=500,
                     description="DOI, bare (10.1177/...) or as a doi.org URL")
    oa_links: bool = Field(default=True, description="Fill ids.fulltext_url with open-access "
                                                    "locations from OpenAlex (free for one DOI, "
                                                    "$0.0001 for a page)")

    _doi = field_validator("doi")(_bare_doi)


class CitationMatchInput(BaseModel):
    """Find the Crossref records that best match a reference as written."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    citation: str = Field(..., min_length=3, max_length=QUERY_MAX,
                          description="A reference as written: author, title, venue, year, in any order")
    rows: int = Field(default=3, ge=1, le=10, description="Candidates to return (1-10)")
    oa_links: bool = Field(default=True, description="Fill ids.fulltext_url with open-access "
                                                    "locations from OpenAlex (free for one DOI, "
                                                    "$0.0001 for a page)")


# ==============================================================================
# Tools
# ==============================================================================

_ANN = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


@mcp.tool(name="cr_search_works", annotations=_ANN)
async def cr_search_works(params: WorkSearchInput) -> str:
    """Search Crossref (DOI registration metadata) for works. Returns the unified envelope.

    Free, no key. Best for English-language journal articles and press books
    with Crossref DOIs; most Japanese-language scholarship is not here. A
    multi-word query matches ANY word and ranks the union, so result.total is
    not a literature: read the top of the ranking, and narrow with author,
    container, year, type or issn rather than more words. At least one of
    query, author, container or issn is required.
    """
    if not any((params.query, params.author, params.container, params.issn)):
        return _envelope(operation="search_works", term="", params={}, matching_mode=MODE_SEARCH,
                         data=None, matched_in="unknown",
                         err=M.diag("error", "INVALID_INPUT",
                                    "Give at least one of query, author, container or issn.", None))
    qp: Dict[str, Any] = {"rows": params.rows, "offset": params.offset, "select": SELECT}
    if params.query:
        qp["query.bibliographic"] = params.query
    if params.author:
        qp["query.author"] = params.author
    if params.container:
        qp["query.container-title"] = params.container
    filters = []
    if params.year_from:
        filters.append(f"from-pub-date:{params.year_from}-01-01")
    if params.year_to:
        filters.append(f"until-pub-date:{params.year_to}-12-31")
    if params.type:
        filters.append(f"type:{params.type}")
    if params.issn:
        filters.append(f"issn:{params.issn}")
    if filters:
        qp["filter"] = ",".join(filters)
    if params.sort != "relevance":
        qp["sort"], qp["order"] = SORTS[params.sort], "desc"
    term = " ".join(x for x in (params.query, params.author, params.container, params.issn) if x)
    data, err = await _cr_request("works", qp)
    diags = _search_diags(params.query) if params.query else []
    oa = None
    if params.oa_links and not err:
        oa, d = await _oa_links(data, single=False)
        diags += [d] if d else []
    return _envelope(operation="search_works", term=term, params=qp, matching_mode=MODE_SEARCH,
                     data=data, err=err, matched_in="bibliographic", extra_diags=diags, oa=oa)


@mcp.tool(name="cr_get_work", annotations=_ANN)
async def cr_get_work(params: WorkLookupInput) -> str:
    """Look up one work by DOI in Crossref. Returns the unified envelope with a single item, NOT_FOUND, or DOI_NOT_REGISTERED.

    When Crossref has no record, doi.org is asked which agency registered the
    DOI: NOT_FOUND names the agency (JaLC for most Japanese DOIs, DataCite,
    KISTI, CNKI) and where to look instead; DOI_NOT_REGISTERED means no agency
    has the DOI at all, so the DOI as written does not exist. Open-access
    locations come from OpenAlex (oa_links).
    """
    data, err = await _cr_request(f"works/{quote(params.doi, safe='/:;()')}")
    diags, oa = [], None
    if err and err.get("code") == "NOT_FOUND":
        err = _agency_diag(params.doi, *await _doi_agency(params.doi))
    elif params.oa_links and not err:
        oa, d = await _oa_links(data, single=True)
        diags += [d] if d else []
    return _envelope(operation="get_work", term=params.doi, params={"doi": params.doi},
                     matching_mode=MODE_LOOKUP, data=data, err=err,
                     matched_in="identifier", single=True, extra_diags=diags, oa=oa)


@mcp.tool(name="cr_match_citation", annotations=_ANN)
async def cr_match_citation(params: CitationMatchInput) -> str:
    """Find the Crossref records closest to a reference as written. Returns candidates, never a verdict.

    Each candidate carries Crossref's relevance score in extra.score. The
    score ranks; it is not a probability, and a book and its reviews score
    close together (the reviews share its title). Compare author, year,
    container and type before accepting a match. A top candidate that does not
    match is evidence only that Crossref lacks the work, not that it does not
    exist.
    """
    qp: Dict[str, Any] = {"query.bibliographic": params.citation, "rows": params.rows, "select": SELECT}
    data, err = await _cr_request("works", qp)
    diags = [M.diag("info", "CANDIDATES_NOT_VERDICT",
                    "These are Crossref's best-ranked candidates for the reference, not a "
                    "confirmed match.",
                    "Accept a candidate only when author, year, title and venue agree; reviews "
                    "of a book share its title and rank beside it.")]
    if M.detect_script(params.citation) != "latin":
        diags += [d for d in _search_diags(params.citation) if d["code"] == "CJK_QUERY_WEAK"]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        built, _ = _build_all(data["items"], "bibliographic")
        diags += _same_title_diags(built)
    oa = None
    if params.oa_links and not err:
        oa, d = await _oa_links(data, single=False)
        diags += [d] if d else []
    return _envelope(operation="match_citation", term=params.citation, params=qp,
                     matching_mode="relevance_ranked_candidates", data=data, err=err,
                     matched_in="bibliographic", extra_diags=diags, oa=oa)


def main() -> None:
    """Run this source alone (normally it is gathered by bibliograph.server)."""
    mcp.run()


if __name__ == "__main__":
    main()
