"""
NDL Next Digital Library MCP Server (v0.2.1)
============================================
An MCP server over 次世代デジタルライブラリー (Next Digital Library), the National
Diet Library's experimental full-text service for its public-domain digitised
holdings: roughly 350,000 items as of November 2022 — about 280,000 books from
the FY2021 OCR project and 60,000 classical materials from the FY2022 experiment.

This is the *full-text* half of the NDL. It is deliberately a separate server
from ndl-mcp, which searches 国立国会図書館サーチ over SRU and returns metadata.
The two differ in every way that matters to a declared scope:

  * different host (lab.ndl.go.jp, not ndlsearch.ndl.go.jp)
  * different corpus (public-domain digitised items, not aggregated bibliography)
  * different licence position — the text here is public domain and may therefore
    be held on disk and indexed, where NDL Search metadata for ndl-dl/ndl-dl-online
    is displayable and not accumulable

Keeping them apart is what lets this server's corpus be harvested into a local
index without touching the undertakings ndl-mcp gave the library in August 2026.

## Provenance of this interface

The endpoints are UNDOCUMENTED. They were read out of the service's own
`app.bundle.js` and probed live from London on 17 September 2026. What follows
is marked by how it is known, and a caller should read the `provenance` field of
any response the same way:

  verified 17 Sep 2026   GET /dl/api/book/search
                         GET /dl/api/book/ngram-search
                         GET /dl/api/book/{id}
                         GET /dl/api/book/fulltext/{id}   (ZIP, not text)
  from client code       GET /dl/api/page/{id}
                         GET /dl/api/book/download/{id}?page=N
                         https://dl.ndl.go.jp/api/iiif/{id}/R{page:07d}/full/full/0/default.jpg
  probed, unresolved     GET /dl/api/page/search  — returns 400; required
                         parameters not established. Not exposed here.

An undocumented interface can change without notice. Every tool therefore reports
the endpoint it called, so a future failure is legible rather than mysterious.

## Request discipline

The service publishes no rate limit. Its terms (the ご利用に当たって section of
lab.ndl.go.jp/service/tsugidigi/, read 25 September 2026) allow API use without
application except where use is both commercial and continuous
(営利目的かつ継続的な利用を除き、申請不要で自由にご利用になれます); such use is
referred to the NDL Lab contact page. The discipline is inherited from the SRU
work, where NDL throttling was measured to present as a read timeout rather
than a 429:

  * requests issued serially, never concurrent
  * a minimum interval of MIN_REQUEST_INTERVAL seconds between requests
  * a single search capped at MAX_RECORDS records; no auto-pagination

## No notification gate (removed in 0.2.0)

Version 0.1.0 assumed that NDL Lab, like the NDL Search API, asked continuous
users to file a usage notification, and refused requests above 20 records until
a marker recorded one. NDL Lab's own terms ask for no application for
non-commercial use, so the gate is gone: non-commercial scholarly use proceeds
at the discipline above, with no marker. The NDL Search API notice (the `ndl`
source) is unaffected.

Requires mediation.py and ledger.py beside it, vendored byte-identical from the
family; the installer copies them rather than reproducing them.
"""
from __future__ import annotations

import asyncio
import html as _html
import io
import logging
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids


def _receipt_id(it: dict):
    """The Digital Collections persistent identifier (see receipt_ids)."""
    return _rids.prefixed("info:ndljp/pid/", _rids.extra_of(it).get("item_id"))


def _emit(env: dict) -> str:
    return M.emit(_rids.finish(env, _receipt_id))

__version__ = "0.2.1"

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ==============================================================================
# Configuration
# ==============================================================================

API_BASE = "https://lab.ndl.go.jp/dl"
IIIF_BASE = "https://dl.ndl.go.jp/api/iiif"
VIEWER_BASE = "https://dl.ndl.go.jp/pid"
TIMEOUT = 60.0
USER_AGENT = "bibliograph-mcp ndl_dl/0.2 (non-commercial scholarly research)"

