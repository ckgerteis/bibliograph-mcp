"""
JDCat source (v0.1.1)
=====================
Search and record retrieval over JDCat, 人文学・社会科学総合データカタログ (Japan
Data Catalog for the Humanities and Social Sciences), the federated metadata
catalogue run by JSPS with NII on WEKO3 since July 2021.

JDCat holds METADATA, not data. Each record points to the institution that
holds the thing described, and that institution's terms govern any use of it.
On 5 October 2026 the catalogue held 187,908 records from seven distributors;
the four largest were 奈良文化財研究所 (mokkan), 神戸大学附属図書館 (新聞記事文庫
clippings and early-modern 地方文書), 一橋大学経済研究所 (table-level records of
the imperial statistical yearbooks and LTES) and 東京大学史料編纂所, with SSJDA,
JGSS and the Keio Panel Data Research Center contributing survey studies.

## Provenance of this interface

Two endpoints, both answered without a key from London on 5-7 October 2026:

  GET https://jdcat.jsps.go.jp/api/records/      WEKO3 (Invenio) JSON search:
      q, size, page, plus facet filters named as the facets are
      (Distributor, "Data Type", Topic, "Geographic Coverage", Access,
      "Data Language") and date_range1_from / date_range1_to, which the
      service accepts only as a pair.
  GET https://jdcat.jsps.go.jp/oai               OAI-PMH 2.0, GetRecord with
      metadataPrefix=jpcoar_2.0.

The JSON API is not documented by JDCat for outside use; parameter behaviour
above was established by probing. It is marked as such in every response.

## Access position, and the discipline it sets

JDCat publishes no API terms and asks no application. Its metadata is CC0.
Its robots.txt, read 7 October 2026, nonetheless disallows /api/ and /oai to
all automated agents. robots.txt is addressed to crawlers; this source is not
one, and is built so that it cannot become one — the WARP model:

  * every request answers a query a person asked; there is no harvest tool,
    no auto-pagination and no tool that takes a list
  * requests are serial and spaced at least MIN_REQUEST_INTERVAL seconds apart
  * one search returns at most MAX_RECORDS records

The robots.txt position is stated in every envelope's coverage note so that it
travels with the result rather than living only in this docstring. A sweep of
JDCat is not a use this source supports.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as _MCPServer

from ... import mediation as M
from ... import receipt_ids as _rids


def _emit(env: dict) -> str:
    """mediation.emit, after conforming the envelope to the family schema."""
    return M.emit(_rids.finish(env))

__version__ = "0.1.1"

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ==============================================================================
# Configuration
# ==============================================================================

SERVER_NAME = "jdcat"
SITE = "https://jdcat.jsps.go.jp"
SEARCH_URL = f"{SITE}/api/records/"
OAI_URL = f"{SITE}/oai"
RECORD_URL = f"{SITE}/records/{{id}}"
OAI_ID = "oai:jdcat.jsps.go.jp:{id:08d}"
TIMEOUT = 60.0
USER_AGENT = (f"bibliograph-mcp jdcat/{__version__} (interactive scholarly use; "
              "serial requests, no harvesting)")

MIN_REQUEST_INTERVAL = 3.0
BACKOFF_SECONDS = 15.0
MAX_RECORDS = 50
ABSTRACT_CHARS = 600

MATCHING_MODE = "metadata_conjunction"

PROVENANCE = {
    "search": "undocumented WEKO3 JSON API; behaviour probed 2026-10-05/07",
    "get_record": "OAI-PMH 2.0 GetRecord, jpcoar_2.0; verified 2026-10-07",
}

ATTRIBUTION = (
    "Metadata via JDCat 人文学・社会科学総合データカタログ (Japan Data Catalog for "
    "the Humanities and Social Sciences), Japan Society for the Promotion of "
    "Science and National Institute of Informatics; JDCat metadata is CC0. "
    "Each record's data is held and licensed by the distributor it names."
)

COVERAGE_NOTE = (
    "JDCat is a metadata catalogue: a record describes material held elsewhere, "
    "and the distributor's own terms govern the material. Coverage is what seven "
    "distributors have deposited (on 5 Oct 2026 mainly 奈良文化財研究所, 神戸大学"
    "附属図書館, 一橋大学経済研究所, 東京大学史料編纂所 and SSJDA), not the "
    "humanities and social sciences at large; absence here is absence from those "
    "deposits. The query matches across all metadata fields, geography and "
    "descriptions included, so a place name returns every record tagged with that "
    "place. English titles on some deposits are not the depositor's original "
    "wording; search and cite the Japanese title. JDCat's robots.txt (read 7 Oct "
    "2026) disallows /api/ and /oai to automated agents; this source issues only "
    "single, person-initiated, spaced requests and never harvests."
)

# The service's Data Type vocabulary has a fixed top term before the colon
# (JDCat humanities schema, schema.irdb.nii.ac.jp/ja/jdcat_h). record_type
# reports that term in English; the full label stays in extra.data_type.
_DATA_TYPE_TOP = {
    "出版物": "publication", "publication": "publication",
    "史資料": "archival_material", "materials": "archival_material",
    "公的統計": "official_statistics", "official statistics": "official_statistics",
    "量的調査": "quantitative_survey", "quantitative research": "quantitative_survey",
    "質的調査": "qualitative_survey", "qualitative research": "qualitative_survey",
    "データベース": "database", "database": "database",
}

# Facet names exactly as the service spells them; the tool's own argument names
# map onto these.
FACETS = ("Distributor", "Data Type", "Topic", "Geographic Coverage", "Time Period(s)",
          "Access", "Data Language")

# A DOI as a whole value, bare or as a doi.org URL. Embedded DOIs inside prose
# (a citation sentence that mentions one) are deliberately not matched.
_DOI_VALUE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s?#]+)$", re.I)

# Stable JDCat item keys shared by both item types seen so far (12 humanities,
# 20 social-science DDI).
_K_TITLE = "item_1551264308487"
_TITLE_VAL, _TITLE_LANG = "subitem_1551255647225", "subitem_1551255648112"

# ==============================================================================
# Transport — serial, interval-held, no auto-pagination
# ==============================================================================

_lock = asyncio.Lock()
_last_request_at = 0.0


async def _get(url: str, params: Any = None) -> tuple[Optional[httpx.Response], list[dict]]:
    """One serial GET with the interval held. Returns (response, diagnostics)."""
    global _last_request_at
    diagnostics: list[dict] = []
    async with _lock:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT,
                                         headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 429:
                    diagnostics.append(M.diag(
                        "warning", "RATE_LIMITED",
                        f"{url} answered 429; backed off {BACKOFF_SECONDS:.0f}s and retried once.",
                        "Stop querying JDCat for some minutes rather than retrying in a loop.",
                    ))
                    await asyncio.sleep(BACKOFF_SECONDS)
                    resp = await client.get(url, params=params)
        except httpx.ReadTimeout:
            diagnostics.append(M.diag(
                "error", "READ_TIMEOUT",
                f"{url} did not answer within {TIMEOUT:.0f}s. A timeout is not a zero "
                "result and not evidence the catalogue lacks the material.",
                "Wait, then issue one request; do not report the query as empty.",
            ))
            return None, diagnostics
        except httpx.HTTPError as exc:
            diagnostics.append(M.diag(
                "error", "TRANSPORT_ERROR", f"{url}: {type(exc).__name__}: {exc}",
                "Check that this machine can reach jdcat.jsps.go.jp before retrying.",
            ))
            return None, diagnostics
        finally:
            _last_request_at = time.monotonic()
    if resp.status_code == 400:
        diagnostics.append(M.diag(
            "error", "API_ERROR",
            f"JDCat rejected the request (400): {resp.text[:300]}",
            "A filter value or date range the service did not accept; the query was "
            "not run, so this is not a zero result.",
        ))
        return None, diagnostics
    if resp.status_code != 200:
        diagnostics.append(M.diag(
            "error", "HTTP_STATUS", f"{url} answered {resp.status_code}.",
            "Report the status rather than treating it as zero results.",
        ))
        return None, diagnostics
    return resp, diagnostics

# ==============================================================================
# Shaping a JSON search hit
# ==============================================================================


def _mlt(im: dict, key: str) -> list:
    v = im.get(key)
    if isinstance(v, dict):
        vals = v.get("attribute_value_mlt")
        return vals if isinstance(vals, list) else []
    return []


def _by_attr(im: dict, *names: str) -> list:
    """attribute_value_mlt of the first attribute whose name matches (trimmed)."""
    wanted = {n.strip().lower() for n in names}
    for v in im.values():
        if isinstance(v, dict) and str(v.get("attribute_name", "")).strip().lower() in wanted:
            vals = v.get("attribute_value_mlt")
            return vals if isinstance(vals, list) else []
    return []


_LANGS = ("ja", "en", "ko")


def _slot(text: str) -> str:
    """'ja', 'ko' or 'en' by script, for values the source gives without a language."""
    script = M.detect_script(text)
    if script == "latin":
        return "en"
    if script in ("hangul", "han_hangul"):
        return "ko"
    return "ja"


def _d(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x: Any) -> list:
    """A list as a list, a lone string as a one-item list, anything else as empty."""
    if isinstance(x, list):
        return x
    return [x] if isinstance(x, str) else []


def _titles(meta: dict, im: dict) -> dict:
    out: dict[str, Optional[str]] = {k: None for k in _LANGS}
    for e in _mlt(im, _K_TITLE):
        if not isinstance(e, dict):
            continue
        val, lang = e.get(_TITLE_VAL), e.get(_TITLE_LANG)
        if isinstance(val, str) and val.strip():
            slot = lang if lang in _LANGS else _slot(val)
            out[slot] = out[slot] or val.strip()
    if not any(out.values()):
        for val in _l(meta.get("title")):
            if isinstance(val, str) and val.strip():
                slot = _slot(val)
                out[slot] = out[slot] or val.strip()
    return out


def _person(pairs: list[tuple[Any, Any]]) -> Optional[dict]:
    """One creator from (name, lang) pairs. The source states the language;
    script decides only where it does not. A `ko` key appears only when a
    Korean name is present, so the family's {ja, en} shape is otherwise kept."""
    p: dict[str, Optional[str]] = {"ja": None, "en": None}
    for name, lang in pairs:
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        slot = lang if lang in _LANGS else _slot(name)
        p[slot] = p.get(slot) or name
    return p if any(p.values()) else None


