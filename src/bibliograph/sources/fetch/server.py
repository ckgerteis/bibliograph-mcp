"""
bibliograph fetch: open-access PDFs into a folder you name, with provenance
=====================================================================

Two tools, added in bibliograph 1.3.0:

  fetch_pdf        download one open-access PDF that a source names, save it to
                   BIBLIOGRAPH_DOWNLOAD_DIR beside a provenance file, and report
                   which of its pages carry a text layer
  fetch_pdf_text   return the text layer of a PDF already saved there, by page

Why it is shaped this way
-------------------------
bibliograph finds sources and records how they were found. Until 1.3.0 a PDF left
that record at the moment it entered a historian's files: the skills that
downloaded did so outside the receipts ledger. Here the download is itself a
receipted operation. The receipt names the record and the SHA-256 of the file
saved, and a provenance file beside the PDF says where it came from, under what
licence the source reported it, and when.

What it will and will not fetch
-------------------------------
* `via="openalex"` or `via="semantic_scholar"`: the open-access copy that the
  source itself names for a work, looked up afresh at the moment of download.
  The licence and open-access status are reported as the source states them.
  A work with no open-access copy is refused with NO_OA_COPY; licensed access
  belongs to your institution's licensed access, not here.
* `via="url"`: a PDF address the caller supplies, typically a `fulltext_url`
  from another source's result (Korea's OAK, for instance). No licence is
  checked, and the envelope says so (SUPPLIED_URL_NO_LICENCE_CHECK).
* Only http(s) addresses on public hosts, checked at every redirect hop. Only
  files that begin as PDFs: a landing or login page is refused (NOT_A_PDF) and
  nothing is written. At most MAX_BYTES. One file per call; no batch, no harvest.
* Nothing is written anywhere unless BIBLIOGRAPH_DOWNLOAD_DIR names a folder, and
  fetch_pdf_text reads only files inside that folder.

Text, not OCR
-------------
The text returned is the PDF's own text layer, as the publisher embedded it.
Pages with none are listed, so that they go to an OCR server (the ocr-mcp
`ocr_document` tool, for instance) rather than being read as empty. A PDF that
forbids text extraction is not extracted (TEXT_EXTRACTION_NOT_PERMITTED).
Japanese set vertically can come out of a text layer in an order that has to be
checked against the page before anything is quoted.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids
from ..openalex import server as _OA
from ..semantic_scholar import server as _S2

__version__ = "0.1.0"

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# ==============================================================================
# Configuration
# ==============================================================================

SERVER_NAME = "fetch"
DOWNLOAD_ENV = "BIBLIOGRAPH_DOWNLOAD_DIR"
MAX_BYTES = 100 * 1024 * 1024
MAX_REDIRECTS = 5
DOWNLOAD_DEADLINE = 300.0   # seconds for a whole download, so a slow drip cannot hold the lock
PARSE_DEADLINE = 120.0      # seconds for reading a text layer
MAX_CANDIDATES = 3
TIMEOUT = 60.0
MIN_REQUEST_INTERVAL = 2.0
PROBE_PAGE_LIMIT = 600      # fetch_pdf_text reads at most this far without a page range
FETCH_PROBE_PAGES = 40      # fetch_pdf checks the text layer on this many pages, to stay quick
MIN_TEXT_CHARS = 25          # fewer non-space characters than this is a page without a text layer
# A page is a scan with someone else's OCR on it when one picture covers at least
# IMAGE_PAGE_SHARE of the page AND at least OCR_OVERLAY_SHARE of its text sits on that
# picture. The second test is what keeps a born-digital page with a large photograph
# from being called a scan. (A repository scan probed on 7 Oct 2026 covered 50% of a
# page whose MediaBox had wide margins, so the first threshold is set low.)
IMAGE_PAGE_SHARE = 0.25
OCR_OVERLAY_SHARE = 0.8
TEXT_DEFAULT_CHARS = 20000
USER_AGENT = (f"bibliograph-mcp fetch/{__version__} (one person-initiated download of an "
              "open-access copy; no harvesting)")

ATTRIBUTION = (
    "Open-access copy as named by the source consulted (OpenAlex, CC0 metadata; or the "
    "Semantic Scholar Academic Graph, Allen Institute for AI; or the address supplied). "
    "The file is the publisher's or repository's, under the licence reported with it."
)
COVERAGE_NOTE = (
    "Fetches only a copy the source names as open access, or an address the caller "
    "supplies. Licence and open-access status are as the source reports them and govern "
    "reuse; a work with no open-access copy is refused, not looked for elsewhere. Text is "
    "the PDF's own text layer, unrevised; pages without one need OCR, and vertical "
    "Japanese setting must be checked against the page before quotation."
)
OCR_HINT = ("Run these pages through OCR (for example the ocr-mcp server's ocr_document) "
            "before reading or quoting them; an empty text layer is not an empty page.")

_TRANSPORT: Optional[httpx.AsyncBaseTransport] = None  # tests substitute a MockTransport
_lock_obj: Optional[asyncio.Lock] = None
_last_request_at = 0.0


def _lock() -> asyncio.Lock:
    global _lock_obj
    if _lock_obj is None:
        _lock_obj = asyncio.Lock()
    return _lock_obj


class Refused(Exception):
    """A typed reason a fetch did not happen; becomes a diagnostic."""

    def __init__(self, code: str, message: str, hint: Optional[str] = None, level: str = "error"):
        super().__init__(message)
        self.code, self.message, self.hint, self.level = code, message, hint, level

    def diag(self) -> dict:
        return M.diag(self.level, self.code, self.message, self.hint)


# ==============================================================================
# The folder
# ==============================================================================

def download_dir() -> Optional[Path]:
    """The configured folder, or None. An unexpanded manifest placeholder counts as unset."""
    raw = (os.environ.get(DOWNLOAD_ENV) or "").strip()
    if not raw or raw.startswith("${"):
        return None
    return Path(raw).expanduser()


def inside(base: Path, candidate: Path) -> bool:
    try:
        b, c = base.resolve(), candidate.resolve()
    except OSError:
        return False
    return c == b or b in c.parents


_SLUG = re.compile(r"[^A-Za-z0-9._-]+")


def slug_for(via: str, record: str) -> str:
    """A filesystem-safe stem naming where the file came from."""
    if via == "url":
        base = f"url-{urlsplit(record).hostname or 'url'}"
    else:
        base = f"{'oa' if via == 'openalex' else 's2'}-{record}"
    base = _SLUG.sub("_", base).strip("._-")[:80]
    return base or "pdf"


_SECRET_PARAM = re.compile(
    r"(token|signature|sig|key|secret|password|passwd|policy|credential|x-amz-|expires|auth|jwt|"
    r"sid|session|code|access|ticket|hmac)", re.I)


def redact_url(url: str) -> str:
    """The address as it may appear in an envelope, receipt or provenance file:
    user information and fragments dropped, credential-like query values removed."""
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        port = p.port
    except ValueError:
        return "(unparseable address)"
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{port}" if port else "")
    q = [(k, "REDACTED" if _SECRET_PARAM.search(k) else v) for k, v in parse_qsl(p.query, keep_blank_values=True)]
    return urlunsplit((p.scheme, netloc, p.path, urlencode(q) if q else "", ""))


def _sha_file(path: Path) -> Optional[str]:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_saved(d: Path, sha: str) -> Optional[Path]:
    """A PDF already in the folder with exactly this SHA-256 (the name carries only
    its first 12 hex digits, so the whole hash is checked)."""
    try:
        candidates = sorted(d.glob(f"*-{sha[:12]}.pdf"))
    except OSError:
        return None
    return next((c for c in candidates if _sha_file(c) == sha), None)


def write_atomic(path: Path, data: bytes) -> None:
    """Write beside the target under a unique name, then rename; never leave the
    temporary file behind."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def read_provenance(path: Path, base: Path) -> dict:
    """The provenance record beside a PDF, or {}. Only read inside the folder."""
    if not inside(base, path) or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def first_fetch(prov: dict) -> dict:
    """The first fetch recorded; older single-record files are read as one fetch."""
    fetches = prov.get("fetches")
    if isinstance(fetches, list) and fetches and isinstance(fetches[0], dict):
        return fetches[0]
    return prov