MIN_REQUEST_INTERVAL = 1.0
BACKOFF_SECONDS = 10.0
MAX_RECORDS = 100

# The service reports `hit` from a search engine whose default result-window
# ceiling is 10,000. A 青年団 search reported hit=10000 while the isClassic facet
# on the same response totalled 17,764. Treat the ceiling as a ceiling.
HIT_CEILING = 10000

# ndl_dl_page_image makes no request, but "1-99999" once built 99,999 URLs and a
# response that took 24 s to serialise (stress test, 7 Oct 2026). No item runs that long.
MAX_PAGE_IMAGES = 500

MATCHING_MODE = "fulltext_ocr_match"

ATTRIBUTION = (
    "Full text via 次世代デジタルライブラリー (Next Digital Library), "
    "National Diet Library, Japan. OCR text from the NDL's 令和3年度 and "
    "令和4年度 OCR text-conversion projects; page images via the NDL "
    "Digital Collections IIIF endpoint. "
    "本サービスは国立国会図書館の次世代デジタルライブラリーを利用しています。"
)

COVERAGE_NOTE = (
    "The corpus is the NDL's PUBLIC-DOMAIN digitised holdings only — about "
    "350,000 items as of November 2022, overwhelmingly pre-1945. Digitised "
    "in-copyright material (the 図書館送信 and 個人送信 tiers) is not here and is "
    "not searchable by this server at all: absence is absence from the "
    "public-domain OCR corpus, not from the NDL's holdings. The text is OCR of "
    "pre-war vertical type and contains recognition error; the service is "
    "labelled experimental by the library. A hit count at 10,000 is a window "
    "ceiling, not a corpus count."
)

PROVENANCE = {
    "book_search": "verified 2026-09-17",
    "book_ngram_search": "verified 2026-09-17",
    "book_record": "verified 2026-09-17",
    "book_fulltext": "verified 2026-09-17",
    "iiif_page_image": "from client code, unverified",
    "viewer_url": "constructed from the item id, unverified against the library",
}

# ==============================================================================
# Transport — serial, interval-held, no auto-pagination
# ==============================================================================

_lock = asyncio.Lock()
_last_request_at = 0.0


async def _get(path: str, params: Optional[dict] = None) -> tuple[Optional[httpx.Response], list[dict]]:
    """One serial GET with the interval held. Returns (response, diagnostics).

    A read timeout is reported as the throttle it usually is, not as an outage:
    on the SRU side, sustained probing stopped answering with no 429 and no
    diagnostic. Back off; do not press.
    """
    global _last_request_at
    diagnostics: list[dict] = []
    url = f"{API_BASE}{path}"
    async with _lock:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        headers = {"User-Agent": USER_AGENT}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    diagnostics.append(M.diag(
                        "warning", "RATE_LIMITED",
                        f"{url} answered 429; backing off {BACKOFF_SECONDS:.0f}s once.",
                        "Reduce the rate of querying rather than retrying in a loop.",
                    ))
                    await asyncio.sleep(BACKOFF_SECONDS)
                    resp = await client.get(url, params=params)
        except httpx.ReadTimeout:
            diagnostics.append(M.diag(
                "error", "READ_TIMEOUT",
                f"{url} did not answer within {TIMEOUT:.0f}s. On NDL hosts a read "
                "timeout is how throttling presents; it is not evidence the "
                "endpoint is down, and it is not evidence of zero results.",
                "Stop querying for several minutes, then issue a single request.",
            ))
            return None, diagnostics
        except httpx.HTTPError as exc:
            diagnostics.append(M.diag(
                "error", "TRANSPORT_ERROR", f"{url}: {exc}",
                "Check network reachability from this machine before retrying.",
            ))
            return None, diagnostics
        finally:
            _last_request_at = time.monotonic()
    if resp.status_code != 200:
        diagnostics.append(M.diag(
            "error", "HTTP_STATUS",
            f"{url} answered {resp.status_code}. This interface is undocumented; "
            "a 400 usually means a parameter this server got wrong, not an empty set.",
            "Report the status and the path rather than treating it as zero results.",
        ))
        return None, diagnostics
    return resp, diagnostics