def _creators(meta: dict, im: dict) -> list[dict]:
    """Creators as {ja, en}, one entry per creator, in the source's order.

    Two shapes are in use: humanities records nest names under
    subitem_1551255898956; social-science records under creatorNames. A
    corporate creator (内務省, 朝鮮総督府) is passed through as the creator the
    record names; nothing is split or reordered.
    """
    out: list[dict] = []
    for e in _by_attr(im, "Creator", "Author"):
        if not isinstance(e, dict):
            continue
        pairs: list[tuple[str, Optional[str]]] = []
        for n in e.get("subitem_1551255898956") if isinstance(e.get("subitem_1551255898956"), list) else []:
            if isinstance(n, dict):
                pairs.append((n.get("subitem_1551255905565"), n.get("subitem_1551255907416")))
        for n in e.get("creatorNames") if isinstance(e.get("creatorNames"), list) else []:
            if isinstance(n, dict):
                pairs.append((n.get("creatorName"), n.get("creatorNameLang")))
        p = _person(pairs)
        if p:
            out.append(p)
    if not out:
        # The flattened field interleaves languages with no tags
        # (内務省, Japan. Ministry of Home Affairs, 朝鮮総督府, ...). A non-Latin
        # name followed directly by a Latin one is taken as one creator; any
        # other name stands alone. Nothing is reordered.
        names = [n.strip() for n in _l(_d(meta.get("creator")).get("creatorName"))
                 if isinstance(n, str) and n.strip()]
        i = 0
        while i < len(names):
            if (i + 1 < len(names) and _slot(names[i]) != "en"
                    and _slot(names[i + 1]) == "en"):
                p = _person([(names[i], None), (names[i + 1], None)])
                i += 2
            else:
                p = _person([(names[i], None)])
                i += 1
            if p:
                out.append(p)
    return out


