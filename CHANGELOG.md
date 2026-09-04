# Changelog

Versions are the thing to cite. The suite version fixes a set of six server
release tags through its dependency pins; a count produced under one set is not
reproducible under another.

## 1.0.1 — 2026-09-04

Pins moved; nothing else. Three of the six servers were re-released the same
afternoon after a claim-by-claim check against live answers found defects in
what they returned, and a suite that still named the earlier tags would have
installed them:

- cinii-mcp v3.0.0 → **v3.0.1**: `cinii_get_record` now reads the single-record
  JSON-LD correctly (authors, NAID and ISSN were dropped; an untagged Japanese
  title was also reported as its own English title).
- jstage-mcp v3.0.0 → **v3.0.1**: an HTTP error status from J-STAGE is
  `API_ERROR`, not `TRANSPORT_ERROR`, as in the rest of the family.
- ndl-mcp v1.1.0 → **v1.1.3**: 雑誌記事索引 records are typed as articles and
  carry their periodical, issue and pages; the 1.1.1 notes introduce the tool.

korea-scholarship-mcp v0.5.0, semantic-scholar-mcp v2.0.0 and openalex-mcp
v2.0.0 are unchanged. A count produced under 1.0.0's pin set is not the same
evidence as one produced under 1.0.1's; cite the suite version actually
installed.

## 1.0.0 — 2026-09-04

First release of the suite package.

- Depends on cinii-mcp v3.0.0, jstage-mcp v3.0.0, ndl-mcp v1.1.0,
  korea-scholarship-mcp v0.5.0, semantic-scholar-mcp v2.0.0 and openalex-mcp
  v2.0.0, each as a direct reference to its GitHub release tag. Nothing is on
  a package index; GitHub releases are the distribution channel.
- `bibliograph install` registers the servers this interpreter can import
  in Claude Desktop: one receipts folder, one session slug, each credential
  asked for once, existing entries backed up and untouched. It refuses to
  point one server at a receipts folder the others do not use unless told
  the split is meant.
- `bibliograph doctor` performs the stdio handshake with every server and
  asserts `ledger.py` and `mediation.py` are byte-identical across the
  install.
- `bibliograph status` and `bibliograph receipts verify-dir | manifest`.
- `bibliograph.installer` is the family's `install.py`, vendored byte-identical.