def _facet_total(payload: dict) -> Optional[int]:
    """Recover a real count from the facets when `hit` is at the window ceiling."""
    facets = payload.get("facets")
    if not isinstance(facets, list):
        return None
    for f in facets:
        counts = f.get("counts") if isinstance(f, dict) else None
        if isinstance(counts, dict) and counts:
            try:
                return sum(int(v) for v in counts.values())
            except (TypeError, ValueError):
                continue
    return None


def _year_distribution(payload: dict) -> dict[str, int]:
    facets = payload.get("facets")
    if not isinstance(facets, list):
        return {}
    for f in facets:
        if isinstance(f, dict) and f.get("field") == "publishyear":
            counts = f.get("counts")
            if isinstance(counts, dict):
                return {str(k): int(v) for k, v in sorted(counts.items())}
    return {}

# ==============================================================================
# Record shaping
# ==============================================================================

_EM = re.compile(r"</?em>")
_JP2 = re.compile(r"\((\d{4,})\.jp2\)")


def _iiif_url(book_id: str, page: int) -> str:
    return f"{IIIF_BASE}/{book_id}/R{page:07d}/full/full/0/default.jpg"


_ENTITY = re.compile(r"&(?:#\d+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);")


def _unescape(s: str) -> str:
    """Decode complete character references only. html.unescape alone also decodes
    legacy entities written without a semicolon, so a query string such as
    ?a=1&region=2 would become ?a=1®ion=2 (second-model review, 7 Oct 2026)."""
    return _ENTITY.sub(lambda m: _html.unescape(m.group(0)), s)


def _clean_highlights(raw: Any, book_id: str) -> list[dict]:
    """Turn the service's highlight strings into located snippets.

    A highlight arrives as e.g. `四、男女<em>青年團</em>等との關係/11  (0011.jp2)` —
    the matched string, the table-of-contents line it sits in, and the page image
    it came from. That is a citable locus, so the page is parsed out rather than
    left in the prose, and the image URL is attached. The <em> wrapper becomes
    ｢｣ so the match stays visible once the markup is gone.
    """
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for h in raw:
        if not isinstance(h, str):
            continue
        m = _JP2.search(h)
        image_page = int(m.group(1)) if m else None
        text = _JP2.sub("", h).strip()
        text = text.replace("<em>", "｢").replace("</em>", "｣")
        text = _EM.sub("", text)
        # The service HTML-escapes highlights (a slash arrives as &#x2F;).
        text = _unescape(text)
        out.append({
            "snippet": text,
            "image_page": image_page,
            "page_image_url": (
                _iiif_url(book_id, image_page) if image_page and book_id else None
            ),
        })
    return out


