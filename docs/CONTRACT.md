# The bibliograph contract, for outside packages

bibliograph gathers several source modules into one MCP server. Most sources live
in `src/bibliograph/sources/`, but `bibliograph-mcp --with PKG.MODULE` (or the
`BIBLIOGRAPH_WITH` environment variable, comma-separated) can also load a server
that ships in a **separate** package — e.g.
`bibliograph-mcp --with korea_scholarship_mcp.server`, which loads
korea-scholarship-mcp from its own repository. This document is what such a
package must honour to be loaded safely, and what bibliograph does with it.

## What `--with` does

From `src/bibliograph/server.py`, `Suite._load()`:

1. **Import the module** named after the dot (`importlib.import_module`).
2. **Find its MCP server object**: the first module-level attribute that is
   an instance of the SDK's server class (`FastMCP`/`MCPServer`) —
   `next(v for v in vars(mod).values() if isinstance(v, _MCPServer))`. There
   must be exactly one; if none exists this raises and the module is
   skipped (see next point), and if several exist the first one `vars()`
   yields is the one used — undefined by contract, so a module must expose
   only one.
3. **Skip-and-report on failure.** Any exception during import or server
   discovery is caught, the module is added to `suite.skipped` with the
   exception type and message, a line is printed to stderr, and every other
   source keeps loading. A broken `--with` module never takes bibliograph down.
4. **Copy its tools into bibliograph.** Every entry in the outside server's tool
   table (`srv._tool_manager._tools`) is copied into bibliograph's own table.
   **First tool name wins on a clash**: if a name is already present (from
   an earlier-loaded source, or an earlier `--with` module), the duplicate
   is dropped and a line is printed to stderr (`"duplicate tool <name> from
   <key>; kept the first"`). Load order is: the built-in `SOURCES` in the
   order listed in `server.py`, then `--with`/`BIBLIOGRAPH_WITH` modules in the
   order given. A colliding outside tool is silently unreachable, not an
   error — hence the naming requirement below.
5. **Record `__version__`.** The outside module's own `__version__` is
   used if present; otherwise bibliograph calls
   `importlib.metadata.version(module.split(".")[0].replace("_", "-"))`
   (the module's top-level package name, underscores turned to hyphens —
   e.g. `korea_scholarship_mcp` → distribution `korea-scholarship-mcp`).
   This is reported by `bibliograph_status`.

Nothing about a loaded tool's behaviour changes: its function object is
copied as-is, so its own rate limits, credentials, diagnostics and receipts
run exactly as they do standalone.

## Requirements on an outside module

To be safe to load with `--with`, a module must:

1. **Expose exactly one MCP server object at module level** (a `FastMCP` or
   `MCPServer` instance, from `mcp.server.fastmcp` or `mcp.server.mcpserver`
   depending on SDK version), the way `korea_scholarship_mcp.server` exposes
   `mcp = _MCPServer("korea_scholarship_mcp", ...)`.
2. **Define `__version__`** at package or module level, so a loaded source
   can be cited against the release that produced a result (`bibliograph_status`
   names it for exactly this reason).
3. **Prefix every tool name with its own source**, and never collide with a
   name bibliograph's built-in sources already use. bibliograph's current prefixes
   (from `src/bibliograph/sources/*/server.py`) are:

   | source | prefix / names |
   |---|---|
   | `ndl` | `ndl_*` (`ndl_search_books`, `ndl_search_national_bibliography`, `ndl_search_articles`, `ndl_search_digital_open`, `ndl_search_digital`, `ndl_search_warp`, `ndl_search_online_journals`, `ndl_search_all`, `ndl_get_record`) |
   | `ndl_dl` | `ndl_dl_*` (`ndl_dl_fulltext_search`, `ndl_dl_book_fulltext`, `ndl_dl_page_image`) |
   | `warp` | `warp_*` (`warp_list_captures`, `warp_nearest_capture`, `warp_read_capture`) |
   | `cinii` | `cinii_*` (`cinii_search_articles`, `cinii_search_books`, `cinii_search_dissertations`, `cinii_search_kaken`, `cinii_search_all`, `cinii_search_data`, `cinii_search_projects_and_products`, `cinii_search_researchers`, `cinii_get_record`, `cinii_get_holdings`, `cinii_search_libraries`) |
   | `jstage` | `jstage_*` (`jstage_search_articles`, `jstage_get_article_by_doi`, `jstage_list_issues`) |
   | `jdcat` | `jdcat_*` (`jdcat_search`, `jdcat_get_record`) |
   | `openalex` | `oa_*` (`oa_search_works`, `oa_get_work`, `oa_search_authors`, `oa_get_author`, `oa_search_sources`, `oa_search_institutions`, `oa_cited_by`, `oa_author_works`) |
   | `semantic_scholar` | `s2_*` (`s2_search_papers`, `s2_get_paper`, `s2_batch_papers`, `s2_citations`, `s2_search_authors`, `s2_get_author`, `s2_author_papers`, `s2_recommend_single`, `s2_recommend_multi`) |
   | `crossref` | `cr_*` (`cr_search_works`, `cr_get_work`, `cr_match_citation`) |
   | `fetch` | `fetch_*` (`fetch_pdf`, `fetch_pdf_text`) |
   | `names` | no single prefix — `name_query_variants`, `resolve_name_readings`, `resolve_name_kanji`, `infer_name_order`, `gloss_term`, `gloss_archaic`, `kanji_by_radical`, `kanji_info`, `find_scholar` |

   Plus `bibliograph_status`, which `Suite` adds itself after every source loads.
   korea-scholarship-mcp's `kci_*` and `oak_*` do not collide with any of
   these. A future outside package should pick a prefix from none of the
   above, `bibliograph_`, `kci_` or `oak_`.
