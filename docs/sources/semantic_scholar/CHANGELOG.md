# Changelog

Versions are the thing to cite. A count produced under one release is not
reproducible against another, so the release actually used should be named in
the text and, where a version DOI exists, cited by it.

Releases earlier than those below are on the repository's releases page; this
file begins where the record is precise enough to be worth writing down.

## 2.1.4 — 2026-10-30

Ports the public semantic-scholar-mcp 2.2.0 stress-test repairs (12 Oct 2026).

- **A 200 whose body is not the expected shape is `API_ERROR`**, quoting Semantic Scholar; it was `ZERO_RESULTS`, or an empty record marked OK.
- **`RECORD_SHAPE_UNEXPECTED` names each skipped record by position and paperId**; a page of only unreadable records is not `ZERO_RESULTS`; in `s2_citations` a wrapper with no usable paper is counted rather than dropped silently.
- **Identifiers stay in their path segment** (percent-encoded; `.`/`..` and control characters refused). `../../author/1` had fetched an author as a paper.
- **The API key is redacted in raw and encoded forms before the 300-character cut**; queries are capped at 2,000 characters; an unformable URL is `TRANSPORT_ERROR`; a non-numeric, infinite, negative or fractional `total` is `TOTAL_NOT_REPORTED`.

## 2.1.3 - 2026-10-07

Repairs of 7 October 2026, released in bibliograph 1.2.0. See bibliograph's CHANGELOG for the detail.

## 2.1.2 — 2026-09-12

**The bundle's environment is built when it is installed, not during the first
connection.**

- **What was wrong.** 2.1.0 and 2.1.1 kept `pyproject.toml`, `uv.lock` and the
  entry point under `server/`. Claude Desktop's UV runtime looks for
  `pyproject.toml` at the bundle root when an extension is installed; finding
  it, it takes a uv already on the PATH or downloads its own (0.9.7 at the time
  of writing) and runs `uv sync` there behind a progress bar, so the interpreter and the libraries arrive before the server is ever
  launched. Not finding it, the app logs `missing pyproject.toml. Cannot
  proceed with UV setup`, installs the extension anyway, and the first
  connection attempt has to fetch uv, an interpreter and roughly 40 MB of
  libraries inside the launch timeout. That took 26 to 46 seconds on the
  author's connection against a limit of about sixty; on a Mac mini (M4,
  macOS 26.6.2) it never completed, and the app showed "Unable to connect to
  extension server" for the ndl, jstage and cinii bundles (reported
  7 September 2026); this bundle had the same layout and the same fault. Read from the app's code, not inferred: the install
  step, its root-path check and its log line, and the launch step that runs
  the app's own uv with the manifest's arguments from the bundle folder.
- **What changed.** `pyproject.toml`, `uv.lock` and `main.py` are at the
  bundle root and the manifest launches `uv run --directory ${__dirname}
  --frozen main.py`. The install-time `uv sync` now runs; measured on the
  ndl bundle with the app's uv 0.9.7 on an empty cache, install took 3 s and
  the launch answered `initialize` in 2.4 s, against 1.8 s for the same
  launch warm. Where a host skips the install step the launch still builds
  the environment itself.
- **The gate that would have caught it.** `tests/bundle_handshake.py` now
  runs the install phase before the launch, fails a bundle whose
  `pyproject.toml` is not at the root, and fails a launch that takes longer
  than thirty seconds to answer. The 2.1.1 bundle fails it. The previous gate
  allowed 240 seconds and launched without the install phase, which is why
  2.1.0 and 2.1.1 passed CI and did not run on the machine that reported them.
