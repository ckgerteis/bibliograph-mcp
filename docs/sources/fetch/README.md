# fetch - open-access PDFs with provenance, and their text layer

v0.1.0, written 7 October 2026. A bibliograph source from the start.

## What it is for

Every other bibliograph source finds records and receipts the search. Until this
source existed, a PDF left that record at the moment it entered the
historian's files, because the download happened somewhere else. `fetch`
makes the download a receipted operation: the receipt names the record and the
SHA-256 of the file saved, and a provenance file beside the PDF records where
the file came from, the licence its source reported, and when it was fetched.

It does not look for copies. It downloads the copy a source names as open
access, or an address the caller supplies, and nothing else. Licensed access
belongs to your institution's licensed access.

## Tools

| Tool | Does |
|---|---|
| `fetch_pdf` | Downloads one PDF into the download folder. `via="openalex"` or `via="semantic_scholar"` asks that source afresh for the work's open-access copy (a work id or DOI as `record`); `via="url"` fetches an address you supply. Reports the file name, SHA-256, size, page count, licence and open-access status as the source states them, and which pages carry a text layer. |
| `fetch_pdf_text` | Returns the text layer of a PDF in the download folder, page by page, up to `max_chars` (default 20,000), for a page list such as `1-5` or `3,7,11-14`. |

## Configuration

`BIBLIOGRAPH_DOWNLOAD_DIR` names the folder. In the Claude Desktop extension it is
the "Download folder" setting. Unset, both tools refuse with
`DOWNLOAD_DIR_NOT_SET` and nothing is fetched, read or written. Files are named
`<source>-<record>-<first 12 hex of SHA-256>.pdf` (for example
`oa-W2996081048-63cb5233da9c.pdf`), beside `<same>.provenance.json`. Files are
written under a temporary name and renamed, so a failed write leaves nothing
behind. The same bytes fetched twice are not written twice (`ALREADY_SAVED`,
checked against the whole SHA-256), and each fetch is added to the provenance
file's `fetches` list, so a second source for the same file is recorded.

## Boundaries

* Only http(s) addresses whose host resolves to globally routable addresses
  (not private, loopback, link-local, CGNAT or site-local space, with IPv6
  forms that carry an IPv4 address judged by that address), checked at every
  redirect hop. The connection is then made to the vetted address itself, with
  the host name kept for the Host header and TLS verification, so a name that
  answers differently a moment later cannot move the download onto a private
  address. No proxy is used, because a proxy would resolve the name itself. At
  most five redirects, and five minutes for a whole download.
* Only files that begin as PDFs. A landing or login page is refused
  (`NOT_A_PDF`) and nothing is written. At most 100 MB.
* One file per call, two seconds apart at the least. There is no batch and no
  harvest.
* User information, fragments and credential-like query values (`token`,
  `signature`, `auth`, `X-Amz-*` and the like) are removed from every address
  that reaches an envelope, a receipt or a provenance file.
* `fetch_pdf_text` reads only files inside the download folder, and refuses a
  network path before anything resolves it.
* Text-layer reading stops after two minutes (`TEXT_PROBE_TIMEOUT`).
* A PDF whose permissions forbid text extraction is not extracted
  (`TEXT_EXTRACTION_NOT_PERMITTED`). Many Japanese repository PDFs set that flag;
  their pages can still be read in a viewer or put through OCR.

## The text layer and what it is not

The text returned is the text layer embedded in the file, unrevised. `fetch_pdf`
checks it on the first 40 pages and reports one of:

| `text_layer` | Meaning |
|---|---|
| `full` | Every page read carries text. |
| `partial` | Some pages carry none (`PARTIAL_TEXT_LAYER`, with the page list). |
| `ocr` | Every page with text is a page image whose text was added by OCR before the file was published (`OCR_TEXT_LAYER`). Present, but of unknown accuracy. |
| `none` | No page carries text: a scan (`NO_TEXT_LAYER`). |
| `unknown` | Extraction was forbidden or the file could not be parsed. |

