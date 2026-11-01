# jdcat — JDCat 人文学・社会科学総合データカタログ

v0.1.0, written 7 October 2026. A bibliograph source from the start; never released
on its own.

## What it is

JDCat (Japan Data Catalog for the Humanities and Social Sciences) is the
federated metadata catalogue that JSPS runs with NII on WEKO3. It was launched in
July 2021 under the JSPS data-infrastructure programme and is now run under the
successor programme (人文学・社会科学データインフラストラクチャー強化事業), with
東京大学史料編纂所 and 社会科学研究所 as core institutions. It holds **metadata
only**. Each record points to the institution that holds the material, and that
institution's terms govern the material. JDCat's own metadata is CC0.

On 5 October 2026 the catalogue reported 187,908 records. That figure is the
API's own total, read from its facet counts, not a count made by this server.
Five distributors account for nearly all of them:

| Distributor (facet label) | Records | What they are |
|---|---|---|
| 奈良文化財研究所 | 79,785 | mokkan records, mostly eighth century; site reports |
| 神戸大学附属図書館 | 65,442 | 新聞記事文庫 newspaper clippings (Meiji to 1971; JaLC DOIs on every record sampled) and early-modern 地方文書 |
| 一橋大学経済研究所 | 34,293 | table-level records of 日本帝国統計年鑑 and the LTES series, colonial tables included (DOIs on every record sampled) |
| 東京大学史料編纂所 | 6,612 | historical materials, among them records announcing the MOJIZO decipherment tools |
| SSJ データアーカイブ | ~1,600 | survey studies (microdata held by SSJDA under its own application route) |

JGSS (120 under its Japanese label) and the Keio Panel Data Research Center
(36) contribute the rest. All counts are the API's facet counts under the
Japanese label, read 5 October 2026.

## Two tools

| Tool | Does | Endpoint |
|---|---|---|
| `jdcat_search` | metadata search with facet filters; returns records plus the facet counts JDCat reports for the query | `GET /api/records/` (WEKO3 JSON) |
| `jdcat_get_record` | one record in full, by id, OAI identifier or record URL | `GET /oai?verb=GetRecord&metadataPrefix=jpcoar_2.0` |

There is no harvest tool. See "Access position" below.

## Access position

JDCat publishes no API terms and asks for no application. Both endpoints
answered without a key on 5 and 7 October 2026, from the cloud and from a
Windows desktop in London. **Its robots.txt, read 7 October 2026, disallows
`/api/` and `/oai` to all automated agents.** robots.txt is addressed to
crawlers. This source is built so that it cannot act as one, on the model
`warp` follows for WARP's terms:

- every request answers a query a person asked;
- there is no auto-pagination, no tool that takes a list, and no harvest;
- requests are serial and spaced at least three seconds apart;
- a search returns at most 50 records.

The robots.txt position is stated in every envelope's `coverage_note`, so
that it travels with each result. A sweep of JDCat is not a use this source
supports. Anyone who wants one should ask JDCat first.

## The search interface is undocumented

JDCat documents the JSON search API for its own front end, not for outside
use. The behaviour below was established by probing on 5 and 7 October 2026,
and every search envelope carries `endpoint_provenance` saying so.

- `q` matches across **every metadata field**: titles, creators,
  descriptions, subjects and geography. Space-separated terms are ANDed. A
  place name therefore returns every record tagged with that place: 朝鮮
  returns about 3,600 imperial-yearbook tables whose coverage includes Korea.
- Facet filters are passed under the facet's own name (`Distributor`,
  `Data Type`, `Topic`, `Geographic Coverage`, `Access`). Several values of
  one facet are ORed. A label is matched exactly, and Japanese and English
  labels both work.
- **Facets describe the query before any filter.** They are post-filter
  aggregations, so they show what a filter is choosing from.
- **Facet counts are per label, not per record.** A record labelled in
  Japanese and English is counted under both, and the two need not agree.
  For 労働組合, SSJDA appears as `SSJ データアーカイブ` 66 and `SSJDA` 64. Never
  add buckets together.
- The date window (`date_range1_from` / `date_range1_to`) is accepted only as
  a pair; a half-open window is a 400. It filters on the **first** date a
  record indexes. A yearbook table covering 1932–1936 is indexed at 1932.
