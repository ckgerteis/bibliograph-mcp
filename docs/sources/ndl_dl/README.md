# ndl-dl-mcp — 次世代デジタルライブラリー full text

v0.1.0, written 17 September 2026. Fifth member of the bibliograph family
(`cinii`, `jstage`, `ndl`, `openalex`, `semantic_scholar`). **Not installed.**

## What it is, and why it is not part of ndl-mcp

`ndl-mcp` searches 国立国会図書館サーチ over SRU and returns metadata. This server
searches the **OCR full text** of the NDL's public-domain digitised holdings
through 次世代デジタルライブラリー — about 350,000 items as of November 2022
(≈280,000 books from the FY2021 OCR project, ≈60,000 classical materials from
FY2022). Different host, different corpus, different licence position: the text
here is public domain and may be held on disk and indexed, where NDL Search
metadata for `ndl-dl`/`ndl-dl-online` is displayable and not accumulable. Keeping
the servers apart is what lets this corpus be harvested into the B1 index without
touching the undertakings `ndl-mcp` gave the library in August 2026.

## Three tools

| Tool | Does | Returns |
|---|---|---|
| `ndl_dl_fulltext_search` | searches OCR text; `mode="distribution"` gives hits by publication year instead of records | records with located snippets (snippet + image page + IIIF URL) |
| `ndl_dl_book_fulltext` | fetches one item's text (the service sends a ZIP; the tool unpacks it) | per-page text keyed by image page, each with its page-image URL |
| `ndl_dl_page_image` | resolves pages to IIIF URLs; makes no request | image URLs for checking a reading or a figure |

## The interface is undocumented

Endpoints were read from the service's own `app.bundle.js` and probed live from
London on 17 September 2026. Every response reports the endpoint it called and
how that endpoint is known.

- **verified** `GET /dl/api/book/search`, `/dl/api/book/ngram-search`,
  `/dl/api/book/{id}`, `/dl/api/book/fulltext/{id}`
- **from client code, unverified** `/dl/api/page/{id}`,
  `/dl/api/book/download/{id}?page=N`,
  `https://dl.ndl.go.jp/api/iiif/{id}/R{page:07d}/full/full/0/default.jpg`
- **probed, unresolved** `/dl/api/page/search` returns 400; the required
  parameters were not established and the endpoint is not exposed
- **constructed, unverified** the viewer URL `https://dl.ndl.go.jp/pid/{id}`

An undocumented interface can change without notice. Treat an HTTP 400 as a
parameter this server got wrong, never as an empty result set.

## Four measured facts the code is built around

1. `hit` caps at **10,000**: a 青年団 search reported `hit=10000` while the
   `isClassic` facet on the same response totalled 17,764. The server raises
   `HIT_COUNT_CAPPED` and substitutes the facet total.
2. `highlights` carries the citable locus — the matched term, its
   table-of-contents line, and the page image (`(0011.jp2)`) — which the server
   parses into `{snippet, image_page, page_image_url}`.
3. The index **normalises old orthography**: a query for 青年団 returns 青年團.
   Do not add kyūjitai variants without testing whether they change anything.
4. `fulltext` returns a **ZIP**, not text: per-page `.txt` plus a per-page `.json`
   sidecar. 26 text members and 264 KB for a 25-page 1935 volume.

Snippets are HTML-unescaped (the service sends a slash as `&#x2F;`). A body that
is not a JSON object is an `API_ERROR`; records that cannot be read are left out
and counted in `RECORD_SHAPE_UNEXPECTED`. `ndl_dl_page_image` resolves at most
500 pages per call and says so in `PAGE_LIST_CAPPED`. Receipts name each item by
its persistent identifier, `info:ndljp/pid/<id>`.

## Request discipline and the notification gate

Serial requests, a one-second floor, at most 100 records per search, no
auto-pagination. The service publishes no rate limit, which is not the same as
having none; on NDL hosts throttling presents as a read timeout rather than a 429,
and the server says so in `READ_TIMEOUT` rather than reporting zero.

NDL Lab's terms for the service (ご利用に当たって, lab.ndl.go.jp/service/tsugidigi/,
read 25 September 2026) allow API use without application except where use is both
commercial and continuous (営利目的かつ継続的な利用を除き、申請不要で自由にご利用になれます),
which they refer to the NDL Lab contact page. Version 0.1.0 assumed a usage
notification was required and refused requests above 20 records until a marker
recorded one; 0.2.0 removes that gate. Non-commercial scholarly use needs no marker.

## Coverage, stated so absence can be read

Public domain only, overwhelmingly pre-1945. Digitised in-copyright material (the
図書館送信 and 個人送信 tiers) is not in this corpus and cannot be searched by this
server: absence here is absence from the public-domain OCR corpus, not from the
NDL's holdings. The text is OCR of pre-war vertical type and contains recognition
error — the smoke test's own first-page sample is largely noise, because page one
is a cover with stamps. Anything to be quoted must be read against the page image.

## How it installs: the .mcpb bundle (18 September 2026)

`dist\ndl-dl-mcp-0.1.0.mcpb`, 75 KB. Install it through Claude Desktop's own
Extensions UI; the app then owns the registration.

