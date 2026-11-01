"""
OpenAlex MCP Server (v2.1.5)
============================
An MCP server for the OpenAlex API — the open scholarly graph maintained by
OurResearch, covering works, authors, sources (journals), and institutions.

v2.0.0 — clean replacement of the response format. Every tool now emits the
unified response envelope shared across the server family (see mediation.py /
response-schema.json): typed query/script, matching_mode, graduated breadth,
per-item matched_in, typed diagnostics, a loggable receipt, and attribution.
This is a breaking change from v1.x, which returned formatted markdown text.

Data source: OpenAlex API (https://api.openalex.org)
API key (free): https://openalex.org/settings/api — set via OPENALEX_API_KEY.
OPENALEX_EMAIL is sent as `mailto` only when no key is set; OpenAlex itself no
longer reads it, but mirrors of the API may.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any, Dict, Optional

from urllib.parse import quote, quote_plus

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids
from ... import namematch as NM

__version__ = "2.1.5"

# ==============================================================================
# Configuration
# ==============================================================================

API_BASE = "https://api.openalex.org"
API_KEY = os.environ.get("OPENALEX_API_KEY", "")
EMAIL = os.environ.get("OPENALEX_EMAIL", "")
TIMEOUT = 30.0
ATTRIBUTION = "Data via OpenAlex (https://openalex.org), OurResearch. CC0."

# OpenAlex's `search` parameter matches title, abstract and (where indexed)
# full text, with stemming and stop-word removal. A high total is therefore a
# loose match, not a catalogued one; the mode name says so.
MODE_SEARCH = "full_text_stemmed"
# Lists produced by `filter=` alone (citations of a work, works of an author)
# match an identifier exactly and choose no term.
MODE_FILTER = "filter_exact"
MODE_LOOKUP = "identifier_lookup"

_SECRET_PARAMS = ("api_key", "mailto")

# OpenAlex prices a request by the call, not by the results it returns: a
# keyword search costs 10 credits ($0.001) at per-page 10 and at per-page 200
# alike (checked live, 1 Nov 2026), so a sweep paging at 10 pays twenty times
# what it would at 200. The defaults stay small because every result is also
# text the client has to read; a sweep should ask for the maximum, and the
# envelope says so when a search pages on at a small page size.
PER_PAGE_MAX = 200
PER_PAGE_DESC = (
    "Results per page (1-200). OpenAlex charges per call, not per result, so a "
    "sweep that will page through results should set 200."
)
SWEEP_PAGE_SIZE_BELOW = 50


def _silence_http_logging() -> None:
    """Two reasons, either sufficient on its own.

    httpx logs every request at INFO with the full URL — and the OpenAlex key
    travels in the query string, so a default logging setup writes the
    credential into whatever stream the client is capturing.

    Second, this is a stdio server: stdout carries JSON-RPC and nothing else.
    Any handler that defaults to stdout corrupts the protocol frame.
    """
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

# mcp 1.x's FastMCP takes no `version`; 2.x's MCPServer does. Passed where it is
# accepted, because a server that answers `initialize` with an empty version
# string cannot be cited by the disclosure that has to name the build it ran.
try:
    mcp = _MCPServer("openalex_mcp", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("openalex_mcp")


# ==============================================================================
# HTTP client
# ==============================================================================


def _redact(text: str) -> str:
    """Strip the key and the contact e-mail from any text that might reach a
    diagnostic, in every form a URL gives them: an upstream error that echoes
    the request URL carries them percent-encoded. Call before truncating, never
    after: a cut through a secret leaves a prefix no match can find."""
    for secret in (API_KEY, EMAIL):
        if secret:
            for form in {secret, quote(secret, safe=""), quote_plus(secret), quote(secret)}:
                text = text.replace(form, "[redacted]")
    return text


def _header_number(headers, name: str) -> Optional[float]:
    try:
        return float(headers.get(name))
    except (TypeError, ValueError):
        return None


def _upstream_message(body: str) -> str:
    try:
        import json as _json
        msg = _json.loads(body).get("message")
    except Exception:  # noqa: BLE001
        msg = None
    return _redact(str(msg))[:240] if msg else ""


def _rate_limit_diag(headers, body: str = "") -> dict:
    """Say which allowance a 429 exhausted.

    OpenAlex meters two things: requests per second, and a daily dollar budget
    ($1 on a key, $0.10 shared per IP without one) that resets at midnight UTC,
    topped up by any prepaid balance. Each response carries the budget in
    X-RateLimit-* headers. Until 1 Nov 2026 every 429 was reported as a rate
    problem with advice to add a key, even when the key was set and the day's
    budget was gone. The code stays RATE_LIMITED, so nothing that branches on
    it changes; the message says which limit it was.
    """
    remaining = _header_number(headers, "X-RateLimit-Remaining-USD")
    prepaid = _header_number(headers, "X-RateLimit-Prepaid-Remaining-USD")
    required = _header_number(headers, "X-RateLimit-Cost-Required-USD")
    reset = _header_number(headers, "X-RateLimit-Reset")
    unknown = "The result of this search is unknown, not empty."

    if remaining is None:
        # Seen live 1 Nov 2026: under load OpenAlex throttles keyless search with
        # a 429 that carries only Retry-After and a message saying so.
        said = _upstream_message(body)
        retry = _header_number(headers, "Retry-After")
        hint = f"{unknown} " + (f"OpenAlex asks for a retry in {int(retry)} s." if retry is not None
                                else "Wait and retry.")
        if not API_KEY:
            hint += " A free key (OPENALEX_API_KEY) raises both allowances."
        return M.diag(
            "error", "RATE_LIMITED",
            "OpenAlex answered 429 without its budget headers"
            + (f': "{said}"' if said else ", so it is not known which limit was exceeded."),
            hint,
        )

    left = remaining + (prepaid or 0.0)
    if left <= 0 or (required is not None and left < required):
        budget = ("the $1 daily budget on this API key" if API_KEY else
                  "the keyless $0.10 daily budget, shared by everyone on this network address")
        msg = f"OpenAlex answered 429: {budget} is spent, and no prepaid balance covers this request"
        msg += f" (it needed ${required:.4f})." if required is not None else "."
        if reset is not None and reset >= 0:
            secs = int(reset)
            msg += f" The budget resets at midnight UTC, in about {secs // 3600} h {secs % 3600 // 60} min."
        else:
            msg += " The budget resets at midnight UTC."
        hint = f"{unknown} Wait for the reset, or add prepaid usage at https://openalex.org/pricing."
        if not API_KEY:
            hint += " A free key (OPENALEX_API_KEY) has a $1 daily budget of its own."
        return M.diag("error", "RATE_LIMITED", msg, hint)

    msg = (f"OpenAlex answered 429: too many requests per second. The daily budget "
           f"is not the cause (${left:.4f} left).")
    hint = f"{unknown} Wait a few seconds and retry."
    if not API_KEY:
        hint += " A free key (OPENALEX_API_KEY) raises the per-second allowance from 10 to 30."
    return M.diag("error", "RATE_LIMITED", msg, hint)


def budget_snapshot() -> dict:
    """The day's OpenAlex budget for the configured key, for bibliograph_status.

    GET /rate-limit is free (its answer carried no cost and the balance did not
    move, 1 Nov 2026). It also returns OpenAlex's current price per request
    type, which is reported as given rather than restated from the help pages.
    Without a key nothing is sent: the keyless budget is shared per IP address.
    """
    if not API_KEY:
        return {"note": "no OPENALEX_API_KEY: keyless use shares a $0.10 daily budget per IP address"}
    try:
        resp = httpx.get(f"{API_BASE}/rate-limit", params={"api_key": API_KEY}, timeout=5.0)
        rl = resp.json().get("rate_limit")
    except Exception as exc:  # noqa: BLE001 - status must answer whatever happens
        return {"error": _redact(f"{type(exc).__name__}: {exc}")[:200]}
    if resp.status_code != 200 or not isinstance(rl, dict):
        return {"error": f"OpenAlex answered {resp.status_code}"}
    keep = ("daily_budget_usd", "daily_used_usd", "daily_remaining_usd",
            "prepaid_remaining_usd", "prepaid_expires_at", "resets_at", "endpoint_costs_usd")
    return {k: rl.get(k) for k in keep}


async def _oa_request(
    endpoint: str, params: Optional[Dict[str, Any]] = None
) -> tuple[Optional[Any], Optional[dict]]:
    """Call one OpenAlex endpoint.

    Returns (data, error_diag). Exactly one is non-None. The caller's `params`
    is never mutated: the credential is added to a copy, so the dict the caller
    goes on to place in the envelope carries no secret.
    """
    sent: Dict[str, Any] = dict(params or {})
    if API_KEY:
        sent["api_key"] = API_KEY
    elif EMAIL:
        sent["mailto"] = EMAIL
    url = f"{API_BASE}/{endpoint}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(url, params=sent)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # InvalidURL is not an HTTPError: a request too long or malformed to
        # send raised it out of the tool. The request was not sent.
        return None, M.diag(
            "error", "TRANSPORT_ERROR",
            f"Could not reach OpenAlex: {_redact(type(exc).__name__ + ': ' + str(exc))[:300]}",
            "The result of this search is unknown, not empty. Retry before "
            "concluding anything about the literature.",
        )

    if resp.status_code == 404:
        return None, M.diag(
            "warning", "NOT_FOUND",
            "OpenAlex has no record for this identifier.",
            "Check the ID form: W…, A…, S…, I… OpenAlex IDs, a bare DOI, an "
            "ORCID, or a PMID.",
        )
    if resp.status_code == 429:
        return None, _rate_limit_diag(resp.headers, resp.text)
    if resp.status_code >= 400:
        return None, M.diag(
            "error", "API_ERROR",
            f"OpenAlex answered {resp.status_code}: {_redact(resp.text)[:300]}",
            None,
        )
    try:
        return resp.json(), None
    except ValueError:
        return None, M.diag(
            "error", "API_ERROR",
            "OpenAlex answered 200 with a body that is not JSON.",
            "Retry; if it persists the API or an intermediary is misbehaving.",
        )


# ==============================================================================
# Record builders
# ==============================================================================


def _bare_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I) or None


def _short_id(oa_id: Optional[str]) -> Optional[str]:
    """'https://openalex.org/W123' -> 'W123'. The full URL stays in ids.url_en."""
    if not oa_id:
        return None
    return oa_id.rsplit("/", 1)[-1]


def _abstract(w: dict) -> Optional[str]:
    idx = w.get("abstract_inverted_index")
    if not isinstance(idx, dict):
        return None
    try:
        pos_word = [(p, word) for word, positions in idx.items() for p in positions]
    except (TypeError, AttributeError):
        return None
    pos_word.sort()
    text = " ".join(word for _, word in pos_word)
    return text[:400] + "…" if len(text) > 400 else (text or None)


def _place_title(text: Optional[str], language: Optional[str]) -> dict:
    """Route a display name into the typed title slots.

    OpenAlex reports a `language` on works; where it does, that decides. Where
    it does not, a Latin-script title is placed in `en` (the family's slot for
    non-CJK text) and a CJK title is left out of the typed slots altogether —
    a han-only string could be Chinese or Japanese, and the server will not
    guess. The untyped text is always kept in `extra.title`.
    """
    out = {"title_ja": None, "title_ko": None, "title_en": None}
    if not text:
        return out
    script = M.detect_script(text)
    if language == "ja" or (not language and script in ("kana", "han_kana")):
        out["title_ja"] = text
    elif language == "ko" or (not language and script in ("hangul", "han_hangul")):
        out["title_ko"] = text
    elif script == "latin":
        # `en` is the family's slot for non-CJK text. A Latin-script title in
        # another language still lands here, as it does in the sibling servers;
        # the language code is kept beside it in extra.language.
        out["title_en"] = text
    # A CJK title that OpenAlex marks neither ja nor ko (e.g. zh), or a han-only
    # string with no language, stays untyped: extra.title carries it.
    return out


def _item_from_work(w: dict, matched_in: str) -> dict:
    title = w.get("display_name") or w.get("title")
    language = w.get("language")
    authors = []
    for a in (w.get("authorships") or [])[:12]:
        au = a.get("author") or {}
        insts = [i.get("display_name") for i in (a.get("institutions") or []) if i.get("display_name")]
        authors.append({
            "name": au.get("display_name"),
            "orcid": au.get("orcid"),
            "openalex_id": _short_id(au.get("id")),
            "affiliation": "; ".join(insts) or None,
        })
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    biblio = w.get("biblio") or {}
    fp, lp = biblio.get("first_page"), biblio.get("last_page")
    pages = f"{fp}-{lp}" if fp and lp else (fp or None)
    oa = w.get("open_access") or {}
    best = w.get("best_oa_location") or {}
    ids = w.get("ids") or {}

    return M.make_item(
        **_place_title(title, language),
        authors=authors,
        journal_en=src.get("display_name"),
        volume=biblio.get("volume"),
        issue=biblio.get("issue"),
        pages=pages,
        year=w.get("publication_year"),
        doi=_bare_doi(w.get("doi")),
        issn=src.get("issn_l"),
        url_en=loc.get("landing_page_url") or w.get("id"),
        fulltext_url=oa.get("oa_url") or best.get("pdf_url"),
        matched_in=matched_in,
        record_type=w.get("type") or "article",
        extra={
            "title": title,
            "language": language,
            "openalex_id": _short_id(w.get("id")),
            "pmid": _short_id(ids.get("pmid")),
            "type_crossref": w.get("type_crossref"),
            "cited_by_count": w.get("cited_by_count"),
            "is_oa": oa.get("is_oa"),
            "publication_date": w.get("publication_date"),
            "topics": [t.get("display_name") for t in (w.get("topics") or [])[:3]],
            "abstract": _abstract(w),
        },
    )


def _item_from_author(a: dict, matched_in: str) -> dict:
    affils = []
    for af in a.get("affiliations") or []:
        inst = af.get("institution") or {}
        years = af.get("years") or []
        affils.append({"name": inst.get("display_name"), "years": sorted(years)})
    stats = a.get("summary_stats") or {}
    return M.make_item(
        title_en=a.get("display_name"),
        url_en=a.get("id"),
        matched_in=matched_in,
        record_type="author",
        extra={
            "openalex_id": _short_id(a.get("id")),
            "orcid": a.get("orcid"),
            "works_count": a.get("works_count"),
            "cited_by_count": a.get("cited_by_count"),
            "h_index": stats.get("h_index"),
            "affiliations": affils,
            "alternate_names": a.get("display_name_alternatives") or [],
        },
    )


def _item_from_source(s: dict, matched_in: str) -> dict:
    return M.make_item(
        title_en=s.get("display_name"),
        issn=s.get("issn_l"),
        url_en=s.get("homepage_url") or s.get("id"),
        matched_in=matched_in,
        record_type="source",
        extra={
            "openalex_id": _short_id(s.get("id")),
            "type": s.get("type"),
            "publisher": s.get("host_organization_name"),
            "works_count": s.get("works_count"),
            "cited_by_count": s.get("cited_by_count"),
            "is_oa": s.get("is_oa"),
            "is_in_doaj": s.get("is_in_doaj"),
            "issns": s.get("issn"),
        },
    )


def _item_from_institution(i: dict, matched_in: str) -> dict:
    return M.make_item(
        title_en=i.get("display_name"),
        url_en=i.get("homepage_url") or i.get("id"),
        matched_in=matched_in,
        record_type="institution",
        extra={
            "openalex_id": _short_id(i.get("id")),
            "ror": i.get("ror"),
            "country_code": i.get("country_code"),
            "type": i.get("type"),
            "works_count": i.get("works_count"),
            "cited_by_count": i.get("cited_by_count"),
        },
    )


# ==============================================================================
# Envelope assembly
# ==============================================================================


def _not_shape(expected: str, data: Any) -> dict:
    """A 200 body that is not the shape asked for is an answer that did not
    arrive, not an empty one (stress test, 12 Oct 2026)."""
    said = ""
    if isinstance(data, dict):
        msg = data.get("error") or data.get("message")
        if msg:
            said = f' It said: "{_redact(str(msg))[:200]}".'
        shape = f"an object with keys {sorted(map(str, data))[:6]}"
    else:
        shape = "null" if data is None else f"a {type(data).__name__}"
    return M.diag(
        "error", "API_ERROR",
        f"OpenAlex answered 200, but with {shape} rather than {expected}.{said}",
        "The result of this search is unknown, not empty. Retry before "
        "concluding anything about the literature.",
    )


def _count(v: Any) -> Optional[int]:
    """A count from the API: a non-negative integer, or None. 1e309 parses as
    infinity and int() of it raises OverflowError; a negative or fractional
    count is not a count either."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 0 else None
    if isinstance(v, float):
        return int(v) if v.is_integer() and v >= 0 else None
    if isinstance(v, str) and v.strip().isdecimal():
        return int(v.strip())
    return None