def _s(v: Any) -> Optional[str]:
    """A text field as a string or None; numbers are kept as their digits."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return str(v)
    return v.strip() or None if isinstance(v, str) else None


def _item_from_record(rec: dict, with_highlights: bool = True) -> dict:
    """One envelope item from one book record.

    `responsibility` is a single statement of responsibility (e.g. 大日本聯合青年団
    編), not a parsed author list. It is passed through as given: splitting a
    Japanese statement of responsibility into authors is an editorial act, and a
    machine-split corporate body presented as an author is a fabrication with the
    shape of a fact.
    """
    book_id = str(rec.get("id") or "")
    if not re.fullmatch(r"[0-9A-Za-z_-]{1,40}", book_id):
        book_id = ""  # an id that is not an id builds no URL
    extra = {
        "item_id": book_id,
        "ndl_bib_id": rec.get("bibId"),
        "call_number": rec.get("callNo"),
        "ndc": rec.get("ndc"),
        "volume": rec.get("volume"),
        "publisher": rec.get("publisher"),
        "published_as_given": rec.get("published"),
        "image_pages": rec.get("page"),
        "is_classic": rec.get("isClassic"),
        "viewer_url": f"{VIEWER_BASE}/{book_id}" if book_id else None,
        "viewer_url_provenance": PROVENANCE["viewer_url"],
        "fulltext_available_via": "ndl_dl_book_fulltext",
    }
    if with_highlights:
        hl = _clean_highlights(rec.get("highlights"), book_id)
        if hl:
            extra["located_snippets"] = hl
    toc = rec.get("index")
    if isinstance(toc, list) and toc:
        extra["toc_lines"] = len(toc)
    return M.make_item(
        title_ja=_s(rec.get("title")),
        authors=[_s(rec.get("responsibility"))] if _s(rec.get("responsibility")) else [],
        journal_ja=None,
        volume=_s(rec.get("volume")),
        year=rec.get("publishyear") if isinstance(rec.get("publishyear"), int) else None,
        url_ja=f"{VIEWER_BASE}/{book_id}" if book_id else None,
        fulltext_url=f"{API_BASE}/api/book/fulltext/{book_id}" if book_id else None,
        matched_in="ocr_fulltext",
        record_type="book",
        holding_org="国立国会図書館",
        extra=extra,
    )


def _parse_page_range(spec: Optional[str], ceiling: int) -> Optional[list[int]]:
    """Parse "5", "5-20", "3,7,11-14" into a page list. None means all."""
    if not spec:
        return None
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            pages.extend(range(lo, min(hi, ceiling) + 1))
        else:
            try:
                pages.append(int(part))
            except ValueError:
                continue
    return sorted({p for p in pages if p > 0}) or None

# ==============================================================================
# Tools
# ==============================================================================

# mcp 1.x's FastMCP takes no `version`; 2.x's MCPServer does. Passed where it is
# accepted, because a server answering `initialize` with an empty version string
# cannot be cited by a disclosure that has to name the build it ran — which is
# exactly what the bundle handshake gate caught here on 18 September 2026.
try:
    mcp = _MCPServer("ndl-dl", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("ndl-dl")


class FulltextSearchInput(BaseModel):
    """Search the OCR full text of the NDL's public-domain digitised holdings."""
    model_config = ConfigDict(extra="forbid")

    keyword: str = Field(..., min_length=1, description=(
        "The Japanese search term. The index normalises old orthography — a query "
        "for 青年団 returns 青年團 — so variant expansion is usually unnecessary; "
        "test before adding variants."
    ))
    mode: Literal["relevance", "distribution"] = Field("relevance", description=(
        "'relevance' returns records with located snippets. 'distribution' returns "
        "the hit count by publication year and no records, for tracking a term "
        "across time."
    ))
    size: int = Field(20, ge=1, le=MAX_RECORDS, description=(
        f"Records to return, at most {MAX_RECORDS}."
    ))
    offset: int = Field(0, ge=0, description="Records to skip. There is no auto-pagination.")
    sort: Optional[Literal["publishyear:asc", "publishyear:desc"]] = Field(
        None, description="Publication-year order. Omit for the service's own relevance order."
    )
    keyword_or: bool = Field(False, description=(
        "Treat a multi-word keyword as OR rather than AND."
    ))


class BookFulltextInput(BaseModel):
    """Retrieve the per-page OCR text of one item."""
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., pattern=r"^\d+$", description=(
        "The Digital Collections item id, as `item_id` in a search result."
    ))
    pages: Optional[str] = Field(None, description=(
        "Image pages to return: '11', '11-20', '3,7,11-14'. Omit for the whole "
        "item, which for a long book is a great deal of text."
    ))
    max_chars: int = Field(20000, ge=500, le=200000, description=(
        "Ceiling on returned characters. Truncation is reported as a diagnostic, "
        "never silently."
    ))