- Observed in the app, not only reproduced: the rebuilt ndl bundle installed
  on the author's machine under a test name, `main.log` shows `Setting up UV
  environment`, `Found system UV`, `Running uv sync` and `Setup completed
  successfully` six seconds later, then a launch that connected with all
  tools eight seconds after the launch line, and a live call answered. The
  same log's predecessor shows the 1.2.1 ndl layout installed on 8 September
  as `ndl-runtime-test` with the app recording `missing pyproject.toml. Cannot
  proceed with UV setup`; the line was there and went unread.

## 2.1.1 — 2026-09-08

- **The bundle no longer pins Python 3.13.** 2.1.0 shipped a `.python-version`
  so that every user ran the interpreter the release gate had run; the cost
  was a 20 MB interpreter download on first launch even where a usable Python
  was already installed. The file is gone: uv now takes any interpreter on
  the machine that satisfies `requires-python` (3.10 or later) and downloads
  one only where there is none. The lock resolves for every version in that
  range, and the handshake gate runs the bundle under 3.10 and 3.12 as well
  as on a cold cache before each release. Nothing in the server changed.

## 2.1.0 — 2026-09-08

**The Claude Desktop bundle runs again, on every supported interpreter.** The
same change as ndl-mcp 1.2.0, where it was proved before being copied here.

- **What was wrong.** Every `.mcpb` published so far imported under CPython
  3.12 and nothing else. `mcpb/build.py` vendored the dependencies with
  `pip install --target` under the interpreter running the build, the release
  workflow pinned that interpreter to 3.12, and `pydantic-core`, `rpds-py` and
  `cffi` ship native wheels tagged for one interpreter. The manifest meanwhile
  declared `runtimes.python >= 3.10` and launched bare `python` from the
  user's PATH, so Claude Desktop picked whatever satisfied the range, the
  import failed at module scope, and the user saw "Server disconnected".
- **What changed.** The manifest now declares `server.type: "uv"` (manifest
  0.4). Claude Desktop runs the bundle with uv, using a uv already on the
  PATH and otherwise the copy the app ships, from `server/pyproject.toml`,
  `server/.python-version` (3.13) and `server/uv.lock`. Nothing compiled is
  in the bundle, so one bundle serves Windows, macOS and Linux and is about
  100 KB instead of 10 to 17 MB. The first launch downloads Python 3.13 if the
  machine lacks it and the locked libraries, roughly 60 MB; measured on
  ndl-mcp at 26 s with a system 3.13 present and 46 s without, against Claude
  Desktop's 60 s request limit. A first launch that runs past the limit
  self-heals on restart, because uv caches what it fetched. Later launches
  take under a second.
- **`main.py` says what is wrong.** The import is guarded: on `ImportError`
  the entry point writes one line naming the running interpreter, its path
  and the supported range to stderr before re-raising. The `MCP_RECEIPT*`
  blank-stripping and every `user_config` field are unchanged.
- **A blank field in Claude Desktop's install dialog no longer becomes a
  folder or a credential.** Claude Desktop substitutes `${user_config.KEY}`
  only for fields that have a value and passes the placeholder verbatim
  otherwise, so a blank receipts folder became a folder named after the
  placeholder and a blank optional key would have been sent to the provider
  as the key. The entry point now drops any variable whose value still
  carries a placeholder before the package imports, and the handshake gate
  checks that it does.
- **A gate that would have caught this.** `tests/bundle_handshake.py`
  (vendored across the family) unpacks the built bundle, runs it exactly as
  the host would, and requires the `initialize` reply to name the manifest's
  version, on a cold cache and under interpreters other than the bundle's
  pin. The release workflow runs it on all three operating systems before
  anything is attached to a release.
- **CI matrix: 3.10, 3.12, 3.13 and 3.14.** 3.12 was the version the old
  bundles shipped and was never tested. The reported `import mcp` failure on
  3.14 (`TypeError: _eval_type() got an unexpected keyword argument
  'prefer_fwd_module'`) was re-tested: it is pydantic ≥ 2.12.4 meeting a 3.14
  interpreter built before the keyword landed (pydantic/pydantic#12544,
  #12597); 3.14.2, 3.14.3 and 3.14.7 are clean with pydantic 2.13.5.
  `requires-python` stays `>=3.10`; pre-release 3.14 builds are not
  supported.
- **The installers ask where to install, and never guess.** `install.py` and
  `install.ps1` chose the virtual environment silently and, run without a
  terminal, fell back to defaults for the receipts folder as well. Both now
  ask for the install location, the receipts folder and the session slug,
  offering a neutral suggestion that Enter accepts, and run without a
  terminal they stop before touching anything unless `--venv` and
  `--receipts-dir` (or `--no-receipts`; `-VenvDir`, `-ReceiptsDir`,
  `-NoReceipts` for PowerShell) say so. The author's own project slugs, which
  had served as examples in the installer help and the bundle's
  `user_config` description, are replaced with neutral ones.
- **A complete public repository.** `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1), `SECURITY.md`, issue forms that ask for the
  install route, the interpreter and the log tail, a pull request template,
  and Dependabot for the workflow actions and the Python dependencies.
  Repository topics and homepage set on GitHub.
