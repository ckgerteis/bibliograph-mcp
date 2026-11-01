# crossref (bibliograph source)

Metadata that publishers deposit with Crossref when they register DOIs, read
through the public REST API at `https://api.crossref.org`. Free; no key.

Added 1 November 2026 so that DOI lookups and citation matching no longer draw
on OpenAlex's metered daily budget or Semantic Scholar's one-request-a-second
key.

## What it holds

Crossref holds what its member publishers deposit: most English-language
journals and many university and commercial presses, with chapters, reviews
and conference papers. It does not hold most Japanese-language scholarship,
which carries no DOI or a JaLC DOI, nor books from presses that register none.
`cr_get_work` answers `NOT_FOUND` for a JaLC, DataCite, KISTI or CNKI DOI; that
says the DOI is not Crossref's, not that the work does not exist. Every search
envelope carries this as its coverage note.

## Tools

| Tool | What it does |
|---|---|
| `cr_search_works` | Search by words (`query.bibliographic`: titles, authors, container, year), author, container title or ISSN, with year, type and ISSN filters and sort by relevance, date or citations. Up to 100 rows, offset to 10,000. |
| `cr_get_work` | One record by DOI, bare or as a doi.org URL. |
| `cr_match_citation` | Candidates for a reference as written, each with Crossref's relevance score in `extra.score`. Returns candidates, never a verdict. |

## How it matches

A multi-word query matches records containing **any** of its words and ranks
the union. On 1 November 2026 `bosozoku Japan` reported 1,184,944 records and
`bosozoku` alone reported 4. `result.total` is therefore not a literature, and
`matching_mode` is `relevance_ranked_any_term` to say so; read the top of the
ranking and narrow with author, container, year, type or ISSN rather than by
adding words. Crossref tokenises Chinese, Japanese and Korean poorly; a CJK
query returns loosely related records.

The relevance score ranks; it is not a probability. For Gerteis, *Mobilizing
Japanese Youth* (Cornell, 2021), the book scored 48.6 and two reviews of it
43.7 and 41.0, because a review carries the book's title. For Gordon, *The
Evolution of Labor Relations in Japan* (Harvard, 1985), a 1986 review ranked
first and the monograph second. `cr_match_citation` raises
`SAME_TITLE_DIFFERENT_TYPE` when candidates share a title but not a type.
Accept a candidate only when author, year, title and venue agree.

Presses type a single-author book `monograph` as often as `book`: a search for
Gerteis with `type` `book` returned nothing, while both of his books are in
Crossref as monographs.

Titles and container names arrive with markup (`<i>`, `<jats:p>`) and HTML
entities (`&amp;`); both are removed. Crossref's links to publisher full text
are not open-access copies, and are not used; licence URLs are kept in
`extra.license_urls`.

## Beyond Crossref

**Which agency registered a DOI.** When `cr_get_work` finds nothing, the DOI
is put to doi.org's registration-agency lookup (`https://doi.org/ra/{doi}`,
free, no key). Tested 1 November 2026 on eight DOIs, it named JaLC, Crossref
and DataCite correctly and answered "DOI does not exist" for invented DOIs and
for a real DOI with one character added. The envelope then says one of three
things: the DOI belongs to another agency (`NOT_FOUND`, naming it and where to
look: J-STAGE or CiNii for JaLC, `oa_get_work` for DataCite); no agency has it
(`DOI_NOT_REGISTERED`: the DOI as written does not exist, which in citation
checking is a finding); or the lookup failed (`NOT_FOUND`, saying so). The
lookup confirms registration, not that the citation attached to the DOI is
right.

**Open-access copies.** With `oa_links` (on by default) each record's DOI is
looked up in OpenAlex and any open copy goes into `ids.fulltext_url`, with
`extra.oa_status`, `extra.oa_license` and `extra.oa_via` = `openalex`. One DOI
is a single-record lookup, which OpenAlex prices at nothing; a page of results
is one list call filtered by DOI, $0.0001 (1 November 2026). Unpaywall was
considered and not used: it now runs on the OpenAlex database, covers Crossref
DOIs only, and OpenAlex advises new integrations to use OpenAlex directly. An
empty `fulltext_url` means OpenAlex knows no open copy, not that none exists;
a failed lookup is reported as `OA_LOOKUP_FAILED` and leaves the Crossref
answer intact.

## Access and rate

Crossref sorts callers into pools and states the current limit on every
response (`x-rate-limit-limit`, `x-rate-limit-interval`). Measured 1 November
2026: public pool 1 request per second, one at a time; polite pool (a contact
address supplied) 3 per second, three at a time. The documentation gives
higher figures; Crossref lowers them under load. This source serialises its
requests and spaces them by the interval the last response stated.

| Variable | Use |
|---|---|
| `CROSSREF_MAILTO` | Contact address for the polite pool; sent as `mailto` and in the User-Agent. Falls back to `OPENALEX_EMAIL`. Redacted from envelopes and receipts. |
| `CROSSREF_PLUS_TOKEN` | Optional Metadata Plus token, sent as `Crossref-Plus-API-Token`. |

Licence: Crossref states that almost none of its metadata is under copyright
and it may be used for any purpose; some abstracts may be under the
publisher's or author's copyright.

## Diagnostics

| Code | Level | Meaning |
|---|---|---|
| `OK` | info | Records returned. |
| `TOTAL_IS_ANY_TERM` | info | The query has more than one word; `result.total` counts records containing any of them. |
| `CJK_QUERY_WEAK` | warning | The query is not in Latin script; Crossref matches CJK text loosely. |
| `SAME_TITLE_DIFFERENT_TYPE` | warning | `cr_match_citation`: two candidates share a title but not a type, so one is probably a review of the other. |
| `CANDIDATES_NOT_VERDICT` | info | `cr_match_citation`: the items are ranked candidates, not a confirmed match. |
| `ZERO_RESULTS` | warning | No records for this query and filter set. Crossref holds only DOI-registered work. |
| `NOT_FOUND` | warning | Crossref has no record for this DOI; the message names the agency that registered it, or says the agency lookup failed. |
| `DOI_NOT_REGISTERED` | warning | No registration agency has the DOI: as written, it does not exist. |
| `OA_FROM_OPENALEX` | info | Open-access locations were looked up in OpenAlex; the message gives how many records have one and what the lookup cost. |
| `OA_LOOKUP_FAILED` | info | The OpenAlex lookup failed; an empty `fulltext_url` then says nothing about open copies. |
| `INVALID_INPUT` | error | `cr_search_works` was given none of query, author, container or ISSN. |
| `RATE_LIMITED` | error | Crossref answered 429; the message names the pool and its stated limit. |
| `RECORD_SHAPE_UNEXPECTED` | warning | Records that could not be read were left out; the message names them. |
| `API_ERROR` | error | Crossref answered with an error (quoted), a 403 block, or a body that is not an ok message. |
| `TRANSPORT_ERROR` | error | The request did not complete; the result is unknown, not empty. |
| `RECEIPT_NOT_DEPOSITED` | info | No receipts destination is configured. |
| `RECEIPT_WRITE_FAILED` | warning | The receipt write was attempted and did not land. |
