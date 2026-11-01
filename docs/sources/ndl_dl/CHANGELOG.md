# Changelog

All notable changes to ndl-dl-mcp. The format follows Keep a Changelog; this
project uses semantic versioning.

## 0.2.1 - 2026-10-07

Repairs of 7 October 2026, released in bibliograph 1.2.0. See bibliograph's CHANGELOG for the detail.

## [0.2.0] — 2026-09-25

### Removed

- The notification gate. NDL Lab's own terms ask for no application for
  non-commercial use (営利目的かつ継続的な利用を除き、申請不要), so the
  `NOTIFICATION_NOT_RECORDED` diagnostic, the `NDL-LAB-NOTIFICATION.txt` marker
  lookup and the `BULK_REFUSED` refusal above 20 records are gone. Requests
  remain serial, spaced at least a second apart, and capped at 100 records.

## [0.1.0] — 2026-09-18

First build. Not yet released, and the usage notification for lab.ndl.go.jp is
not yet filed, so the server refuses retrieval above 20 records in process.

### Added

- `ndl_dl_fulltext_search` — OCR full-text search over the public-domain corpus,
  returning located snippets (matched term, its line, image page, IIIF URL). A
  `distribution` mode returns the hit count by publication year instead of records.
- `ndl_dl_book_fulltext` — per-page OCR text for one item; the service sends a ZIP
  of per-page `.txt` with JSON sidecars, and the tool unpacks it and reports
  truncation rather than trimming silently.
- `ndl_dl_page_image` — resolves pages to IIIF image URLs; makes no request.
- The family response envelope (mediation 2.3.0) and hash-chained receipts
  (ledger 1.1.0), deposited per server when `MCP_RECEIPT_DIR` is set.
- A notification gate: without a recorded filing every response carries
  `NOTIFICATION_NOT_RECORDED` and requests above 20 records are refused.

### Measured at build, 2026-09-17, from London

- `hit` caps at 10,000; the facet total on the same response gave 17,764 for 青年団.
  The server raises `HIT_COUNT_CAPPED` and substitutes the facet sum.
- The index normalises old orthography: 青年団 returns 青年團.
- `book/fulltext` returns a ZIP, not text: 26 members and 264 KB for one 1935 volume.
- `page/search` answers 400 and its required parameters were not established, so
  it is not exposed.