def page_ranges(pages: list[int]) -> str:
    """[1, 2, 3, 7] -> '1-3, 7'."""
    out, run = [], []
    for p in sorted(set(pages)):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        if run:
            out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [p]
    if run:
        out.append(f"{run[0]}-{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


def parse_pages(spec: Optional[str], ceiling: int = 100000) -> Optional[list[int]]:
    """'5', '5-20', '3,7,11-14' -> sorted page list (1-based). None for all pages.
    Raises ValueError on anything else."""
    if spec is None or not spec.strip():
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d{1,6})(?:\s*-\s*(\d{1,6}))?", part)
        if not m:
            raise ValueError(f"cannot read the page list {spec!r}; use forms like '5', '5-20' or '3,7,11-14'")
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if lo > hi:
            lo, hi = hi, lo
        if hi > ceiling:
            raise ValueError(f"page {hi} is beyond any document this tool reads (ceiling {ceiling})")
        pages.update(range(max(lo, 1), hi + 1))
    return sorted(pages)


# ==============================================================================
# Address checks
# ==============================================================================

def _ip_is_public(ip: str) -> bool:
    """Globally routable only. IPv6 forms that carry an IPv4 address (mapped, 6to4,
    Teredo, NAT64) are judged by the address they carry. CGNAT (100.64/10) and
    site-local space are not public (second-model review, 7 Oct 2026)."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address):
        teredo = a.teredo[1] if a.teredo else None
        for inner in (a.ipv4_mapped, a.sixtofour, teredo):
            if inner is not None:
                return _ip_is_public(str(inner))
        if a in ipaddress.ip_network("64:ff9b::/96"):
            return _ip_is_public(str(ipaddress.IPv4Address(int(a) & 0xFFFFFFFF)))
        if a.is_site_local:  # deprecated fec0::/10, which Python still counts as global
            return False
    return a.is_global and not a.is_multicast


async def vet(url: str) -> tuple[Optional[str], Optional[str]]:
    """(reason the address is refused, or None; the public IP to connect to).

    The connection is then made to that IP, with the original host name in the
    Host header and for TLS verification, so a name that answers differently a
    moment later (DNS rebinding) cannot move the download onto a private address."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "not a valid address", None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "not an http(s) address", None
    host = parts.hostname
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, port or 443, 0, socket.SOCK_STREAM)
        except OSError:
            return f"the host {host} could not be resolved", None
        addrs = sorted({i[4][0] for i in infos})
    if not addrs or not all(_ip_is_public(a) for a in addrs):
        return f"the host {host} is not a public address", None
    return None, addrs[0]


