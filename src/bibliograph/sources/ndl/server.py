"""
NDL Search MCP Server (v1.5.1)
==============================
An MCP server for searching 国立国会図書館サーチ (NDL Search), operated by the
National Diet Library of Japan, over the SRU searchRetrieve interface.

Built to the undertakings given to the NDL when continuous use was registered
on 19 August 2026 (電子情報部 電子情報流通課). The library has since confirmed
that registration is no longer required, only welcome; the undertakings are kept
anyway, because they are the right way to treat a public service and because
they are the specification this server was written against, not commentary:

  * requests are issued serially — one connection, never concurrent
  * a minimum interval of MIN_REQUEST_INTERVAL seconds is held between requests
  * a single search is capped at MAX_RECORDS records; there is no auto-pagination
  * the harvesting interface (OAI-PMH) is not used and is not implemented
  * every response carries credit to the NDL Search API, and provider credit
    where the API提供対象データプロバイダ一覧 makes it a condition
  * retrieved metadata is displayed, not accumulated; nothing is cached

Only twelve NDL-created data providers are reachable: the five declared on
19 August 2026, the six added by the supplementary notification filed on
18 September 2026, and iss-ndl-opac-bib, added on the NDL's answer to that
filing (9 October 2026). A request for any other dpid is refused in process rather
than sent — a declared scope a reader can check is worth more than a wide one
nobody can.

The metadata this server retrieves is NDL-created throughout, and deliberately
so. 国立国会図書館ウェブサイトのコンテンツ利用規約 places NDL website content —
書誌データ included — under 公共データ利用規約（第1.0版）(PDL1.0), read with
「国以外の者」 as 「国立国会図書館以外の者」, and then carves out as third-party
rights 「書誌データ、書影等のうち、国立国会図書館以外の者が作成したもの」,
naming NDL Search metadata created by others as an instance of it. Records
aggregated from the other ~110 providers reach the user under conditions the NDL
does not set and this server cannot assert. Restricting to NDL-created sets is
what makes the attribution line truthful.

Two of the twelve, the Digital Collections sets ndl-dl and ndl-dl-online, are
NDL-created but carry no open licence. Their metadata is displayed for the
search that asked for it and is never redistributed or stored, and the credit
line names them separately so a reader can tell the two conditions apart.

There is no credential. The NDL search APIs are open — no application ID, no
key, no token. The application filed with the library is a permission and
notification procedure, not a credential grant. See README.md.

Requires mediation.py and ledger.py beside it, vendored byte-identical from
cinii-mcp; install.ps1 copies them rather than reproducing them.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from typing import Any, Optional
from xml.etree import ElementTree as ET

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids
from ... import notices as _notices


def _emit(env: dict) -> str:
    """mediation.emit, plus a typed note when no NDL usage notification is on record.

    The NDL asks continuous users of the Search API to report who they are and how
    they use it (API help, section 17). That is each user's filing, not this
    package's; the note makes its absence visible instead of silent.
    """
    if not _notices.recorded("ndl"):
        env.setdefault("diagnostics", []).append(M.diag(
            "info", "NOTIFICATION_NOT_RECORDED",
            "No NDL Search API usage notification is recorded for this installation.",
            f"File it at https://form2.ndl.go.jp/form/pub/ndl07/api (see "
            f"https://ndlsearch.ndl.go.jp/help/api), then write the date and the declared "
            f"data providers to {_notices.marker_path('ndl')}."))
    return M.emit(_rids.finish(env, _receipt_id))


def _receipt_id(it: dict):
    """NDL's own identifiers, named as NDL names them (see receipt_ids)."""
    ex = _rids.extra_of(it)
    return (_rids.prefixed("NDLBibID:", ex.get("ndl_bib_id"))
            or _rids.prefixed("JPNO:", ex.get("jpno"))
            or (it.get("ids") or {}).get("url_ja"))


def _squash(s):
    """Collapse internal whitespace. NDL's RDF pretty-prints some literals, so a
    volume can arrive as a value, a newline and a run of indentation."""
    return re.sub(r"\s+", " ", s).strip() or None if s else None

__version__ = "1.5.2"

# httpx logs every request URL at INFO. There is no credential in an NDL request,
# so nothing leaks — but a search term travels in that URL, and the line lands on
# the stderr Claude Desktop captures. Mute it, as the rest of the family does.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
# The MCP SDK logs every request it handles at INFO ("Processing request of
# type ListToolsRequest"). Noise, not a leak; still, stderr should carry faults only.
logging.getLogger("mcp").setLevel(logging.WARNING)

# ==============================================================================
# Configuration
# ==============================================================================

SRU_BASE = "https://ndlsearch.ndl.go.jp/api/sru"
TIMEOUT = 30.0
USER_AGENT = "ndl-mcp/1.0 (scholarly research; +https://github.com/ckgerteis/ndl-mcp)"

# Filed with the NDL: a minimum one-second interval, requests issued serially.
MIN_REQUEST_INTERVAL = 1.0

# NDL answers 429 even inside that interval, so a 429 buys a single backoff.
BACKOFF_SECONDS = 10.0

# Filed with the NDL: a ceiling on the records returned by a single search.
# Deliberately far below the NDL's own limit of 500 — no mechanical bulk retrieval.
MAX_RECORDS = 100

MATCHING_MODE = "metadata_conjunction"

ATTRIBUTION = (
    "Data via 国立国会図書館サーチ (NDL Search), National Diet Library, Japan, "
    "retrieved through the NDL Search API. "
    "本サービスは国立国会図書館サーチのAPIを利用しています。"
)

COVERAGE_NOTE = (
    "NDL Search aggregates records from some 117 providers; this server queries "
    "only the twelve NDL-created sets it declares. Absence here is absence from "
    "the sets the tool searched, not from the NDL's holdings as a whole, and still "
    "less from NDL Search. Records held by other libraries and aggregated into NDL "
    "Search are outside scope, as is ndl-article-online: the NDL permits only its "
    "records tagged ndl-dl-open, and the Search API offers no way to restrict a "
    "search to them."
)