def _build_all(records: list, build, matched_in: str) -> tuple[list[dict], list[str]]:
    """Build every record that can be read; return the rest as names.

    Same contract as receipt_ids.build_items, but each skipped record is named
    by its position on the page and, where it has one, its identifier, so the
    RECORD_SHAPE_UNEXPECTED diagnostic can say which."""
    items: list[dict] = []
    bad: list[str] = []
    for pos, rec in enumerate(records, 1):
        try:
            if not isinstance(rec, dict):
                raise TypeError("record is not an object")
            items.append(build(rec, matched_in))
        except Exception:  # noqa: BLE001
            rid = rec.get("id") if isinstance(rec, dict) else None
            bad.append(f"#{pos}" + (f" ({rid[:100]})" if isinstance(rid, str) and rid else ""))
    return items, bad


def _envelope(
    *,
    operation: str,
    term: str,
    params: dict,
    matching_mode: str,
    data: Optional[Any],
    err: Optional[dict],
    build,
    matched_in: str,
    single: bool = False,
    coverage_note: Optional[str] = None,
    person_query: Optional[str] = None,
) -> str:
    """Assemble and emit one envelope from an OpenAlex response.

    `single` marks a lookup, whose body is the record itself rather than a
    {meta, results} page; total is then 1 or 0. `params` is what the caller
    chose; the credential never enters it.

    `person_query` is set only by oa_search_authors: OpenAlex's author search
    is a loose name match that returns duplicate people, so each item is
    graded against the query name (extra.name_match) rather than filtered or
    reordered.
    """
    items: list[dict] = []
    bad: list[str] = []
    paging_cost: Optional[tuple[int, int]] = None
    n_records = 0
    total = 0
    start = 1
    ds: list[dict] = []
    if err:
        ds.append(err)
    elif single:
        if isinstance(data, dict) and isinstance(data.get("id"), str):
            n_records = 1
            items, bad = _build_all([data], build, matched_in)
            total = len(items)
        else:
            ds.append(_not_shape("a record", data))
    elif not (isinstance(data, dict) and isinstance(data.get("results"), list)
              and isinstance(data.get("meta"), dict)):
        ds.append(_not_shape("a results page", data))
    else:
        n_records = len(data["results"])
        items, bad = _build_all(data["results"], build, matched_in)
        meta = data["meta"]
        total = _count(meta.get("count"))
        if total is None:
            total = len(items)
        per_page = _count(meta.get("per_page")) or _count(params.get("per-page")) or len(items) or 1
        page = _count(meta.get("page")) or _count(params.get("page")) or 1
        start = (page - 1) * per_page + 1
        if page > 1 and per_page < SWEEP_PAGE_SIZE_BELOW:
            paging_cost = (page, per_page)

    if bad and single:
        # Bibliograph's 7 Oct repair: the one record asked for is an error, not a warning.
        ds.append(M.diag("error", "API_ERROR",
                         f"OpenAlex returned this record in a shape that could not be read ({bad[0]}).",
                         "Do not treat the record as absent; report the id."))
    elif bad:
        named = "; ".join(bad[:10]) + ("; and more" if len(bad) > 10 else "")
        ds.append(M.diag(
            "warning", "RECORD_SHAPE_UNEXPECTED",
            f"{len(bad)} of {n_records} record(s) in the response had an unexpected shape "
            f"and were left out: {named}.",
            "The upstream record is malformed, not absent. The other records are complete; "
            "look the omitted ones up by identifier or retry later."))
    if person_query and items:
        counts = {"exact": 0, "partial": 0, "none": 0}
        for it in items:
            cands = [it["title"].get("en")] + list(it.get("extra", {}).get("alternate_names") or [])
            best = NM.best_author_match(person_query, cands)
            it["extra"]["name_match"] = best
            counts[best] += 1
        non_exact = counts["partial"] + counts["none"]
        if non_exact:
            parts = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
            ds.append(M.diag(
                "info", "LOOSE_NAME_MATCH",
                f"Author-name matching against '{person_query}' is not exact for "
                f"{non_exact} of {len(items)} result(s) ({parts}). OpenAlex's author "
                "search is a loose name match that returns duplicate people.",
                "Read extra.name_match on each item; treat 'partial' and 'none' as "
                "other people until confirmed by affiliation, topic or other evidence.",
            ))

    if not ds and not items:
        ds.append(M.diag(
            "warning", "ZERO_RESULTS",
            "No records. OpenAlex matched nothing for this term and filter set.",
            "Vary the rendering or loosen the filters. Non-English titles are "
            "indexed as supplied by the publisher, often without translation, "
            "so an English rendering of a Japanese or Korean title may not match.",
        ))
    if not ds:
        ds.append(M.diag("info", "OK", f"{total} record(s) reported by OpenAlex.", None))
    if paging_cost:
        # Appended after OK and ZERO_RESULTS are decided, so it never displaces them.
        page, per_page = paging_cost
        ds.append(M.diag(
            "info", "PAGING_COST",
            f"This is page {page} at {per_page} results per page. OpenAlex charges "
            "per call, not per result, so each page costs as much as a page of 200.",
            "To continue a sweep, set per_page to 200 and start from the first "
            "result not yet seen.",
        ))

    clean = {k: v for k, v in params.items() if k not in _SECRET_PARAMS and v is not None}
    env = M.build_envelope(
        server="openalex", operation=operation,
        input_terms=term, normalized=term, params=clean,
        matching_mode=matching_mode, total=total, start=start,
        items=items, diagnostics=ds, attribution=ATTRIBUTION,
        coverage_note=coverage_note,
    )
    return M.emit(_rids.finish(env, lambda it: _rids.prefixed('openalex:', _rids.extra_of(it).get('openalex_id'))))