async def public_host(url: str) -> Optional[str]:
    """The refusal reason alone (None when the address may be fetched)."""
    return (await vet(url))[0]


def pinned(url: str, ip: str) -> tuple[str, dict, dict]:
    """(address with the host replaced by the vetted IP, headers, extensions)."""
    p = urlsplit(url)
    host = p.hostname or ""
    shown_host = f"[{host}]" if ":" in host else host
    ip_host = f"[{ip}]" if ":" in ip else ip
    suffix = f":{p.port}" if p.port else ""
    target = urlunsplit((p.scheme, ip_host + suffix, p.path or "/", p.query, ""))
    return target, {"Host": shown_host + suffix}, {"sni_hostname": host}


# ==============================================================================
# Resolving a record to the PDF addresses its source names
# ==============================================================================

def _http(u: Any) -> bool:
    return isinstance(u, str) and u.startswith(("http://", "https://"))


def openalex_candidates(w: dict) -> tuple[list[str], dict]:
    """PDF addresses OpenAlex names for a work, best first, and what it says of them.
    open_access.oa_url can be a landing page; it is tried last, and the PDF check
    refuses it if it is not a PDF."""
    best = w.get("best_oa_location") if isinstance(w.get("best_oa_location"), dict) else {}
    oa = w.get("open_access") if isinstance(w.get("open_access"), dict) else {}
    urls: list[str] = []
    for u in [best.get("pdf_url")] + [
            loc.get("pdf_url") for loc in (w.get("locations") if isinstance(w.get("locations"), list) else [])
            if isinstance(loc, dict) and loc.get("is_oa")] + [oa.get("oa_url")]:
        if _http(u) and u not in urls:
            urls.append(u)
    src = best.get("source") if isinstance(best.get("source"), dict) else {}
    info = {"is_oa": oa.get("is_oa"), "oa_status": oa.get("oa_status"),
            "licence": best.get("license"), "version": best.get("version"),
            "host": src.get("display_name")}
    return urls[:MAX_CANDIDATES], info


def s2_candidates(p: dict) -> tuple[list[str], dict]:
    pdf = p.get("openAccessPdf") if isinstance(p.get("openAccessPdf"), dict) else {}
    urls = [pdf["url"]] if _http(pdf.get("url")) else []
    info = {"is_oa": bool(urls), "oa_status": pdf.get("status"), "licence": pdf.get("license"),
            "version": None, "host": None}
    return urls, info


async def resolve(via: str, record: str) -> dict:
    """Look the record up afresh at its source. Returns
    {candidates, info, title, doi, record_id, error_diag}."""
    out: dict[str, Any] = {"candidates": [], "info": {}, "title": None, "doi": None,
                           "record_id": record, "error_diag": None}
    if via == "url":
        if not _http(record):
            out["error_diag"] = M.diag("error", "BAD_IDENTIFIER", f"{record!r} is not an http(s) address.",
                                       "With via='url', pass the PDF's full address.")
            return out
        out["candidates"] = [record]
        out["info"] = {"is_oa": None, "oa_status": None, "licence": None, "version": None,
                       "host": urlsplit(record).hostname}
        return out
    if via == "openalex":
        rid = record.strip()
        if rid.lower().startswith("https://openalex.org/"):
            rid = rid.rsplit("/", 1)[-1]
        if (not (rid.startswith("10.") or rid.lower().startswith("https://doi.org/") or re.fullmatch(r"[Ww]\d+", rid))
                or re.search(r"[?#\s]|\.\./", rid)):
            out["error_diag"] = M.diag("error", "BAD_IDENTIFIER", f"{record!r} is not an OpenAlex work id or DOI.",
                                       "Pass e.g. 'W2741809807' or '10.1017/S0026749X10000156'.")
            return out
        data, err = await _OA._oa_request(f"works/{_OA._as_work_id(rid)}")
        if err:
            out["error_diag"] = err
            return out
        if not isinstance(data, dict):
            out["error_diag"] = M.diag("error", "API_ERROR", "OpenAlex returned a record of an unexpected shape.",
                                       "Report the id; do not treat the work as absent.")
            return out
        out["candidates"], out["info"] = openalex_candidates(data)
        out["title"] = data.get("display_name") or data.get("title")
        out["doi"] = _OA._bare_doi(data.get("doi")) if isinstance(data.get("doi"), str) else None
        oid = data.get("id")
        out["record_id"] = oid.rsplit("/", 1)[-1] if isinstance(oid, str) else rid
        return out
    # semantic_scholar
    pid = record.strip()
    if pid.lower().startswith("s2:"):
        pid = pid[3:]
    if pid.startswith("10."):
        pid = "DOI:" + pid
    if not pid or re.search(r"[?#\s]|\.\./", pid):
        out["error_diag"] = M.diag("error", "BAD_IDENTIFIER", f"{record!r} is not a Semantic Scholar paper id or DOI.",
                                   "Pass e.g. a 40-character paper id or '10.1017/S0026749X10000156'.")
        return out
    data, err = await _S2._api_request("GET", f"{_S2.API_BASE}/paper/{pid}",
                                       params={"fields": "title,externalIds,openAccessPdf"})
    if err:
        out["error_diag"] = err
        return out
    if not isinstance(data, dict):
        out["error_diag"] = M.diag("error", "API_ERROR", "Semantic Scholar returned a record of an unexpected shape.",
                                   "Report the id; do not treat the paper as absent.")
        return out
    out["candidates"], out["info"] = s2_candidates(data)
    out["title"] = data.get("title")
    ext = data.get("externalIds") if isinstance(data.get("externalIds"), dict) else {}
    out["doi"] = ext.get("DOI") if isinstance(ext.get("DOI"), str) else None
    out["record_id"] = data.get("paperId") if isinstance(data.get("paperId"), str) else pid
    return out


