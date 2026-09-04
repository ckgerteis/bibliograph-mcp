# bibliograph-mcp

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

### The suite

```bash
python3 -m venv ~/bibliograph
~/bibliograph/bin/pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.0"
~/bibliograph/bin/bibliograph install
```

On Windows, `py -3 -m venv %USERPROFILE%\bibliograph`, then `%USERPROFILE%\bibliograph\Scripts\pip install "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.0"` and `…\Scripts\bibliograph install`. Git must be on PATH: the suite's dependencies are the six repositories at their release tags, fetched by pip from GitHub. Nothing is on a package index; the tag is the thing to cite.

`bibliograph install` registers every server the interpreter can import, asks once for a receipts folder and a session slug, asks once for each credential a server needs (CiNii application ID; the others are optional), backs up `claude_desktop_config.json`, and writes the entries. Servers already registered under other names are left alone. Restart Claude Desktop afterwards.

Or `uvx --from "git+https://github.com/ckgerteis/bibliograph-mcp@v1.0.0" bibliograph install` for a throwaway environment; note that Claude Desktop will then be pointed at uv's cache, which uv may prune.

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