# ==============================================================================
# Data providers
# ==============================================================================
#
# The first five, registered with the NDL in August 2026, are all
# marked ○ in BOTH the 非営利 and 営利 columns of the API提供対象データプロバイダ
# 一覧 — no usage application, whatever the use — and all five carry the NDL's
# own bibliographic-data condition. Adding to this table widens what this server
# declares about itself, so update the README, NDL-API-NOTIFICATION.txt and this
# comment in the same commit. The library no longer requires notification of a
# change; a reader still requires an accurate description.
#
# On the licence: the 一覧 records these sets as 「CC BY」 by way of 国立国会図書館
# ウェブサイトのコンテンツ利用規約, which places them under 公共データ利用規約
# （第1.0版）(PDL1.0) and states that condition to be *compatible with* CC BY 4.0.
# PDL1.0 is the governing instrument; CC BY 4.0 is the compatibility claim. The
# credit lines below say so rather than asserting a licence the NDL has not
# granted.
#
# Six sets were added by the supplementary notification filed on 18 September
# 2026 (the same filing corrected the national-bibliography dpid): ndl-boj, warp,
# iss-ndl-opac-inprocess and issn-online, open like the first five; and the
# Digital Collections proper, ndl-dl and ndl-dl-online, which the 一覧 marks ○ for
# 非営利 and △ for 営利 and whose metadata carries no open licence. For those two
# the filing undertook display only — no redistribution, no store — and a credit
# line that keeps them apart from the PDL1.0 sets; "licence": "display_only" is
# what provider_credit() reads to do that. ndl-dl-doi was not declared.
#
# Two further dpids, iss-ndl-opac-bib and ndl-article-online, are documented in
# the help text but absent from the 一覧. The filing asked the library about them;
# the NDL answered by email (di-api@ndl.go.jp, reply to the filing of 18 Sep 2026):
#   - iss-ndl-opac-bib is contained in iss-ndl-opac and carries the same terms
#     (CC BY), and may be named in a search. It is in this table. Live check,
#     9 Oct 2026, title="婦人公論": iss-ndl-opac-bib 91, iss-ndl-opac 1701, the
#     difference being serial-issue records.
#   - ndl-article-online may be named in a search, but only its records tagged
#     ndl-dl-open (setSpec) may be used; the rest is third-party metadata from the
#     Digital Collections. Not in this table, because neither route to that
#     restriction works. Live check, 9 Oct 2026, title="婦人参政権":
#     dpid="ndl-article-online" AND dpid="ndl-dl-open" returned the same 22
#     records as dpid="ndl-dl-open" alone, books not articles, so the first
#     clause is not applied; and dcndl records carry no setSpec to filter on.
#
# Set algebra, from 国立国会図書館作成書誌のデータプロバイダ詳細. It matters
# because a union over these dpids is not a sum:
#   iss-ndl-opac  ⊃ iss-ndl-opac-national, ndl-boj, iss-ndl-opac-bib
#   iss-ndl-opac  ∌ iss-ndl-opac-inprocess, zassaku, zassaku-online,
#                   ndl-dl, ndl-dl-online
# The last line is about provider membership, not about what comes back: NDL
# Search clusters records, so a search on dpid="ndl-dl" returns the holdings
# record (R100000002-…) as the representative of a digitised book, with the
# digitised copy (R100000039-…) as one of its items. Measured 18 Sep 2026.
#   zassaku       ∌ zassaku-online
#   ndl-dl-open   ⊆ ndl-dl ∪ ndl-dl-online, and so disjoint from iss-ndl-opac
# Since 2024-01 iss-ndl-opac also carries serial-issue-level records the pre-2024
# set did not; iss-ndl-opac-bib is the same set without them.