4. **Return the unified envelope**, at the current `SCHEMA_VERSION`
   (`mediation.SCHEMA_VERSION`, currently **`"2.3.0"`**), with its
   documented top-level keys: `server`, `schema_version`, `operation`,
   `searched_for` (search operations only), `query`, `matching_mode`,
   `result`, `items`, `diagnostics`, `coverage_note`, `receipt`,
   `attribution`, and optionally `suggestions`. Build it with
   `mediation.build_envelope()` and serialize with `mediation.dumps()` or
   `mediation.emit()`, never a server-composed summary string.
5. **Deposit through a ledger** at the current `LEDGER_VERSION`
   (`ledger.LEDGER_VERSION`, currently **`"1.2.0"`**), writing to
   `<MCP_RECEIPT_DIR>/<server>.jsonl` (one file per server, chosen by
   `ledger.log_path_for()`), and honouring `MCP_RECEIPT_LOG` (single-file
   fallback when `MCP_RECEIPT_DIR` is unset), `MCP_RECEIPT_SESSION` (a
   free-text label written into every line), and `MCP_RECEIPT_STRICT` (`1`
   makes a write failure raise instead of passing silently). Both
   `MCP_RECEIPT_DIR`/`MCP_RECEIPT_LOG` unset means off, and nothing fails.
   Call `mediation.emit()` (not bare `dumps()`) so the deposit actually
   happens.
6. **Typed diagnostics only**: `{level, code, message, hint}` via
   `mediation.diag()`, never free prose standing in for a diagnostic.
7. **Never write to stdout except JSON-RPC.** This is a stdio MCP server:
   stdout carries the protocol frame and nothing else. Any logging handler
   that defaults to stdout must be redirected to stderr or disabled (see
   `korea_scholarship_mcp.server._silence_http_logging()` for the pattern).
8. **Read credentials only from its own environment variables**, and read
   them without failing at import — a missing key is reported by the tool
   or by a status tool at call time (e.g. `korea_sources_status`), not by
   raising while bibliograph is still assembling the suite. A module that raises
   on import because a key is unset would be caught and skipped by step 3
   above, silently losing every tool it carries.

## Version compatibility rule

An outside package's `mediation.py` and `ledger.py` must be **byte-identical**
to bibliograph's own copies (`src/bibliograph/mediation.py`, `src/bibliograph/ledger.py`) for
the versions they claim, **or** the package must declare in its own docs which
`SCHEMA_VERSION`/`LEDGER_VERSION` it implements, so a mismatch is a documented
fact rather than a silent drift. Both files describe themselves as vendored
byte-identical across the whole server family for exactly this reason: an
envelope or a ledger line that a relaying client (or a receipts-folder
manifest spanning several servers) has to reconcile across drifted schemas
defeats the point of a unified contract.

### Checking a package

Compare hashes (PowerShell):

```powershell
Get-FileHash -Algorithm SHA256 "<bibliograph-mcp>\src\bibliograph\mediation.py"
Get-FileHash -Algorithm SHA256 "<outside-pkg>\src\<outside_pkg>\mediation.py"
Get-FileHash -Algorithm SHA256 "<bibliograph-mcp>\src\bibliograph\ledger.py"
Get-FileHash -Algorithm SHA256 "<outside-pkg>\src\<outside_pkg>\ledger.py"
```

