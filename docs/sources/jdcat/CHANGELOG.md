# jdcat changelog

## 0.1.1 - 2026-10-07

Repairs of 7 October 2026, released in bibliograph 1.2.0. See bibliograph's CHANGELOG for the detail.

## 0.1.0 — 2026-10-07

First version, written as a bibliograph source.

- `jdcat_search`: metadata search over JDCat's WEKO3 JSON API. It takes facet
  filters (distributor, data type, topic, geographic coverage, access) and an
  inclusive date window. Search envelopes carry a top-level `facets` object
  with the counts JDCat reports. Facets are pre-filter and per label, and
  `FACET_COUNTS_PER_LABEL` says so on every search.
- `jdcat_get_record`: one record by id, OAI identifier or URL, fetched through
  OAI-PMH GetRecord (`jpcoar_2.0`).
- Built to the WARP model because JDCat's robots.txt disallows `/api/` and
  `/oai`: serial requests at least three seconds apart, at most 50 records per
  search, no auto-pagination and no harvest tool. The robots.txt position is
  stated in every envelope's `coverage_note`.
- DOIs are taken only where a field holds a DOI as its whole value. In
  probing, DOIs were present on Kobe clippings, Hitotsubashi tables and SSJDA
  studies.
- A year or month upper bound on the date window is sent as its last day.
  JDCat reads a bare year there as 1 January, so a 1919–1919 window returned
  nothing until this was done.
- `source.year` is left null by design. Coverage dates are in
  `extra.temporal`.
- Hardened against malformed responses after a second-model review the same
  day. A wrong-shaped body is now an `API_ERROR`, not a crash. A string where
  a list belongs is no longer split into characters. An Elasticsearch-7 total
  object is unwrapped. Impossible or reversed date windows are refused.
  Hangul titles go to `title.ko`. `ids.doi` is only ever the record's own
  DOI, never one taken from a typed relation.