**Why not a config entry.** It was tried on 17 September and it does not hold.
An `ndl_dl` entry written directly into `claude_desktop_config.json` at 18:58
was gone by 19:57, the file having been rewritten at 19:11 by the app; re-applied
at 19:57, it was gone again after CG's restart, and no `mcp-server-ndl_dl.log`
was ever created, so the app never attempted to start it. This build
re-serialises that file from its own state and discards entries added underneath
it. The bundle route is not a convenience here, it is the only durable one.

**Layout.** `server.type` is `uv`, manifest 0.4, and nothing is vendored:
`manifest.json`, `pyproject.toml`, `uv.lock` and `main.py` sit at the bundle
root with `src/ndl_dl_mcp/` beside them. Claude Desktop finds the root
`pyproject.toml` at install time and runs `uv sync` there behind a progress bar;
each launch then runs `uv run --directory <bundle> --frozen main.py` and reuses
that environment. This is the pattern that replaced the vendored lib tree after
the 8 September diagnosis, when every published family bundle turned out to
carry `cp312`-tagged native wheels and to import under CPython 3.12 alone.

**Three user_config fields** in the standalone 0.1.0 bundle, all optional: the
receipts folder, the receipt session slug, and the path to the notification
marker that 0.1.0's gate read (the gate and the marker are gone from 0.2.0). `main.py` strips
unsubstituted `${user_config.KEY}` placeholders before the package imports,
because a field left blank arrives as the placeholder verbatim — which once had
the ledger writing into a folder literally named `${user_config.receipts_dir}`.

**Gates run before this bundle was called done.**

- `tests/bundle_handshake.py` installs and launches the built bundle the way the
  app does, under Python 3.10, 3.12 and 3.13 — none of them the 3.13.9 that
  wrote the lock. All three complete `initialize`, list three tools and strip
  placeholders. First run FAILED on all three: the server answered an empty
  version string, because `_MCPServer` was constructed without one. Fixed with
  the family's try/TypeError idiom; the bundle now answers `ndl-dl 0.1.0`.
- `tests/test_release_metadata.py`: four passed. `pyproject.toml`,
  `mcpb/manifest.template.json`, `.zenodo.json` and `CITATION.cff` all read
  0.1.0, and the CFF spec version is a real one.
- `tests/smoke_test.py`: 24 lines, 0 failures, against the src layout.

Receipts, when a folder is configured, land at `receipts\ndl-dl-mcp.jsonl` —
`ledger.py` 1.1.0 writes one file per server, which is why the shared
`receipts.jsonl` stopped growing on 23 August and why that was never a fault.

## Installed 18 September 2026, into the app's extension store

Installed as a standalone extension, not folded into the gerteis-skills plugin.

Claude Desktop's own Extensions UI could not be driven from here: the Claude app
is the one application this device refuses to resolve for computer use, so its
settings pane is out of reach. The install was done at the file level instead,
which the store's shape permits — an unpacked folder plus a small settings file,
with nothing in `config.json` enumerating extensions and `dxt:allowlistEnabled`
set to false, so sideloading is not policy-blocked here:

- `Claude Extensions\local.ndl-dl-mcp\` — the bundle unpacked (manifest.json,
  main.py, pyproject.toml, uv.lock, src/, README, LICENSE, CHANGELOG,
  response-schema.json).
- `Claude Extensions Settings\local.ndl-dl-mcp.json` — `isEnabled: true`, with
  `receipts_dir` pointed at the family receipts folder and `receipt_session`
  `rhs-transactions-2026`. The notification field is deliberately left unset.
- `uv sync --frozen` was run in that folder, so the environment (Python 3.13.9)
  is already provisioned and the first launch does not have to build it inside
  the host's connection window — the fault that made three family bundles
  unreachable from a Mac mini on 7 September.

Verified by launching the manifest's own command from the installed folder:
`initialize` answered `ndl-dl 0.1.0` in 4.0 s with three tools and empty stderr.

Additive and reversible. Nothing existing was touched, and the whole install
undoes by moving those two paths aside. Every extension already present came
from the Anthropic directory (`ant.dir.*`), so a local id has no precedent on
this machine: if the app ignores `local.` on restart, the fallback is the
Extensions UI with the .mcpb in `dist\`, which the allowlist setting permits.

## Test

`smoke_test.py` runs twelve pure-helper assertions and four live requests
(spaced 1.2 s, nothing harvested). The Cowork Linux VM has no egress to
lab.ndl.go.jp, so run it on the Windows box with the family venv; it writes
`smoke_report.txt` in UTF-8 because Windows stdout is cp1252 and CJK crashes a
bare print. Runs of 17 September 2026, against the source copy and again against the installed copy with the newer vendored ledger: 20 checks, 0 failures each.

## Not done

- `/dl/api/page/search` parameters unresolved.
- Layer 3 harvester (walk a result set, write per-item text plus corpus-sidecar
  records) — waits on the notification.
- Illustration search (`/dl/api/illustration/`, `/dl/api/imagefeatures`) not
  wrapped; possibly useful for the CHEA figure work.
- Packaging: flat layout, no `pyproject.toml`, no release metadata guard yet.