or (POSIX):

```sh
sha256sum bibliograph-mcp/src/bibliograph/mediation.py outside-pkg/src/outside_pkg/mediation.py
sha256sum bibliograph-mcp/src/bibliograph/ledger.py    outside-pkg/src/outside_pkg/ledger.py
```

A match on both files is a pass without further reading. A mismatch means
reading the outside copy's own `SCHEMA_VERSION`/`LEDGER_VERSION` constants and
its docstring to see what it declares, and confirming bibliograph and the client
reading `bibliograph_status` can tolerate the difference.

Load it and inspect what actually loaded:

```sh
bibliograph-mcp --with outside_pkg.server --list
```

(`--list` only prints the built-in `SOURCES` table and exits — it does not
reflect `--with`. To see the outside module's own result, run the server and
call its `bibliograph_status` tool, or in Python:)

```python
from bibliograph.server import Suite
suite = Suite(extra=["outside_pkg.server"])
print(suite.status())          # loaded / skipped, with the outside module's __version__
print(sorted(suite.loaded[-1]["tools"]))   # the tool names it actually contributed
```

`suite.skipped` is empty and `suite.loaded[-1]["outside"]` is `True` when the
module loaded cleanly; any import or discovery failure lands in `skipped`
with the exception's type and message.

## Current status: korea-scholarship-mcp

Checked 30 Oct 2026 against
the working copy of `korea-scholarship-mcp` on branch `feat/dbpia-links-0.7.0`
(package `korea_scholarship_mcp`, `__version__ = "0.7.0"`: the public 0.6.3 of
12 Oct 2026 plus `dbpia_links`).

- **Hash check — pass.** `sha256(mediation.py)` and `sha256(ledger.py)` are
  identical between `bibliograph/mediation.py`/`bibliograph/ledger.py` and
  `korea_scholarship_mcp/mediation.py`/`korea_scholarship_mcp/ledger.py`:

  | file | sha256 |
  |---|---|
  | `mediation.py` (both) | `089eaea5d707071da4ecb762ee476c2183a1be3509c7616606aaee0b35ac18a2`\* |
  | `ledger.py` (both) | `d0bf4175edbc5bc143b08635ef1a3ca80f19b4183ba45239dcd43d1b3eca1bc1`\* |

  \*As computed by `Get-FileHash -Algorithm SHA256` on this machine — 64
  hex characters; re-run the commands above to verify independently.

- **Envelope**: `SCHEMA_VERSION = "2.3.0"` — matches bibliograph's current
  `mediation.SCHEMA_VERSION`, consistent with the byte-identical file.
- **Ledger**: `LEDGER_VERSION = "1.1.0"` — matches bibliograph's current
  `ledger.LEDGER_VERSION`, same reason.
- **Tool prefixes**: `kci_*` (`kci_search`, `kci_article`, `kci_references`,
  `kci_journal_metrics`, `kci_harvest`) and `oak_*` (`oak_harvest`,
  `oak_record`), plus its own status tool `korea_sources_status`. None of
  these collide with the prefixes listed in the table above.
- **Deviation named in the brief (co-authors packed into a pipe-joined
  string, audit of 23 Sep 2026) — not found in the current source.** Reading
  `src/korea_scholarship_mcp/server.py` as it stands on 24 Sep 2026:
  - `_kci_authors()` (line 323) builds a `list[dict]`, one dict per author,
    from KCI REST's `이름(소속기관)` strings — `{"name", "name_en",
    "affiliation", "orcid"}` per person, not a single joined string.
  - `_kci_oai_item()`'s creator handling (line 888) splits each `<creator>`
    blob on `;` and appends one author dict per split part.
  - `_oak_item()`'s author list (line 994) is likewise one dict per name in
    `dc.get("author", [])`.

  If the 23 Sep 2026 audit is accurate for the code it examined, either the
  packing was fixed between that audit and this check (`git log` on this
  repo shows no commit that reads as that fix in the 20–26 Sep 2026 range,
  so this cannot be confirmed from history alone), or the finding concerned
  a different code path than the three above. Re-run the audit's own
  reproduction steps against the current `server.py` before relying on
  either conclusion; this document only reports what a fresh reading of the
  three author-building functions shows today.