def _year_filter(year_from: Optional[int], year_to: Optional[int]) -> Optional[str]:
    if year_from and year_to:
        return f"publication_year:{year_from}-{year_to}"
    if year_from:
        return f"publication_year:>{year_from - 1}"
    if year_to:
        return f"publication_year:<{year_to + 1}"
    return None


def _as_work_id(work_id: str) -> str:
    return f"https://doi.org/{work_id}" if work_id.startswith("10.") else work_id


# ==============================================================================
# Input Models
# ==============================================================================


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
QUERY_MAX = 2000  # far above any real search; well below httpx's URL limit


def _filter_value(v: Optional[str]) -> Optional[str]:
    """A value that goes into `filter=`. The syntax has no escape and a comma
    starts a new filter. '|' stays allowed: it ORs values within one filter."""
    if v is not None and ("," in v or _CONTROL.search(v)):
        raise ValueError("must not contain a comma or a control character "
                         "(a comma would start a filter of its own)")
    return v


def _path_id(v: str) -> str:
    """An identifier that becomes a path segment: '.'/'..' segments walk to
    another endpoint. Reserved characters are percent-encoded where the
    request is built."""
    if _CONTROL.search(v) or any(seg in (".", "..") for seg in v.split("/")):
        raise ValueError("must be an identifier, not a path: no '.' or '..' "
                         "segments and no control characters")
    return v


