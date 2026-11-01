# openalex-mcp

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22336885.svg)](https://doi.org/10.5281/zenodo.22336885)

MCP stdio server for the OpenAlex API (global scholarly graph).

Data via OpenAlex, OurResearch.

## What this is for

OpenAlex maps roughly 240 million works and the relations between them, and this is the instrument for questions about circulation rather than content.

Ask who cites a given work and from which countries and institutions; assemble an author's full output across the name variants that defeat a title search; find which institutions cluster around a problem; identify the journals and repositories where a field actually publishes. Open-access status and PDF links come back with each record.

For a historian, the useful move is tracing whether an argument travelled — out of its language, out of its discipline, out of the decade that produced it — which is a question a bibliographic catalogue cannot answer and a citation graph can.

## What the receipts are for

A search you cannot re-run is a claim you cannot check. When a footnote rests on a database
query, say that no article in this index uses a term before a certain year, the reader is asked to
take the search on trust: which term, in which script, on what date, against which index and which
version of it, and how far down the results the author went. Ordinary searching leaves none of
that behind. This server leaves all of it. Every
query-answering tool returns its envelope through the ledger, which appends one line to an
append-only file: the term actually sent and its script, how the source matched it, how many
records existed and how many came back, the diagnostics, the tool and its parameters, the server
version, a timestamp, and the hash of the previous line. The hash makes the file a chain: a line
cannot be altered, removed or reordered afterwards without the verifier saying so.

What that gives a researcher:

- **A citable search.** Name the receipt in the footnote (session slug, server, date, line hash)
  and a reader can see exactly what was asked and run it again against the same version.
- **Negative findings that carry weight.** "Not found" is evidence only if the search that
  produced it is on record, with its term, its script and its breadth.
- **A method section that writes itself.** `openalex-mcp-ledger` `manifest <folder>` summarises every
  query a project made, by server, script and session: the disclosure a journal, a
  data-availability statement or a research-integrity review asks for.
- **A record of AI-mediated research.** When a model chose the term, the receipt shows the term
  it chose and what came back, which is the thing to disclose about work done with an assistant.
- **Nothing interpreted.** The receipt is the source's own answer with credentials removed. The
  server does not summarise, rank or paraphrase, so the record is of the source, not of the tool.

Receipts are off until you name a folder (`MCP_RECEIPT_DIR`); each server then writes its own
`<server>.jsonl` inside it, and `MCP_RECEIPT_SESSION` stamps a project or article slug on every
line so one folder can serve several projects. `openalex-mcp-ledger` `verify-dir <folder>` checks the chains.
The mechanics, the variables and what the envelope says when nothing is deposited are in the
receipts section below.

## Install

Three routes. All three give you the same server; pick by how much you want to see of it.

**Python.** The pip and source routes need Python 3.10 or later; 3.10, 3.12, 3.13 and 3.14 are tested in CI on Windows, macOS and Linux. The Claude Desktop bundle uses whichever of these is already installed, and has uv download one only if none is.

### Getting Python

Every route needs Python 3.10 to 3.14. The Claude Desktop bundle uses one already on the machine
and has uv download one only if none is; the other routes also need the `venv` module, which the
official installers include.

- **Windows.** Download the 64-bit installer from [python.org/downloads](https://www.python.org/downloads/)
  and run it; tick "Add python.exe to PATH" on the first screen. Afterwards `py --version` (the
  launcher the installer adds) or `python --version` in a new terminal should print 3.1x. If typing
  `python` opens the Microsoft Store instead, Windows has no Python yet: that Store page is a stub,
  and it is also what "'python' is not recognized" usually means.
- **macOS.** The [python.org installer](https://www.python.org/downloads/macos/), or
  `brew install python@3.13` with [Homebrew](https://brew.sh). The `/usr/bin/python3` that Xcode's
  command-line tools provide may be older than 3.10; `python3 --version` says.
- **Linux.** Your distribution's package: `sudo apt install python3 python3-venv` on Debian and
  Ubuntu, `sudo dnf install python3` on Fedora. Or let uv provide one (next line).
- **Any platform, with uv.** [uv](https://docs.astral.sh/uv/getting-started/installation/)
  installs Python itself: `uv python install 3.13`, then `uv venv` or the `uvx` route below.

### One click: the Claude Desktop bundle

Download `openalex-mcp-2.1.2.mcpb` from the [latest release](https://github.com/ckgerteis/openalex-mcp/releases/latest) and open it; Claude Desktop installs it. One bundle serves Windows, macOS (Apple Silicon and Intel) and Linux. Claude Desktop asks for OpenAlex API key and Contact email (legacy mailto) and a receipts folder at install time; the key is stored in the OS keychain.

The bundle carries the server's source and a lock file, nothing compiled, and needs no Python of its own. Claude Desktop builds the bundle's environment when you install it, with [uv](https://docs.astral.sh/uv/), a copy already on your PATH if there is one and otherwise one the app downloads for itself: uv takes a Python 3.10 or later already on the machine, downloads one only if there is none, and installs the locked libraries, roughly 40 MB, behind the install progress bar. Every launch then reuses that environment and takes under a second. Bundles 2.1.0 and 2.1.1 kept `pyproject.toml` one folder down, which made Claude Desktop skip that install step and download everything during the first connection attempt instead; on a slow or filtered network that attempt never completed and the app reported it could not connect to the extension server. Bundles before 2.1.0 vendored libraries compiled for CPython 3.12 only and failed on every other interpreter. See [Troubleshooting](#troubleshooting).

### From GitHub, pinned to a release

```bash
pip install "git+https://github.com/ckgerteis/openalex-mcp@v2.1.2"
# or, without an environment of your own:
uvx --from "git+https://github.com/ckgerteis/openalex-mcp@v2.1.2" openalex-mcp
```

installs the `openalex-mcp` console script and `openalex-mcp-ledger`. The tag is the thing to cite; `@main` gets whatever is current. Then register it in Claude Desktop (below), or let `install.py` do that.

### The whole family

```bash
pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.3" && bibliograph install
```

installs all six servers and registers them together — one receipts folder, credentials asked for once. See [bibliograph-mcp](https://github.com/ckgerteis/bibliograph-mcp). From a checkout of this repository, `python install.py` does the same for this server alone, `python install.py --all` for the six, on Windows, macOS and Linux; `install.ps1` remains for Windows.

### From source

```bash
python3 -m venv .venv
.venv/bin/pip install .
```

On Windows:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\pip.exe install .
```

Or straight from the repository, without cloning:

```bash
uvx --from "git+https://github.com/ckgerteis/openalex-mcp" openalex-mcp
```

Verify the install:

```bash
.venv/bin/python -c "import openalex_mcp; print(openalex_mcp.__version__)"
```

That fails loudly if the package or one of its vendored modules is missing. Do
not use `openalex-mcp --help` as the check: unknown arguments are ignored, the
server starts, reads end-of-input and exits 0, so it reports success whatever
the state of the code.

### Installing more than this one

Six independent packages. None imports another, none depends on another, and
each installs and answers on its own — `pip install .` in this directory is a
complete install of this server and nothing else.

They do share three things: a response envelope, a query ledger, and — if you
run more than one — a receipts folder. `install.ps1` is vendored byte-identical
into all six and handles that on Windows; `install.py` is its cross-platform port. **Both install this server by default**, because
cloning one repository is not a request for five more.

```powershell
.\install.ps1                        # this server
.\install.ps1 -All                   # all six
.\install.ps1 -Servers openalex,cinii      # a chosen subset
```

Nothing about where things go is decided for you. The script asks where to
install (the virtual environment Claude Desktop will be pointed at), which
folder receives the receipts, and which session slug to stamp on them,
offering a neutral suggestion for each that Enter accepts; run without a
terminal it does not guess, and stops unless `--venv` and `--receipts-dir`
(or `--no-receipts`; `-VenvDir` and `-ReceiptsDir` for `install.ps1`) say
so. Whatever subset you name is registered against one receipts folder, asked for
once. The script prefers a sibling checkout to the network, carries across
credentials already registered rather than asking again, leaves servers it was
not asked about alone, and stops rather than guessing where the servers already
registered disagree about the folder or the session slug. It also asserts that
`ledger.py` and `mediation.py` are byte-identical across everything it
installed, so two envelope versions cannot end up in one environment unnoticed.

### Any other MCP client

Nothing here is specific to Claude. The server speaks the Model Context Protocol over stdio and
nothing else: any client that can start a process and talk JSON-RPC to it (Claude Code, Cursor,
VS Code and Continue, Zed, LibreChat, a script of your own using an MCP SDK) can use it. The
Claude Desktop bundle and the installers are conveniences for one client; the server underneath is
the same console script. Register it anywhere by giving the client the absolute path of the
console script and, optionally, the environment:

```json
{
  "mcpServers": {
    "openalex": {
      "command": "/absolute/path/to/.venv/bin/openalex-mcp",
      "env": {
        "OPENALEX_API_KEY": "your key (optional)",
        "MCP_RECEIPT_DIR": "/absolute/path/to/receipts",
        "MCP_RECEIPT_SESSION": "project-or-article-slug"
      }
    }
  }
}
```

Claude Code takes the same thing on the command line:

```bash
claude mcp add openalex -- /absolute/path/to/.venv/bin/openalex-mcp
```

On Windows the path ends in `\.venv\Scripts\openalex-mcp.exe`. `MCP_RECEIPT_DIR` and `MCP_RECEIPT_SESSION`
are optional; without them the server runs and every envelope says `RECEIPT_NOT_DEPOSITED`. The
stdio transport is the only one: there is no HTTP endpoint to expose, and nothing to host.

## Troubleshooting

**"Server disconnected"** is all Claude Desktop says when the server process exited before or during the handshake, whatever the reason. The reason is in the log:

- Windows: `%LOCALAPPDATA%\Claude\Logs\mcp-server-<name>.log` (builds before August 2026: `%APPDATA%\Claude\logs`) (the extension's display name, or the key under `mcpServers`), with `mcp.log` beside it for the app's side of the conversation.
- macOS: `~/Library/Logs/Claude/mcp-server-<name>.log` and `mcp.log`.
- Linux: `~/.config/Claude/logs/`.

Read the last launch from the bottom up. Three shapes account for nearly every report:

- **A Python traceback ending in `ImportError` or `ModuleNotFoundError`** (for example `No module named 'pydantic_core._pydantic_core'`). The interpreter started, the code was found, and a compiled library did not match that interpreter. This is what every bundle before 2.1.0 did on any Python other than 3.12. Install the current bundle, or use the pip route, which resolves wheels for the interpreter you install into.
- **`'python' is not recognized`, `spawn python ENOENT`, or a line from the Microsoft Store**: no interpreter was found on the PATH Claude Desktop constructs. Nothing of this server ran. The current bundle does not launch `python` at all; for the pip route, register the console script by absolute path as shown above.
- **A line from uv** (`error: ...`, or a download that never finished), or `Unable to connect to extension server` with nothing from the server in the log: the environment was not built. From 2.1.2 the app builds it at install time; look in `main.log` beside the server log for lines tagged `[UV Runtime]`, which record the download and the `uv sync`, and for `missing pyproject.toml`, which means a bundle older than 2.1.2. If the install-time build failed (no network, a proxy that blocks github.com or pypi.org), reinstall the bundle once the network is back; the launch also rebuilds the environment itself, so a second launch on a working network completes.

The bundle's own entry point writes one line naming the interpreter, its path and the supported range before re-raising an import failure, so a log from 2.1.0 onwards says which of these it is.

## Tools

| Tool | Purpose |
| --- | --- |
| `oa_search_works` | Works (articles, books, datasets, theses) by term, with year, author, institution, source and open-access filters |
| `oa_get_work` | One work by OpenAlex ID, DOI or PMID |
| `oa_search_authors` | Authors by name, optionally within an institution |
| `oa_get_author` | One author by OpenAlex ID or ORCID |
| `oa_search_sources` | Journals, repositories and conferences by name |
| `oa_search_institutions` | Institutions by name, optionally by country |
| `oa_cited_by` | Works citing a given work, most-cited first |
| `oa_author_works` | An author's works, with year filter and sort |

All eight return one typed JSON response envelope — see [Response format](#response-format). (Releases before 2.0.0 returned formatted markdown text; that is a breaking change, not a formatting preference.)

## Response format

Every tool returns one JSON response envelope, built by `mediation.py` and defined in [`response-schema.json`](response-schema.json). Schema version 2.3.0. The same module and schema are vendored byte-identically across the server family, so an envelope from one server can be read by a consumer written for another.

The envelope reports how the search was made, not only what it found:

- **`searched_for`** — on search operations, the term actually sent, its detected script, and the matching mode, hoisted to the top of the envelope so a relaying client cannot drop it. Lookups (`oa_get_work`, `oa_get_author`) and identifier filters (`oa_cited_by`, `oa_author_works`) omit it: they were handed an identifier and chose no term.
- **`query`** — `input_terms` as supplied, `normalized` as sent, and the detected `script`. The credential never enters `params`.
- **`matching_mode`** — `full_text_stemmed` for term searches: OpenAlex matches title, abstract and indexed full text with stemming, so `result.total` is a loose count and a high breadth is expected. `filter_exact` for identifier filters; `identifier_lookup` for single-record fetches.
- **`result.breadth`** — `none`, `narrow` (1–50), `broad` (51–1000), `very_broad` (>1000).
- **`items[]`** — the family's item shape. OpenAlex's own `language` field decides which typed title slot a work's title lands in (`ja`, `ko`; Latin-script titles in any other language go to `en`). A CJK title OpenAlex marks neither `ja` nor `ko`, or a han-only title with no language, is left untyped rather than guessed; `extra.title` always carries the text and `extra.language` the code. OpenAlex identifiers, citation counts, open-access flags, topics and the reconstructed abstract sit in `extra`; the DOI (bare, without the `https://doi.org/` prefix) in `ids.doi`; the landing page in `ids.url_en`; an open-access copy in `ids.fulltext_url`. Author, source and institution records use `record_type` `author`, `source` and `institution` with their metrics in `extra`.
- **`receipt`** — an ISO 8601 timestamp, a SHA-256 over the normalised query and its parameters, and the DOIs returned. Works without a DOI are identified only in `extra.openalex_id`, which the receipt's `result_ids` now reads, as `openalex:<id>` (bibliograph 1.2.0).
- **`attribution`** — the required credit line, in every response.

### Diagnostic codes

Typed and closed. A diagnostic is never prose the client has to parse.

| Code | Level | Meaning |
| --- | --- | --- |
| `OK` | info | Records returned; nothing to flag. |
| `ZERO_RESULTS` | warning | No records for this term and filter set. Non-English titles are indexed as the publisher supplied them, so an English rendering of a Japanese or Korean title may not match. |
| `LOOSE_NAME_MATCH` | info | `oa_search_authors`: OpenAlex's author search is a loose name match that returns duplicate people, so at least one result does not match the queried name exactly. Each item carries `extra.name_match` (`exact`/`partial`/`none`), graded against the display name plus any `extra.alternate_names`; items are never filtered or reordered on it. |
| `NOT_FOUND` | warning | A lookup by identifier answered 404. |
| `RATE_LIMITED` | error | OpenAlex answered 429. OpenAlex meters a per-second rate and a daily dollar budget ($1 on a key, $0.10 per IP without one, reset at midnight UTC, topped up by any prepaid balance). The message says which was exceeded, read from OpenAlex's `X-RateLimit-*` headers: a spent budget names the time to reset and points to prepaid usage; a per-second limit gives the budget left. |
| `PAGING_COST` | info | A search or list was read beyond page 1 at fewer than 50 results per page. OpenAlex charges per call, not per result, so a sweep should set `per_page` 200. Appended after `OK` or `ZERO_RESULTS`, never in place of them. |
| `RECORD_SHAPE_UNEXPECTED` | warning | One or more records in the response could not be read and were left out; the message gives the number. `result.total` is the source's own count and still includes them. |
| `API_ERROR` | error | The API answered, and answered with an error (or with a 200 that was not JSON). |
| `TRANSPORT_ERROR` | error | The request did not complete. Kept distinct from `API_ERROR` because a failed search has an unknown result and must never be written up as an absence. |
| `RECEIPT_NOT_DEPOSITED` | info | The response was not written to the query ledger, because no receipts destination is configured. |
| `RECEIPT_WRITE_FAILED` | warning | A receipts destination is set, the write was attempted, and it did not land. |

## Configuration

```
OPENALEX_API_KEY=your_openalex_api_key
OPENALEX_EMAIL=your_email        # legacy; see below
```

OpenAlex retired the polite pool on 13 February 2026 and replaced it with an API
key regime; the `mailto` parameter it depended on is now ignored. `OPENALEX_API_KEY`
is the access route. `OPENALEX_EMAIL` is kept only as a fallback for anyone running
against a mirror that still honours `mailto`, and sends nothing OpenAlex reads.

### Claude Desktop

Add an entry to `%APPDATA%\Claude\claude_desktop_config.json` under
`mcpServers`, pointing at the console script in the environment you installed
into. On macOS or Linux use the absolute path to `.venv/bin/openalex-mcp`.

```json
{
  "mcpServers": {
    "openalex": {
      "command": "C:\\path\\to\\.venv\\Scripts\\openalex-mcp.exe",
      "env": {
        "OPENALEX_API_KEY": "your_openalex_api_key"
      }
    }
  }
}
```

**Changed in 2.0.0.** Tools return the JSON envelope rather than markdown; any consumer that parsed the 1.x text must be rewritten.

**Changed in 1.1.0.** Earlier versions were registered by path —
`"command": "…\\python.exe", "args": ["…\\server.py"]`. That entry will not
start this version, because `server.py` is now a module inside a package rather
than a script beside its imports. Replace it with the console script above.

Restart Claude Desktop. The eight tools should appear under "openalex" in the
tool list.

## Query receipts

Every envelope can be deposited to an append-only, hash-chained JSONL log by
`openalex_mcp.ledger`. Since 2.0.0 the envelope says whether that happened: `RECEIPT_NOT_DEPOSITED` when no destination is set, `RECEIPT_WRITE_FAILED` when one is set and the write did not land. It is **off unless `MCP_RECEIPT_DIR` (or the legacy `MCP_RECEIPT_LOG`) is set**, and a
logging failure is swallowed rather than raised — a search matters more than
the record of it. Secrets are redacted before a line is composed.

```
MCP_RECEIPT_DIR=C:\path\to\receipts        # a folder, not a file
MCP_RECEIPT_SESSION=project-or-article-slug
MCP_RECEIPT_STRICT=1                         # optional: make logging failure raise
MCP_RECEIPT_LOG=C:\path\to\receipts.jsonl  # legacy single file; ignored when _DIR is set
```

**A folder, and one file per server.** `MCP_RECEIPT_DIR` points at a directory
and each server writes its own `<server>.jsonl` inside it. That is not tidiness.
Appending is read-the-last-hash-then-write, and the lock around it is a threading
lock, which holds within one process and not between several — six servers are
six processes, and two answering at the same moment will both read the same
predecessor and both claim it. Measured, not theorised: six processes writing 150
lines to one file produced fourteen forks. `MCP_RECEIPT_LOG` still works and is
still correct for a single server; it is the wrong shape for a family.

`install.ps1` sets this up for all six and writes a README into the folder.

Verify one chain, or the whole folder:

```bash
openalex-mcp-ledger verify      receipts/openalex.jsonl
openalex-mcp-ledger verify-dir  receipts
openalex-mcp-ledger manifest    receipts        # writes receipts/manifest.json
```

`verify` exits non-zero on failure and says which kind it found: a **fork**
(concurrent writers — a configuration fault, and every line is still there), a
**missing** line, a **reordering**, or **tamper** (a line that does not hash to
its own content). Only the last is a claim about honesty, and reporting them
alike would invite a reader to mistake one for the other. The manifest is the
object to cite: one description of the whole deposit — per-file line counts,
first and last timestamps, terminal hashes, and combined totals by server,
script and session.

## Tests

```bash
.venv/bin/pip install pytest jsonschema
.venv/bin/python -m pytest -q tests
```

The suite runs against recorded OpenAlex responses under `tests/fixtures/` (captured 2026-09-04) and validates every envelope against `response-schema.json`; it needs no network and no key. `RUN_LIVE=1` adds one request to the live API.

## MCP SDK compatibility

Runs on both `mcp` 1.x and 2.x. Version 2.0.0 of the SDK removed
`mcp.server.fastmcp`; this server imports `FastMCP` where it exists and falls
back to `MCPServer` where it does not.

## License

MIT © 2026 Christopher Gerteis. Covers the server code only; it grants no
rights over OpenAlex, OurResearch data, which remains governed by that provider's
terms. OpenAlex releases its data under [CC0](https://help.openalex.org/hc/en-us/articles/24397140742807-What-is-the-license-for-OpenAlex-data),
so no attribution is legally required; OurResearch asks for a credit and a link where the data is
shown, and the `attribution` line in every envelope carries one.

## Author

[Dr Christopher Gerteis](https://www.christophergerteis.net), SOAS University
of London.