- **A bare year as the upper bound means 1 January.** The window 1919–1919
  returned no clippings, while 1919 to 1919-12-31 returned 30. The tool sends
  a year or month upper bound as its last day and records the value it sent.
  Both ends of the window are therefore inclusive, as a reader expects.
- `size` was accepted up to at least 200. This source caps it at 50.
- An impossible date (month 13, 31 February) or a window whose start falls
  after its end is refused before any request is made.

## Field mapping

| Envelope field | From |
|---|---|
| `title.ja` / `title.en` / `title.ko` | the Title attribute with its stated language. Script is used only when the source gives no language, and Hangul goes to `ko` |
| `authors[]` | `{ja, en}` per creator, in the source's order. Corporate creators (内務省, 朝鮮総督府) are passed through as named and never split |
| `ids.doi` | the record's **own** DOI: the first DOI given as a whole value in an untyped relation, the identifier, or the study-ID/URI fields. A relation with a `relationType` (isPartOf, references) names another work and is never taken. A DOI inside a citation sentence is never taken. Every DOI found is kept in `extra.dois`, and `extra.own_doi_found` says whether `ids.doi` was set |
| `ids.oai_id` | the record's OAI identifier |
| `ids.url_ja`, `extra.record_url` | `https://jdcat.jsps.go.jp/records/{id}` |
| `source.holding_org` | the first Distributor name |
| `source.year` | **always null.** JDCat records a coverage date, which is a clipping's date or a table's period, not a publication year. The server does not choose between them. Read `extra.temporal` |
| `record_type` | the top term of JDCat's Data Type vocabulary, in English: `publication`, `archival_material`, `official_statistics`, `quantitative_survey`, `qualitative_survey`, `database` or `unknown`. The full label is kept in `extra.data_type` |
| `extra` | `distributors`, `data_type`, `temporal`, `date_range_indexed`, `geographic_coverage`, `subjects`, `publisher`, `access_rights`, `rights`, `identifiers`, `dois`, `language`, `item_type`, `abstract` (search: the first 600 characters, with `abstract_truncated`), `deposited`. `jdcat_get_record` adds `dates`, `related_identifiers`, `oai_datestamp` and `oai_sets` |

Search envelopes also carry a top-level `facets` object: for each facet, the
buckets as `{label, count}` and the source's `other_count`.

## Known source-side defects

- English titles on some deposits are not the depositor's wording. One Kobe
  clipping about a peace conference (和平会議) carried the English title "inter-Korean security cooperation".
  Search and cite the Japanese title.
- Some social-science records give names with no language tag, and citation
  metadata reached through the DOI (not through JDCat) puts corporate authors
  in the `given` field. Repair this at filing; it is not this source's to fix.
- An SSJDA record's `date` is the deposit date (2005 for a 1995 survey). The
  survey period is in `extra.temporal`.

## Diagnostic registry

| Code | Level | Meaning |
|---|---|---|
| `TOTAL_IS_LOWER_BOUND` | warning | the service reported its total as a lower bound; cite it as "at least" |
| `TOTAL_UNREPORTED` | warning | no usable total in the response; the count given is the page, not the corpus |
| `OK` | info | records returned and nothing else to report (`jdcat_get_record`) |
| `ZERO_RESULTS` | info | the query ran and matched nothing in JDCat's deposits |
| `FACET_COUNTS_PER_LABEL` | info | facets are per label and pre-filter; never sum them |
| `FILTER_LABEL_NOT_IN_FACETS` | warning | a filter value is not among the labels the query's facets returned |
| `DATE_FILTER_FIRST_DATE_ONLY` | info | the window filtered on each record's first indexed date; an upper bound was closed out to its last day |
| `NOT_FOUND` | warning | OAI `idDoesNotExist` for the record asked for |
| `BAD_IDENTIFIER` | error | the input is not a JDCat id, OAI identifier or record URL; no request was made |
| `API_ERROR` | error | a 400 from the search API, an OAI error other than `idDoesNotExist`, or a body that could not be parsed. **The query did not run: this is not a zero result** |
| `HTTP_STATUS` | error | any other non-200 status |
| `RATE_LIMITED` | warning | a 429; backed off fifteen seconds and retried once |
| `READ_TIMEOUT` | error | no answer within 60 s; not a zero result |
| `TRANSPORT_ERROR` | error | the host could not be reached from this machine |
| `RECEIPT_NOT_DEPOSITED` / `RECEIPT_WRITE_FAILED` | info / warning | the family ledger diagnostics (see the root README) |