class PageImageInput(BaseModel):
    """Resolve item pages to IIIF image URLs. Downloads nothing."""
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., pattern=r"^\d+$")
    pages: str = Field(..., description="Image pages: '11', '11-20', '3,7,11-14'.")


@mcp.tool()
async def ndl_dl_fulltext_search(params: FulltextSearchInput) -> str:
    """Search the OCR full text of 次世代デジタルライブラリー.

    This searches TEXT, not catalogue records: a hit means the term occurs in the
    OCR of a page. Each record carries located snippets with the image page they
    came from, so a hit can be cited and the page read.

    In 'distribution' mode the same query returns its hit count by publication
    year instead of records — the diachronic shape of a term across the
    public-domain corpus.

    The corpus is public-domain only and weighted to the pre-1945 period. A term
    that belongs to the post-war decades will be thin or absent here for reasons
    of copyright tier, not of history.
    """
    diagnostics: list[dict] = []

    endpoint = "/api/book/ngram-search" if params.mode == "distribution" else "/api/book/search"
    query: dict[str, Any] = {"keyword": params.keyword, "size": params.size}
    if params.offset:
        query["from"] = params.offset
    if params.sort:
        query["sort"] = params.sort
    if params.keyword_or:
        query["keywordOr"] = "true"

    resp, tdiag = await _get(endpoint, query)
    diagnostics.extend(tdiag)
    if resp is None:
        return _emit(M.build_envelope(
            server="ndl-dl-mcp", operation="search_fulltext",
            input_terms=params.keyword, normalized=params.keyword,
            params=query, matching_mode=MATCHING_MODE, total=0,
            start=params.offset, items=[], diagnostics=diagnostics,
            attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
        ))

    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        diagnostics.append(M.diag(
            "error", "API_ERROR", "The service returned a body that is not a JSON object.",
            "The interface is undocumented and may have changed; report the endpoint."))
        return _emit(M.build_envelope(
            server="ndl-dl-mcp", operation="search_fulltext",
            input_terms=params.keyword, normalized=params.keyword,
            params=query, matching_mode=MATCHING_MODE, total=0,
            start=params.offset, items=[], diagnostics=diagnostics,
            attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
        ))
    hit = payload.get("hit")
    try:
        facet_total = _facet_total(payload)
    except Exception:  # noqa: BLE001
        facet_total = None
    total = hit if isinstance(hit, int) else 0
    if isinstance(hit, int) and hit >= HIT_CEILING:
        diagnostics.append(M.diag(
            "warning", "HIT_COUNT_CAPPED",
            f"The service reported hit={hit}, which is its result-window ceiling "
            f"and not a count. The facet total on the same response is "
            f"{facet_total if facet_total is not None else 'unavailable'}.",
            "Cite the facet total, or narrow the query until the count falls "
            f"below {HIT_CEILING}.",
        ))
        if facet_total is not None:
            total = facet_total

    items: list[dict] = []
    if params.mode == "distribution":
        try:
            dist = _year_distribution(payload)
        except Exception:  # noqa: BLE001
            dist = None
        if not dist:
            diagnostics.append(M.diag(
                "warning", "NO_YEAR_FACET",
                "The response carried no publishyear facet, so no distribution "
                "could be built.",
                "Re-run in 'relevance' mode and report the absence.",
            ))
    else:
        raw = payload.get("list")
        malformed = 0
        for rec in raw if isinstance(raw, list) else []:
            if not isinstance(rec, dict):
                malformed += 1
                continue
            try:
                items.append(_item_from_record(rec))
            except Exception:  # noqa: BLE001
                malformed += 1
        if malformed:
            diagnostics.append(M.diag(
                "warning", "RECORD_SHAPE_UNEXPECTED",
                f"{malformed} record(s) in the response had an unexpected shape and were left out.",
                "The interface is undocumented; report the endpoint if this persists."))

    env = M.build_envelope(
        server="ndl-dl-mcp", operation="search_fulltext",
        input_terms=params.keyword, normalized=params.keyword,
        params=query, matching_mode=MATCHING_MODE, total=total,
        start=params.offset, items=items, diagnostics=diagnostics,
        attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
    )
    env["endpoint"] = f"{API_BASE}{endpoint}"
    env["endpoint_provenance"] = PROVENANCE[
        "book_ngram_search" if params.mode == "distribution" else "book_search"
    ]
    if params.mode == "distribution":
        env["year_distribution"] = dist
    return _emit(env)