# ==============================================================================
# Download
# ==============================================================================

def looks_like_pdf(body: bytes) -> bool:
    """The PDF header may sit anywhere in the first 1024 bytes."""
    return b"%PDF-" in body[:1024]


async def download(url: str) -> dict:
    """Fetch one address under the serial lock, vetting and pinning every hop.
    Returns {body, final_url, redirects, content_type}; raises Refused.

    No proxy is used (trust_env=False): through a proxy the host would be resolved
    by the proxy, and the address check here would mean nothing."""
    global _last_request_at
    state = {"current": url}
    hops: list[str] = []

    async def run() -> dict:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=False, transport=_TRANSPORT, trust_env=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf, */*;q=0.5"},
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                current = state["current"]
                why, ip = await vet(current)
                if why:
                    raise Refused("ADDRESS_REFUSED", f"{redact_url(current)} was not fetched: {why}.",
                                  "Only public http(s) addresses are fetched, at every redirect.")
                target, headers, ext = pinned(current, ip)
                async with client.stream("GET", target, headers=headers, extensions=ext) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            raise Refused("HTTP_STATUS", f"{redact_url(current)} redirected without saying where.")
                        hops.append(redact_url(current))
                        state["current"] = urljoin(current, loc)
                        continue
                    if resp.status_code != 200:
                        raise Refused(
                            "HTTP_STATUS", f"{redact_url(current)} answered HTTP {resp.status_code}.",
                            "A 401 or 403 usually means this copy is not open to an automated request; "
                            "it is not evidence the file is absent. Try it in a browser or through your library's licensed access.")
                    declared = resp.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_BYTES:
                        raise Refused("FILE_TOO_LARGE",
                                      f"The file declares {int(declared):,} bytes; the limit is {MAX_BYTES:,}.")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > MAX_BYTES:
                            raise Refused("FILE_TOO_LARGE", f"The file passed the {MAX_BYTES:,}-byte limit.")
                    return {"body": bytes(buf), "final_url": current, "redirects": hops,
                            "content_type": resp.headers.get("content-type")}
            raise Refused("REDIRECT_LIMIT", f"More than {MAX_REDIRECTS} redirects from {redact_url(url)}.")

    async with _lock():
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await asyncio.wait_for(run(), DOWNLOAD_DEADLINE)
        except asyncio.TimeoutError:
            raise Refused("READ_TIMEOUT", f"{redact_url(state['current'])} did not finish within "
                          f"{DOWNLOAD_DEADLINE:.0f} s.", "Retry later; a timeout is not evidence the file is absent.") from None
        except httpx.TimeoutException:
            raise Refused("READ_TIMEOUT", f"{redact_url(state['current'])} did not answer within {TIMEOUT:.0f} s.",
                          "Retry later; a timeout is not evidence the file is absent.") from None
        except httpx.HTTPError as exc:
            raise Refused("TRANSPORT_ERROR", f"{redact_url(state['current'])} could not be reached "
                          f"({type(exc).__name__}).", "Retry later.") from None
        finally:
            _last_request_at = time.monotonic()


# ==============================================================================
# The text layer
# ==============================================================================

def page_texts(data: bytes, wanted: Optional[list[int]] = None, limit: int = PROBE_PAGE_LIMIT,
               budget: Optional[int] = None) -> dict:
    """Read the text layer page by page.

    Returns {page_count, texts {page: text}, image_pages, read_through,
    truncated_at, error}. `image_pages` are pages mostly covered by one picture:
    a scan, whose text layer (if any) was added by someone's OCR.
    `wanted` restricts which pages are read; `limit` is the last page read at
    all; `budget` stops reading once that many characters are held. `error` is
    TEXT_EXTRACTION_NOT_PERMITTED, PDF_UNREADABLE or None.
    """
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTContainer, LTImage, LTTextContainer
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import resolve1

    out: dict[str, Any] = {"page_count": None, "texts": {}, "image_pages": [], "read_through": 0, "page_cut": None,
                           "truncated_at": None, "error": None}
    want = set(wanted) if wanted is not None else None
    try:
        doc = PDFDocument(PDFParser(io.BytesIO(data)))
        try:
            out["page_count"] = int(resolve1(resolve1(doc.catalog["Pages"])["Count"]))
        except Exception:  # noqa: BLE001 - a missing count is recovered by reading
            pass
        rsrc = PDFResourceManager(caching=True)
        # all_texts: text drawn inside Form XObjects is laid out too; without it a
        # born-digital page wrapped in a form read as empty (second-model review).
        agg = PDFPageAggregator(rsrc, laparams=LAParams(all_texts=True))
        interp = PDFPageInterpreter(rsrc, agg)
        held = 0
        last = max(want) if want else limit
        for i, page in enumerate(PDFPage.get_pages(io.BytesIO(data), check_extractable=True), start=1):
            if i > last:
                break
            out["read_through"] = i
            if want is not None and i not in want:
                continue
            interp.process_page(page)
            layout = agg.get_result()
            parts: list[str] = []
            boxes: list[tuple] = []
            big, big_area = None, 0.0
            stack = list(layout)
            while stack:
                o = stack.pop(0)
                if isinstance(o, LTTextContainer):
                    t = o.get_text()
                    parts.append(t)
                    boxes.append((o.bbox, len(t.strip())))
                    continue
                if isinstance(o, LTImage) and float(o.width) * float(o.height) > big_area:
                    big, big_area = o.bbox, float(o.width) * float(o.height)
                if isinstance(o, LTContainer):
                    stack[0:0] = list(o)
            area = float(layout.width) * float(layout.height)
            if big and area and big_area >= IMAGE_PAGE_SHARE * area:
                x0, y0, x1, y1 = big
                total = sum(n for _, n in boxes)
                on = sum(n for (a, b, c, d), n in boxes
                         if x0 <= (a + c) / 2 <= x1 and y0 <= (b + d) / 2 <= y1)
                if total and on >= OCR_OVERLAY_SHARE * total:
                    out["image_pages"].append(i)
            text = "".join(parts)
            if budget is not None and held + len(text) > budget:
                if not out["texts"]:
                    # One page larger than the whole budget: return its first part, said so.
                    out["texts"][i] = text[:budget]
                    out["page_cut"] = i
                out["truncated_at"] = i
                break
            out["texts"][i] = text
            held += len(text)
        else:
            # Every page was walked: the walk is the count when the catalogue gave none.
            if out["page_count"] is None:
                out["page_count"] = out["read_through"]
    except Exception as exc:  # noqa: BLE001
        out["error"] = ("TEXT_EXTRACTION_NOT_PERMITTED" if type(exc).__name__ == "PDFTextExtractionNotAllowed"
                        else "PDF_UNREADABLE")
    return out


async def probe_text(data: bytes, wanted: Optional[list[int]] = None, limit: int = PROBE_PAGE_LIMIT,
                     budget: Optional[int] = None) -> dict:
    """page_texts in a worker thread, abandoned after PARSE_DEADLINE seconds."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(page_texts, data, wanted, limit, budget), PARSE_DEADLINE)
    except asyncio.TimeoutError:
        return {"page_count": None, "texts": {}, "image_pages": [], "read_through": 0, "page_cut": None,
                "truncated_at": None, "error": "TEXT_PROBE_TIMEOUT"}


def has_text(text: str) -> bool:
    return len(re.sub(r"\s+", "", text or "")) >= MIN_TEXT_CHARS


def text_layer_diags(probe: dict, scope_pages: list[int]) -> tuple[str, list[int], list[dict]]:
    """('full'|'partial'|'ocr'|'none'|'unknown', pages without text, diagnostics).

    'ocr' means every page that has text is a page image whose text layer was added by
    OCR before the file reached us: present, but of unknown accuracy (7 Oct 2026: a
    repository scan of a two-column Japanese article read with its columns interleaved).
    """
    if probe["error"] == "TEXT_EXTRACTION_NOT_PERMITTED":
        return "unknown", [], [M.diag("info", "TEXT_EXTRACTION_NOT_PERMITTED",
                                      "The PDF forbids text extraction, so its text layer was not read.",
                                      "Read the file in a PDF viewer; this server respects the restriction.")]
    if probe["error"] == "TEXT_PROBE_TIMEOUT":
        return "unknown", [], [M.diag("warning", "TEXT_PROBE_TIMEOUT",
                                      f"Reading the text layer did not finish within {PARSE_DEADLINE:.0f} s.",
                                      "Ask fetch_pdf_text for a short page range, or open the file in a viewer.")]
    if probe["error"]:
        where = (f" beyond page {probe['read_through']}" if probe.get("read_through") else "")
        return "unknown", [], [M.diag("warning", "PDF_UNREADABLE",
                                      f"The file begins as a PDF but could not be parsed for text{where}.",
                                      "Open it in a viewer to check it is complete; it may need repair or OCR.")]
    empty = [p for p in scope_pages if not has_text(probe["texts"].get(p, ""))]
    if not scope_pages:
        return "unknown", [], []
    if len(empty) == len(scope_pages):
        return "none", empty, [M.diag("warning", "NO_TEXT_LAYER",
                                      f"No page read ({page_ranges(scope_pages)}) carries a text layer: this is a scan.",
                                      OCR_HINT)]
    with_text = [p for p in scope_pages if p not in empty]
    ocr = [p for p in with_text if p in set(probe.get("image_pages") or [])]
    diags: list[dict] = []
    if ocr:
        diags.append(M.diag(
            "warning", "OCR_TEXT_LAYER",
            f"Pages {page_ranges(ocr)} are page images whose text layer was added by OCR before "
            "the file was published; its accuracy is unknown, and columns or vertical setting "
            "may be read out of order.",
            "Check every quotation against the page image; re-OCR if the text reads poorly."))
    if empty:
        diags.insert(0, M.diag("warning", "PARTIAL_TEXT_LAYER",
                               f"Pages {page_ranges(empty)} carry no text layer.", OCR_HINT))
        return "partial", empty, diags
    return ("ocr" if ocr and len(ocr) == len(with_text) else "full"), [], diags


# ==============================================================================
# Envelopes
# ==============================================================================

def _title_kwargs(title: Optional[str]) -> dict:
    if not isinstance(title, str) or not title.strip():
        return {}
    script = M.detect_script(title)
    if script in ("hangul", "han_hangul"):
        return {"title_ko": title}
    if script in ("han", "kana", "han_kana", "mixed"):
        return {"title_ja": title}
    return {"title_en": title}


def _envelope(operation: str, input_terms: str, params: dict, items: list[dict], diags: list[dict],
              extra_ids: Optional[list[str]] = None, endpoint: Optional[str] = None) -> str:
    env = M.build_envelope(
        server=SERVER_NAME, operation=operation, input_terms=input_terms, normalized=input_terms,
        params=params, matching_mode="identifier_fetch", total=len(items), start=0, items=items,
        diagnostics=diags, attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
    )
    if endpoint:
        env["endpoint"] = endpoint
    _rids.finish(env, lambda it: it["ids"].get("fulltext_url"))
    # The receipt names the file as well as the record: the SHA-256 is what lets a
    # PDF on disk be matched, years later, to the search that brought it in.
    if extra_ids:
        env["receipt"]["result_ids"].extend(x for x in extra_ids if x not in env["receipt"]["result_ids"])
    return M.emit(env)


def _not_configured(operation: str, input_terms: str, params: dict) -> str:
    return _envelope(operation, input_terms, params, [], [M.diag(
        "error", "DOWNLOAD_DIR_NOT_SET",
        f"No download folder is configured ({DOWNLOAD_ENV}), so nothing was fetched or read.",
        f"Set {DOWNLOAD_ENV} (in Claude Desktop, the extension's 'Download folder' setting) to the "
        "folder fetched PDFs should go to.")])


# ==============================================================================
# Server and tools
# ==============================================================================

try:
    mcp = _MCPServer("fetch", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("fetch")


class FetchPdfInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    via: Literal["openalex", "semantic_scholar", "url"] = Field(..., description=(
        "Where the PDF's address comes from. 'openalex' or 'semantic_scholar': the source is asked "
        "afresh for the work's open-access copy, and its licence is reported. 'url': an address "
        "you supply (e.g. a fulltext_url from another result); no licence is checked."))
    record: str = Field(..., min_length=1, max_length=2000, description=(
        "openalex: a work id (W2741809807) or DOI. semantic_scholar: a paper id or DOI. "
        "url: the PDF's http(s) address."))


class PdfTextInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    file: str = Field(..., min_length=1, max_length=1000, description=(
        "A PDF in the download folder: its file name as fetch_pdf reported it, or a path inside "
        "that folder. Files elsewhere are refused."))
    pages: Optional[str] = Field(default=None, max_length=200, description=(
        "Pages to read, 1-based, e.g. '5', '5-20' or '3,7,11-14'. Default: from the start until "
        "max_chars is reached."))
    max_chars: int = Field(default=TEXT_DEFAULT_CHARS, ge=500, le=200000, description=(
        "Stop once this many characters are held. Ask for a page range rather than raising it."))


_SOURCE_NAME = {"openalex": "OpenAlex", "semantic_scholar": "Semantic Scholar", "url": "The address supplied"}


@mcp.tool()
async def fetch_pdf(params: FetchPdfInput) -> str:
    """Download one open-access PDF into the configured download folder, with its provenance.

    With via='openalex' or via='semantic_scholar' the source is asked afresh for the
    work's open-access copy, and the licence and open-access status it reports are
    returned and written to a provenance file beside the PDF. With via='url' the
    address you supply is fetched and no licence is checked. A work with no
    open-access copy is refused (NO_OA_COPY): licensed access is your institution's,
    not this tool's. A landing or login page is refused (NOT_A_PDF) and nothing is
    written.

    Reports the saved file's name, SHA-256, size and page count, and which pages
    carry a text layer; pages without one are a scan and need OCR before reading.
    The receipt names the record and the file's SHA-256. One file per call.
    """
    via, record = params.via, params.record
    shown = redact_url(record) if via == "url" else record
    rparams = {"via": via, "record": shown}
    d = download_dir()
    if d is None:
        return _not_configured("fetch_pdf", shown, rparams)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _envelope("fetch_pdf", shown, rparams, [], [M.diag(
            "error", "DOWNLOAD_DIR_UNUSABLE",
            f"The download folder could not be created or opened ({type(exc).__name__}).",
            f"Check that the folder named in {DOWNLOAD_ENV} exists and can be written to.")])

    found = await resolve(via, record)
    if found["error_diag"]:
        return _envelope("fetch_pdf", shown, rparams, [], [found["error_diag"]])
    info = found["info"]
    if not found["candidates"]:
        return _envelope("fetch_pdf", shown, rparams, [], [M.diag(
            "warning", "NO_OA_COPY",
            f"{_SOURCE_NAME[via]} names no open-access copy of this work.",
            "For licensed access use your institution's licensed access; "
            "this tool does not look for copies elsewhere.")])

    attempts: list[dict] = []
    got: Optional[dict] = None
    refusals: list[Refused] = []
    for url in found["candidates"]:
        try:
            got = await download(url)
        except Refused as r:
            attempts.append({"url": redact_url(url), "refused": r.code})
            refusals.append(r)
            got = None
            continue
        if not looks_like_pdf(got["body"]):
            attempts.append({"url": redact_url(url), "refused": "NOT_A_PDF", "content_type": got["content_type"]})
            refusals.append(Refused(
                "NOT_A_PDF",
                f"{redact_url(got['final_url'])} returned {got['content_type'] or 'an unlabelled body'}, "
                "not a PDF; nothing was saved.",
                "This is usually a landing or login page. Open it in a browser to find the PDF, "
                "then pass that address with via='url'."))
            got = None
            continue
        break
    if got is None:
        # Every refusal is reported: the first candidate is the source's best copy,
        # and its reason matters more than that of a fallback landing page.
        diags = [r.diag() for r in refusals]
        if len(attempts) > 1:
            diags.append(M.diag("info", "CANDIDATES_TRIED", f"{len(attempts)} addresses were tried: " + "; ".join(
                f"{a['url']} ({a['refused']})" for a in attempts), None))
        return _envelope("fetch_pdf", shown, rparams, [], diags)

    body = got["body"]
    sha = hashlib.sha256(body).hexdigest()
    existing = await asyncio.to_thread(find_saved, d, sha)
    already = existing is not None
    if already:
        path = existing
    else:
        stem = slug_for(via, found["record_id"] if via != "url" else record)
        path = d / f"{stem}-{sha[:12]}.pdf"
        try:
            await asyncio.to_thread(write_atomic, path, body)
        except OSError as exc:
            return _envelope("fetch_pdf", shown, rparams, [], [M.diag(
                "error", "DOWNLOAD_DIR_UNUSABLE",
                f"The PDF was downloaded but could not be written ({type(exc).__name__}).",
                f"Check that the folder named in {DOWNLOAD_ENV} can be written to, and that the "
                "file is not open in another program.")])

    probe = await probe_text(body, None, FETCH_PROBE_PAGES)
    read = sorted(probe["texts"])
    layer, empty, tdiags = text_layer_diags(probe, read)
    source_url = redact_url(got["final_url"])
    fetch_record = {
        "title": found["title"], "doi": found["doi"],
        "resolved_via": via, "record": shown, "record_id": found["record_id"] if via != "url" else None,
        "source_url": source_url, "redirects": got["redirects"], "content_type": got["content_type"],
        "licence": info.get("licence"), "oa_status": info.get("oa_status"), "version": info.get("version"),
        "host": info.get("host") if isinstance(info.get("host"), str) else None,
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "fetched_by": f"bibliograph-mcp {_bibliograph_version()} fetch {__version__}",
    }
    # One provenance file per PDF. Every fetch of the same bytes is added to it, so
    # a second source for the same file is recorded rather than discarded.
    prov_path = d / f"{path.stem}.provenance.json"
    prov = await asyncio.to_thread(read_provenance, prov_path, d)
    fetches = prov.get("fetches") if isinstance(prov.get("fetches"), list) else (
        [{k: v for k, v in prov.items() if k not in ("file", "sha256", "bytes")}] if prov else [])
    prov = {"file": path.name, "sha256": sha, "bytes": len(body), "fetches": fetches + [fetch_record]}
    prov_written = True
    try:
        await asyncio.to_thread(write_atomic, prov_path,
                                json.dumps(prov, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError:
        prov_written = False

    item = M.make_item(
        **_title_kwargs(found["title"]), doi=found["doi"], fulltext_url=source_url,
        matched_in="identifier", record_type="pdf", holding_org=info.get("host"),
        extra={
            "saved_path": str(path), "file": path.name, "sha256": sha, "bytes": len(body),
            "page_count": probe["page_count"], "text_layer": layer,
            "pages_without_text": page_ranges(empty) or None,
            "licence": info.get("licence"), "oa_status": info.get("oa_status"),
            "version": info.get("version"), "resolved_via": via,
            "record_id": found["record_id"] if via != "url" else None,
            "redirects": got["redirects"], "provenance_file": prov_path.name if prov_written else None,
            "already_saved": already, "attempts_refused": attempts or None,
        },
    )
    diags = [M.diag("info", "ALREADY_SAVED" if already else "SAVED",
                    (f"This file (SHA-256 {sha[:12]}…) was already in the download folder as {path.name}; "
                     "it was not written again." if already else
                     f"Saved as {path.name} ({len(body):,} bytes, SHA-256 {sha[:12]}…)."), None)]
    diags += tdiags
    if not prov_written:
        diags.append(M.diag("warning", "PROVENANCE_NOT_WRITTEN",
                            "The PDF was saved but its provenance file could not be written.",
                            "The receipt still records the record and the SHA-256; re-run to write it."))
    if probe["page_count"] and probe["page_count"] > FETCH_PROBE_PAGES and not probe["error"]:
        diags.append(M.diag("info", "PROBE_LIMITED",
                            f"The text layer was checked on the first {FETCH_PROBE_PAGES} of "
                            f"{probe['page_count']} pages only.", "Use fetch_pdf_text with a page range for the rest."))
    if via == "url":
        diags.append(M.diag("info", "SUPPLIED_URL_NO_LICENCE_CHECK",
                            "The address was supplied, so no source reported a licence for this copy.",
                            "Establish the licence before reuse beyond private study."))
    elif not info.get("licence"):
        diags.append(M.diag("info", "LICENCE_NOT_STATED",
                            f"{_SOURCE_NAME[via]} reports this copy as open to read"
                            f"{' (' + str(info.get('oa_status')) + ')' if info.get('oa_status') else ''} "
                            "but states no licence.",
                            "Reuse beyond private study is not established by this record."))
    return _envelope("fetch_pdf", shown, rparams, [item], diags,
                     extra_ids=[f"sha256:{sha}"], endpoint=source_url)


@mcp.tool()
async def fetch_pdf_text(params: PdfTextInput) -> str:
    """Return the text layer of a PDF in the download folder, page by page.

    The text is the PDF's own, as embedded: no OCR is done. Pages without a text
    layer are listed (they are scans and need OCR), and a PDF that forbids
    extraction is not read. Reading stops at max_chars and says where; ask for the
    next pages with `pages`. Japanese set vertically can come out in an order that
    must be checked against the page before quotation. Only files inside the
    download folder are read.
    """
    d = download_dir()
    name = Path(params.file).name
    rparams = {"file": name, "pages": params.pages, "max_chars": params.max_chars}
    if d is None:
        return _not_configured("fetch_pdf_text", name, rparams)
    if params.file.startswith(("\\\\", "//")):
        # A network path is refused before anything resolves it: on Windows resolving a
        # UNC path can open a connection to that host.
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag(
            "error", "FILE_REFUSED", f"{name} is on a network path; only the download folder is read.", None)])
    p = Path(params.file).expanduser()
    if not p.is_absolute():
        p = d / p
    if p.suffix.lower() != ".pdf" or not inside(d, p):
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag(
            "error", "FILE_REFUSED", f"{name} is not a PDF inside the download folder; only those are read.",
            "Fetch it with fetch_pdf first, or move it into the download folder.")])
    if not p.is_file():
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag(
            "error", "FILE_NOT_FOUND", f"There is no {name} in the download folder.",
            "Use the file name fetch_pdf reported.")])
    try:
        wanted = parse_pages(params.pages)
    except ValueError as exc:
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag("error", "BAD_PAGES", str(exc), None)])
    if wanted == []:
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag(
            "error", "BAD_PAGES", "Pages are numbered from 1; no page was asked for.", None)])
    try:
        data = await asyncio.to_thread(p.read_bytes)
    except OSError as exc:
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag(
            "error", "FILE_UNREADABLE", f"{name} could not be read ({type(exc).__name__}).",
            "Close it in any program that has it open, and check its permissions.")])
    sha = hashlib.sha256(data).hexdigest()
    if not looks_like_pdf(data):
        return _envelope("fetch_pdf_text", name, rparams, [], [M.diag(
            "error", "NOT_A_PDF", f"{name} does not begin as a PDF.", None)], extra_ids=[f"sha256:{sha}"])

    probe = await probe_text(data, wanted, PROBE_PAGE_LIMIT if wanted is None else max(wanted), params.max_chars)
    read = sorted(probe["texts"])
    layer, empty, diags = text_layer_diags(probe, read)
    if wanted and probe["page_count"] and max(wanted) > probe["page_count"]:
        beyond = [x for x in wanted if x > probe["page_count"]]
        diags.append(M.diag("info", "PAGES_OUT_OF_RANGE",
                            f"The PDF has {probe['page_count']} pages; pages {page_ranges(beyond)} do not exist.", None))
    if probe["truncated_at"]:
        t = probe["truncated_at"]
        end = probe["page_count"] or (t + 20)
        if probe.get("page_cut"):
            msg = (f"Page {t} alone is longer than the {params.max_chars:,}-character ceiling; "
                   f"its first {params.max_chars:,} characters are returned.")
            hint = "Raise max_chars to read the whole page."
        else:
            msg = (f"Returned pages {page_ranges(read)}; stopped before page {t} "
                   f"at the {params.max_chars:,}-character ceiling.")
            hint = f"Ask for the next pages, e.g. pages='{t}-{end}'."
        diags.append(M.diag("warning", "TEXT_TRUNCATED", msg, hint))
    elif (wanted is None and probe["page_count"] and not probe["error"]
          and probe["read_through"] < probe["page_count"]):
        nxt = probe["read_through"] + 1
        diags.append(M.diag("warning", "TEXT_TRUNCATED",
                            f"Read the first {probe['read_through']} of {probe['page_count']} pages, "
                            "the most this tool reads without a page range.",
                            f"Ask for the rest with pages='{nxt}-{probe['page_count']}'."))
    prov = first_fetch(read_provenance(p.with_name(f"{p.stem}.provenance.json"), d))
    item = M.make_item(
        **_title_kwargs(prov.get("title")), doi=prov.get("doi") if isinstance(prov.get("doi"), str) else None,
        fulltext_url=prov.get("source_url") if isinstance(prov.get("source_url"), str) else None,
        matched_in="file", record_type="pdf",
        extra={"file": name, "sha256": sha, "page_count": probe["page_count"], "text_layer": layer,
               "pages_without_text": page_ranges(empty) or None,
               "pages": [{"page": i, "chars": len(probe["texts"][i]), "text": probe["texts"][i]} for i in read],
               "provenance": prov or None,
               "page_cut": probe.get("page_cut")},
    )
    return _envelope("fetch_pdf_text", name, rparams, [item], diags, extra_ids=[f"sha256:{sha}"])


def _bibliograph_version() -> str:
    try:
        from ... import __version__ as v
        return v
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> None:  # pragma: no cover
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