PROVIDERS: dict[str, dict[str, Optional[str]]] = {
    "iss-ndl-opac": {
        "ja": "国立国会図書館蔵書",
        "en": "NDL holdings",
        "credit": "国立国会図書館蔵書 (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    # NB: the 一覧 spells this dpid with a hyphen before "national". The
    # registration of 19 Aug 2026 and v1.0.0 of this file both wrote
    # "iss-ndl-opacnational", which names no provider: SRU matches nothing and
    # ndl_search_national_bibliography returned a clean, credible zero for every
    # query put to it. Corrected 20 Aug 2026. The set intended was always the
    # national bibliography, as named; only the identifier was wrong.
    "iss-ndl-opac-national": {
        "ja": "国立国会図書館全国書誌情報",
        "en": "Japanese National Bibliography",
        "credit": "国立国会図書館全国書誌情報 (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": "iss-ndl-opac",
        "licence": "pdl",
    },
    "zassaku": {
        "ja": "国立国会図書館雑誌記事索引",
        "en": "NDL Japanese Periodicals Index",
        "credit": "国立国会図書館雑誌記事索引 (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    "zassaku-online": {
        "ja": "国立国会図書館雑誌記事索引オンライン資料編",
        "en": "NDL Japanese Periodicals Index (online materials)",
        "credit": "国立国会図書館雑誌記事索引オンライン資料編 (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    "ndl-dl-open": {
        "ja": "国立国会図書館デジタルコレクション（オープンデータ）",
        "en": "NDL Digital Collections (Open Data)",
        "credit": "国立国会図書館デジタルコレクション（オープンデータ） (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    # ---- declared 18 September 2026 ----
    "ndl-boj": {
        "ja": "国立国会図書館日本関係外国語図書",
        "en": "NDL foreign-language books on Japan",
        "credit": "国立国会図書館日本関係外国語図書 (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": "iss-ndl-opac",
        "licence": "pdl",
    },
    # Added 9 Oct 2026 on the NDL's answer. The holdings without the
    # serial-issue-level records iss-ndl-opac has carried since 2024-01: the set
    # to search when book counts must be comparable across that break.
    "iss-ndl-opac-bib": {
        "ja": "国立国会図書館蔵書（巻号以外）",
        "en": "NDL holdings (excluding serial issues)",
        "credit": "国立国会図書館蔵書（巻号以外） (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": "iss-ndl-opac",
        "licence": "pdl",
    },
    "iss-ndl-opac-inprocess": {
        "ja": "国立国会図書館新着書誌情報",
        "en": "NDL in-process bibliographic records",
        "credit": "国立国会図書館新着書誌情報 (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    "issn-online": {
        "ja": "ISSN登録国内発行オンラインジャーナル",
        "en": "Japanese online journals registered for an ISSN",
        "credit": "ISSN登録国内発行オンラインジャーナル (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    "warp": {
        "ja": "インターネット資料収集保存事業（WARP）",
        "en": "Web Archiving Project (WARP) catalogue",
        "credit": "インターネット資料収集保存事業（WARP） (PDL1.0; CC BY 4.0 compatible)",
        "subset_of": None,
        "licence": "pdl",
    },
    "ndl-dl": {
        "ja": "国立国会図書館デジタルコレクション",
        "en": "NDL Digital Collections",
        "credit": "国立国会図書館デジタルコレクション",
        "subset_of": None,
        "licence": "display_only",
    },
    "ndl-dl-online": {
        "ja": "国立国会図書館デジタルコレクション（電子書籍・電子雑誌）",
        "en": "NDL Digital Collections (e-books and e-journals)",
        "credit": "国立国会図書館デジタルコレクション（電子書籍・電子雑誌）",
        "subset_of": None,
        "licence": "display_only",
    },
}

BOOK_DPIDS = ["iss-ndl-opac"]
BOOK_NO_ISSUES_DPIDS = ["iss-ndl-opac-bib"]
BOJ_DPIDS = ["ndl-boj"]
INPROCESS_DPIDS = ["iss-ndl-opac-inprocess"]
BIBLIOGRAPHY_DPIDS = ["iss-ndl-opac-national"]
ARTICLE_DPIDS = ["zassaku", "zassaku-online"]
DIGITAL_OPEN_DPIDS = ["ndl-dl-open"]
DIGITAL_DPIDS = ["ndl-dl", "ndl-dl-online"]
WARP_DPIDS = ["warp"]
ONLINE_JOURNAL_DPIDS = ["issn-online"]

DECLARED_DPIDS = list(PROVIDERS.keys())

# ndl_search_all unions the declared set, less three members. iss-ndl-opac-national
# is kept although it is a subset of iss-ndl-opac: the union is unchanged by it,
# and its credit is the one a reader of a 全国書誌 record needs. ndl-boj is left out
# for the opposite reason: also a subset, but its credit adds nothing to that of
# 蔵書, and iss-ndl-opac-bib likewise. warp returns records of websites, not
# publications, and the in-process set returns records that may yet change; each
# is reached only by asking for it.
ALL_DPIDS = [d for d in DECLARED_DPIDS
             if d not in ("ndl-boj", "iss-ndl-opac-bib", "warp", "iss-ndl-opac-inprocess")]


DISPLAY_ONLY_NOTICE = (
    "metadata not openly licensed; shown for this search only, not to be "
    "redistributed or stored. 表示のみ（再配布・蓄積不可）."
)


def provider_credit(dpids: list[str]) -> str:
    """The provider-level credit line required alongside the API attribution.

    Open (PDL1.0) providers and display-only providers are named in separate
    clauses, because the conditions differ and a single list would imply that
    one licence covers both.
    """
    known = [d for d in dpids if d in PROVIDERS]
    open_names = [PROVIDERS[d]["credit"] for d in known if PROVIDERS[d]["licence"] == "pdl"]
    shown_names = [PROVIDERS[d]["credit"] for d in known if PROVIDERS[d]["licence"] == "display_only"]
    line = ATTRIBUTION
    if open_names:
        line += " Provider: " + "; ".join(open_names) + "."
    if shown_names:
        line += " Display only: " + "; ".join(shown_names) + " — " + DISPLAY_ONLY_NOTICE
    return line


# ==============================================================================
# Rate limiting — serial requests, minimum interval
# ==============================================================================
#
# The lock is what makes the "no concurrent access" undertaking true: it is held
# across the wait AND the request, so two tool calls cannot be in flight at once.

_rate_lock = asyncio.Lock()
_last_request_at = 0.0


# ==============================================================================
# HTTP
# ==============================================================================


async def _sru_request(params: dict[str, Any]) -> str:
    """Issue one SRU request. Serialised; never concurrent; never paginated.

    NDL publishes no rate figure — 「具体的な数値の目安をお示しすることができません」 —
    but it enforces one, and answers HTTP 429 when it is exceeded. Observed on
    19 August 2026 at well under one request per second sustained, so the filed
    one-second floor is a minimum and not a guarantee. On 429 the server backs
    off once, honouring Retry-After, and then gives up rather than pressing.
    """
    global _last_request_at
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/xml"}
    async with _rate_lock:
        for attempt in (0, 1):
            wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                    resp = await client.get(SRU_BASE, params=clean, headers=headers)
            finally:
                _last_request_at = time.monotonic()
            if resp.status_code != 429 or attempt == 1:
                break
            retry_after = resp.headers.get("Retry-After")
            try:
                pause = float(retry_after) if retry_after else BACKOFF_SECONDS
            except ValueError:
                pause = BACKOFF_SECONDS
            # Only a finite, non-negative number of seconds is honoured. "nan"
            # parsed, min() kept it, and asyncio.sleep(nan) never returns on
            # Python 3.10-3.12: inside _rate_lock that hung every later call.
            if not math.isfinite(pause) or pause < 0:
                pause = BACKOFF_SECONDS
            await asyncio.sleep(min(pause, 30.0))
    resp.raise_for_status()
    return resp.text


def _error_diag(exc: Exception) -> dict:
    """Classify a failure as API_ERROR (the service answered) or TRANSPORT_ERROR."""
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 429:
            return M.diag(
                "error",
                "RATE_LIMITED",
                "NDL Search declined this request as too frequent (HTTP 429), after one backoff.",
                "Wait a minute and repeat the search. The result is unknown, not empty — "
                "do not read this as an absence in the index.",
            )
        return M.diag(
            "error",
            "API_ERROR",
            f"NDL Search returned HTTP {exc.response.status_code} for this query.",
            "Check the query syntax; retry once before treating it as an outage.",
        )
    if isinstance(exc, ET.ParseError):
        return M.diag(
            "error",
            "API_ERROR",
            "NDL Search returned a response that could not be parsed as XML.",
            "The service may be returning an error page; retry once.",
        )
    if isinstance(exc, httpx.HTTPError):
        return M.diag(
            "error",
            "TRANSPORT_ERROR",
            f"Could not reach NDL Search: {type(exc).__name__}.",
            "Network or timeout failure; the query was not answered.",
        )
    # Anything else was raised after the service answered — a numberOfRecords
    # that is not a number, an unexpected element shape — and is a malformed
    # answer, not a failure to reach the service. Labelling it TRANSPORT_ERROR
    # would tell the reader to retry a request that was in fact answered.
    return M.diag(
        "error",
        "API_ERROR",
        f"NDL Search answered, but the response could not be read: {type(exc).__name__}.",
        "Retry once; if it persists, the response shape has changed and the parser needs updating.",
    )


# ==============================================================================
# CQL
# ==============================================================================
#
# NDL's SRU rejects a query outright when a search term carries a bare AND or OR
# between words. That is a property of the corpus a historian will hit —
# English-language titles — so it is caught here and reported as a typed
# diagnostic rather than sent and returned as a parse failure.
#
# The rule was measured against the live API on 27 August 2026, because the
# earlier version of it was wrong in both directions:
#
#   anywhere="cats and dogs"    rejected      anywhere="cats AND dogs"  rejected
#   anywhere="cats And dogs"    rejected      anywhere="cats or dogs"   rejected
#   anywhere="cats OR dogs"     rejected
#   anywhere="cats not dogs"    96 records    anywhere="cats NOT dogs"  96 records
#   anywhere="war not peace"    351 records   title="not for sale"      119 records
#
# So: AND and OR are reserved in ANY case, and NOT is not reserved at all. The
# previous pattern was case-sensitive, which let every lowercase "and" through to
# be refused by NDL and reported as API_ERROR — a rejected search wearing the
# face of an empty one. It also caught NOT, refusing in process a query the
# library answers perfectly well.
#
# Position matters too, and the pattern follows what was measured rather than
# what would be tidy:
#
#   anywhere="and Peace"   14,375 records    leading, tolerated
#   anywhere="Peace and"   rejected          trailing
#   anywhere="cats and dogs"  rejected       infix
#
# Hence whitespace required before, whitespace or end-of-string after. A word
# that merely contains the letters is untouched: Thailand, Andorra and notation
# all return records and none of them matches.

_RESERVED = re.compile(r"\s(and|or)(?:\s|$)", re.IGNORECASE)

# Index name -> whether NDL matches it partially. Kept for the record; the server
# does not offer indexes outside this table.
CQL_INDEXES = {
    "title": "partial",
    "creator": "partial",
    "publisher": "partial",
    "subject": "partial",
    "description": "partial",
    "anywhere": "partial",
    "ndc": "prefix",
    "isbn": "exact",
    "issn": "exact",
    "jpno": "exact",
    "from": "exact",
    "until": "exact",
    "dpid": "exact",
}


def _cql_value(value: str) -> str:
    """Quote a CQL literal. NDL takes double quotes; escape any inside."""
    return '"' + value.replace('"', '\\"') + '"'


def reserved_word_hits(values: dict[str, Optional[str]]) -> list[str]:
    """Names of fields whose value carries a bare AND / OR / NOT."""
    return [
        name
        for name, value in values.items()
        if isinstance(value, str) and _RESERVED.search(value)
    ]


def build_cql(fields: dict[str, Optional[Any]], dpids: list[str]) -> str:
    """Assemble the CQL string actually sent.

    Several providers are expressed as REPEATED dpid clauses joined by AND, not
    as an OR group. That reads backwards and is what NDL accepts: repeating dpid
    unions the providers and deduplicates across them.

        anywhere="X" AND dpid="iss-ndl-opac" AND dpid="zassaku"   ->  54,182
        dpid="iss-ndl-opac" AND anywhere="X"                      ->  19,251
        dpid="zassaku"      AND anywhere="X"                      ->  34,931

    The obvious construction is rejected outright. Every parenthesised form was
    tried against the live API on 23 August 2026 and each returned SRU diagnostic
    info:srw/diagnostic/1/1, "illegal query syntax":

        (dpid="a" OR dpid="b") AND anywhere="X"
        anywhere="X" AND (dpid="a" OR dpid="b")
        dpid="a" OR dpid="b" AND anywhere="X"

    Until this was corrected, every tool that searches more than one provider —
    ndl_search_articles over the two periodical indexes, and ndl_search_all over
    all five — returned API_ERROR for every query ever put to it. The
    single-provider tools were unaffected, which is why it survived: the server
    looked as though it worked.
    """
    clauses: list[str] = []
    for name, value in fields.items():
        if value is None or value == "":
            continue
        clauses.append(f"{name}={_cql_value(str(value))}")
    clauses.extend(f"dpid={_cql_value(d)}" for d in dpids)
    return " AND ".join(clauses)


# ==============================================================================
# DC-NDL parsing
# ==============================================================================

NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "diag": "http://www.loc.gov/zing/srw/diagnostic/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcndl": "http://ndl.go.jp/dcndl/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
}

_RDF_DATATYPE = f"{{{NS['rdf']}}}datatype"
_RDF_RESOURCE = f"{{{NS['rdf']}}}resource"

_YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


def _text(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None:
        return None
    txt = "".join(elem.itertext())
    txt = txt.strip()
    return txt or None


def _first(parent: ET.Element, path: str) -> Optional[str]:
    return _text(parent.find(path, NS))


def _identifier(res: ET.Element, name: str) -> Optional[str]:
    """dcterms:identifier carries its kind in rdf:datatype, not in the tag."""
    suffix = "/" + name
    for node in res.findall("dcterms:identifier", NS):
        datatype = node.attrib.get(_RDF_DATATYPE, "")
        if datatype.endswith(suffix):
            return _text(node)
    return None


def _creators(res: ET.Element) -> list[dict[str, Optional[str]]]:
    """Structured creators first; fall back to the flat dc:creator strings."""
    names = [
        _text(agent.find("foaf:name", NS))
        for agent in res.findall("dcterms:creator/foaf:Agent", NS)
    ]
    names = [n for n in names if n]
    if not names:
        names = [t for t in (_text(n) for n in res.findall("dc:creator", NS)) if t]
    return [{"ja": n, "en": None} for n in names]


def _year(res: ET.Element) -> Optional[int]:
    for path in ("dcterms:issued", "dcterms:date"):
        raw = _first(res, path)
        if raw:
            match = _YEAR_RE.search(raw)
            if match:
                return int(match.group(1))
    return None


def _permalink(res: ET.Element) -> Optional[str]:
    node = res.find("rdfs:seeAlso", NS)
    if node is not None:
        link = node.attrib.get(_RDF_RESOURCE)
        if link:
            return link
    about = res.attrib.get(f"{{{NS['rdf']}}}about")
    return about or None


_RDFS_LABEL = f"{{{NS['rdfs']}}}label"


def _record_type(res: ET.Element) -> str:
    """NDL states the material type in attributes, not text:
    <dcndl:materialType rdf:resource=".../ndltype/Article" rdfs:label="記事・論文"/>.
    Until 1.1.2 this read the (empty) element text, fell through, and typed every
    periodicals-index record as a book."""
    material = " ".join(
        " ".join(filter(None, (
            node.attrib.get(_RDF_RESOURCE, ""), node.attrib.get(_RDFS_LABEL, ""), _text(node) or "",
        )))
        for node in res.findall("dcndl:materialType", NS)
    ).lower()
    # WARP catalogue records describe a website and state its start URL.
    if any(d.startswith("起点URL") for d in _descriptions(res)):
        return "website"
    # A journal-title record from the ISSN register, not an article in a journal.
    if "onlinejournal" in material and not _first(res, "dcndl:publicationName"):
        return "serial"
    if "雑誌" in material or "article" in material or "記事" in material:
        return "article"
    if "図書" in material or "book" in material:
        return "book"
    if _first(res, "dcndl:sourceTitle") or _first(res, "dcndl:publicationName"):
        return "article"
    return "book"


_DL_PID = re.compile(r"^https://dl\.ndl\.go\.jp/pid/(\d+)")
# The provider ID of 国立国会図書館デジタルコレクション in NDL Search record URIs.
# A digitised book's copy appears as an item whose URI carries it.
DIGITAL_REPOSITORY = "R100000039"
_DL_PROVIDER_MARK = "/" + DIGITAL_REPOSITORY + "-"


def _see_also(node: ET.Element) -> list[str]:
    return [n.attrib.get(_RDF_RESOURCE, "") for n in node.findall("rdfs:seeAlso", NS)]


def _descriptions(res: ET.Element) -> list[str]:
    return [t for t in (_text(n) for n in res.findall("dcterms:description", NS)) if t]


_REPOSITORY = re.compile(r"/books/(R\d{9})-")


def _repository(res: ET.Element) -> Optional[str]:
    """The NDL Search repository number the record was taken from (R100000002 is
    the NDL catalogue, R100000039 the Digital Collections, R000000020 WARP)."""
    m = _REPOSITORY.search(res.attrib.get(f"{{{NS['rdf']}}}about", ""))
    return m.group(1) if m else None


def _extra(res: ET.Element, dl_items: list[ET.Element]) -> dict[str, Any]:
    """Fields the shared item schema has no slot for, keyed plainly.

    source_repository  the repository the displayed record came from; NDL Search
                   clusters records, and the representative of a cluster can come
                   from a different set than the one searched

    access_rights  dcterms:accessRights as stated (e-books and e-journals state it;
                   digitised holdings, in the Search API, do not)
    viewer_url     the Digital Collections viewer, from the record or from the
                   digitised-copy item that NDL Search clusters under a holdings record
    warp_*         WARP catalogue records: the site's start URL, the WARP page, and
                   the collection types WARP files it under
    issn_l         linking ISSN, for journal-title records
    """
    out: dict[str, Any] = {}
    repo = _repository(res)
    if repo:
        out["source_repository"] = repo
    rights = [t for t in (_text(n) for n in res.findall("dcterms:accessRights", NS)) if t]
    if rights:
        out["access_rights"] = rights
    links = _see_also(res)
    for item in dl_items:
        links += _see_also(item)
    viewer = next((u for u in links if _DL_PID.match(u)), None)
    if viewer:
        out["viewer_url"] = viewer
    descs = _descriptions(res)
    start = next((d.split(":", 1)[1].strip() for d in descs if d.startswith("起点URL")), None)
    if start:
        out["warp_start_url"] = start
        warp_page = next((u for u in links if "warp.ndl.go.jp" in u), None)
        if warp_page:
            out["warp_url"] = warp_page
        kinds = [d.split(":", 1)[1].strip() for d in descs if d.startswith("コレクション種別")]
        if kinds:
            out["warp_collection"] = kinds
    issn_l = _identifier(res, "ISSNL")
    if issn_l:
        out["issn_l"] = issn_l
    return out


def _resource_to_item(res: ET.Element, dl_items: Optional[list[ET.Element]] = None) -> dict[str, Any]:
    # Article records carry the host periodical as dcndl:publicationName, the
    # issue as dcndl:issue and the pages as dcndl:pageRange; book records use
    # dcterms:extent and dcndl:volume. Read both layouts.
    pages = _squash(_first(res, "dcterms:extent") or _first(res, "dcndl:pageRange"))
    # NDLBibID and JPNO are NDL's identifiers, not CiNii's: until bibliograph 1.2.0 they rode in
    # ids.crid and ids.naid, which name CiNii Research and CiNii Articles records.
    extra = _extra(res, dl_items or [])
    bib_id, jpno = _identifier(res, "NDLBibID"), _identifier(res, "JPNO")
    if bib_id:
        extra["ndl_bib_id"] = bib_id
    if jpno:
        extra["jpno"] = jpno
    return M.make_item(
        title_ja=_first(res, "dcterms:title") or _first(res, "dc:title"),
        title_en=None,
        title_romanized=_first(res, "dc:title/rdf:Description/dcndl:transcription"),
        authors=_creators(res),
        journal_ja=(_first(res, "dcndl:sourceTitle") or _first(res, "dcndl:publicationName")
                    or _first(res, "dcndl:seriesTitle")),
        journal_en=None,
        volume=_squash(_first(res, "dcndl:volume")),
        issue=_squash(_first(res, "dcndl:number") or _first(res, "dcndl:issue")),
        pages=pages,
        year=_year(res),
        doi=_identifier(res, "DOI") or _dl_doi(dl_items or []),
        crid=None,
        naid=None,
        issn=_identifier(res, "ISSN"),
        url_ja=_permalink(res),
        url_en=None,
        matched_in="metadata",
        record_type=_record_type(res),
        extra=extra,
    )


def _dl_doi(dl_items: list[ET.Element]) -> Optional[str]:
    """The JaLC DOI NDL assigns a digitised copy (10.11501/<pid>), if one is linked."""
    for item in dl_items:
        for link in _see_also(item):
            if link.startswith("https://doi.org/10.11501/"):
                return link[len("https://doi.org/"):]
    return None


def _not_sru(why: str) -> dict:
    return M.diag(
        "error", "API_ERROR",
        f"NDL Search answered, but not with an SRU search response: {why}. "
        "The search was not answered; this is not an empty result.",
        "Usually a maintenance or throttling page. Retry later.",
    )


def _parse_sru(xml_text: str) -> tuple[int, list[dict[str, Any]], Optional[dict]]:
    """Return (total, items, diagnostic-or-None) from one SRU response."""
    root = ET.fromstring(xml_text)

    node = root.find("srw:diagnostics/diag:diagnostic", NS)
    if node is None:
        node = root.find("srw:diagnostics", NS)
    if node is not None:
        message = _text(node) or "NDL Search returned a diagnostic without a message."
        # NDL reports an empty result set as a diagnostic ("Record does not exist"),
        # not as numberOfRecords=0. Reading that as a service error would tell a
        # reader the search failed when in fact it succeeded and found nothing —
        # the one confusion a search tool must not create. Pass it through as zero.
        if "record does not exist" in message.lower():
            return 0, [], None
        return 0, [], M.diag(
            "error", "API_ERROR", f"NDL Search diagnostic: {message}",
            "The query was rejected. Check index names and quoting.",
        )

    # SRU requires numberOfRecords. A maintenance page or throttle notice served
    # with status 200 is still well-formed XML; without this check it parsed as a
    # response with no records and came back as "No record matched", an outage
    # reported as an empty index.
    count = _first(root, "srw:numberOfRecords")
    if count is None:
        return 0, [], _not_sru(f"<{root.tag}> carries no SRU numberOfRecords")
    total = int(count)
    # NDL emits more than one BibResource per record: the bibliographic one, and a
    # manifestation stub carrying an rdf:about and nothing else. Taking every
    # BibResource doubles the result set with blanks. Keep the ones with a title.
    #
    # With onlyBib=false a record also carries dcndl:Item elements, most of them
    # holdings reported by other libraries. Only the Digital Collections item is
    # read, for its viewer link and DOI; the rest are not parsed, displayed or
    # kept, because they are other institutions' data and outside the declared set.
    items = []
    records = root.findall("srw:records/srw:record", NS) or [root]
    for record in records:
        dl_items = [
            it for it in record.findall(".//dcndl:Item", NS)
            if _DL_PROVIDER_MARK in it.attrib.get(f"{{{NS['rdf']}}}about", "")
        ]
        for res in record.findall(".//dcndl:BibResource", NS):
            if not (_first(res, "dcterms:title") or _first(res, "dc:title")):
                continue
            items.append(_resource_to_item(res, dl_items))
    return total, items, None


# ==============================================================================
# Server + inputs
# ==============================================================================

# mcp 1.x's FastMCP takes no `version`; 2.x's MCPServer does. Passed where it is
# accepted, because a server that answers `initialize` with an empty version
# string cannot be cited by the disclosure that has to name the build it ran.
try:
    mcp = _MCPServer("ndl", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("ndl")


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, description="Title words (partial match).")
    creator: Optional[str] = Field(default=None, description="Author or editor (partial match).")
    publisher: Optional[str] = Field(default=None, description="Publisher (partial match).")
    subject: Optional[str] = Field(default=None, description="Subject heading (partial match).")
    anywhere: Optional[str] = Field(default=None, description="Free keyword across the simple-search fields.")
    ndc: Optional[str] = Field(default=None, description="NDC / NDLC classification (prefix match).")
    isbn: Optional[str] = Field(default=None, description="ISBN, 10 or 13 digit.")
    issn: Optional[str] = Field(default=None, description="ISSN.")
    from_year: Optional[str] = Field(default=None, description="Earliest publication date, YYYY or YYYY-MM or YYYY-MM-DD.")
    to_year: Optional[str] = Field(default=None, description="Latest publication date, same forms.")
    count: int = Field(default=20, ge=1, le=MAX_RECORDS, description=f"Records to return, 1-{MAX_RECORDS}.")
    start: int = Field(default=1, ge=1, description="First record position.")


class BooksInput(SearchInput):
    include_in_process: bool = Field(
        default=False,
        description="Also search 新着書誌情報 (iss-ndl-opac-inprocess): records for newly "
        "received books that are still being catalogued and may change.",
    )
    japan_related_foreign_language_only: bool = Field(
        default=False,
        description="Restrict to 日本関係外国語図書 (ndl-boj): foreign-language books about "
        "Japan, a subset of the holdings.",
    )
    exclude_serial_issues: bool = Field(
        default=True,
        description="On by default: search 蔵書（巻号以外） (iss-ndl-opac-bib), the holdings "
        "without the serial-issue-level records 蔵書 has carried since January 2024; a "
        "serial's title-level record is kept. Set false to search 蔵書 (iss-ndl-opac) "
        "with every issue record, as bibliograph 1.3.0 and earlier did. Ignored with "
        "japan_related_foreign_language_only.",
    )


class GetRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ndl_bib_id: Optional[str] = Field(default=None, description="NDL bibliographic ID.")
    jpno: Optional[str] = Field(default=None, description="Japanese national bibliography number (全国書誌番号).")

    @field_validator("ndl_bib_id", "jpno")
    @classmethod
    def _identifier_shape(cls, v: Optional[str]) -> Optional[str]:
        """An identifier is 1-32 letters, digits and hyphens. Anything else ("a and b",
        a quote that would close the CQL value) is refused before a request is built."""
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _IDENTIFIER.fullmatch(v):
            raise ValueError("an NDL identifier is 1-32 letters, digits or hyphens")
        return v


_IDENTIFIER = re.compile(r"[0-9A-Za-z-]{1,32}")
# get_record asks for this many candidates and keeps the one whose identifier
# matches: ndl_bib_id has no exact CQL index, so it is matched as free text.
GET_RECORD_CANDIDATES = 10


def _fields(params: SearchInput) -> dict[str, Optional[str]]:
    return {
        "title": params.title,
        "creator": params.creator,
        "publisher": params.publisher,
        "subject": params.subject,
        "anywhere": params.anywhere,
        "ndc": params.ndc,
        "isbn": params.isbn,
        "issn": params.issn,
        "from": params.from_year,
        "until": params.to_year,
    }


def _input_terms(fields: dict[str, Optional[str]]) -> str:
    return " ".join(str(v) for v in fields.values() if v)


# ==============================================================================
# The one search path
# ==============================================================================


async def _search(
    operation: str,
    params: SearchInput,
    dpids: list[str],
    *,
    only_bib: bool = True,
    notes: Optional[list[dict]] = None,
) -> str:
    fields = _fields(params)
    terms = _input_terms(fields)
    attribution = provider_credit(dpids)

    for dpid in dpids:
        if dpid not in PROVIDERS:
            env = M.build_envelope(
                server="ndl", operation=operation, input_terms=terms, normalized=terms,
                params={}, matching_mode=MATCHING_MODE, total=0, start=1, items=[],
                diagnostics=[M.diag(
                    "error", "DPID_NOT_PERMITTED",
                    f"Provider '{dpid}' is outside the set declared to the NDL and was not requested.",
                    "Declared providers: " + ", ".join(PROVIDERS) + ". "
                    "ndl_data_providers.json beside this file carries the full 一覧 "
                    "with each provider's application and licence conditions. Widening "
                    "the set means updating what this server says about itself, not "
                    "obtaining permission.",
                )],
                attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
            )
            return _emit(env)

    if not terms:
        env = M.build_envelope(
            server="ndl", operation=operation, input_terms="", normalized="",
            params={}, matching_mode=MATCHING_MODE, total=0, start=1, items=[],
            diagnostics=[M.diag(
                "warning", "ZERO_CONJUNCTION",
                "No search term was given, and NDL Search will not accept a provider-only query.",
                "Supply at least one of title, creator, publisher, subject or anywhere.",
            )],
            attribution=attribution, coverage_note=COVERAGE_NOTE,
        )
        return _emit(env)

    offending = reserved_word_hits(fields)
    if offending:
        env = M.build_envelope(
            server="ndl", operation=operation, input_terms=terms, normalized=terms,
            params={}, matching_mode=MATCHING_MODE, total=0, start=1, items=[],
            diagnostics=[M.diag(
                "error", "RESERVED_WORD_IN_QUERY",
                "NDL Search rejects a query whose terms carry a bare AND or OR between "
                f"words, in any case; found in: {', '.join(offending)}.",
                "The query was not sent, so this is not a result. Drop the conjunction — "
                "\"Civil Information and Education Section\" is refused, \"Civil "
                "Information Education Section\" is not — or search a distinctive part "
                "of the phrase. NOT is safe and is not caught.",
            )],
            attribution=attribution, coverage_note=COVERAGE_NOTE,
        )
        return _emit(env)

    cql = build_cql(fields, dpids)
    request = {
        "operation": "searchRetrieve",
        "version": "1.2",
        "query": cql,
        "recordSchema": "dcndl",
        "recordPacking": "xml",
        "maximumRecords": min(params.count, MAX_RECORDS),
        "startRecord": params.start,
        "onlyBib": "true" if only_bib else "false",
    }

    try:
        total, items, diagnostic = _parse_sru(await _sru_request(request))
    except Exception as exc:  # noqa: BLE001
        total, items, diagnostic = 0, [], _error_diag(exc)
    # The cap holds on what is shown, not only on what was asked for: a response
    # carrying more records than maximumRecords is cut to it.
    items = items[:request["maximumRecords"]]

    diags: list[dict] = list(notes or [])

    # NDL Search returns one representative record per cluster, and it need not
    # come from the set searched: a search of the ISSN register returned a Digital
    # Collections e-journal record on 18 Sep 2026. That record's metadata is
    # display-only whatever set found it, so the credit has to say so. The
    # open-data tool is exempt: its R100000039 records are the openly licensed ones.
    if dpids != DIGITAL_OPEN_DPIDS and not set(dpids) & set(DIGITAL_DPIDS):
        if any(it["extra"].get("source_repository") == DIGITAL_REPOSITORY for it in items):
            attribution = provider_credit(dpids + ["ndl-dl"])
            diags.append(M.diag(
                "info", "DISPLAY_ONLY_METADATA",
                "Some records shown come from the NDL Digital Collections, whose metadata "
                "carries no open licence: shown for this search, not to be redistributed "
                "or stored.",
                "extra.source_repository R100000039 marks them.",
            ))
    if diagnostic:
        diags.append(diagnostic)
    else:
        if M.detect_script(terms) == "latin":
            diags.append(M.diag(
                "warning", "SCRIPT_LATIN_QUERY",
                "The term sent was in Latin script. NDL Search indexes Japanese-language "
                "records in Japanese script; a romanised term will under-return.",
                "Send the Japanese form of the term.",
            ))
        if total == 0:
            diags.append(M.diag(
                "warning", "ZERO_CONJUNCTION",
                "No record matched all of the fields given, which are combined with AND.",
                "Drop the narrowest field and search again before concluding the work is absent.",
            ))
        else:
            diags.append(M.diag("info", "OK", f"{total} record(s) on metadata match.", None))

    env = M.build_envelope(
        server="ndl", operation=operation, input_terms=terms, normalized=terms,
        params=request,
        matching_mode=MATCHING_MODE, total=total, start=params.start,
        items=items, diagnostics=diags,
        attribution=attribution, coverage_note=COVERAGE_NOTE,
    )
    return _emit(env)


# ==============================================================================
# Tools
# ==============================================================================

_ANN = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


PROVISIONAL_NOTE = M.diag(
    "warning", "PROVISIONAL_RECORDS",
    "The search included 国立国会図書館新着書誌情報 (iss-ndl-opac-inprocess): records for "
    "newly received material that is still being catalogued. They may be revised or "
    "withdrawn when the finished record is made.",
    "Check imprint details against the finished record in 蔵書 or 全国書誌 before citing.",
)


@mcp.tool(name="ndl_search_books", annotations={"title": "Search NDL holdings (books)", **_ANN})
async def ndl_search_books(params: BooksInput) -> str:
    """Search 国立国会図書館蔵書 for books and monographs.

    Fields are combined with AND; title, creator, publisher and subject match
    partially. Returns the unified response envelope. Records are displayed, not
    stored.

    japan_related_foreign_language_only narrows to 日本関係外国語図書 (ndl-boj).
    include_in_process adds 新着書誌情報, records still being made, and every
    response that does so says so. exclude_serial_issues, on by default, searches
    蔵書（巻号以外）, leaving out the serial-issue-level records 蔵書 has carried since
    2024 (婦人公論, 9 Oct 2026: 91 records against 1,701); set it false for 蔵書 whole.
    """
    if params.japan_related_foreign_language_only:
        dpids = list(BOJ_DPIDS)
    elif params.exclude_serial_issues:
        dpids = list(BOOK_NO_ISSUES_DPIDS)
    else:
        dpids = list(BOOK_DPIDS)
    notes = []
    if params.include_in_process:
        dpids += INPROCESS_DPIDS
        notes.append(PROVISIONAL_NOTE)
    base = SearchInput(**params.model_dump(exclude={"include_in_process", "japan_related_foreign_language_only",
                                                  "exclude_serial_issues"}))
    return await _search("search_books", base, dpids, notes=notes)


@mcp.tool(name="ndl_search_national_bibliography", annotations={"title": "Search the Japanese National Bibliography", **_ANN})
async def ndl_search_national_bibliography(params: SearchInput) -> str:
    """Search 国立国会図書館全国書誌情報.

    The national bibliography is the authority for Japanese imprint data — use it
    when a publication date, publisher or edition statement has to be right rather
    than merely plausible.
    """
    return await _search("search_national_bibliography", params, BIBLIOGRAPHY_DPIDS)


@mcp.tool(name="ndl_search_articles", annotations={"title": "Search the NDL periodicals index", **_ANN})
async def ndl_search_articles(params: SearchInput) -> str:
    """Search 国立国会図書館雑誌記事索引, including the online-materials set.

    The index covers Japanese periodical articles, including many not in CiNii or
    J-STAGE. It indexes articles, not their full text.
    """
    return await _search("search_articles", params, ARTICLE_DPIDS)


@mcp.tool(name="ndl_search_digital_open", annotations={"title": "Search NDL Digital Collections (Open Data)", **_ANN})
async def ndl_search_digital_open(params: SearchInput) -> str:
    """Search 国立国会図書館デジタルコレクション（オープンデータ）.

    The open-data set only: items anyone can view online, with openly licensed
    metadata. For the whole of the Digital Collections, including items served
    to partner libraries or on NDL premises only, use ndl_search_digital.
    """
    return await _search("search_digital_open", params, DIGITAL_OPEN_DPIDS)


@mcp.tool(name="ndl_search_digital", annotations={"title": "Search the whole NDL Digital Collections", **_ANN})
async def ndl_search_digital(params: SearchInput) -> str:
    """Search 国立国会図書館デジタルコレクション (ndl-dl and ndl-dl-online).

    Digitised holdings and born-digital e-books and e-journals, whether open online,
    served to libraries and registered individuals (送信), or viewable on NDL
    premises only. Each item carries extra.viewer_url where the record links one,
    and extra.access_rights where the record states it: e-books and e-journals do,
    digitised holdings in the Search API do not, and for those the viewer page is
    the authority. This metadata is not openly licensed; it is displayed for this
    search and must not be redistributed or stored.
    """
    notes = [M.diag(
        "info", "DISPLAY_ONLY_METADATA",
        "Digital Collections metadata carries no open licence: shown for this search, "
        "not to be redistributed or stored.",
        None,
    )]
    return await _search("search_digital", params, DIGITAL_DPIDS, only_bib=False, notes=notes)


@mcp.tool(name="ndl_search_warp", annotations={"title": "Search the WARP web-archive catalogue", **_ANN})
async def ndl_search_warp(params: SearchInput) -> str:
    """Search the catalogue of インターネット資料収集保存事業（WARP）, the NDL web archive, for
    its records of archived websites and serial collections, by subject.

    This finds WARP's catalogue records — a ministry, a council, a university, a serial —
    found by name, creator or subject, through the NDL Search API; it does not search or
    return archived pages themselves, and it is the first step, not the last. Each record's
    extra.warp_start_url is the site's start URL as WARP records it: pass it to
    warp_list_captures or warp_nearest_capture to find a capture, then to warp_read_capture
    to read it. extra.warp_url is the WARP catalogue page for the site.
    """
    notes = [M.diag(
        "info", "WARP_CATALOGUE",
        "These are catalogue records for archived websites, not captures.",
        "For captures of a site, call warp_list_captures with extra.warp_start_url.",
    )]
    return await _search("search_warp", params, WARP_DPIDS, notes=notes)


@mcp.tool(name="ndl_search_online_journals", annotations={"title": "Search Japanese online journals with an ISSN", **_ANN})
async def ndl_search_online_journals(params: SearchInput) -> str:
    """Search ISSN登録国内発行オンラインジャーナル: Japanese online journals registered
    for an ISSN.

    Journal-title records, not articles. Useful for settling a journal's title
    history, publisher and ISSN / ISSN-L (extra.issn_l). For articles, use
    ndl_search_articles.
    """
    return await _search("search_online_journals", params, ONLINE_JOURNAL_DPIDS)


@mcp.tool(name="ndl_search_all", annotations={"title": "Search all declared NDL sets", **_ANN})
async def ndl_search_all(params: SearchInput) -> str:
    """Search the declared sets at once: holdings, national bibliography, both
    periodical indexes, the Digital Collections and the online-journal register.

    WARP and the in-process records are left out; each has its own route. Use when
    the material type is unknown. For a bibliographic check, the narrower tools
    return a cleaner set.
    """
    return await _search("search_all", params, ALL_DPIDS)


@mcp.tool(name="ndl_get_record", annotations={"title": "Fetch one NDL record by identifier", **_ANN})
async def ndl_get_record(params: GetRecordInput) -> str:
    """Retrieve a single record by NDL bibliographic ID or 全国書誌番号 (JP number).

    A fetch, not a search: the envelope omits `searched_for` because no term was
    chosen. Exactly one identifier is required.
    """
    given = {"jpno": params.jpno, "ndl_bib_id": params.ndl_bib_id}
    supplied = {k: v for k, v in given.items() if v}
    attribution = provider_credit(ALL_DPIDS)

    if len(supplied) != 1:
        env = M.build_envelope(
            server="ndl", operation="get_record", input_terms="", normalized="",
            params={}, matching_mode=MATCHING_MODE, total=0, start=1, items=[],
            diagnostics=[M.diag(
                "error", "ZERO_CONJUNCTION",
                "Give exactly one identifier: jpno or ndl_bib_id.",
                None,
            )],
            attribution=attribution,
        )
        return _emit(env)

    key, value = next(iter(supplied.items()))
    index = "jpno" if key == "jpno" else "anywhere"
    # Keep a fetch inside the declared set, as a search is. Until 1.3.0 this query
    # named no provider, so an identifier matched in another institution's records
    # would have come back under an NDL credit line.
    cql = build_cql({index: value}, ALL_DPIDS)
    request = {
        "operation": "searchRetrieve", "version": "1.2", "query": cql,
        "recordSchema": "dcndl", "recordPacking": "xml",
        "maximumRecords": GET_RECORD_CANDIDATES, "startRecord": 1, "onlyBib": "true",
    }

    try:
        _total, items, diagnostic = _parse_sru(await _sru_request(request))
    except Exception as exc:  # noqa: BLE001
        _total, items, diagnostic = 0, [], _error_diag(exc)

    # Only a record carrying the identifier asked for is that record. The
    # identifiers live in extra.ndl_bib_id / extra.jpno (not ids.crid / ids.naid).
    id_field = "jpno" if key == "jpno" else "ndl_bib_id"
    match = [it for it in items if (it.get("extra") or {}).get(id_field) == value]
    if diagnostic:
        diags = [diagnostic]
    elif match:
        diags = [M.diag("info", "OK", "Resolved to one record.", None)]
    elif items:
        others = ", ".join(str((it.get("extra") or {}).get(id_field)) for it in items[:3])
        diags = [M.diag(
            "warning", "ZERO_CONJUNCTION",
            f"No record carries {key}={value}. NDL returned {len(items)} other record(s) "
            f"({others}), which are not shown.",
            "Check the identifier; NDL bibliographic IDs are matched as free text.",
        )]
    else:
        diags = [M.diag(
            "warning", "ZERO_CONJUNCTION",
            f"No record matched {key}={value}.",
            "Check the identifier; NDL bibliographic IDs are matched as free text.",
        )]

    env = M.build_envelope(
        server="ndl", operation="get_record", input_terms=value, normalized=value,
        params=request,
        matching_mode=MATCHING_MODE, total=1 if match else 0, start=1,
        items=match[:1], diagnostics=diags, attribution=attribution,
    )
    return _emit(env)


def main() -> None:
    """Console-script entry point (`ndl-mcp`)."""
    mcp.run()


if __name__ == "__main__":
    main()
