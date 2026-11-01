# semantic-scholar-mcp

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22336887.svg)](https://doi.org/10.5281/zenodo.22336887)

MCP stdio server for the Semantic Scholar Academic Graph API.

Data via Semantic Scholar, Allen Institute for AI.

## What this is for

The Semantic Scholar Academic Graph, reached through citation traversal in both directions: the works a paper cites, and the works that went on to cite it. Look up as many as five hundred papers in a single call when a bibliography needs resolving.

The recommendation tools answer a question searching cannot: hand it two or three papers you already trust and it proposes adjacent work, which is how you enter a literature whose vocabulary you have not yet learned.

Records carry abstracts, influential-citation counts, open-access links, and machine-generated one-line summaries useful for triage. Where [`openalex-mcp`](https://github.com/ckgerteis/openalex-mcp) is strongest on institutions and geography, this is strongest on the shape of a citation network.

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
- **A method section that writes itself.** `semantic-scholar-mcp-ledger` `manifest <folder>` summarises every
  query a project made, by server, script and session: the disclosure a journal, a
  data-availability statement or a research-integrity review asks for.
- **A record of AI-mediated research.** When a model chose the term, the receipt shows the term
  it chose and what came back, which is the thing to disclose about work done with an assistant.
- **Nothing interpreted.** The receipt is the source's own answer with credentials removed. The
  server does not summarise, rank or paraphrase, so the record is of the source, not of the tool.

Receipts are off until you name a folder (`MCP_RECEIPT_DIR`); each server then writes its own
`<server>.jsonl` inside it, and `MCP_RECEIPT_SESSION` stamps a project or article slug on every
line so one folder can serve several projects. `semantic-scholar-mcp-ledger` `verify-dir <folder>` checks the chains.
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

Download `semantic-scholar-mcp-2.1.2.mcpb` from the [latest release](https://github.com/ckgerteis/semantic-scholar-mcp/releases/latest) and open it; Claude Desktop installs it. One bundle serves Windows, macOS (Apple Silicon and Intel) and Linux. Claude Desktop asks for Semantic Scholar API key and a receipts folder at install time; the key is stored in the OS keychain.

The bundle carries the server's source and a lock file, nothing compiled, and needs no Python of its own. Claude Desktop builds the bundle's environment when you install it, with [uv](https://docs.astral.sh/uv/), a copy already on your PATH if there is one and otherwise one the app downloads for itself: uv takes a Python 3.10 or later already on the machine, downloads one only if there is none, and installs the locked libraries, roughly 40 MB, behind the install progress bar. Every launch then reuses that environment and takes under a second. Bundles 2.1.0 and 2.1.1 kept `pyproject.toml` one folder down, which made Claude Desktop skip that install step and download everything during the first connection attempt instead; on a slow or filtered network that attempt never completed and the app reported it could not connect to the extension server. Bundles before 2.1.0 vendored libraries compiled for CPython 3.12 only and failed on every other interpreter. See [Troubleshooting](#troubleshooting).

### From GitHub, pinned to a release

```bash
pip install "git+https://github.com/ckgerteis/semantic-scholar-mcp@v2.1.2"
# or, without an environment of your own:
uvx --from "git+https://github.com/ckgerteis/semantic-scholar-mcp@v2.1.2" semantic-scholar-mcp
```

installs the `semantic-scholar-mcp` console script and `semantic-scholar-mcp-ledger`. The tag is the thing to cite; `@main` gets whatever is current. Then register it in Claude Desktop (below), or let `install.py` do that.

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
uvx --from "git+https://github.com/ckgerteis/semantic-scholar-mcp" semantic-scholar-mcp
```

Verify the install:

```bash
.venv/bin/python -c "import semantic_scholar_mcp; print(semantic_scholar_mcp.__version__)"
```

That fails loudly if the package or one of its vendored modules is missing. Do
not use `semantic-scholar-mcp --help` as the check: unknown arguments are ignored, the
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
.\install.ps1 -Servers semantic_scholar,cinii# a chosen subset
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
    "semantic_scholar": {
      "command": "/absolute/path/to/.venv/bin/semantic-scholar-mcp",
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "your key (optional)",
        "MCP_RECEIPT_DIR": "/absolute/path/to/receipts",
        "MCP_RECEIPT_SESSION": "project-or-article-slug"
      }
    }
  }
}
```

Claude Code takes the same thing on the command line:

```bash
claude mcp add semantic_scholar -- /absolute/path/to/.venv/bin/semantic-scholar-mcp
```

On Windows the path ends in `\.venv\Scripts\semantic-scholar-mcp.exe`. `MCP_RECEIPT_DIR` and `MCP_RECEIPT_SESSION`
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
| `s2_search_papers` | Papers by keyword, with year, field-of-study, citation-count and open-access filters |
| `s2_get_paper` | One paper by S2 ID, DOI, ArXiv ID or URL |
| `s2_batch_papers` | Up to 500 papers by ID in one call |
| `s2_citations` | Papers citing a paper, or the papers it cites |
| `s2_search_authors` | Authors by name |
| `s2_get_author` | One author by S2 Author ID |
| `s2_author_papers` | An author's papers, paginated |
| `s2_recommend_single` | Papers similar to one seed paper |
| `s2_recommend_multi` | Papers similar to a set of seeds, unlike optional negatives |

All nine return one typed JSON response envelope — see [Response format](#response-format). (Releases before 2.0.0 returned formatted markdown text; that is a breaking change, not a formatting preference.)

## Response format

Every tool returns one JSON response envelope, built by `mediation.py` and defined in [`response-schema.json`](response-schema.json). Schema version 2.3.0. The same module and schema are vendored byte-identically across the server family, so an envelope from one server can be read by a consumer written for another.

The envelope reports how the search was made, not only what it found:

- **`searched_for`** — on the two term searches (`s2_search_papers`, `s2_search_authors`), the term actually sent, its detected script, and the matching mode, hoisted to the top of the envelope so a relaying client cannot drop it. Lookups, citation traversals, batch and recommendations omit it: they were handed identifiers and chose no term.
- **`query`** — `input_terms` as supplied, `normalized` as sent, and the detected `script`. For batch and multi-seed recommendations the identifiers asked for are in `params`, so the receipt hash fixes the request and not only the answer. The key is sent as a header and never enters `params`.
- **`matching_mode`** — `relevance_ranked` for term searches (title, abstract and venue, ranked; `result.total` is the API's estimate); `filter_exact` for citation and authorship traversals; `identifier_lookup` for fetches and batch; `similarity_ranked` for the recommender.
- **`result.breadth`** — `none`, `narrow` (1–50), `broad` (51–1000), `very_broad` (>1000).
- **`items[]`** — the family's item shape. Semantic Scholar reports no language, so script decides the typed title slot: kana or Hangul place a title in `ja` or `ko`, Latin script in `en`, and a han-only title is left untyped rather than guessed; `extra.title` always carries the text. S2 and Corpus IDs, ArXiv and PubMed IDs, citation and influential-citation counts, fields of study, TL;DR and the abstract sit in `extra`; the DOI in `ids.doi`; the S2 page in `ids.url_en`; an open-access PDF in `ids.fulltext_url`. Author records use `record_type` `author`.
- **`receipt`** — an ISO 8601 timestamp, a SHA-256 over the normalised query and its parameters, and the DOIs returned. Papers without a DOI are identified only in `extra.s2_paper_id`, which the receipt's `result_ids` now reads, as `s2:<id>` (bibliograph 1.2.0).
- **`attribution`** — the required credit line, in every response.

### Diagnostic codes

Typed and closed. A diagnostic is never prose the client has to parse.

| Code | Level | Meaning |
| --- | --- | --- |
| `OK` | info | Records returned; nothing to flag. |
| `TOTAL_NOT_REPORTED` | info | The endpoint reports no corpus total (citations, references, an author's papers, batch, recommendations); `result.total` is the returned count, and the message says whether the API offers a further page. |
| `LOOSE_NAME_MATCH` | info | `s2_search_authors`: Semantic Scholar's author search returns loose matches and duplicate people, so at least one result does not match the queried name exactly. Each item carries `extra.name_match` (`exact`/`partial`/`none`), graded against the name plus any `extra.aliases`; items are never filtered or reordered on it. |
| `ZERO_RESULTS` | warning | No records. Coverage of non-English humanities scholarship is thin; consult the CiNii, J-STAGE, NDL and KCI servers before concluding the literature is absent. |
| `PARTIAL_NOT_FOUND` | warning | Batch: some identifiers resolved to no record; they are listed in `coverage_note`. |
| `NOT_FOUND` | warning | A lookup by identifier answered 404. |
| `RATE_LIMITED` | error | The API answered 429. Keyless callers share one pool and search endpoints are throttled first; a free key gives 1 request/second, which the server enforces. |
| `RECORD_SHAPE_UNEXPECTED` | warning | One or more records in the response could not be read and were left out; the message gives the number. `result.total` is the source's own count and still includes them. |
| `API_ERROR` | error | The API answered, and answered with an error (or with a 200 that was not JSON). |
| `TRANSPORT_ERROR` | error | The request did not complete. Kept distinct from `API_ERROR` because a failed search has an unknown result and must never be written up as an absence. |
| `RECEIPT_NOT_DEPOSITED` | info | The response was not written to the query ledger, because no receipts destination is configured. |
| `RECEIPT_WRITE_FAILED` | warning | A receipts destination is set, the write was attempted, and it did not land. |

## Configuration

```
SEMANTIC_SCHOLAR_API_KEY=your_semantic_scholar_api_key
```

### Claude Desktop

Add an entry to `%APPDATA%\Claude\claude_desktop_config.json` under
`mcpServers`, pointing at the console script in the environment you installed
into. On macOS or Linux use the absolute path to `.venv/bin/semantic-scholar-mcp`.

```json
{
  "mcpServers": {
    "semantic-scholar": {
      "command": "C:\\path\\to\\.venv\\Scripts\\semantic-scholar-mcp.exe",
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "your_semantic_scholar_api_key"
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

Restart Claude Desktop. The nine tools should appear under "semantic-scholar" in the
tool list.

## Query receipts

Every envelope can be deposited to an append-only, hash-chained JSONL log by
`semantic_scholar_mcp.ledger`. It is **off unless `MCP_RECEIPT_DIR` (or the legacy `MCP_RECEIPT_LOG`) is set**, and a
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
semantic-scholar-mcp-ledger verify      receipts/semantic-scholar.jsonl
semantic-scholar-mcp-ledger verify-dir  receipts
semantic-scholar-mcp-ledger manifest    receipts        # writes receipts/manifest.json
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

The suite runs against recorded Semantic Scholar responses under `tests/fixtures/` (captured 2026-09-04 without a key) and validates every envelope against `response-schema.json`; it needs no network and no key. `RUN_LIVE=1` adds one request to the live API.

## MCP SDK compatibility

Runs on both `mcp` 1.x and 2.x. Version 2.0.0 of the SDK removed
`mcp.server.fastmcp`; this server imports `FastMCP` where it exists and falls
back to `MCPServer` where it does not.

## License

MIT © 2026 Christopher Gerteis. Covers the server code only; it grants no
rights over Semantic Scholar, Allen Institute for AI data, which remains governed by that provider's
terms: the [Semantic Scholar API License Agreement](https://www.semanticscholar.org/product/api/license)
and the [API documentation](https://api.semanticscholar.org/). Those terms ask that Semantic Scholar be
credited, with a link, wherever its data is shown, which the `attribution` line in every envelope
carries, and that published work built on the API cite the platform: Kinney et al., "The Semantic
Scholar Open Data Platform" (2023, arXiv:2301.10140).

## Author

[Dr Christopher Gerteis](https://www.christophergerteis.net), SOAS University
of London.
