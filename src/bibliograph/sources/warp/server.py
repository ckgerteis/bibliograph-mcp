"""
warp-mcp — an MCP server for the NDL Web Archiving Project (WARP,
国立国会図書館インターネット資料収集保存事業).

WARP holds what the National Diet Library has captured of the Japanese web
since 2002, and since the 2010 amendment of the National Diet Library Law
it collects the sites of national and local government, public
corporations and national universities by statute, without asking. For
Japanese public-sector pages it is usually the archive that actually holds
the page, where the Internet Archive holds nothing or a thin sample.

WARP is a browser-first service: the NDL offers no API for bulk or programmatic
access, only ordinary browsing plus the Memento interface this server uses one
URL at a time, with requests serialised and spaced at least MIN_REQUEST_INTERVAL
seconds apart; heavy automated use may be blocked by the NDL. The intended path
through these tools is: to find archived sites by subject, use ndl_search_warp
(the NDL Search catalogue) to get a URL; with that URL, call warp_list_captures
or warp_nearest_capture to find a capture; then warp_read_capture to read it.
Archived content remains the copyright of its original publisher, not the NDL's
or this server's, and the viewer_url each tool returns is the citable form of a
capture, not a URL to redistribute the page's content under.

What this server uses, and why nothing else
-------------------------------------------
WARP supports the Memento protocol (RFC 7089) since July 2023. Its help
page (https://warp.ndl.go.jp/info/help, section 7) gives two entry points,
a TimeMap and a TimeGate, and says 「APIの利用に、必要な手続き等はありません」.
Its Q&A (https://warp.ndl.go.jp/info/qanda) says just as plainly that WARP
is meant to be browsed, that it has no bulk-download or data API, and that
heavy mechanical access will be blocked. This server therefore does three
things a reader in a browser does, one page at a time:

  * reads the TimeMap for one URL (the list of captures WARP holds);
  * picks the capture nearest a date from that TimeMap;
  * opens one capture and returns its text.

It does not crawl, does not follow links, does not paginate through a site,
does not cache, and does not use WARP's full-text search, which has no API.

The undertakings, which are the specification
---------------------------------------------
  * Serial requests only, one at a time across all tools.
  * MIN_REQUEST_INTERVAL seconds between any two requests (3.0).
  * At most MAX_REDIRECT_HOPS archived redirects followed per read.
  * One TimeMap fetch per list or nearest-capture call; no pagination.
  * Nothing stored except the receipt line, and that only when
    MCP_RECEIPT_DIR is set.

Two facts learned by probing on 18 Sep 2026 that shape the code
---------------------------------------------------------------
  1. /web/<timestamp>/<url> is a viewer page, not the capture. The capture
     is in an iframe whose src is /<collection>/<capture-timestamp>/<url>,
     and the capture timestamp there can differ from the one requested
     (a request for 20260801000537 opened 20260705001243). The capture
     timestamp reported is always the one from the iframe.
  2. Some captures are viewable only inside NDL buildings. WARP answers
     those with HTTP 403 and a page titled "Available only within the
     facilities of the National Diet Library, Japan." (seen on a 2010
     capture of www.mhlw.go.jp). That is reported as status
     "ndl_premises_only", never as an absence and never as an error.

An empty TimeMap is also not evidence that WARP lacks the page: WARP keys
captures by exact URL, so http/https, a trailing slash or an explicit
index.html can each miss. The response says so and lists the variants to
try.
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit

import httpx

try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids

__version__ = "0.2.1"

SERVER_NAME = "warp"
BASE = "https://warp.ndl.go.jp"
TIMEMAP_BASE = BASE + "/collections/timemap/"
VIEWER_BASE = BASE + "/web/"
USER_AGENT = (
    f"warp-mcp/{__version__} (scholarly research, one page at a time; "
    "contact christopher.gerteis@soas.ac.uk)"
)

MIN_REQUEST_INTERVAL = 3.0
REQUEST_TIMEOUT = 40.0
MAX_REDIRECT_HOPS = 3
MAX_CAPTURES_RETURNED = 100
MAX_CHARS_RETURNED = 20000
MAX_LINKS_RETURNED = 60

PREMISES_ONLY_MARKER = "Available only within the facilities of the National Diet Library"

ATTRIBUTION = (
    "Source: 国立国会図書館インターネット資料収集保存事業（WARP）, National Diet Library, "
    "https://warp.ndl.go.jp/. Archived pages remain the work of their original publishers; "
    "reuse is governed by WARP's terms of use (see https://warp.ndl.go.jp/)."
)

# stdout is the JSON-RPC channel. Nothing may log to it.
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
log = logging.getLogger("warp_mcp")

# Test seam: a transport to use instead of the network.
_TRANSPORT: Optional[httpx.AsyncBaseTransport] = None

_lock: Optional[asyncio.Lock] = None
_last_request_at = 0.0


# ------------------------------------------------------------------ http


class WarpUnavailable(Exception):
    """WARP did not answer, or answered in a way that means 'back off'."""


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def _get(url: str, headers: Optional[dict] = None) -> httpx.Response:
    """One request, serialised across the whole process and spaced by
    MIN_REQUEST_INTERVAL. Redirects are never followed automatically."""
    global _last_request_at
    async with _get_lock():
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
                transport=_TRANSPORT,
            ) as client:
                resp = await client.get(url, headers=headers or {})
        except httpx.TimeoutException as e:
            raise WarpUnavailable(
                f"WARP did not answer within {REQUEST_TIMEOUT:.0f} s. The NDL throttles "
                "without always sending 429, so treat this as throttling: wait several "
                "minutes before trying again, and do not retry in a loop."
            ) from e
        except httpx.HTTPError as e:
            raise WarpUnavailable(f"Network error reaching WARP: {type(e).__name__}") from e
        finally:
            _last_request_at = time.monotonic()
    if resp.status_code in (429, 503):
        raise WarpUnavailable(
            f"WARP answered HTTP {resp.status_code}: it is asking clients to slow down. "
            "Wait several minutes before the next request."
        )
    return resp


# ------------------------------------------------------------------ urls & dates


_NON_WEB_SCHEMES = {"javascript", "vbscript", "data", "file", "mailto", "tel", "sms", "about",
                    "blob", "ftp", "ws", "wss", "chrome", "view-source"}


def normalise_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise ValueError("url is empty")
    scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):(?!//)", u)
    authority = u.split("/", 1)[0]
    name = scheme.group(1).lower() if scheme else None
    if name in _NON_WEB_SCHEMES or (name and "." not in name and "@" not in authority
                                    and name not in ("http", "https", "localhost")):
        # 7 Oct 2026: javascript:alert(1) became http://javascript:alert(1), went to WARP,
        # and its 403 was reported as WARP_UNAVAILABLE.
        raise ValueError(f"not an http(s) URL: {url!r}")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "http://" + u
    parts = urlsplit(u)
    try:
        port = parts.port
    except ValueError:
        raise ValueError(f"not a valid URL (bad port): {url!r}") from None
    if port == 0:
        raise ValueError(f"not a valid URL (port 0): {url!r}")
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"not an http(s) URL: {url!r}")
    if parts.netloc.lower().endswith("warp.ndl.go.jp"):
        raise ValueError(
            "Pass the ORIGINAL page URL (e.g. https://www.mhlw.go.jp/), not a WARP URL. "
            "To open a capture you already have, pass its original URL and its 14-digit timestamp."
        )
    return u


def url_variants(url: str) -> list[str]:
    """Spellings WARP may hold a page under, other than the one given."""
    parts = urlsplit(url)
    other_scheme = "https" if parts.scheme == "http" else "http"
    path = parts.path or "/"
    out = []
    swap = f"{other_scheme}://{parts.netloc}{path}" + (f"?{parts.query}" if parts.query else "")
    out.append(swap)
    if path.endswith("/"):
        out.append(f"{parts.scheme}://{parts.netloc}{path}index.html")
    elif path.endswith(("/index.html", "/index.htm")):
        out.append(f"{parts.scheme}://{parts.netloc}{path.rsplit('/', 1)[0]}/")
    elif "." not in path.rsplit("/", 1)[-1]:
        out.append(f"{parts.scheme}://{parts.netloc}{path}/")
    if parts.netloc.startswith("www."):
        out.append(f"{parts.scheme}://{parts.netloc[4:]}{path}")
    else:
        out.append(f"{parts.scheme}://www.{parts.netloc}{path}")
    seen, res = {url}, []
    for v in out:
        if v not in seen:
            seen.add(v)
            res.append(v)
    return res


def parse_date_bound(s: Optional[str], *, end: bool = False) -> Optional[str]:
    """'2011', '2011-03', '2011-03-11', '20110311' -> 14-digit timestamp bound."""
    if s is None or str(s).strip() == "":
        return None
    digits = re.sub(r"[^0-9]", "", str(s))
    if len(digits) not in (4, 6, 8, 10, 12, 14):
        raise ValueError(f"date {s!r} must be YYYY, YYYY-MM, YYYY-MM-DD or a 14-digit timestamp")
    if end:
        pad = {4: "1231235959", 6: "31235959", 8: "235959", 10: "5959", 12: "59", 14: ""}
    else:
        pad = {4: "0101000000", 6: "01000000", 8: "000000", 10: "0000", 12: "00", 14: ""}
    ts = digits + pad[len(digits)]
    if end and len(digits) == 6:  # clamp day to month length
        y, m = int(ts[:4]), int(ts[4:6])
        import calendar
        ts = ts[:6] + f"{calendar.monthrange(y, m)[1]:02d}" + ts[8:]
    datetime.strptime(ts, "%Y%m%d%H%M%S")  # validates
    return ts


def ts_to_iso(ts: str) -> str:
    return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def viewer_url(url: str, ts: str) -> str:
    return f"{VIEWER_BASE}{ts}/{url}"


# ------------------------------------------------------------------ timemap


_LINK_RE = re.compile(r'<([^>]*)>((?:\s*;\s*[A-Za-z_-]+\s*=\s*(?:"[^"]*"|[^;,<]*))*)')
_ATTR_RE = re.compile(r'([A-Za-z_-]+)\s*=\s*(?:"([^"]*)"|([^;,<]*))')
_TS_IN_URL = re.compile(r"/web/(\d{14})/")


def parse_timemap(text: str) -> dict:
    """Parse an application/link-format TimeMap into captures (sorted)."""
    captures, meta = [], {}
    for m in _LINK_RE.finditer(text or ""):
        target, attrs_s = m.group(1), m.group(2)
        attrs = {a.group(1).lower(): (a.group(2) if a.group(2) is not None else a.group(3).strip())
                 for a in _ATTR_RE.finditer(attrs_s)}
        rels = attrs.get("rel", "").split()
        if "memento" in rels:
            ts = None
            tm = _TS_IN_URL.search(target)
            if tm:
                ts = tm.group(1)
            elif attrs.get("datetime"):
                try:
                    ts = parsedate_to_datetime(attrs["datetime"]).strftime("%Y%m%d%H%M%S")
                except (TypeError, ValueError, IndexError, OverflowError):
                    meta["unparseable_mementos"] = meta.get("unparseable_mementos", 0) + 1
            if ts:
                captures.append({"timestamp": ts, "datetime_utc": ts_to_iso(ts), "viewer_url": target})
        elif "original" in rels:
            meta["original"] = target
        elif "self" in rels:
            meta["from"] = attrs.get("from")
            meta["until"] = attrs.get("until")
    captures.sort(key=lambda c: c["timestamp"])
    dedup, seen = [], set()
    for c in captures:
        if c["timestamp"] not in seen:
            seen.add(c["timestamp"])
            dedup.append(c)
    return {"captures": dedup, **meta}


async def _fetch_timemap(url: str) -> tuple[dict, int]:
    resp = await _get(TIMEMAP_BASE + url)
    if resp.status_code == 404:
        return {"captures": []}, 404
    if resp.status_code != 200:
        raise WarpUnavailable(f"WARP TimeMap answered HTTP {resp.status_code}")
    return parse_timemap(resp.text), 200


def _memento_diags(tm: dict) -> list[dict]:
    n = tm.get("unparseable_mementos") or 0
    if not n:
        return []
    return [M.diag("warning", "MEMENTO_DATE_UNPARSEABLE",
                   f"{n} TimeMap line(s) carried a date that could not be read and were left out.",
                   "The capture count excludes them; report the URL if this persists.")]


def _year_histogram(captures: list[dict]) -> dict:
    h: dict[str, int] = {}
    for c in captures:
        h[c["timestamp"][:4]] = h.get(c["timestamp"][:4], 0) + 1
    return h


# ------------------------------------------------------------------ html


_IFRAME_SRC = re.compile(r'<iframe[^>]*\bid="pywb-frame"[^>]*\bsrc="([^"]+)"', re.I)
_IFRAME_SRC_ANY = re.compile(r'<iframe[^>]*\bsrc="(/\d+/\d{14}[a-z_]*/[^"]+)"', re.I)
_INNER_PATH = re.compile(r"^/(\d+)/(\d{14})[a-z_]*/(.+)$")
_META_CHARSET = re.compile(rb'<meta[^>]+charset\s*=\s*["\']?\s*([A-Za-z0-9_.:-]+)', re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_HREF = re.compile(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def find_capture_frame(viewer_html: str) -> Optional[str]:
    m = _IFRAME_SRC.search(viewer_html) or _IFRAME_SRC_ANY.search(viewer_html)
    return _html.unescape(m.group(1)) if m else None


def split_inner_path(path: str) -> Optional[tuple[str, str, str]]:
    """'/20260723/20260705001243/https://x/' -> ('20260723','20260705001243','https://x/')"""
    m = _INNER_PATH.match(urlsplit(path).path + (("?" + urlsplit(path).query) if urlsplit(path).query else ""))
    return (m.group(1), m.group(2), m.group(3)) if m else None


def decode_body(content: bytes, header_ct: Optional[str]) -> tuple[str, str]:
    """Decode an archived page. Old Japanese sites are often Shift_JIS or
    EUC-JP and do not always say so in the header."""
    candidates = []
    if header_ct:
        m = re.search(r"charset\s*=\s*([A-Za-z0-9_.:-]+)", header_ct, re.I)
        if m and m.group(1).lower() not in ("iso-8859-1", "latin-1", "us-ascii"):
            candidates.append(m.group(1))
    mm = _META_CHARSET.search(content[:4096])
    if mm:
        candidates.append(mm.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "cp932", "euc_jp", "iso2022_jp"]
    for enc in candidates:
        e = enc.lower().replace("shift_jis", "cp932").replace("shift-jis", "cp932").replace("x-sjis", "cp932")
        try:
            return content.decode(e), e
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace"), "utf-8 (with replacement characters)"


def html_to_text(doc: str) -> str:
    s = re.sub(r"<!--.*?-->", " ", doc, flags=re.S)
    s = re.sub(r"<(script|style|noscript|template)\b.*?</\1\s*>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</?(p|div|li|tr|h[1-6]|table|ul|ol|dl|dt|dd|section|article|header|footer|nav|td|th)\b[^>]*>",
               "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = s.replace("　", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*", "\n", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def extract_links(doc: str, page_url: str) -> list[dict]:
    """Links on an archived page, rewritten back to their ORIGINAL URLs."""
    out, seen = [], set()
    for m in _HREF.finditer(doc):
        href = _html.unescape(m.group(1).strip())
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        inner = split_inner_path(href) if href.startswith("/") else None
        if inner:
            target = inner[2]
        else:
            absu = urljoin(page_url, href)
            p = urlsplit(absu)
            if p.netloc.endswith("warp.ndl.go.jp"):
                inner = split_inner_path(p.path + (("?" + p.query) if p.query else ""))
                if not inner:
                    continue
                target = inner[2]
            else:
                target = absu
        if target in seen:
            continue
        seen.add(target)
        text = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append({"text": text[:120], "original_url": target})
        if len(out) >= MAX_LINKS_RETURNED:
            break
    return out


# ------------------------------------------------------------------ envelope & receipts
#
# Diagnostic codes emitted here (documented in docs/sources/warp/README.md):
#   INVALID_INPUT, WARP_UNAVAILABLE, EMPTY_TIMEMAP, TRUNCATED_BY_LIMIT,
#   NO_CAPTURES_IN_RANGE, NDL_PREMISES_ONLY, CAPTURE_TIMESTAMP_DIFFERS_FROM_REQUEST,
#   REDIRECT_HOP_LIMIT, REDIRECT_TARGET_UNPARSEABLE, REDIRECT_TARGET_NOT_ARCHIVED,
#   NON_HTML, NO_CAPTURE_FRAME, ENCODING_UNCERTAIN, VIEWER_<http_status>,
#   ARCHIVED_REDIRECT_UNRESOLVED, CAPTURE_<http_status>, MEMENTO_DATE_UNPARSEABLE,
#   OK (mediation's default).

MATCHING_MODE = "exact_url"


def _url_field_kwargs(u: str, title: Optional[str] = None) -> dict:
    """Where to put the capture's URL: ids.url_ja by default, ids.url_en only
    when a page title is known and is not Japanese-scripted."""
    if title and M.detect_script(title) not in ("han", "kana", "han_kana", "hangul", "han_hangul", "mixed"):
        return {"url_en": u}
    return {"url_ja": u}


def _receipt_id(it: dict):
    """A capture is named by its viewer URL, which carries the timestamp; the
    original URL alone would not say which capture was read (see receipt_ids)."""
    ids, ex = it.get("ids") or {}, _rids.extra_of(it)
    if ex.get("viewer_url"):
        return ex["viewer_url"]
    orig = ids.get("url_ja") or ids.get("url_en")
    ts = ex.get("capture_timestamp") or ex.get("timestamp")
    return viewer_url(orig, ts) if orig and ts else orig


def _emit(op: str, input_terms: str, normalized: str, params: dict, items: list[dict],
         total: int, diagnostics: list[dict], suggestions: Optional[list[dict]] = None) -> dict:
    env = M.build_envelope(
        server=SERVER_NAME, operation=op, input_terms=input_terms, normalized=normalized,
        params={k: v for k, v in params.items() if v is not None}, matching_mode=MATCHING_MODE,
        total=total, start=1, items=items, diagnostics=diagnostics, attribution=ATTRIBUTION,
        suggestions=suggestions,
    )
    M.emit(_rids.finish(env, _receipt_id))  # deposits the receipt (when configured) and serialises; we keep the dict
    return env


def _invalid_input(op: str, url: str, params: dict, message: str) -> dict:
    return _emit(op, url, url, params, [], 0,
                [M.diag("error", "INVALID_INPUT", message, "Fix the argument and retry.")])


def _warp_unavailable(op: str, url: str, u: str, params: dict, message: str) -> dict:
    return _emit(op, url, u, params, [], 0,
                [M.diag("error", "WARP_UNAVAILABLE", message,
                        "WARP may be throttling without a 429; wait several minutes before retrying.")])


def _empty_timemap(op: str, url: str, u: str, params: dict, extra: Optional[list] = None) -> dict:
    variants = url_variants(u)
    diags = [M.diag(
        "info", "EMPTY_TIMEMAP",
        "WARP returned an empty TimeMap for this exact URL. That is not evidence that WARP lacks "
        "the page: captures are keyed by exact URL, so scheme, www., a trailing slash or an explicit "
        "index.html can each be held separately.",
        "Try a variant spelling from `suggestions`, or the site's top page. WARP's full-text search "
        "has no API and must be used in a browser.",
    )]
    suggestions = [{"url": v, "reason": "alternate spelling WARP may hold this capture under"} for v in variants]
    return _emit(op, url, u, params, [], 0, diags + list(extra or []), suggestions=suggestions)


# ------------------------------------------------------------------ tools (plain async functions, testable)


async def list_captures(url: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
                        limit: int = 50, newest_first: bool = False) -> dict:
    op = "warp_list_captures"
    params = {"from_date": from_date, "to_date": to_date, "limit": limit, "newest_first": newest_first}
    try:
        u = normalise_url(url)
        lo, hi = parse_date_bound(from_date), parse_date_bound(to_date, end=True)
        limit = max(1, min(int(limit), MAX_CAPTURES_RETURNED))
    except (ValueError, TypeError) as e:
        return _invalid_input(op, url, params, str(e))
    q = {**params, "from": lo, "to": hi, "limit": limit}
    try:
        tm, _ = await _fetch_timemap(u)
    except WarpUnavailable as e:
        return _warp_unavailable(op, url, u, q, str(e))
    caps = tm["captures"]
    if not caps:
        return _empty_timemap(op, url, u, q, _memento_diags(tm))
    inrange = [c for c in caps if (lo is None or c["timestamp"] >= lo) and (hi is None or c["timestamp"] <= hi)]
    ordered = list(reversed(inrange)) if newest_first else inrange
    shown = ordered[:limit]
    diags = _memento_diags(tm)
    if len(inrange) > len(shown):
        diags.append(M.diag("info", "TRUNCATED_BY_LIMIT",
                            f"{len(inrange)} capture(s) in range; {len(shown)} returned (limit={limit}).",
                            "Raise `limit` (max 100), or narrow from_date/to_date, to see the rest."))
    if (lo or hi) and not inrange:
        diags.append(M.diag("info", "NO_CAPTURES_IN_RANGE",
                            f"WARP holds {len(caps)} capture(s) of this URL, none in the requested date range.",
                            "Widen or drop from_date/to_date."))
    year_hist = _year_histogram(caps)
    first_dt, last_dt = caps[0]["datetime_utc"], caps[-1]["datetime_utc"]
    items = [
        M.make_item(
            **_url_field_kwargs(u), year=int(c["timestamp"][:4]),
            matched_in="capture_list", record_type="web_capture",
            extra={
                "timestamp": c["timestamp"], "datetime_utc": c["datetime_utc"], "viewer_url": c["viewer_url"],
                "captures_by_year": year_hist, "first_capture": first_dt, "last_capture": last_dt,
            },
        )
        for c in shown
    ]
    return _emit(op, url, u, q, items, len(caps), diags)


async def nearest_capture(url: str, date: str) -> dict:
    op = "warp_nearest_capture"
    params = {"date": date}
    try:
        u = normalise_url(url)
        target = parse_date_bound(date)
    except (ValueError, TypeError) as e:
        return _invalid_input(op, url, params, str(e))
    q = {"date": target}
    try:
        tm, _ = await _fetch_timemap(u)
    except WarpUnavailable as e:
        return _warp_unavailable(op, url, u, q, str(e))
    caps = tm["captures"]
    if not caps:
        return _empty_timemap(op, url, u, q, _memento_diags(tm))
    tdt = datetime.strptime(target, "%Y%m%d%H%M%S")
    before = [c for c in caps if c["timestamp"] <= target]
    after = [c for c in caps if c["timestamp"] > target]
    b = before[-1] if before else None
    a = after[0] if after else None

    def gap(c):
        return abs((datetime.strptime(c["timestamp"], "%Y%m%d%H%M%S") - tdt).total_seconds())

    nearest = min([c for c in (b, a) if c], key=gap)
    item = M.make_item(
        **_url_field_kwargs(u), year=int(nearest["timestamp"][:4]),
        matched_in="nearest_capture", record_type="web_capture",
        extra={
            "timestamp": nearest["timestamp"], "datetime_utc": nearest["datetime_utc"],
            "viewer_url": nearest["viewer_url"], "days_from_requested": round(gap(nearest) / 86400, 1),
            "requested": ts_to_iso(target), "at_or_before": b, "after": a,
            "total_captures": len(caps), "captures_by_year": _year_histogram(caps),
            "first_capture": caps[0]["datetime_utc"], "last_capture": caps[-1]["datetime_utc"],
            "note": ("Chosen from WARP's TimeMap, not its TimeGate: the TimeGate redirects to the "
                     "requested timestamp rather than to a capture. When the before and after "
                     "captures straddle an event, say which one you read."),
        },
    )
    return _emit(op, url, u, q, [item], len(caps), _memento_diags(tm))


def _title_field_kwargs(title: Optional[str]) -> dict:
    if not title:
        return {}
    if M.detect_script(title) in ("han", "kana", "han_kana", "hangul", "han_hangul", "mixed"):
        return {"title_ja": title}
    return {"title_en": title}


async def read_capture(url: str, timestamp: str, max_chars: int = 6000, offset: int = 0,
                       include_links: bool = False) -> dict:
    op = "warp_read_capture"
    params = {"timestamp": timestamp, "max_chars": max_chars, "offset": offset, "include_links": include_links}
    try:
        u = normalise_url(url)
        ts = re.sub(r"[^0-9]", "", str(timestamp))
        if len(ts) != 14:
            raise ValueError("timestamp must be the 14-digit YYYYMMDDhhmmss of a capture "
                             "(from warp_list_captures or warp_nearest_capture)")
        datetime.strptime(ts, "%Y%m%d%H%M%S")
        max_chars = max(200, min(int(max_chars), MAX_CHARS_RETURNED))
        offset = max(0, int(offset))
    except (ValueError, TypeError) as e:
        return _invalid_input(op, url, params, str(e))
    q = {**params, "timestamp": ts}
    diags: list[dict] = []
    hops: list[dict] = []
    try:
        viewer = viewer_url(u, ts)
        vresp = await _get(viewer)
        if vresp.status_code != 200:
            code = "VIEWER_" + str(vresp.status_code)
            diags = [M.diag("error", code,
                            f"WARP's viewer page answered HTTP {vresp.status_code} for this URL/timestamp.",
                            "Check the URL and timestamp, or use warp_list_captures / warp_nearest_capture "
                            "to find a valid one.")]
            suggestions = None
            if vresp.status_code == 404:
                suggestions = [{"url": v, "reason": "alternate spelling WARP may hold this capture under"}
                               for v in url_variants(u)]
            return _emit(op, url, u, q, [], 0, diags, suggestions=suggestions)
        frame = find_capture_frame(vresp.text)
        if not frame:
            diags = [M.diag("error", "NO_CAPTURE_FRAME",
                            "WARP's viewer page carried no capture frame. WARP may have changed its page layout.",
                            "Open the viewer URL in a browser.")]
            return _emit(op, url, u, q, [], 0, diags)
        frame_url = urljoin(BASE, frame)
        resp = await _get(frame_url, headers={"Referer": viewer})
        for _ in range(MAX_REDIRECT_HOPS + 1):
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                if len(hops) >= MAX_REDIRECT_HOPS:
                    diags.append(M.diag("warning", "REDIRECT_HOP_LIMIT",
                                        f"Stopped after {MAX_REDIRECT_HOPS} archived redirect(s).",
                                        "Open the viewer URL in a browser to follow further redirects."))
                    break
                loc = urljoin(frame_url, resp.headers["location"])
                # The redirect target is rarely captured at the same instant or in the same
                # collection, and WARP's inner frame path does not do closest-match (measured
                # 18 Sep 2026: /20260723/20260705001243/.../index.html -> 404). So every hop
                # goes back through the viewer, which resolves the nearest capture.
                lp = urlsplit(loc)
                if lp.netloc.endswith("warp.ndl.go.jp"):
                    inner = split_inner_path(lp.path + (("?" + lp.query) if lp.query else ""))
                    target, hop_ts = (inner[2], inner[1]) if inner else (None, ts)
                else:
                    target, hop_ts = loc, (split_inner_path(urlsplit(frame_url).path) or (None, ts))[1]
                hops.append({"archived_status": resp.status_code, "to_original_url": target})
                if not target:
                    diags.append(M.diag("warning", "REDIRECT_TARGET_UNPARSEABLE",
                                        "The archived redirect's target could not be parsed.", None))
                    break
                viewer = viewer_url(target, hop_ts)
                v2 = await _get(viewer)
                f2 = find_capture_frame(v2.text) if v2.status_code == 200 else None
                if not f2:
                    diags.append(M.diag("warning", "REDIRECT_TARGET_NOT_ARCHIVED",
                                        "The redirect target is not itself archived by WARP.", None))
                    break
                frame_url = urljoin(BASE, f2)
                resp = await _get(frame_url, headers={"Referer": viewer})
            else:
                break
    except WarpUnavailable as e:
        diags = [M.diag("error", "WARP_UNAVAILABLE", str(e),
                        "WARP may be throttling without a 429; wait several minutes before retrying.")]
        items = []
        if hops:
            items = [M.make_item(**_url_field_kwargs(u), matched_in="capture_read", record_type="web_capture",
                                 extra={"status": "warp_unavailable", "redirects": hops})]
        return _emit(op, url, u, q, items, 0, diags)

    parts = split_inner_path(urlsplit(frame_url).path + (("?" + urlsplit(frame_url).query) if urlsplit(frame_url).query else ""))
    collection, cap_ts, cap_url = parts if parts else (None, None, u)
    base_extra = {
        "original_url": cap_url,
        "requested_timestamp": ts,
        "capture_timestamp": cap_ts,
        "capture_datetime_utc": ts_to_iso(cap_ts) if cap_ts else None,
        "collection": collection,
        "viewer_url": viewer_url(cap_url, cap_ts) if cap_ts else viewer,
        "redirects": hops,
    }
    cap_year = int(cap_ts[:4]) if cap_ts else None
    if cap_ts and cap_ts != ts:
        diags.append(M.diag("info", "CAPTURE_TIMESTAMP_DIFFERS_FROM_REQUEST",
                            f"WARP served capture {cap_ts}, not the requested {ts}.",
                            "This is normal: /web/<ts>/<url> is a viewer page whose iframe can point to a "
                            "nearby capture, not necessarily the one requested."))

    body_head = resp.text[:4000] if resp.content else ""
    if resp.status_code == 403 and PREMISES_ONLY_MARKER in body_head:
        diags.append(M.diag(
            "info", "NDL_PREMISES_ONLY",
            "WARP holds this capture but makes it viewable only on NDL premises (Tokyo Main Library, "
            "Kansai-kan, International Library of Children's Literature). This is a finding about "
            "access, not an absence.",
            "A later capture of the same URL may be public: check warp_list_captures.",
        ))
        item = M.make_item(**_url_field_kwargs(cap_url), year=cap_year, matched_in="capture_read",
                           record_type="web_capture", extra={**base_extra, "status": "ndl_premises_only"})
        return _emit(op, url, u, q, [item], 1, diags)
    if resp.status_code in (301, 302, 303, 307, 308):
        item = M.make_item(**_url_field_kwargs(cap_url), year=cap_year, matched_in="capture_read",
                           record_type="web_capture",
                           extra={**base_extra, "status": "archived_redirect_unresolved",
                                  "archived_http_status": resp.status_code, "location": resp.headers.get("location")})
        return _emit(op, url, u, q, [item], 1, diags)
    if resp.status_code >= 400:
        diags.append(M.diag("warning", "CAPTURE_" + str(resp.status_code),
                            "WARP returned an error status for the capture itself.",
                            "Open the viewer URL in a browser."))
        item = M.make_item(**_url_field_kwargs(cap_url), year=cap_year, matched_in="capture_read",
                           record_type="web_capture",
                           extra={**base_extra, "status": "archived_error_status",
                                  "archived_http_status": resp.status_code})
        return _emit(op, url, u, q, [item], 1, diags)

    ctype = (resp.headers.get("content-type") or "").lower()
    if "html" not in ctype and "xml" not in ctype and not ctype.startswith("text/"):
        diags.append(M.diag("info", "NON_HTML",
                            "The capture is not a web page (e.g. a PDF). This server does not download files.",
                            "Open the viewer URL in a browser."))
        item = M.make_item(**_url_field_kwargs(cap_url), year=cap_year, matched_in="capture_read",
                           record_type="web_capture",
                           extra={**base_extra, "status": "non_html", "content_type": ctype,
                                  "bytes": len(resp.content)})
        return _emit(op, url, u, q, [item], 1, diags)

    text_doc, encoding = decode_body(resp.content, resp.headers.get("content-type"))
    tm = _TITLE.search(text_doc)
    title = re.sub(r"\s+", " ", _html.unescape(tm.group(1))).strip() if tm else None
    full = html_to_text(text_doc) if "html" in ctype or "<html" in text_doc[:2000].lower() else text_doc
    chunk = full[offset:offset + max_chars]
    extra = {
        **base_extra,
        "status": "ok",
        "archived_http_status": resp.status_code,
        "content_type": ctype,
        "decoded_as": encoding,
        "total_chars": len(full),
        "offset": offset,
        "returned_chars": len(chunk),
        "truncated": offset + len(chunk) < len(full),
        "text": chunk,
    }
    if include_links:
        extra["links"] = extract_links(text_doc, cap_url)
    if "replacement" in encoding:
        diags.append(M.diag("warning", "ENCODING_UNCERTAIN",
                            f"Decoded with replacement characters ({encoding}).",
                            "The archived page's declared encoding may be wrong; check the text for mojibake."))
    item = M.make_item(**_url_field_kwargs(cap_url, title), **_title_field_kwargs(title), year=cap_year,
                       matched_in="capture_read", record_type="web_capture", extra=extra)
    return _emit(op, url, u, q, [item], 1, diags)


# ------------------------------------------------------------------ MCP wiring


mcp = _MCPServer("warp")


@mcp.tool()
async def warp_list_captures(url: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
                             limit: int = 50, newest_first: bool = False) -> dict:
    """List the captures the NDL Web Archiving Project (WARP) holds for ONE exact URL.

    WARP is browser-first: the NDL offers no API for bulk use, only Memento access one URL
    at a time, spaced at least MIN_REQUEST_INTERVAL seconds apart; heavy automated use may
    be blocked. Don't know the URL yet? Use ndl_search_warp first to find the site by
    subject in the NDL catalogue, then pass its URL here.

    Returns the total number of captures, first and last capture, a count per year, and up
    to `limit` captures (max 100) inside the optional date range, each with its 14-digit
    timestamp and citable viewer URL. One request to WARP. Pass a timestamp to
    warp_read_capture to read one. Archived content remains the copyright of its original
    publisher; the viewer_url is the citable form of a capture.

    Args:
        url: the ORIGINAL page URL, e.g. "https://www.mhlw.go.jp/". Exact spelling matters.
        from_date: optional lower bound, "YYYY", "YYYY-MM" or "YYYY-MM-DD".
        to_date: optional upper bound, same formats (inclusive).
        limit: captures to list, 1-100 (default 50).
        newest_first: list the newest captures first.

    An empty result is NOT proof that WARP lacks the page; the response lists URL
    variants to try.
    """
    return await list_captures(url, from_date, to_date, limit, newest_first)


@mcp.tool()
async def warp_nearest_capture(url: str, date: str) -> dict:
    """Find the WARP capture of ONE exact URL nearest to a date, plus the captures just
    before and just after it.

    WARP is browser-first: the NDL offers no API for bulk use, only Memento access one URL
    at a time, spaced at least MIN_REQUEST_INTERVAL seconds apart; heavy automated use may
    be blocked. Don't know the URL yet? Use ndl_search_warp first to find the site by
    subject, then pass its URL here.

    Args:
        url: the ORIGINAL page URL.
        date: "YYYY", "YYYY-MM", "YYYY-MM-DD" or a 14-digit timestamp.

    One request to WARP. Use the returned timestamp with warp_read_capture. Archived
    content remains the copyright of its original publisher; the viewer_url is the
    citable form of a capture.
    """
    return await nearest_capture(url, date)


@mcp.tool()
async def warp_read_capture(url: str, timestamp: str, max_chars: int = 6000, offset: int = 0,
                            include_links: bool = False) -> dict:
    """Open one WARP capture and return its text.

    WARP is browser-first: the NDL offers no API for bulk use, only Memento access one URL
    at a time, spaced at least MIN_REQUEST_INTERVAL seconds apart; heavy automated use may
    be blocked. This tool reads one capture, found beforehand with warp_list_captures or
    warp_nearest_capture (and those, in turn, from a URL found by subject with
    ndl_search_warp if you did not already have one).

    Args:
        url: the ORIGINAL page URL.
        timestamp: the 14-digit capture timestamp from warp_list_captures or
            warp_nearest_capture.
        max_chars: characters of text to return (200-20000, default 6000).
        offset: character offset for reading a long page in pieces.
        include_links: also return up to 60 links on the page, rewritten to their original
            URLs (useful for finding PDFs and sub-pages; this server does not open them).

    Two requests to WARP (viewer page, then capture), plus one per archived redirect, up to
    three. Reports status "ndl_premises_only" when WARP holds the capture but limits it to
    NDL buildings — a finding about access, not an absence. The capture timestamp returned
    may differ from the one requested. Archived content remains the copyright of its
    original publisher, not the NDL's or this server's; cite the returned viewer_url, the
    citable form of the capture, not a URL to redistribute the page's content under.
    """
    return await read_capture(url, timestamp, max_chars, offset, include_links)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
