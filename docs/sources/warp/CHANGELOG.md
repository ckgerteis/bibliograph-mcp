# Changelog

## 0.2.1 - 2026-10-07

Repairs of 7 October 2026, released in bibliograph 1.2.0. See bibliograph's CHANGELOG for the detail.

## 0.2.0 — 2026-09-24
- **Family envelope adopted.** All three tools now answer through
  `mediation.build_envelope`/`mediation.emit`, matching the rest of the
  family (cinii, jstage, ndl, ndl_dl): `matching_mode` `"exact_url"`, one
  item per capture (`record_type: "web_capture"`, URL in `ids.url_ja`/
  `url_en`, capture-specific fields in `extra`), typed `diagnostics[]`,
  `suggestions[]` for alternate URL spellings, a receipt, and attribution.
  This is a breaking change from 0.1.0's bespoke JSON shape.
- The separate `ledger.record_request` call is gone; `mediation.emit()`
  deposits the receipt once, so nothing is recorded twice.
- See `README.md`'s "Response format" section for the field mapping and the
  diagnostic code registry.

## 0.1.0 — 2026-09-18
- First version: `warp_list_captures`, `warp_nearest_capture`, `warp_read_capture` over WARP's Memento TimeMap and viewer pages.
- Serial requests, 3 s floor, redirect cap 3, no caching; premises-only captures reported as such; family ledger vendored.