- **The README says what the receipts are for.** A section after the opening
  explains, for a researcher rather than a maintainer, why a hash-chained
  record of every query matters: a citable search, negative findings that
  carry weight, a method section the manifest writes, a record of what an
  assistant actually asked, and nothing interpreted.
- **The README says where to get Python.** A "Getting Python" subsection at
  the head of Install: python.org on Windows with the PATH tick and the
  Microsoft Store stub explained, python.org or Homebrew on macOS, the
  distribution package on Linux, or uv on any of them.
- **Nothing here is specific to Claude, and the README now says so.** The
  server is a Model Context Protocol server over stdio; the bundle and the
  installers are conveniences for one client. A new "Any other MCP client"
  section gives the JSON any client takes and the `claude mcp add` line for
  Claude Code, with the receipts variables as optional environment.
- **The DOI is in the repository.** The Zenodo concept DOI is a badge under
  the README title and an identifier in `CITATION.cff`; neither carried it
  before, although every release has been archived.
- `tests/smoke_stdio.py` finds the console script through `sysconfig` and
  with its `.exe` suffix on Windows, so it no longer depends on the scripts
  directory being on PATH. Vendored across the family.
- `install.ps1` gains `-ConfigPath`, as `install.py` already had, and writes
  the configuration file as UTF-8 without a byte-order mark.
- README: how to read a "Server disconnected" log, where the log lives on
  each platform, and how an `ImportError` differs from a missing interpreter.
  Pins moved to v2.1.0.
- The `attribution` line in every envelope now carries the Semantic Scholar
  URL beside the Allen Institute's name, as the API licence asks; the
  README's licence section links the API License Agreement and gives the
  platform paper the licence asks published work to cite. Text only; the
  envelope schema is unchanged.
- `tests/test_server.py` drives coroutines with `asyncio.run`: since Python
  3.14 `get_event_loop()` no longer creates a loop in the main thread, and
  the suite failed on 3.14 for that reason alone. The server was unaffected.
- Workflow actions moved to their current majors; setup-uv is pinned exactly
  (v10.0.1) because it publishes no moving major tag past v7.

## 2.0.1 — 2026-09-05

No change to the server. The 2.0.0 tag was cut before this repository was
enabled on Zenodo, so that release was never archived and no DOI was minted
for it. This release exists to fire the Zenodo webhook. The code is identical
to 2.0.0 apart from the version strings and the pinned install lines below.

## 2.0.0 — 2026-09-04

**Breaking: every tool now returns the family's JSON response envelope.** 1.x
returned formatted markdown. Any consumer that parsed that text must be
rewritten; the input models and tool names are unchanged.

- **Released on GitHub as a package.** `.github/workflows/release.yml` runs
  on a `vX.Y.Z` tag: tests on three OSes, wheel and sdist, one Claude
  Desktop `.mcpb` bundle per platform, then a GitHub release carrying all of
  them. Installable pinned to the tag with `pip install
  "git+https://github.com/ckgerteis/semantic-scholar-mcp@vX.Y.Z"` or `uvx --from`
  the same URL. The release is what fires the Zenodo webhook. Nothing is
  published to a package index.
