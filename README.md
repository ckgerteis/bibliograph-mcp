# bibliograph-mcp

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22307233.svg)](https://doi.org/10.5281/zenodo.22307233)

Six MCP servers for scholarly search, installed and registered as one suite. Each answers with the same typed JSON envelope — the term actually sent and its script, how the source matched it, how broad the set is, typed diagnostics, a receipt hash, the provider's attribution — and each can deposit its receipts to one append-only, hash-chained ledger, so a search standing behind a footnote can be named, cited, and run again by someone else.

| Server | Source | Coverage |
| --- | --- | --- |
| [cinii-mcp](https://github.com/ckgerteis/cinii-mcp) | CiNii Research (NII) | Japanese articles, books, dissertations, KAKEN projects, researchers |
| [jstage-mcp](https://github.com/ckgerteis/jstage-mcp) | J-STAGE (JST) | Full text of Japanese learned-society journals |
| [ndl-mcp](https://github.com/ckgerteis/ndl-mcp) | NDL Search (National Diet Library) | Books, articles, the national bibliography, open digital collections |
| [korea-scholarship-mcp](https://github.com/ckgerteis/korea-scholarship-mcp) | KCI and Open Access Korea | Korean articles, references, journal metrics, OAI-PMH harvests |
| [openalex-mcp](https://github.com/ckgerteis/openalex-mcp) | OpenAlex | Works, authors, sources, institutions, citation relations, worldwide |
| [semantic-scholar-mcp](https://github.com/ckgerteis/semantic-scholar-mcp) | Semantic Scholar Academic Graph | Papers, citations, authors, recommendations, worldwide |

Six repositories, six packages, six independent releases. This seventh repository holds nothing but the suite: a package whose dependencies are the six at pinned release tags, and a `bibliograph` command that registers them in Claude Desktop together, checks that the module they all vendor is byte-identical across the install, and verifies a receipts folder as one deposit.

## Install

### Getting Python

The Claude Desktop bundle needs no Python of your own. The other routes need Python 3.10 to 3.14
and its `venv` module, which the official installers include.

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

### The suite

```bash
python3 -m venv ~/bibliograph
~/bibliograph/bin/pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.4"
~/bibliograph/bin/bibliograph install
```

On Windows, `py -3 -m venv %USERPROFILE%\bibliograph`, then `%USERPROFILE%\bibliograph\Scripts\pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.4"` and `…\Scripts\bibliograph install`. Git must be on PATH: the suite's dependencies are the six repositories at their release tags, fetched by pip from GitHub. Nothing is on a package index; the tag is the thing to cite.

`bibliograph install` registers every server the interpreter can import, asks once for a receipts folder and a session slug, asks once for each credential a server needs (CiNii application ID; the others are optional), backs up `claude_desktop_config.json`, and writes the entries. Servers already registered under other names are left alone. Restart Claude Desktop afterwards.

Or `uvx --from "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.4" bibliograph install` for a throwaway environment; note that Claude Desktop will then be pointed at uv's cache, which uv may prune.

### One server

Each repository's README gives three routes for that server alone: a Claude Desktop `.mcpb` bundle from its GitHub release, `pip install "git+https://github.com/ckgerteis/<repo>@vX.Y.Z"`, and `python install.py` from a checkout. The six `install.py` files are byte-identical and are the same code this package ships as `bibliograph.installer`; `python install.py --all` from any checkout builds a fresh environment with all six, which is the route to take when the machine has no environment yet.

### Credentials

| Server | Variable | Needed? |
| --- | --- | --- |
| cinii | `CINII_APPID` | Required; free from https://api.ci.nii.ac.jp/en/ |
| korea_scholarship | `KCI_API_KEY` | Optional; four KCI REST tools need it, OAK does not |
| openalex | `OPENALEX_API_KEY` | Optional but recommended; keyless access is metered per IP per day |
| semantic_scholar | `SEMANTIC_SCHOLAR_API_KEY` | Optional but recommended; keyless calls share one throttled pool |
| jstage, ndl | — | None |

### Any other MCP client

Nothing in the six servers is specific to Claude: each is a Model Context Protocol server over
stdio, usable from Claude Code, Cursor, VS Code, Zed or any client that can start a process and
speak JSON-RPC to it. `bibliograph install` writes Claude Desktop's configuration file because that
is the client with no command line; for any other client, point it at the console scripts this
package installs (`cinii-mcp`, `jstage-mcp`, `ndl-mcp`, `korea-scholarship-mcp`, `openalex-mcp`,
`semantic-scholar-mcp`, in the environment's `bin/` or `Scripts\`) with `MCP_RECEIPT_DIR` and
`MCP_RECEIPT_SESSION` in the environment. Each server's own README shows the JSON and the
`claude mcp add` line.

## What the receipts are for

A search you cannot re-run is a claim you cannot check. When a footnote rests on a database
query, say that no article in this index uses a term before a certain year, the reader is asked to
take the search on trust: which term, in which script, on what date, against which index and which
version of it, and how far down the results the author went. Ordinary searching leaves none of
that behind. Each of these servers leaves all of it. Every
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
- **A method section that writes itself.** the server's `<name>-ledger` command `manifest <folder>` summarises every
  query a project made, by server, script and session: the disclosure a journal, a
  data-availability statement or a research-integrity review asks for.
- **A record of AI-mediated research.** When a model chose the term, the receipt shows the term
  it chose and what came back, which is the thing to disclose about work done with an assistant.
- **Nothing interpreted.** The receipt is the source's own answer with credentials removed. The
  server does not summarise, rank or paraphrase, so the record is of the source, not of the tool.

Receipts are off until you name a folder (`MCP_RECEIPT_DIR`); each server then writes its own
`<server>.jsonl` inside it, and `MCP_RECEIPT_SESSION` stamps a project or article slug on every
line so one folder can serve several projects. the server's `<name>-ledger` command `verify-dir <folder>` checks the chains.
The mechanics, the variables and what the envelope says when nothing is deposited are in the
receipts section below.

## The command

```
bibliograph status                 versions, registration, receipts folder and session per server
bibliograph doctor                 stdio handshake with each server; vendored-module identity check
bibliograph install [--servers a,b] [--receipts-dir DIR] [--session SLUG] [--no-receipts] [--dry-run]
bibliograph receipts verify-dir DIR
bibliograph receipts manifest DIR  writes DIR/manifest.json — the object a disclosure cites
```

`doctor` is the check to run before a session whose searches are meant to be citable evidence, and again before writing them up: it starts each server over stdio exactly as Claude Desktop does and reports the version each answers with, then asserts that `ledger.py` and `mediation.py` are byte-identical across everything installed, so two envelope versions cannot sit in one environment unnoticed.

## Receipts

Every server writes its own `<server>.jsonl` into the one folder `bibliograph install` registered (`MCP_RECEIPT_DIR`), each line hash-chained to the last. One writer per file is the design: appending is read-the-last-hash-then-write, and six servers are six processes, so a shared file forks. `bibliograph receipts verify-dir` walks the folder and reports, per file, whether the chain verifies and, if not, which kind of break it found — a **fork** (concurrent writers; a configuration fault), a **missing** line, a **reordering**, or **tamper** (a line that does not hash to its own content). Only the last is a claim about honesty. `manifest` writes one description of the whole deposit: per-file counts, first and last timestamps, terminal hashes, totals by server, script and session.

## Versioning

The suite has its own version and its own DOI. Its dependency pins name the release tag of each server; moving a pin is a suite release. A count produced under one pin set is not reproducible under another, so a disclosure should cite the suite version actually installed (`bibliograph status` prints it) or the six server versions individually.

## Tests

```bash
pip install "bibliograph-mcp[test] @ git+https://github.com/ckgerteis/bibliograph-mcp" && python -m pytest -q tests
```

The suite's own tests cover the CLI against a temporary Claude Desktop config; each server's tests live in its own repository and run in its own CI.

## License

MIT © 2026 Christopher Gerteis. Covers this package and the six servers' code only; the data each server returns remains governed by its provider's terms, and every envelope carries the attribution line that provider requires.

## Author

[Dr Christopher Gerteis](https://www.christophergerteis.net), SOAS University of London.
