# Changelog

Versions are the thing to cite. The suite version fixes a set of six server
release tags through its dependency pins; a count produced under one set is not
reproducible under another.

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