- **Suite install.** `install.py` is the cross-platform port of `install.ps1`
  (Windows, macOS, Linux; same behaviour, importable). The family is also
  installable as one package, `bibliograph-mcp`, whose `bibliograph install`
  registers all six with one receipts folder.
- **`mediation.py` and `response-schema.json` vendored**, byte-identical to the
  copies in cinii-mcp, jstage-mcp, ndl-mcp, korea-scholarship-mcp and
  openalex-mcp. The README's claim that the family shares one envelope is now
  true of this server. Every response carries `searched_for` on term
  searches, a typed `query`, `matching_mode`, graduated `result.breadth`,
  per-item `matched_in`, typed diagnostics, a receipt and the attribution line.
- **Receipts go through `emit()`.** The per-request `ledger.record_request`
  call is gone; the envelope itself is deposited, and it reports
  `RECEIPT_NOT_DEPOSITED` or `RECEIPT_WRITE_FAILED` when a deposit did not
  happen. The 1.1.0 gap — batch and multi-seed recommendation receipts not
  recording which identifiers were asked for — is closed: the IDs are in
  `query.params` and so under the receipt hash.
- **Matching modes named for what the API does.** `relevance_ranked` for
  search, `filter_exact` for citation and authorship traversals,
  `identifier_lookup` for fetches and batch, `similarity_ranked` for the
  recommender.
- **A returned count is never passed off as a corpus count.** Endpoints that
  report no total (citations, references, an author's papers, batch,
  recommendations) set `result.total` to the returned count and raise
  `TOTAL_NOT_REPORTED`, saying whether a further page exists.
- **Titles typed by script**, since the API reports no language: kana or
  Hangul decide `ja` or `ko`, Latin goes to `en`, han-only stays untyped in
  `extra.title`.
- **Typed diagnostics** replace `"Error: …"` strings: `ZERO_RESULTS`,
  `PARTIAL_NOT_FOUND`, `NOT_FOUND`, `RATE_LIMITED`, `API_ERROR`,
  `TRANSPORT_ERROR`. A 200 whose body is not JSON is `API_ERROR` rather than
  an uncaught exception.
- **The rate limiter is now atomic.** 1.x read the last-request time, slept,
  and wrote it back with nothing held across the three steps, so two
  concurrent tool calls could both pass the check and fire together. An
  `asyncio.Lock` now spans check, sleep and request.
- httpx request logging is silenced, as in the rest of the family: the key
  travels in a header, but the search term travels in the URL.
- **Tests.** `tests/test_server.py` runs against recorded responses and
  validates every envelope against the schema. No network, no key.
- Known limit: the receipt's `result_ids` reads DOIs only, so a paper without
  one is fixed by the receipt hash and `extra.s2_paper_id` but not listed.
  Extending `make_receipt` is a family-wide schema change and is deferred.

## 1.1.0 — 2026-08-23

**Not released.** No tag was cut and no Zenodo record exists for this version, so
it is citable by commit alone. Tagging waits on confirmation that this
repository's Zenodo webhook is live: a release that mints nothing spends a
version number and returns nothing citable for it.

- **A receipts folder, and one chain per server.** `ledger.py` 1.1.0 adds
  `MCP_RECEIPT_DIR`: point it at a directory and each server writes its own
  `<server>.jsonl` inside it. `MCP_RECEIPT_LOG` still names a single file and is
  honoured when `MCP_RECEIPT_DIR` is unset, so nothing existing breaks.
- **Why, precisely.** Appending is read-the-last-hash-then-write and `_LOCK` is a
  `threading.Lock`, which holds within one process and not between several. Six
  servers are six processes. Six of them writing 150 lines to one file produced
  **fourteen forks** — two lines claiming the same predecessor, over and over.
  That was measured, not inferred, and it means the family's shared log was never
  safe to verify as one chain. One writer per file removes the race rather than
  mitigating it.
