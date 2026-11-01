# Changelog

Versions are the thing to cite. A count produced under one release is not
reproducible against another, so the release actually used should be named in
the text.

## 0.1.0 — 2026-11-01

First release, inside bibliograph 1.7.0. `cr_search_works`, `cr_get_work` and
`cr_match_citation` over the Crossref REST API; polite pool by
`CROSSREF_MAILTO` (falling back to `OPENALEX_EMAIL`); requests serialised and
spaced by Crossref's own rate headers; markup and entities stripped from
titles; any-term counts, weak CJK matching and candidate scores stated in the
envelope rather than left to be inferred. A DOI Crossref lacks is put to
doi.org's agency lookup (`DOI_NOT_REGISTERED` when no agency has it), and
open-access locations are filled from OpenAlex (`oa_links`).
