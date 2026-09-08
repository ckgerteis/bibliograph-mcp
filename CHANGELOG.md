# Changelog

Versions are the thing to cite. The suite version fixes a set of six server
release tags through its dependency pins; a count produced under one set is not
reproducible under another.

## 1.0.2 — 2026-09-08

- **Pins moved to the releases whose Claude Desktop bundles run:** cinii-mcp
  v3.1.0, jstage-mcp v3.1.0, ndl-mcp v1.2.0, korea-scholarship-mcp v0.6.0,
  openalex-mcp v2.1.0, semantic-scholar-mcp v2.1.0. 1.0.1 still pinned
  openalex and semantic-scholar at v2.0.0 while the CV cited the 2.0.1 DOIs.
- **The installer asks where things go, and never guesses.** `installer.py`
  is the family's `install.py` at the version the six now carry: it asks for
  the receipts folder and the session slug, offers a neutral suggestion, and
  run without a terminal stops before touching anything unless
  `--receipts-dir` (or `--no-receipts`) says so. `bibliograph install`
  passes the environment it runs in as the install location, which the user
  chose by creating it. No path, slug or name of the author's is in it.
- **A complete public repository.** `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1), `SECURITY.md`, issue forms, a pull request
  template, Dependabot; the Zenodo concept DOI as a badge and in
  `CITATION.cff`; README sections on what the receipts are for, where to get
  Python, and use from any MCP client.
- CI matrix adds 3.12 and 3.14; workflow actions on their current majors.

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