def _strings(o: Any):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def _dois(*blobs: Any) -> list[str]:
    seen: list[str] = []
    for blob in blobs:
        for s in _strings(blob):
            m = _DOI_VALUE.match(s.strip())
            if m:
                doi = m.group(1).rstrip(".,;)")
                if doi not in seen:
                    seen.append(doi)
    return seen


def _own_doi_fields(meta: dict, im: dict) -> list:
    """The fields that identify the record itself, as opposed to a related work.

    A relation carrying a relationType (isPartOf, references, ...) names some
    other work, so only untyped relations count; the social-science Study ID
    and URI attributes identify the study itself.
    """
    rel = _d(meta.get("relation"))
    types = _l(_d(rel.get("@attributes")).get("relationType"))
    typed = any(isinstance(t, list) and any(t) or isinstance(t, str) and t for t in types)
    own: list = []
    if not typed:
        own.append(rel.get("relatedIdentifier"))
    own += [_by_attr(im, "Study ID"), _by_attr(im, "URI"), _by_attr(im, "識別子", "Identifier")]
    return own


def _record_type(labels: list[str]) -> str:
    for lab in labels:
        top = lab.split(":", 1)[0].strip()
        if top in _DATA_TYPE_TOP:
            return _DATA_TYPE_TOP[top]
    return "unknown"