A page counts as an OCR'd scan when one picture covers at least a quarter of it
and at least 80% of its text sits on that picture. The second test keeps a
born-digital page with a large photograph from being called a scan. Pages
without text, and OCR'd scans that read badly, belong with an OCR server (the
ocr-mcp `ocr_document` tool), not with this source.

Probed 7 October 2026 on five live open-access PDFs:
* an English article (Japanese Research in Business History) and a Cambridge
  article came back `full` and clean;
* a horizontally set Japanese article from a university repository came back
  `full` and clean, kanji and kana intact;
* a two-column Japanese article that is a repository scan came back `ocr`, its
  columns interleaved in the text;
* a Keio repository PDF forbade extraction.

Japanese set vertically can come out of a text layer in an order that must be
checked against the page before quotation.

## Diagnostics

| Code | Level | Meaning |
|---|---|---|
| `SAVED` | info | The file was written; the message gives its name, size and SHA-256. |
| `ALREADY_SAVED` | info | A file with the same SHA-256 is already in the folder; nothing was written. |
| `DOWNLOAD_DIR_NOT_SET` | error | `BIBLIOGRAPH_DOWNLOAD_DIR` is not set; nothing was done. |
| `DOWNLOAD_DIR_UNUSABLE` | error | The folder could not be created or written to. |
| `BAD_IDENTIFIER` | error | The record is not a work id, DOI or http(s) address of the kind `via` expects. |
| `NO_OA_COPY` | warning | The source names no open-access copy. Not evidence that none exists; licensed access is your institution's. |
| `NOT_A_PDF` | error | The address returned something other than a PDF, usually a landing or login page. |
| `ADDRESS_REFUSED` | error | An address, or a redirect, pointed at a non-public host or a non-http(s) scheme. |
| `HTTP_STATUS` | error | The host answered with an error status. A 401 or 403 usually means the copy is closed to automated requests. |
| `FILE_TOO_LARGE` | error | The file exceeded 100 MB. |
| `REDIRECT_LIMIT` | error | More than five redirects. |
| `READ_TIMEOUT`, `TRANSPORT_ERROR` | error | The host did not answer, or could not be reached. Not evidence the file is absent. |
| `CANDIDATES_TRIED` | info | More than one address was tried; the message lists each with its outcome. |
| `PARTIAL_TEXT_LAYER`, `NO_TEXT_LAYER`, `OCR_TEXT_LAYER` | warning | See the table above. |
| `TEXT_EXTRACTION_NOT_PERMITTED` | info | The PDF forbids extraction; it was not read. |
| `PDF_UNREADABLE` | warning | The file begins as a PDF but could not be parsed. |
| `PROBE_LIMITED` | info | The text layer was checked on the first 40 pages only. |
| `SUPPLIED_URL_NO_LICENCE_CHECK` | info | `via="url"`: no source reported a licence. |
| `LICENCE_NOT_STATED` | info | The source reports the copy as open to read but states no licence. |
| `FILE_REFUSED`, `FILE_NOT_FOUND` | error | `fetch_pdf_text`: the file is outside the download folder, is not a PDF, or is not there. |
| `BAD_PAGES`, `PAGES_OUT_OF_RANGE` | error / info | The page list could not be read, or names pages the file does not have. |
| `TEXT_TRUNCATED` | warning | Reading stopped at `max_chars`, or at the 600-page reach of a call without a page range, or within one page longer than `max_chars`; the hint gives what to ask next. |
| `TEXT_PROBE_TIMEOUT` | warning | Reading the text layer did not finish within two minutes. |
| `PROVENANCE_NOT_WRITTEN` | warning | The PDF was saved but its provenance file could not be written; the receipt still holds the record and SHA-256. |
| `FILE_UNREADABLE` | error | `fetch_pdf_text`: the file could not be read (open elsewhere, or permissions). |

## Receipts

`result_ids` holds the record's DOI (or, without one, the address fetched) and
`sha256:<hex>` of the file. `fetch_pdf_text` receipts carry the same pair, read
from the provenance file, so a quotation can be traced to the exact file it
came from.