@mcp.tool()
async def ndl_dl_book_fulltext(params: BookFulltextInput) -> str:
    """Retrieve the OCR text of one public-domain item, page by page.

    The service returns a ZIP of per-page text with a JSON sidecar for each page;
    this tool unpacks it and returns text keyed by image page, with the IIIF URL
    for each page so the reading can be checked against the scan. The text is
    public domain and may be kept.

    It is OCR of pre-war vertical type. Recognition error is normal, ruby and
    marginalia land in unexpected places, and a passage that will be quoted must
    be read against the page image.
    """
    diagnostics = []
    resp, tdiag = await _get(f"/api/book/fulltext/{params.item_id}")
    diagnostics.extend(tdiag)
    base = {
        "server": "ndl-dl-mcp", "operation": "get_book_fulltext",
        "input_terms": params.item_id, "normalized": params.item_id,
        "params": {"item_id": params.item_id, "pages": params.pages},
        "matching_mode": "identifier_fetch", "start": 0,
        "attribution": ATTRIBUTION, "coverage_note": COVERAGE_NOTE,
    }
    if resp is None:
        return _emit(M.build_envelope(total=0, items=[], diagnostics=diagnostics, **base))

    try:
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
    except zipfile.BadZipFile:
        diagnostics.append(M.diag(
            "error", "NOT_A_ZIP",
            "The fulltext endpoint returned something that is not a ZIP archive. "
            "This interface is undocumented and may have changed.",
            "Inspect the raw response before trusting any other tool here.",
        ))
        return _emit(M.build_envelope(total=0, items=[], diagnostics=diagnostics, **base))

    texts: dict[int, str] = {}
    for name in archive.namelist():
        if not name.endswith(".txt"):
            continue
        m = re.search(r"_(\d+)\.txt$", name)
        if not m:
            continue
        try:
            texts[int(m.group(1))] = archive.read(name).decode("utf-8", errors="replace")
        except KeyError:  # pragma: no cover
            continue

    if not texts:
        diagnostics.append(M.diag(
            "warning", "NO_TEXT_IN_ARCHIVE",
            "The archive held no per-page .txt members, so this item has no OCR "
            "text in the service — which is not the same as the item being blank.",
            "Read the page images instead, or OCR them yourself.",
        ))

    ceiling = max(texts) if texts else 0
    wanted = _parse_page_range(params.pages, ceiling)
    pages = sorted(texts) if wanted is None else [p for p in wanted if p in texts]
    missing = [] if wanted is None else [p for p in wanted if p not in texts]
    if missing:
        diagnostics.append(M.diag(
            "info", "PAGES_NOT_IN_ARCHIVE",
            f"No OCR text for image pages {missing}. The item runs to {ceiling} "
            "text pages in this archive.",
            "Check the page numbering against the viewer: image pages include "
            "covers and plates, so they do not match printed page numbers.",
        ))

    out_pages: list[dict] = []
    used = 0
    truncated_at: Optional[int] = None
    for p in pages:
        body = texts[p]
        if used + len(body) > params.max_chars:
            truncated_at = p
            break
        used += len(body)
        out_pages.append({
            "image_page": p,
            "text": body,
            "page_image_url": _iiif_url(params.item_id, p),
        })
    if truncated_at is not None:
        diagnostics.append(M.diag(
            "warning", "TEXT_TRUNCATED",
            f"Returned {len(out_pages)} of {len(pages)} pages; stopped at image "
            f"page {truncated_at} on the {params.max_chars}-character ceiling.",
            "Request a page range rather than raising the ceiling, or harvest the "
            "item to disk and index it.",
        ))

    item = M.make_item(
        title_ja=None,
        record_type="book",
        matched_in="identifier",
        url_ja=f"{VIEWER_BASE}/{params.item_id}",
        fulltext_url=f"{API_BASE}/api/book/fulltext/{params.item_id}",
        holding_org="国立国会図書館",
        extra={
            "item_id": params.item_id,
            "text_pages_in_archive": len(texts),
            "pages_returned": [p["image_page"] for p in out_pages],
            "pages": out_pages,
            "viewer_url_provenance": PROVENANCE["viewer_url"],
        },
    )
    env = M.build_envelope(total=len(texts), items=[item], diagnostics=diagnostics, **base)
    env["endpoint"] = f"{API_BASE}/api/book/fulltext/{params.item_id}"
    env["endpoint_provenance"] = PROVENANCE["book_fulltext"]
    return _emit(env)