class WorkSearchInput(BaseModel):
    """Search OpenAlex for scholarly works."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search query (searches title, abstract, fulltext)", min_length=1, max_length=QUERY_MAX)
    year_from: Optional[int] = Field(default=None, description="Start year filter")
    year_to: Optional[int] = Field(default=None, description="End year filter")
    author_id: Optional[str] = Field(default=None, description="OpenAlex author ID filter (e.g., 'A1234567890')")
    institution_id: Optional[str] = Field(default=None, description="OpenAlex institution ID filter")
    source_id: Optional[str] = Field(default=None, description="OpenAlex source/journal ID filter")
    open_access: Optional[bool] = Field(default=None, description="Filter for open access works only")
    sort_by: Optional[str] = Field(default=None, description="Sort: 'cited_by_count', 'publication_date', 'relevance_score'")
    per_page: int = Field(default=10, description=PER_PAGE_DESC, ge=1, le=PER_PAGE_MAX)
    page: int = Field(default=1, description="Page number", ge=1)

    _filters = field_validator("author_id", "institution_id", "source_id", "sort_by")(_filter_value)


class WorkLookupInput(BaseModel):
    """Look up a specific work by ID or DOI."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    work_id: str = Field(
        ...,
        description="OpenAlex work ID (e.g., 'W1234567890'), DOI URL, or PMID",
        min_length=1,
    )

    _path = field_validator("work_id")(_path_id)