def _data_type_labels(meta: dict, im: dict) -> list[str]:
    labels: list[str] = []
    for e in _by_attr(im, "Data K", "Data Kind"):
        if isinstance(e, dict):
            labels += [v for k, v in e.items() if k == "subitem_1591178807921" and isinstance(v, str)]
    for d in meta.get("description") if isinstance(meta.get("description"), list) else []:
        if isinstance(d, dict) and d.get("descriptionType") == "Other":
            v = d.get("value")
            if isinstance(v, str) and ":" in v and v.split(":", 1)[0].strip() in _DATA_TYPE_TOP:
                labels.append(v)
    return list(dict.fromkeys(labels))


def _abstract(meta: dict) -> tuple[Optional[str], bool]:
    for d in meta.get("description") if isinstance(meta.get("description"), list) else []:
        if isinstance(d, dict) and d.get("descriptionType") == "Abstract":
            v = d.get("value")
            if isinstance(v, str) and v.strip():
                v = v.strip()
                return (v[:ABSTRACT_CHARS], True) if len(v) > ABSTRACT_CHARS else (v, False)
    return None, False


def _flat(v: Any) -> list[str]:
    return [s for s in _strings(v) if s.strip()]


def item_from_hit(hit: dict) -> dict:
    """One envelope item from one JSON search hit."""
    meta = _d(hit.get("metadata"))
    im = _d(meta.get("_item_metadata"))
    rid = str(hit.get("id") or meta.get("control_number") or "")
    t = _titles(meta, im)
    distributors = [n for n in _l(_d(meta.get("contributor")).get("contributorName"))
                    if isinstance(n, str) and n.strip()]
    own = _dois(*_own_doi_fields(meta, im))
    dois = own + [x for x in _dois(meta.get("relation"), meta.get("identifier"), im)
                  if x not in own]
    labels = _data_type_labels(meta, im)
    abstract, cut = _abstract(meta)
    oai = (_d(meta.get("_oai")) or _d(im.get("_oai"))).get("id")
    oai = oai.strip() or None if isinstance(oai, str) else None  # the schema takes a string or null
    extra = {
        "jdcat_id": rid,
        "distributors": distributors,
        "data_type": labels,
        "temporal": _flat(meta.get("temporal")),
        "date_range_indexed": [r for r in meta.get("date_range1") or [] if isinstance(r, dict)]
        if isinstance(meta.get("date_range1"), list) else [],
        "geographic_coverage": _flat(_d(meta.get("geoLocation")).get("geoLocationPlace")),
        "subjects": [s.get("value") for s in (meta.get("subject") if isinstance(meta.get("subject"), list) else [])
                     if isinstance(s, dict) and isinstance(s.get("value"), str)],
        "publisher": _flat(meta.get("publisher")),
        "access_rights": _flat(meta.get("accessRights")),
        "rights": _flat(meta.get("rights")) + [
            s for e in _by_attr(im, "Rights") for s in _flat(e)],
        "identifiers": [i.get("value") for i in (meta.get("identifier") if isinstance(meta.get("identifier"), list) else [])
                        if isinstance(i, dict) and isinstance(i.get("value"), str)],
        "dois": dois,
        "own_doi_found": bool(own),
        "language": _flat(meta.get("language")),
        "item_type": meta.get("itemtype"),
        "abstract": abstract,
        "abstract_truncated": cut,
        "record_url": RECORD_URL.format(id=rid) if rid else None,
        "deposited": meta.get("publish_date"),
    }
    return M.make_item(
        title_ja=t["ja"], title_en=t["en"], title_ko=t["ko"],
        authors=_creators(meta, im),
        doi=own[0] if own else None,
        oai_id=oai,
        url_ja=RECORD_URL.format(id=rid) if rid else None,
        matched_in="metadata_any_field",
        record_type=_record_type(labels),
        holding_org=distributors[0] if distributors else None,
        extra=extra,
    )


def facets_from(payload: dict) -> dict:
    """Facet buckets exactly as the service returned them.

    Counts are per LABEL: a record labelled in both Japanese and English is
    counted under each label, and the two labels for one value need not agree
    (a deposit may carry the Japanese label only). Never add buckets together.
    """
    out: dict[str, dict] = {}
    for name, agg in _d(payload.get("aggregations")).items():
        if name not in FACETS or not isinstance(agg, dict):
            continue
        inner = agg.get(name) if isinstance(agg.get(name), dict) else agg
        out[name] = {
            "buckets": [{"label": b.get("key") if isinstance(b.get("key"), str) else None,
                         "count": b.get("doc_count") if isinstance(b.get("doc_count"), int) else None}
                        for b in (inner.get("buckets") if isinstance(inner.get("buckets"), list) else [])
                        if isinstance(b, dict)],
            "other_count": inner.get("sum_other_doc_count") if isinstance(
                inner.get("sum_other_doc_count"), int) else None,
        }
    return out