@mcp.tool()
async def ndl_dl_page_image(params: PageImageInput) -> str:
    """Resolve item pages to IIIF image URLs. No request is made and nothing is downloaded.

    Use it when a figure, a table or a doubtful OCR reading has to be looked at.
    The URL pattern was read from the service's client code and has not been
    verified against the library's documentation, so a 404 is a defect in this
    server's assumption rather than evidence the page is absent.
    """
    pages = [p for p in (_parse_page_range(params.pages, 99999) or []) if p >= 1]
    diagnostics = []
    if len(pages) > MAX_PAGE_IMAGES:
        diagnostics.append(M.diag(
            "warning", "PAGE_LIST_CAPPED",
            f"{len(pages)} pages were requested; the first {MAX_PAGE_IMAGES} are resolved.",
            "Request the range you need; ndl_dl_book_fulltext reports how many pages the item has.",
        ))
        pages = pages[:MAX_PAGE_IMAGES]
    if not pages:
        diagnostics.append(M.diag(
            "error", "NO_PAGES_PARSED",
            f"Could not parse any page number from {params.pages!r}.",
            "Use forms like '11', '11-20' or '3,7,11-14'.",
        ))
    item = M.make_item(
        record_type="book", matched_in="identifier",
        url_ja=f"{VIEWER_BASE}/{params.item_id}",
        holding_org="国立国会図書館",
        extra={
            "item_id": params.item_id,
            "page_images": [
                {"image_page": p, "url": _iiif_url(params.item_id, p)} for p in pages
            ],
            "url_provenance": PROVENANCE["iiif_page_image"],
        },
    )
    env = M.build_envelope(
        server="ndl-dl-mcp", operation="resolve_page_image",
        input_terms=params.item_id, normalized=params.item_id,
        params={"item_id": params.item_id, "pages": params.pages},
        matching_mode="identifier_fetch", total=len(pages), start=0,
        items=[item], diagnostics=diagnostics,
        attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
    )
    env["endpoint"] = IIIF_BASE
    env["endpoint_provenance"] = PROVENANCE["iiif_page_image"]
    return _emit(env)


def main() -> None:
    """Console-script entry point.

    Import failures in a bundled server reach the user as nothing more than
    "Server disconnected" — the traceback goes to a log nobody opens. The family
    learned that on 8 September 2026, when every published bundle turned out to
    be CPython 3.12 only. So say something actionable on the way down.
    """
    try:
        mcp.run()
    except ImportError as exc:  # pragma: no cover
        sys.stderr.write(
            "ndl-dl-mcp %s could not start: %s\n"
            "This usually means the interpreter cannot load a dependency built "
            "for another Python version. Check `uv run ndl-dl-mcp` in the bundle "
            "directory and the interpreter it provisions.\n" % (__version__, exc)
        )
        raise


if __name__ == "__main__":
    main()