class AuthorSearchInput(BaseModel):
    """Search OpenAlex for authors."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Author name to search", min_length=1, max_length=QUERY_MAX)
    institution_id: Optional[str] = Field(default=None, description="Filter by institution OpenAlex ID")
    per_page: int = Field(default=10, description=PER_PAGE_DESC, ge=1, le=PER_PAGE_MAX)
    page: int = Field(default=1, ge=1)

    _filters = field_validator("institution_id")(_filter_value)


class AuthorLookupInput(BaseModel):
    """Look up a specific author."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    author_id: str = Field(..., description="OpenAlex author ID (e.g., 'A1234567890') or ORCID", min_length=1)

    _path = field_validator("author_id")(_path_id)


class SourceSearchInput(BaseModel):
    """Search OpenAlex for sources (journals, repositories, conferences)."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Source name to search", min_length=1, max_length=QUERY_MAX)
    type: Optional[str] = Field(default=None, description="Filter by type: 'journal', 'repository', 'conference'")
    per_page: int = Field(default=10, description=PER_PAGE_DESC, ge=1, le=PER_PAGE_MAX)
    page: int = Field(default=1, ge=1)

    _filters = field_validator("type")(_filter_value)


class InstitutionSearchInput(BaseModel):
    """Search OpenAlex for institutions."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Institution name to search", min_length=1, max_length=QUERY_MAX)
    country_code: Optional[str] = Field(default=None, description="ISO country code filter (e.g., 'JP', 'GB', 'US')")
    per_page: int = Field(default=10, description=PER_PAGE_DESC, ge=1, le=PER_PAGE_MAX)
    page: int = Field(default=1, ge=1)

    _filters = field_validator("country_code")(_filter_value)