# ==============================================================================
# Shaping an OAI-PMH jpcoar_2.0 record
# ==============================================================================

_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "jpcoar": "https://github.com/JPCOAR/schema/blob/master/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "datacite": "https://schema.datacite.org/meta/kernel-4/",
}
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _txt(el: Optional[ET.Element]) -> Optional[str]:
    return el.text.strip() if el is not None and el.text and el.text.strip() else None


def item_from_oai(xml_text: str) -> tuple[Optional[dict], Optional[str], dict]:
    """(item, oai_error_code, header) from one GetRecord response."""
    root = ET.fromstring(xml_text)
    err = root.find("oai:error", _NS)
    if err is not None:
        return None, err.get("code") or "unknown", {}
    rec = root.find(".//oai:record", _NS)
    md = rec.find("oai:metadata/jpcoar:jpcoar", _NS) if rec is not None else None
    if md is None:
        return None, "noMetadata", {}
    header = {
        "oai_id": _txt(rec.find("oai:header/oai:identifier", _NS)),
        "datestamp": _txt(rec.find("oai:header/oai:datestamp", _NS)),
        "sets": [s.text for s in rec.findall("oai:header/oai:setSpec", _NS) if s.text],
    }
    t: dict[str, Optional[str]] = {k: None for k in _LANGS}
    for el in md.findall("dc:title", _NS):
        v = _txt(el)
        if v:
            lang = el.get(_XML_LANG)
            slot = lang if lang in _LANGS else _slot(v)
            t[slot] = t[slot] or v
    authors = []
    for c in md.findall("jpcoar:creator", _NS):
        p = _person([(_txt(n), n.get(_XML_LANG)) for n in c.findall("jpcoar:creatorName", _NS)])
        if p:
            authors.append(p)
    distributors = [_txt(n) for c in md.findall("jpcoar:contributor", _NS)
                    if c.get("contributorType") == "Distributor"
                    for n in c.findall("jpcoar:contributorName", _NS) if _txt(n)]
    related, own_related = [], []
    for rel in md.findall("jpcoar:relation", _NS):
        for r in rel.findall("jpcoar:relatedIdentifier", _NS):
            v = _txt(r)
            if v:
                related.append(v)
                if not rel.get("relationType"):  # a typed relation names another work
                    own_related.append(v)
    identifiers = [_txt(i) for i in md.findall("jpcoar:identifier", _NS) if _txt(i)]
    own = _dois(own_related, identifiers)
    dois = own + [x for x in _dois(related) if x not in own]
    labels = [v for v in (_txt(d) for d in md.findall("datacite:description", _NS))
              if v and ":" in v and v.split(":", 1)[0].strip() in _DATA_TYPE_TOP]
    abstract = next((_txt(d) for d in md.findall("datacite:description", _NS)
                     if d.get("descriptionType") == "Abstract" and _txt(d)), None)
    rid = (header["oai_id"] or "").rsplit(":", 1)[-1].lstrip("0") or None
    extra = {
        "jdcat_id": rid,
        "distributors": distributors,
        "data_type": list(dict.fromkeys(labels)),
        "temporal": [_txt(x) for x in md.findall("dcterms:temporal", _NS) if _txt(x)],
        "dates": [{"type": d.get("dateType"), "value": _txt(d)}
                  for d in md.findall("datacite:date", _NS) if _txt(d)],
        "geographic_coverage": [_txt(g) for g in md.findall(
            "datacite:geoLocation/datacite:geoLocationPlace", _NS) if _txt(g)],
        "subjects": [_txt(s) for s in md.findall("jpcoar:subject", _NS) if _txt(s)],
        "publisher": [_txt(p) for p in md.findall("dc:publisher", _NS) if _txt(p)],
        "access_rights": [_txt(a) for a in md.findall("dcterms:accessRights", _NS) if _txt(a)],
        "rights": [_txt(r) for r in md.findall("dc:rights", _NS) if _txt(r)],
        "identifiers": identifiers,
        "related_identifiers": related,
        "dois": dois,
        "own_doi_found": bool(own),
        "language": [_txt(x) for x in md.findall("dc:language", _NS) if _txt(x)],
        "abstract": abstract,
        "abstract_truncated": False,
        "record_url": RECORD_URL.format(id=rid) if rid else None,
        "oai_datestamp": header["datestamp"],
        "oai_sets": header["sets"],
    }
    item = M.make_item(
        title_ja=t["ja"], title_en=t["en"], title_ko=t["ko"], authors=authors,
        doi=own[0] if own else None, oai_id=header["oai_id"],
        url_ja=RECORD_URL.format(id=rid) if rid else None,
        matched_in="identifier", record_type=_record_type(labels),
        holding_org=distributors[0] if distributors else None, extra=extra,
    )
    return item, None, header

