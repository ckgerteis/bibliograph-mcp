# fetch changelog

## 0.1.0 - 2026-10-07

First version, written as a bibliograph source.

- `fetch_pdf`: one open-access PDF per call into `BIBLIOGRAPH_DOWNLOAD_DIR`, by
  OpenAlex, Semantic Scholar or a supplied address, with a provenance file,
  a receipt naming the record and the file's SHA-256, and a text-layer report.
- `fetch_pdf_text`: the text layer of a saved PDF, page by page, read only
  inside the download folder.
- Public-host check at every redirect hop, PDF-header check, 100 MB ceiling,
  credential-like query values redacted, extraction permissions respected.
- Scans carrying someone else's OCR are named (`OCR_TEXT_LAYER`): a picture
  covering a quarter of the page with 80% of the text on it. Calibrated on a
  live repository scan that the first threshold (60% coverage) missed.
- After a second-model review the same day: only globally routable addresses
  (CGNAT, site-local and IPv4-carrying IPv6 forms closed); the connection is
  pinned to the vetted address (DNS rebinding) and no proxy is used; user
  information and fragments redacted; text inside Form XObjects read; a page
  longer than `max_chars` cut and said; the 600-page reach said; whole-download
  and parsing deadlines; atomic provenance that keeps every fetch; dedupe
  checked against the whole SHA-256; no `.part` left on a failed write; network
  paths and request-altering identifiers refused.
- Every refusal is reported when more than one candidate address is tried,
  not only the last; the first draft hid a private-address refusal behind the
  fallback landing page's 404.