class CitedByInput(BaseModel):
    """Get works that cite a specific work."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    work_id: str = Field(..., description="OpenAlex work ID or DOI", min_length=1)
    per_page: int = Field(default=20, description=PER_PAGE_DESC, ge=1, le=PER_PAGE_MAX)
    page: int = Field(default=1, ge=1)

    _filters = field_validator("work_id")(_filter_value)


class AuthorWorksInput(BaseModel):
    """Get works by a specific author."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    author_id: str = Field(..., description="OpenAlex author ID or ORCID", min_length=1)
    year_from: Optional[int] = Field(default=None, description="Start year filter")
    year_to: Optional[int] = Field(default=None, description="End year filter")
    sort_by: Optional[str] = Field(default=None, description="Sort: 'cited_by_count', 'publication_date'")
    per_page: int = Field(default=20, description=PER_PAGE_DESC, ge=1, le=PER_PAGE_MAX)
    page: int = Field(default=1, ge=1)

    _filters = field_validator("author_id", "sort_by")(_filter_value)


# ==============================================================================
# Tools
# ==============================================================================

_ANN = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


@mcp.tool(name="oa_search_works", annotations=_ANN)
async def oa_search_works(params: WorkSearchInput) -> str:
    """Search OpenAlex for scholarly works (articles, books, datasets, theses). Returns the unified envelope.

    OpenAlex matches title, abstract and indexed full text with stemming, so
    result.total is a loose count (matching_mode full_text_stemmed) and a high
    breadth is expected. Titles are typed by OpenAlex's own language field;
    where that is absent, a CJK title is kept only in extra.title rather than
    guessed into ja or ko. Filters by year, author, institution, source and
    open-access status narrow the set exactly. OpenAlex charges per call, not
    per result: a sweep that pages through results should set per_page 200.
    """
    qp: Dict[str, Any] = {"search": params.query, "per-page": params.per_page, "page": params.page}
    filters = [f for f in (
        _year_filter(params.year_from, params.year_to),
        f"authorships.author.id:{params.author_id}" if params.author_id else None,
        f"authorships.institutions.id:{params.institution_id}" if params.institution_id else None,
        f"primary_location.source.id:{params.source_id}" if params.source_id else None,
        "is_oa:true" if params.open_access is True else None,
    ) if f]
    if filters:
        qp["filter"] = ",".join(filters)
    if params.sort_by:
        qp["sort"] = f"{params.sort_by}:desc"
    data, err = await _oa_request("works", qp)
    return _envelope(operation="search_works", term=params.query, params=qp,
                     matching_mode=MODE_SEARCH, data=data, err=err,
                     build=_item_from_work, matched_in="title_abstract_fulltext")