- **`verify_chain()` now types its failures.** It reported everything as
  `prev_hash mismatch`. It distinguishes a **fork** (concurrent writers; every
  line still present, and the file is several chains rather than one), a
  **missing** line, a **reordering**, and **tamper** (a line that does not hash to
  its own content). Only the last is a claim about honesty, and a reader given one
  label for all four cannot tell a misconfiguration from interference.
- **`verify_dir()` and a manifest.** One pass over a receipts folder returns
  per-file verdicts, line counts, first and last timestamps and terminal hashes,
  plus combined totals by server, script and session. `<dist>-ledger manifest
  <dir>` writes it to `manifest.json`. That file is what a disclosure cites: one
  description of the deposit rather than six assertions to reconcile.
- `<dist>-ledger` gains `verify-dir` and `manifest`, and `verify` now exits
  non-zero when a chain does not verify.
- **`install.ps1` installs this server by default, not the family.** These are
  six independent packages — none imports another, none depends on another, and
  each installs alone. The installer defaulted to all six, so cloning one
  repository and running it would have registered five servers nobody asked for
  and fetched them from GitHub. It now resolves the default from the repository
  it sits in; `-All` opts into the family and `-Servers` names a subset.
- The verification step now **asserts that `ledger.py` and `mediation.py` are
  byte-identical across everything it installed** and stops if they are not.
  Nothing else enforces that invariant at install time, and two envelope
  versions in one environment is precisely the sort of thing that would be found
  later, in a deposit.
- **`install.ps1` installs the family.** Vendored byte-identical into all six
  repositories: it installs any or all of the six into one environment, asks once
  for the receipts folder and the session slug, and registers every server against
  the same pair. It prefers a sibling checkout to the network, carries across
  credentials already registered rather than asking again, and stops rather than
  guessing where the registered servers disagree about either value.
- **`src/` layout. Breaking: the server is started by console script, not by
  path.** `server.py` and `ledger.py` move to `src/semantic_scholar_mcp/` and install as a
  package. The flat layout installed them as *top-level* modules, so any two
  servers of this family in one environment overwrote each other — and
  `pip check` reported nothing wrong. The later install simply won, silently,
  and the survivor answered under the wrong server's name. All six now coexist:
  verified by installing every wheel into one environment and driving each
  through `initialize` and `tools/list`.
- **Claude Desktop entries must change.** Replace
  `"command": "…\\python.exe", "args": ["…\\server.py"]` with
  `"command": "…\\Scripts\\semantic-scholar-mcp.exe"`. An existing entry keeps working
  against an existing flat deployment and will fail against this one.
- `python -m semantic_scholar_mcp` and a `semantic-scholar-mcp-ledger` console script are installed
  alongside it.
- **The server reports its build.** `initialize` was answered with an empty
  `serverInfo.version`. It now carries `__version__` where the SDK accepts one
  (mcp 2.x `MCPServer`). Under mcp 1.x, whose `FastMCP` takes no `version`, the
  field still reports the SDK's version rather than the server's — the argument
  is passed only where it is accepted.
- The `[tool.hatch.build.targets.wheel]` comment claimed a `src` layout the
  repository did not have. It does now.

## 1.0.0 — 2026-08-22

**Never tagged.** This version was merged to `main` and no release was cut for
it; it has no tag and no DOI.

- MCP stdio server for the Semantic Scholar Academic Graph: papers, authors,
  citation traversal, batch lookup and recommendations, rate-limited to the
  1 RPS keyed allowance.
- Append-only, hash-chained query receipts via `ledger.py`, recorded from inside
  the HTTP helper. **Off unless `MCP_RECEIPT_LOG` is set**, and a logging
  failure is swallowed rather than raised.
- Runs on `mcp` 1.x and 2.x.

Two limits worth stating for anyone citing this as an instrument. It does not
vendor `mediation.py`, so its receipts carry no `searched_for` headline and no
typed envelope, and it has no equivalent of the `RECEIPT_NOT_DEPOSITED`
diagnostic the envelope servers gained in schema 2.3.0. And the batch and
recommendation tools send their payload as a JSON body rather than as query
parameters, so the receipt for those calls records the request without the list
of identifiers requested.
