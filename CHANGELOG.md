# Changelog

Versions are the thing to cite. From 2.0.0 one release fixes every source's
code; `bibliograph_status` names each source's own version, which should be
cited with it. Before 2.0.0 the suite version fixed a set of six server release
tags through its dependency pins. A count produced under one release is not
reproducible under another.

## 2.0.0 — 2026-11-01

**One server.** bibliograph-mcp is no longer a suite pinning six separate
servers: it is one MCP server, `bibliograph-mcp`, holding every source in one
process, built from the same code as the author's development platform (shoshi
1.7.0) under the public name. This is a breaking change in how it installs, not
in what the tools are called.

- **Sources.** NDL Search (`ndl_*`), NDL Digital Collections full text via NDL
  Lab (`ndl_dl_*`), the WARP web archive (`warp_*`), CiNii Research (`cinii_*`),
  J-STAGE (`jstage_*`), JDCat (`jdcat_*`), OpenAlex (`oa_*`), Semantic Scholar
  (`s2_*`), Crossref (`cr_*`, new), Japanese name and authority resolution
  (`name_*`, `resolve_*`, `gloss_*`, `kanji_*`), and open-access PDF fetching
  (`fetch_*`); korea-scholarship-mcp v0.7.0 (`kci_*`, `oak_*`, `dbpia_links`) is
  a dependency loaded by default; 71 tools load by default, 73 with JDCat.
  `bibliograph_status` reports what loaded,
  each source's version, and the day's OpenAlex budget.
- **JDCat is opt-in.** JDCat's robots.txt asks automated agents to stay out of
  its API. The `jdcat` tools are built never to crawl (searches a person asks
  for, three seconds apart, at most 50 records, no harvest), but whether to use
  them is each user's decision: they load only when named in `--only` or when
  `BIBLIOGRAPH_ENABLE_JDCAT=1` is set (in the bundle, *Enable JDCat*, off by
  default), and `bibliograph_status` lists the source as skipped otherwise.
- **The bundle has a KCI key field** (`KCI_API_KEY`) for korea-scholarship-mcp's
  REST tools; its OAI-PMH tools need none.
- **Each shared source is ahead of its separate repository**: cinii 3.3.1,
  jstage 3.2.2, ndl 1.5.2, openalex 2.1.5, semantic_scholar 2.1.4. The source
  CHANGELOGs under `docs/sources/` record what changed.
- **Installing.** `pip install "bibliograph-mcp @ git+https://github.com/ckgerteis/bibliograph-mcp@v2.0.0"`,
  then `bibliograph install`, which registers the one server, keeps any
  credential already registered, backs up the config, and names (without
  deleting) the six 1.x entries to remove. Or the `.mcpb` bundle from the
  release, which needs no Python. `bibliograph doctor` starts the server and
  lists its tools; `bibliograph receipts verify-dir DIR` checks a receipts
  folder.
- **Removed**: the six-server installer (`install.py`, `bibliograph.installer`)
  and `VENDORED.sha256`, which checked that the six vendored identical modules;
  in one package there is one copy.
- The six separate repositories stay published and citable at their own
  releases.

## 1.0.6 — 2026-10-30

- Pins moved to cinii-mcp v3.3.0, jstage-mcp v3.1.4 and korea-scholarship-mcp
  v0.7.0; ndl-mcp, openalex-mcp and semantic-scholar-mcp are unchanged.
  cinii-mcp adds four tools (NACSIS-CAT holdings and library search, research
  data, projects with their products), CiNii's v2 filters and sort orders,
  and fixes a `journal` filter that CiNii never applied; jstage-mcp no longer
  fails a page on one unreadable entry; korea-scholarship-mcp adds
  `dbpia_links`. Each server's CHANGELOG lists what changed. Counts made
  through cinii-mcp with a journal filter before v3.3.0 were unfiltered.

## 1.0.5 — 2026-10-12

- Pins moved to cinii-mcp v3.2.0, jstage-mcp v3.1.3, ndl-mcp v1.2.3,
  korea-scholarship-mcp v0.6.3, openalex-mcp v2.2.0, semantic-scholar-mcp
  v2.2.0: the maintenance releases from the stress test of 12 October 2026.
  Each server's CHANGELOG lists what changed; the new diagnostic
  `RECORD_UNREADABLE` appears in OpenAlex, Semantic Scholar and CiNii.
- `set_version.py` and `tests/test_release_metadata.py`, carried byte-identical
  from the family, now also set and check `__version__`.
- Python: CI tests 3.11 as well; `requires-python` is capped below 3.15.

## 1.0.4 — 2026-09-12

- Pins moved to cinii-mcp v3.1.2, jstage-mcp v3.1.2, ndl-mcp v1.2.2,
  korea-scholarship-mcp v0.6.2, openalex-mcp v2.1.2, semantic-scholar-mcp
  v2.1.2: the releases whose Claude Desktop bundles keep `pyproject.toml`,
  `uv.lock` and the entry point at the bundle root, so the app builds the
  environment when the extension is installed rather than during the first
  connection attempt. The 1.0.3 bundles skipped that install step on every
  machine and could not connect on a network where the first launch ran past
  the app's timeout (reported from macOS 26 on 7 September 2026). No change
  to this package.

## 1.0.3 — 2026-09-08

- Pins moved to cinii-mcp v3.1.1, jstage-mcp v3.1.1, ndl-mcp v1.2.1,
  korea-scholarship-mcp v0.6.1, openalex-mcp v2.1.1, semantic-scholar-mcp
  v2.1.1: the releases whose Claude Desktop bundles no longer pin Python
  3.13 and use an installed 3.10 or later instead, downloading one only
  where there is none. No change to this package.

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