@mcp.tool(name="oa_get_work", annotations=_ANN)
async def oa_get_work(params: WorkLookupInput) -> str:
    """Look up one work by OpenAlex ID, DOI, or PMID. Returns the unified envelope with a single item, or NOT_FOUND."""
    data, err = await _oa_request(f"works/{quote(_as_work_id(params.work_id), safe=':/')}")
    return _envelope(operation="get_work", term=params.work_id, params={"work_id": params.work_id},
                     matching_mode=MODE_LOOKUP, data=data, err=err,
                     build=_item_from_work, matched_in="identifier", single=True)


@mcp.tool(name="oa_search_authors", annotations=_ANN)
async def oa_search_authors(params: AuthorSearchInput) -> str:
    """Search OpenAlex for authors by name. Returns the unified envelope; each item is an author record (record_type author) with affiliations, work and citation counts, and h-index in extra."""
    qp: Dict[str, Any] = {"search": params.query, "per-page": params.per_page, "page": params.page}
    if params.institution_id:
        qp["filter"] = f"affiliations.institution.id:{params.institution_id}"
    data, err = await _oa_request("authors", qp)
    return _envelope(operation="search_authors", term=params.query, params=qp,
                     matching_mode=MODE_SEARCH, data=data, err=err,
                     build=_item_from_author, matched_in="display_name",
                     person_query=params.query)