# ==============================================================================
# Tools
# ==============================================================================

try:
    mcp = _MCPServer("jdcat", version=__version__)
except TypeError:  # mcp SDK 1.x
    mcp = _MCPServer("jdcat")


class SearchInput(BaseModel):
    """Search JDCat's metadata."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description=(
        "Search terms. Space-separated terms are ANDed across every metadata field "
        "(titles, creators, descriptions, subjects, geography). Search in Japanese: "
        "English titles exist only on some deposits."
    ))
    distributor: Optional[list[str]] = Field(None, description=(
        "Restrict to distributors, by facet label, e.g. '神戸大学附属図書館', "
        "'一橋大学経済研究所', 'SSJ データアーカイブ', '東京大学史料編纂所', "
        "'奈良文化財研究所'. Several values are ORed."
    ))
    data_type: Optional[list[str]] = Field(None, description=(
        "Restrict by Data Type label, e.g. '出版物: テキスト', '公的統計: 集計データ、統計表', "
        "'量的調査: ミクロデータ'. Several values are ORed."
    ))
    topic: Optional[list[str]] = Field(None, description="Restrict by Topic label, e.g. '政治'.")
    geographic_coverage: Optional[list[str]] = Field(None, description=(
        "Restrict by Geographic Coverage label, e.g. '朝鮮', '台湾'."))
    access: Optional[list[str]] = Field(None, description=(
        "Restrict by Access label: 'open access', 'metadata only access', "
        "'restricted access' (or the Japanese labels)."))
    date_from: Optional[str] = Field(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$", description=(
        "Start of a date window (YYYY, YYYY-MM or YYYY-MM-DD). Must be given with "
        "date_to. Filters on the FIRST date a record indexes, so a table covering "
        "1932-1936 is found by a window containing 1932 only. Both ends are "
        "inclusive: date_to '1919' is sent as 1919-12-31."))
    date_to: Optional[str] = Field(None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$",
                                   description="End of the date window; with date_from.")
    size: int = Field(20, ge=1, le=MAX_RECORDS, description=f"Records to return, at most {MAX_RECORDS}.")
    page: int = Field(1, ge=1, description="Results page. There is no auto-pagination.")

    @model_validator(mode="after")
    def _pair(self):
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("date_from and date_to must be given together; JDCat "
                             "rejects a half-open date window")
        if self.date_from and self.date_to:
            lo, hi = _as_date(self.date_from, start=True), _as_date(self.date_to, start=False)
            if lo > hi:
                raise ValueError(f"date_from {self.date_from} is after date_to {self.date_to}")
        return self


class GetRecordInput(BaseModel):
    """Fetch one JDCat record."""
    model_config = ConfigDict(extra="forbid")

    record: str = Field(..., min_length=1, description=(
        "A JDCat record id (e.g. '7058'), its OAI identifier "
        "('oai:jdcat.jsps.go.jp:00007058') or its URL "
        "('https://jdcat.jsps.go.jp/records/7058')."))


_FILTER_FIELDS = {
    "distributor": "Distributor", "data_type": "Data Type", "topic": "Topic",
    "geographic_coverage": "Geographic Coverage", "access": "Access",
}


def _as_date(d: str, start: bool) -> date:
    """The first (start=True) or last day a YYYY, YYYY-MM or YYYY-MM-DD names.
    Raises ValueError on an impossible month or day."""
    parts = [int(x) for x in d.split("-")]
    y = parts[0]
    m = parts[1] if len(parts) > 1 else (1 if start else 12)
    if not 1 <= m <= 12:
        raise ValueError(f"{d!r}: month must be 01-12")
    if len(parts) > 2:
        return date(y, m, parts[2])
    return date(y, m, 1 if start else calendar.monthrange(y, m)[1])


def window_end(d: str) -> str:
    """The last day a YYYY or YYYY-MM upper bound names.

    JDCat reads a bare year in date_range1_to as 1 January of that year
    (probed 7 Oct 2026: 1919-1919 returned 0 clippings, 1919-1919-12-31
    returned 30), so a window the user means as inclusive is closed out here
    and the value actually sent is what the receipt records.
    """
    return _as_date(d, start=False).isoformat()


def search_params(p: SearchInput) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = [("q", p.query), ("size", str(p.size)), ("page", str(p.page))]
    for arg, facet in _FILTER_FIELDS.items():
        for v in getattr(p, arg) or []:
            out.append((facet, v))
    if p.date_from and p.date_to:
        out += [("date_range1_from", p.date_from), ("date_range1_to", window_end(p.date_to))]
    return out


def _receipt_params(pairs: list[tuple[str, str]]) -> dict:
    d: dict[str, Any] = {}
    for k, v in pairs:
        if k in d:
            d[k] = (d[k] if isinstance(d[k], list) else [d[k]]) + [v]
        else:
            d[k] = v
    return d


def parse_record_id(s: str) -> Optional[int]:
    s = s.strip()
    m = (re.fullmatch(r"\d+", s) or re.fullmatch(r"oai:jdcat\.jsps\.go\.jp:(\d+)", s)
         or re.fullmatch(r"https?://jdcat\.jsps\.go\.jp/records/(\d+)/?(?:[?#].*)?", s))
    if not m:
        return None
    return int(m.group(1) if m.groups() else m.group(0))


def search_envelope(p: SearchInput, payload: Optional[dict], diagnostics: list[dict]) -> dict:
    pairs = search_params(p)
    items: list[dict] = []
    total = 0
    facets: dict = {}
    hits = _d(payload.get("hits")) if isinstance(payload, dict) else {}
    if payload is not None and not (hits and isinstance(hits.get("hits"), list)):
        diagnostics.append(M.diag(
            "error", "API_ERROR",
            "JDCat answered with a body that has no hits list; the response shape "
            "has changed or the request was not understood.",
            "Report the query; this is not a zero result."))
        payload = None
    if payload is not None:
        raw_total = hits.get("total")
        if isinstance(raw_total, dict):  # Elasticsearch 7 shape: {"value": n, "relation": ...}
            if raw_total.get("relation") not in (None, "eq"):
                diagnostics.append(M.diag(
                    "warning", "TOTAL_IS_LOWER_BOUND",
                    f"JDCat reported the total as a lower bound ({raw_total.get('relation')}).",
                    "Cite it as 'at least'."))
            raw_total = raw_total.get("value")
        items = [item_from_hit(h) for h in hits["hits"] if isinstance(h, dict)]
        facets = facets_from(payload)
        if isinstance(raw_total, int) and not isinstance(raw_total, bool):
            total = raw_total
        else:
            total = len(items)
            diagnostics.append(M.diag(
                "warning", "TOTAL_UNREPORTED",
                "JDCat's response carried no usable total; the count given is the "
                "number of records on this page, not a corpus count.",
                "Do not cite this total."))
            raw_total = None
        if raw_total == 0 and not items:
            diagnostics.append(M.diag(
                "info", "ZERO_RESULTS",
                "JDCat returned no records for this query and filter set.",
                "A zero here is a zero across the deposits JDCat holds, not across "
                "the field; check the filter labels against the facets of an "
                "unfiltered search.",
            ))
        if facets:
            diagnostics.append(M.diag(
                "info", "FACET_COUNTS_PER_LABEL",
                "Facet counts are per label as the service reports them: one record "
                "can be counted under a Japanese and an English label, and the two "
                "need not agree. Facets describe the query before any filter.",
                "Cite one label's count; never add a Japanese and an English bucket.",
            ))
        for arg, facet in _FILTER_FIELDS.items():
            known = {b["label"] for b in (facets.get(facet) or {}).get("buckets", [])}
            for v in getattr(p, arg) or []:
                if known and v not in known:
                    diagnostics.append(M.diag(
                        "warning", "FILTER_LABEL_NOT_IN_FACETS",
                        f"The {facet} filter value {v!r} is not among the labels this "
                        "query's facets returned; the filter may match nothing.",
                        "Use a label exactly as the facets spell it.",
                    ))
        if p.date_from:
            diagnostics.append(M.diag(
                "info", "DATE_FILTER_FIRST_DATE_ONLY",
                "The date window filters on the first date each record indexes "
                "(date_range1), not on its whole coverage period. An upper bound "
                "given as a year or month was sent as its last day.",
                "Read extra.temporal for the period a record covers.",
            ))
    env = M.build_envelope(
        server=SERVER_NAME, operation="search_metadata",
        input_terms=p.query, normalized=p.query.strip(),
        params=_receipt_params(pairs), matching_mode=MATCHING_MODE,
        total=total, start=(p.page - 1) * p.size, items=items,
        diagnostics=diagnostics, attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
    )
    env["endpoint"] = SEARCH_URL
    env["endpoint_provenance"] = PROVENANCE["search"]
    env["facets"] = facets
    return env


def record_envelope(raw: str, oai_id: str, xml_text: Optional[str],
                    diagnostics: list[dict]) -> dict:
    items: list[dict] = []
    if xml_text is not None:
        try:
            item, err, _ = item_from_oai(xml_text)
        except ET.ParseError as exc:
            item, err = None, None
            diagnostics.append(M.diag(
                "error", "API_ERROR", f"The OAI response was not well-formed XML: {exc}",
                "Report the record id; do not treat it as absent."))
        except Exception as exc:  # noqa: BLE001 - well-formed XML of an unexpected shape
            item, err = None, None
            diagnostics.append(M.diag(
                "error", "API_ERROR",
                f"The OAI record had an unexpected shape ({type(exc).__name__}).",
                "Report the record id; do not treat it as absent."))
        if item is not None:
            items.append(item)
        elif err == "idDoesNotExist":
            diagnostics.append(M.diag(
                "warning", "NOT_FOUND", f"JDCat has no record {oai_id}.",
                "Check the id; a withdrawn record answers the same way."))
        elif err:
            diagnostics.append(M.diag(
                "error", "API_ERROR", f"The OAI-PMH service answered error {err!r}.",
                "Report the code and the record id."))
    env = M.build_envelope(
        server=SERVER_NAME, operation="get_record",
        input_terms=raw, normalized=oai_id,
        params={"verb": "GetRecord", "metadataPrefix": "jpcoar_2.0", "identifier": oai_id},
        matching_mode="identifier_fetch", total=len(items), start=0, items=items,
        diagnostics=diagnostics, attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
    )
    env["endpoint"] = OAI_URL
    env["endpoint_provenance"] = PROVENANCE["get_record"]
    return env


@mcp.tool()
async def jdcat_search(params: SearchInput) -> str:
    """Search JDCat (人文学・社会科学総合データカタログ), the JSPS/NII metadata catalogue
    of humanities and social-science research data.

    Returns records with their distributor, data type, coverage period, geography,
    DOI where the record carries one, and the access terms the distributor states,
    plus the facet counts JDCat reports for the query — by distributor, data type,
    topic, geography, period and access — so the composition of a result set can
    be read before any record is.

    Main holdings: 神戸大学附属図書館's 新聞記事文庫 newspaper clippings (Meiji to
    1971, with record-level DOIs), 一橋大学経済研究所's table-level records of the
    imperial statistical yearbooks and LTES, SSJDA survey studies, 東京大学史料編纂所
    materials and 奈良文化財研究所 mokkan. A record is metadata only: the
    material is held, and licensed, by the distributor named.

    One page per call, at most 50 records, requests spaced three seconds apart.
    This tool is for asking questions of JDCat, not for harvesting it.
    """
    pairs = search_params(params)
    resp, diagnostics = await _get(SEARCH_URL, pairs)
    payload = None
    if resp is not None:
        try:
            payload = resp.json()
        except ValueError:
            diagnostics.append(M.diag(
                "error", "API_ERROR", "JDCat answered 200 with a body that is not JSON.",
                "The undocumented interface may have changed; report it."))
    return _emit(search_envelope(params, payload, diagnostics))


@mcp.tool()
async def jdcat_get_record(params: GetRecordInput) -> str:
    """Fetch one JDCat record in full, by id, OAI identifier or URL, through
    JDCat's OAI-PMH service (jpcoar_2.0).

    Returns every creator, distributor, date, period, place, subject, rights
    statement and related identifier the record carries, with the DOI where one
    is present and the OAI datestamp of the record as fetched.
    """
    rid = parse_record_id(params.record)
    if rid is None:
        env = M.build_envelope(
            server=SERVER_NAME, operation="get_record", input_terms=params.record,
            normalized=params.record, params={}, matching_mode="identifier_fetch",
            total=0, start=0, items=[], attribution=ATTRIBUTION, coverage_note=COVERAGE_NOTE,
            diagnostics=[M.diag(
                "error", "BAD_IDENTIFIER",
                f"{params.record!r} is not a JDCat record id, OAI identifier or record URL.",
                "Pass e.g. '7058', 'oai:jdcat.jsps.go.jp:00007058' or the record URL.")],
        )
        return _emit(env)
    oai_id = OAI_ID.format(id=rid)
    resp, diagnostics = await _get(OAI_URL, {"verb": "GetRecord", "metadataPrefix": "jpcoar_2.0",
                                             "identifier": oai_id})
    return _emit(record_envelope(params.record, oai_id,
                                  resp.text if resp is not None else None, diagnostics))


def main() -> None:  # pragma: no cover
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