@mcp.tool(name="oa_get_author", annotations=_ANN)
async def oa_get_author(params: AuthorLookupInput) -> str:
    """Look up one author by OpenAlex ID or ORCID. Returns the unified envelope with a single author item, or NOT_FOUND."""
    data, err = await _oa_request(f"authors/{quote(params.author_id, safe=':/')}")
    return _envelope(operation="get_author", term=params.author_id, params={"author_id": params.author_id},
                     matching_mode=MODE_LOOKUP, data=data, err=err,
                     build=_item_from_author, matched_in="identifier", single=True)


@mcp.tool(name="oa_search_sources", annotations=_ANN)
async def oa_search_sources(params: SourceSearchInput) -> str:
    """Search OpenAlex for sources: journals, repositories, conferences. Returns the unified envelope (record_type source)."""
    qp: Dict[str, Any] = {"search": params.query, "per-page": params.per_page, "page": params.page}
    if params.type:
        qp["filter"] = f"type:{params.type}"
    data, err = await _oa_request("sources", qp)
    return _envelope(operation="search_sources", term=params.query, params=qp,
                     matching_mode=MODE_SEARCH, data=data, err=err,
                     build=_item_from_source, matched_in="display_name")


@mcp.tool(name="oa_search_institutions", annotations=_ANN)
async def oa_search_institutions(params: InstitutionSearchInput) -> str:
    """Search OpenAlex for institutions. Returns the unified envelope (record_type institution); useful for finding institution IDs to filter work searches."""
    qp: Dict[str, Any] = {"search": params.query, "per-page": params.per_page, "page": params.page}
    if params.country_code:
        qp["filter"] = f"country_code:{params.country_code}"
    data, err = await _oa_request("institutions", qp)
    return _envelope(operation="search_institutions", term=params.query, params=qp,
                     matching_mode=MODE_SEARCH, data=data, err=err,
                     build=_item_from_institution, matched_in="display_name")


@mcp.tool(name="oa_cited_by", annotations=_ANN)
async def oa_cited_by(params: CitedByInput) -> str:
    """Works that cite a given work, most-cited first. Returns the unified envelope. This is a filter on an identifier, not a term search, so no searched_for headline is set."""
    qp: Dict[str, Any] = {
        "filter": f"cites:{_as_work_id(params.work_id)}",
        "per-page": params.per_page, "page": params.page, "sort": "cited_by_count:desc",
    }
    data, err = await _oa_request("works", qp)
    return _envelope(operation="cited_by", term=params.work_id, params=qp,
                     matching_mode=MODE_FILTER, data=data, err=err,
                     build=_item_from_work, matched_in="referenced_works")


@mcp.tool(name="oa_author_works", annotations=_ANN)
async def oa_author_works(params: AuthorWorksInput) -> str:
    """Works by one author, with optional year filter and sort. Returns the unified envelope. A filter on an identifier, not a term search."""
    filters = [f"authorships.author.id:{params.author_id}"]
    yf = _year_filter(params.year_from, params.year_to)
    if yf:
        filters.append(yf)
    qp: Dict[str, Any] = {"filter": ",".join(filters), "per-page": params.per_page, "page": params.page}
    if params.sort_by:
        qp["sort"] = f"{params.sort_by}:desc"
    data, err = await _oa_request("works", qp)
    return _envelope(operation="author_works", term=params.author_id, params=qp,
                     matching_mode=MODE_FILTER, data=data, err=err,
                     build=_item_from_work, matched_in="authorships")


# ==============================================================================
# Entry point
# ==============================================================================

def main() -> None:
    """Console-script entry point (`openalex-mcp`)."""
    mcp.run()


if __name__ == "__main__":
    main()
