# Changelog

Versions are the thing to cite. A count produced under one release is not
reproducible against another, so the release actually used should be named in
the text and, where a version DOI exists, cited by it.

Releases earlier than those below are on the repository's releases page; this
file begins where the record is precise enough to be worth writing down.

## 1.5.2 — 2026-10-30

Ports the public ndl-mcp 1.2.3 stress-test repairs (12 Oct 2026), adapted to bibliograph's declared set and identifiers in `extra`.

- **A 200 that is not an SRU response (no `numberOfRecords`) is `API_ERROR`**, not `ZERO_CONJUNCTION`.
- **`ndl_get_record` returns a record only when its `extra.ndl_bib_id` or `extra.jpno` equals the identifier given**; otherwise `ZERO_CONJUNCTION` names what NDL returned and shows none of it. Identifiers must be 1–32 letters, digits or hyphens. The query was already confined to bibliograph's declared set; a test now pins that.
- **No more than `maximumRecords` records are shown**; `total` still reports NDL's count.
- **`Retry-After`** is honoured only when finite and non-negative, capped at 30 s; `nan`, `inf` or negative values fall back to the 10 s back-off (`nan` had hung every later call).

## 1.5.1 — 2026-10-09

Released in bibliograph 1.4.1.

- **The coverage note miscounted the declared set.** Under 1.5.0 every
  response said the server queried "the eleven NDL-created sets it declares";
  it declared twelve. Corrected, with the module docstring and the README,
  and a test now ties the note's count to the table. No change to what is
  searched or to any count.

## 1.5.0 — 2026-10-09

Released in bibliograph 1.4.0.

- **`ndl_search_books` now searches 蔵書（巻号以外） by default, so its counts
  are not comparable with those made under 1.4.0 and earlier.** Since January
  2024 蔵書 has carried a record for each issue of a serial, and a title search
  that matched a magazine's name returned them all: 婦人公論, 9 Oct 2026, 1,701
  records in 蔵書 against 91 in 蔵書（巻号以外）, of which 84 books and 7 serial
  title records. The serial's title-level record is kept. Set
  `exclude_serial_issues` false for the old behaviour.
- **`iss-ndl-opac-bib` declared; `ndl-article-online` stays out, now for a stated
  reason.** The NDL answered the question put in the 18 September filing.
  `iss-ndl-opac-bib` (蔵書（巻号以外）) is contained in `iss-ndl-opac` under the same
  terms (PDL1.0). It is left out of `ndl_search_all`, which already covers it. `ndl-article-online` may be used only for records
  tagged `ndl-dl-open`; tested the same day, the API cannot apply that
  restriction, so the set remains refused and the coverage note says why.

## 1.4.0 - 2026-10-07

Repairs of 7 October 2026, released in bibliograph 1.2.0. See bibliograph's CHANGELOG for the detail.

## 1.3.0 — 2026-09-18

**Six more NDL-created sets, declared to the library the same day, and a second
credit condition for the two that are not openly licensed.**

- **What changed in scope.** A supplementary notification filed with the NDL on
  18 September 2026 added `ndl-boj`, `warp`, `iss-ndl-opac-inprocess`,
  `issn-online`, `ndl-dl` and `ndl-dl-online` to the declared set, and corrected
  the national-bibliography dpid named in the August notification. Eleven sets are
  now reachable. `iss-ndl-opac-bib` and `ndl-article-online`, which the help text
  documents and the provider list omits, stay refused until the library answers
  the question the filing put to it.
- **New tools.** `ndl_search_digital` (the whole Digital Collections, with the
  viewer link and, where the record states it, the access condition),
  `ndl_search_warp` (WARP's catalogue of archived websites, with each site's start
  URL for warp-mcp), and `ndl_search_online_journals` (the ISSN register of
  Japanese online journals). `ndl_search_books` gains
  `japan_related_foreign_language_only` and `include_in_process`; the second adds
  a `PROVISIONAL_RECORDS` warning to every response that uses it, as the filing
  undertook.
- **Two credit conditions, kept apart.** `ndl-dl` and `ndl-dl-online` metadata
  carries no open licence. `provider_credit()` names those sets in a separate
  "Display only" clause instead of folding them into the PDL1.0 list. Because NDL
  Search clusters records and the representative can come from a set other than
  the one searched (seen live: a Digital Collections e-journal record answering a
  search of the ISSN register), each item now carries `extra.source_repository`,
  and a Digital Collections record found outside its own set brings the
  display-only clause and a `DISPLAY_ONLY_METADATA` diagnostic with it.
- **`ndl_get_record` now stays inside the declared set.** Until this release its
  query named no provider, so an identifier matched in another institution's
  records could have come back under an NDL credit line. It now carries the same
  dpid clauses as `ndl_search_all`.
- **Record types.** WARP records are typed `website` and ISSN-register records
  `serial`; `_record_type` now reads every `dcndl:materialType`, not only the first.
- **The gate.** `tests/test_declared_set.py` runs on fixtures captured live on
  18 September 2026, one request per new provider. The test for the out-of-set
  credit was mutation-checked: disabling the guard fails it.

## 1.2.2 — 2026-09-12

**The bundle's environment is built when it is installed, not during the first
connection.**

- **What was wrong.** 1.2.0 and 1.2.1 kept `pyproject.toml`, `uv.lock` and the
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
  extension server" for this bundle, jstage and cinii alike (reported
  7 September 2026). Read from the app's code, not inferred: the install
  step, its root-path check and its log line, and the launch step that runs
  the app's own uv with the manifest's arguments from the bundle folder.
- **What changed.** `pyproject.toml`, `uv.lock` and `main.py` are at the
  bundle root and the manifest launches `uv run --directory ${__dirname}
  --frozen main.py`. The install-time `uv sync` now runs; measured with the
  app's uv 0.9.7 on an empty cache, install took 3 s and the launch answered
  `initialize` in 2.4 s, against 1.8 s for the same launch warm. Where a host
  skips the install step the launch still builds the environment itself.
- **The gate that would have caught it.** `tests/bundle_handshake.py` now
  runs the install phase before the launch, fails a bundle whose
  `pyproject.toml` is not at the root, and fails a launch that takes longer
  than thirty seconds to answer. The 1.2.1 bundle fails it. The previous gate
  allowed 240 seconds and launched without the install phase, which is why
  1.2.0 and 1.2.1 passed CI and did not run on the machine that reported them.
- Observed in the app, not only reproduced: installed here under a test name,
  `main.log` shows `Setting up UV environment`, `Found system UV`,
  `Running uv sync` and `Setup completed successfully` six seconds later, then
  a launch that connected with all tools eight seconds after the launch line,
  and a live call answered. The same log's predecessor shows the 1.2.1 layout
  installed on 8 September as `ndl-runtime-test` with the app recording
  `missing pyproject.toml. Cannot proceed with UV setup`; the line was there
  and went unread.

## 1.2.1 — 2026-09-08

- **The bundle no longer pins Python 3.13.** 1.2.0 shipped a `.python-version`
  so that every user ran the interpreter the release gate had run; the cost
  was a 20 MB interpreter download on first launch even where a usable Python
  was already installed. The file is gone: uv now takes any interpreter on
  the machine that satisfies `requires-python` (3.10 or later) and downloads
  one only where there is none. The lock resolves for every version in that
  range, and the handshake gate runs the bundle under 3.10 and 3.12 as well
  as on a cold cache before each release. Nothing in the server changed.

## 1.2.0 — 2026-09-08

**The Claude Desktop bundle runs again, on every supported interpreter.**

- **What was wrong.** Every `.mcpb` published so far imported under CPython
  3.12 and nothing else. `mcpb/build.py` vendored the dependencies with
  `pip install --target` under the interpreter running the build, the release
  workflow pinned that interpreter to 3.12, and `pydantic-core`, `rpds-py` and
  `cffi` ship native wheels tagged for one interpreter. The manifest meanwhile
  declared `runtimes.python >= 3.10` and launched bare `python` from the
  user's PATH, so Claude Desktop picked whatever satisfied the range, the
  import failed at module scope, and the user saw "Server disconnected".
  Measured, not inferred: the published bundles carry `cp312` binaries, and
  the openalex bundle answered `initialize` under 3.12 alone. The author's
  own machine registers the servers from a venv and had never run a bundle.
- **What changed.** The manifest now declares `server.type: "uv"` (manifest
  0.4). Claude Desktop runs the bundle with uv, using a uv already on the
  PATH and otherwise the copy the app ships (`uv-runtime`, 0.9.7 at the time
  of writing), from `server/pyproject.toml`, `server/.python-version` (3.13)
  and `server/uv.lock`. Nothing compiled is in the bundle, so one bundle
  serves Windows, macOS and Linux and is about 100 KB instead of 10 to 17 MB.
  The first launch downloads Python 3.13 if the machine lacks it and the
  locked libraries, roughly 60 MB; measured at 26 s with a system 3.13 present
  and 46 s without, against Claude Desktop's 60 s request limit. A first
  launch that runs past the limit self-heals on restart, because uv caches
  what it fetched. Later launches take under a second.
- **How the route was chosen.** Claude Desktop's launcher (read from the
  app bundle) treats `server.type: "uv"` as a request for its own uv
  discovery, but resolves a python-type extension that merely names `uv` as
  its command by a plain PATH search. The working uv-based extension on the
  author's machine is of the second kind and runs only because a personal uv
  is installed; the declared type is what makes the route safe for others.
- **`main.py` says what is wrong.** The import is guarded: on `ImportError`
  the entry point writes one line naming the running interpreter, its path
  and the supported range to stderr before re-raising, so the log carries a
  diagnosis rather than a traceback alone.
- **A blank field in Claude Desktop's install dialog no longer becomes a
  folder or a credential.** Found by installing this bundle into Claude
  Desktop 1.46 with both fields left blank: the app substitutes
  `${user_config.KEY}` only for fields that have a value and passes the
  placeholder verbatim otherwise (its own launcher code confirms it), so the
  ledger wrote `ndl.jsonl` into a folder named `${user_config.receipts_dir}`
  beside the bundle and stamped `${user_config.receipt_session}` on the
  line. Every earlier bundle in the family had the same exposure, and for
  the servers with an optional key it would have sent the placeholder to the
  provider as the key. The entry point now drops any variable whose value
  still carries a placeholder, as well as blank receipt variables, before
  the package imports. `tests/bundle_handshake.py` passes the manifest's
  env block verbatim, as the host does, imports the entry point with a
  placeholder credential added, and fails if any placeholder survives.
- **A gate that would have caught this.** `tests/bundle_handshake.py`
  (vendored across the family) unpacks the built bundle, runs it exactly as
  the host would, and requires the `initialize` reply to name the manifest's
  version, on a cold cache and under interpreters other than the bundle's
  pin. The release workflow runs it on all three operating systems before
  anything is attached to a release; `npx @anthropic-ai/mcpb validate` stays,
  but it checks the manifest, not whether the server runs.
- **CI matrix: 3.10, 3.12, 3.13 and 3.14.** 3.12 was the version the old
  bundles shipped and was never tested; 3.14 was reported to fail at
  `import mcp` with `TypeError: _eval_type() got an unexpected keyword
  argument 'prefer_fwd_module'`. Re-tested before this release: that error is
  pydantic ≥ 2.12.4 meeting a 3.14 interpreter built before the keyword
  landed (pydantic/pydantic#12544, #12597), and `import mcp` plus this
  server's full handshake are clean under 3.14.2, 3.14.3 and 3.14.7 with
  pydantic 2.13.5. `requires-python` therefore stays `>=3.10` rather than
  being capped below 3.14, and 3.14 is in the matrix so that the claim is
  re-checked on every push. Pre-release 3.14 builds are not supported.
- **The installers ask where to install, and never guess.** `install.py` and
  `install.ps1` chose the virtual environment silently (a `mcp-servers`
  folder beside Claude Desktop's configuration) and, run without a terminal,
  fell back to defaults for the receipts folder as well. Both now ask for the
  install location, the receipts folder and the session slug, offering a
  neutral suggestion that Enter accepts, and run without a terminal they stop
  before touching anything unless `--venv` and `--receipts-dir` (or
  `--no-receipts`; `-VenvDir`, `-ReceiptsDir`, `-NoReceipts` for PowerShell)
  say so. `--dry-run` and `--print-config` show the suggestions and touch
  nothing. The author's own project slugs, which had served as examples in
  the installer help and the bundle's `user_config` description, are
  replaced with neutral ones; no path or name of the author's is in either
  script.
- **A complete public repository.** `CONTRIBUTING.md` (set-up, the checks,
  the vendored-file rule, what a pull request carries), `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1), `SECURITY.md` (what counts as a security report
  for a credential-holding stdio server, and the private route), issue forms
  that ask for the install route, the interpreter and the log tail, a pull
  request template, and Dependabot for the workflow actions and the Python
  dependencies. Repository topics and homepage set on GitHub.
- **The README says what the receipts are for.** A section after the opening
  explains, for a researcher rather than a maintainer, why a hash-chained
  record of every query matters: a citable search, negative findings that
  carry weight, a method section the manifest writes, a record of what an
  assistant actually asked, and nothing interpreted. The mechanics stay in
  the receipts section below it.
- **The README says where to get Python.** A "Getting Python" subsection at
  the head of Install: python.org on Windows with the PATH tick and the
  Microsoft Store stub explained, python.org or Homebrew on macOS, the
  distribution package on Linux, or uv on any of them.
- **Nothing here is specific to Claude, and the README now says so.** The
  server is a Model Context Protocol server over stdio; the bundle and the
  installers are conveniences for one client. A new "Any other MCP client"
  section gives the JSON any client takes and the `claude mcp add` line for
  Claude Code, with the receipts variables as optional environment.
- **The DOI is in the repository.** The Zenodo concept DOI
  (10.5281/zenodo.22306174) is a badge under the README title and an
  identifier in `CITATION.cff`; neither carried it before, although every
  release since 1.1.0 has been archived.
- `tests/smoke_stdio.py` finds the console script through `sysconfig` and
  with its `.exe` suffix on Windows, so it no longer depends on the scripts
  directory being on PATH. Vendored across the family.
- `install.ps1` gains `-ConfigPath`, as `install.py` already had, so an
  install can target another client's file or be tested without touching
  the live one; and it writes the configuration file as UTF-8 without a
  byte-order mark. Windows PowerShell's `-Encoding utf8` adds one, which a
  strict JSON reader refuses.
- README: how to read a "Server disconnected" log, where the log lives on
  each platform, and how an `ImportError` differs from a missing interpreter.
  Pins moved to v1.2.0; the suite pin was `bibliograph-mcp@v1.0.0` and is
  now v1.0.1.
- Workflow actions moved to their current majors (checkout v7, setup-python
  v7, setup-node v7, upload-artifact v7, download-artifact v8, setup-uv v10),
  which also ends the Node 20 deprecation annotations on every run. setup-uv publishes no moving major tag past v7, so it is pinned exactly.

## 1.1.3 — 2026-09-04

- The MCP SDK's per-request INFO lines ("Processing request of type
  ListToolsRequest") no longer reach stderr. Noise rather than a leak — no
  term or credential is in them — but the stream Claude Desktop captures
  should carry faults only, as it does for the rest of the family.

## 1.1.2 — 2026-09-04

- **Periodicals-index records come back as articles, with their periodical.**
  NDL states the material type only in the attributes of an empty element
  (`<dcndl:materialType rdf:resource=".../ndltype/Article" rdfs:label="記事・論文"/>`),
  names the host periodical as `dcndl:publicationName`, the issue as
  `dcndl:issue` and the pages as `dcndl:pageRange`. The parser read element
  text and the book-record field names, so every 雑誌記事索引 record was typed
  `book` and returned with no journal, issue or pages — a bibliographic
  citation could not be built from it. Found on 2026-09-04 by reading a live
  answer against the claim that this server reaches the article index; the
  claim was true and the record was useless. Both layouts are now read, and
  `tests/test_parse.py` checks each against a response captured from NDL.
- CI runs `pytest` as well as the stdio smoke test.
- The 1.1.1 introduction said a *lowercase* `and` or `or` is refused by NDL.
  The library's check is case-insensitive, as the README and the code have said
  since 27 August; the introduction below is corrected.

## 1.1.1 — 2026-09-04

No change to the code. This release exists so that the archived record carries
an introduction to the tool rather than a list of patches, and so that the
archive holds a release published after archiving was switched on.

### What ndl-mcp is

ndl-mcp connects an AI assistant such as Claude Desktop to NDL Search
(国立国会図書館サーチ), the public catalog of the National Diet Library of Japan.
It is an MCP server: a small program that runs on your own computer, which the
assistant calls when it wants to search the library. The program sends the query
to NDL over the library's SRU interface, exactly as a browser would, and hands
the records back for the assistant to read. There is no account and no key. The
NDL search APIs are open, and the library has confirmed that registration of
continuous use is welcome but no longer required.

Six tools reach five of the library's own catalogs: the general holdings
(`ndl_search_books`), the Japanese National Bibliography
(`ndl_search_national_bibliography`), the 雑誌記事索引 periodicals index in both
its print and online-materials sets (`ndl_search_articles`), the open-data
digital collections (`ndl_search_digital_open`), all five at once
(`ndl_search_all`), and a single record by JP number or NDL bibliographic ID
(`ndl_get_record`). The national bibliography is the place to check an imprint
fact — a date, a publisher, an edition statement — because it is the authority
other catalogs copy from. The periodicals index reaches article-level records
for Japanese magazines and journals going back well beyond what CiNii or J-STAGE
hold, which is where prewar and early postwar material becomes searchable.

The server was built to the undertakings filed with the library when continuous
use was notified on 19 August 2026, and the code enforces them rather than
recommending them: requests go out one at a time with at least one second
between them; each search is capped at 100 records with no automatic paging; the
harvesting interface is not implemented; only the five declared, openly licensed
data providers are reachable, and a request naming any other is refused before
it is sent; every response carries the library's credit; nothing is cached. It
also knows what the library itself rejects. A bare `and` or `or` between words,
in any case, makes NDL refuse the whole query, so those are caught in the server, with a
diagnostic, before they fail silently at the other end.

### Why every answer comes with a record

An assistant can turn an English question into several Japanese renderings, try
each against the catalog, and read hundreds of records in minutes. What it
cannot do on its own is tell you afterwards which rendering it actually sent,
whether a result of zero meant an empty literature or a term the catalog does
not index, or whether the library answered at all. So every response from this
server carries a structured record written by the program, not the model: the
term actually sent and its script (kanji, kana, romaji), how the catalog matched
it, how many records exist, and typed diagnostics that keep a failed connection
distinct from an empty result. Optionally, each query is also appended to a
tamper-evident ledger on your own machine, one file per server, so that a search
standing behind a footnote can be named, cited by version, verified, and rerun
by someone else.

### Installing

Each GitHub release carries a Claude Desktop bundle (`.mcpb`) for Windows, Apple
Silicon Macs, and Linux; download it, open it, and Claude Desktop asks only for a
folder to keep the search log in. The bundle needs a Python 3.10 or later
installation on the machine. From a command line, `pip install
"git+https://github.com/ckgerteis/ndl-mcp@v1.1.3"` installs the server pinned
to the current release, and the README explains how to register it by hand. Nothing is
on a package index; the release version is the thing to cite in a methods note.

ndl-mcp is one of three companions for Japanese sources, with
[cinii-mcp](https://github.com/ckgerteis/cinii-mcp) for CiNii Research and
[jstage-mcp](https://github.com/ckgerteis/jstage-mcp) for J-STAGE, and one of six
in the [bibliograph](https://github.com/ckgerteis/bibliograph-mcp) suite. All
share one response format and one ledger, so results from different catalogs can
be read side by side and verified as one deposit.

### Changed in 1.1.1

- Version metadata only: `pyproject.toml`, the MCPB manifest, `__version__`,
  `CITATION.cff`, `.zenodo.json`, and the pinned install lines in the README.
- The 1.1.0 entry below no longer describes itself as unreleased; it was tagged
  and released on 2026-09-04.

## 1.1.0 — 2026-09-04

Tagged and released on GitHub on 2026-09-04 (the version was first written on
2026-08-23 and held until the release pipeline existed).

### Added on 2026-09-04, released with the tag

- **Released on GitHub as a package.** `.github/workflows/release.yml` runs
  on a `vX.Y.Z` tag: tests on three OSes, wheel and sdist, one Claude
  Desktop `.mcpb` bundle per platform, then a GitHub release carrying all of
  them. Installable pinned to the tag with `pip install
  "git+https://github.com/ckgerteis/ndl-mcp@vX.Y.Z"` or `uvx --from`
  the same URL. The release is what fires the Zenodo webhook. Nothing is
  published to a package index.
- **Suite install.** `install.py` is the cross-platform port of `install.ps1`
  (Windows, macOS, Linux; same behaviour, importable). The family is also
  installable as one package, `bibliograph-mcp`, whose `bibliograph install`
  registers all six with one receipts folder.
- **A malformed answer is `API_ERROR`, not `TRANSPORT_ERROR`.** `_error_diag`
  labelled every exception that was neither an HTTP status nor an XML parse
  failure as a transport failure — including a `numberOfRecords` that would
  not parse as an integer, raised after NDL had answered. The reader was told
  the service was unreachable when it had in fact replied. Only `httpx`
  transport exceptions are `TRANSPORT_ERROR` now; anything else raised after
  a response is `API_ERROR` with the exception type named.
- `tests/smoke_stdio.py`: stdio handshake, `tools/list` checked against the
  README table, optional live call. Vendored byte-identical across the six.
- `response-schema.json`'s self-description said 2.2.0 and named four
  servers; it now says 2.3.0 and names six. Text only; the schema is unchanged.
- Module docstring banner corrected from v1.0.1 to v1.1.0.

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
  path.** `server.py`, `mediation.py` and `ledger.py` move to `src/ndl_mcp/` and install as a
  package. The flat layout installed them as *top-level* modules, so any two
  servers of this family in one environment overwrote each other — and
  `pip check` reported nothing wrong. The later install simply won, silently,
  and the survivor answered under the wrong server's name. All six now coexist:
  verified by installing every wheel into one environment and driving each
  through `initialize` and `tools/list`.
- **Claude Desktop entries must change.** Replace
  `"command": "…\\python.exe", "args": ["…\\server.py"]` with
  `"command": "…\\Scripts\\ndl-mcp.exe"`. An existing entry keeps working
  against an existing flat deployment and will fail against this one.
- `python -m ndl_mcp` and a `ndl-mcp-ledger` console script are installed
  alongside it.
- **The server reports its build.** `initialize` was answered with an empty
  `serverInfo.version`. It now carries `__version__` where the SDK accepts one
  (mcp 2.x `MCPServer`). Under mcp 1.x, whose `FastMCP` takes no `version`, the
  field still reports the SDK's version rather than the server's — the argument
  is passed only where it is accepted.
- **Two of the six tools had never worked.** `build_cql` expressed several
  providers as `(dpid="a" OR dpid="b") AND field="x"`. NDL rejects that outright
  — SRU diagnostic `info:srw/diagnostic/1/1`, "illegal query syntax" — so
  `ndl_search_articles`, which spans the two periodical indexes, and
  `ndl_search_all`, which spans all five providers, returned `API_ERROR` for
  every query ever put to them. The four single-provider paths were unaffected,
  which is exactly why it survived: the server looked as though it worked.
  Found by running the tools against the live API on 23 August 2026.
- **"Record does not exist" is NDL's way of saying zero, not a fault**, and the
  passthrough that treats it so is now verified rather than merely read. Every
  provider answers that way for a term with no hits. The server reports
  `total: 0` with `ZERO_CONJUNCTION`, not `API_ERROR` — which is the distinction
  the envelope exists to preserve. `ndl_get_record` verified against a live
  identifier at the same time. Only the backoff path remains unexercised.
- **NDL's idiom is a repeated `dpid`, joined by AND, and it means union.** It
  reads backwards and it is what the interface accepts. Verified against the
  live API: `anywhere="労働運動" AND dpid="iss-ndl-opac"` returns 19,251,
  `dpid="zassaku"` alone returns 34,931, and the two together return 54,182 —
  the sum, so a union rather than an intersection, deduplicated where a record
  sits in more than one provider. `ndl_search_articles` now answers 34,931 for
  that term and `ndl_search_all` 82,644 for `title="戦後"`, where both
  previously answered nothing at all.
- **`install.ps1` is now the family installer** described above, replacing the
  NDL-only script. The NDL notification step survives inside it and runs whenever
  `ndl` is among the servers being installed. The old vendoring step, which
  copied `mediation.py` and `ledger.py` over this repository's copies from
  whatever was on the machine, is gone: each package now carries its own and the
  installer asserts they match across everything it installed rather than
  overwriting anything.
- **The installer no longer carries a receipt path of its own.** Until now it
  defaulted `MCP_RECEIPT_LOG` to a path inside the author's Dropbox folder —
  correct for one machine, wrong for every other, and a private folder layout
  published in a public repository. It also set `MCP_RECEIPT_SESSION` to
  `ndl-mcp`, where the rest of the family uses a project slug; the slug groups a
  project's queries, so NDL was filing itself out of the group it belongs to.
  Both are now asked for once and applied to every server installed.
- **README gained the install and Claude Desktop sections it never had.** The
  file documented the undertakings, the providers and the rate limit in detail
  and never said how to install the thing.
- **The installer no longer carries a receipt-log path of its own.** Until now
  it defaulted `MCP_RECEIPT_LOG` to a path inside the author's Dropbox folder —
  correct for one machine, wrong for every other, and a private folder layout
  published in a public repository. It now reads `MCP_RECEIPT_LOG` and
  `MCP_RECEIPT_SESSION` from the servers already registered in
  `claude_desktop_config.json`, which is the only way to be sure of joining the
  chain in use rather than a compiled-in guess at it. `MCP_RECEIPT_SESSION` was
  also being set to `ndl-mcp`, where the rest of the family uses a project slug;
  the slug is what groups a project's queries in the deposit, so NDL was
  labelling itself out of the group it belongs to.
- Order of preference: `-ReceiptLog` / `-ReceiptSession`, then the value the
  registered servers share, then whatever a previous run registered for `ndl`,
  then nothing. Disagreement between registered servers stops the install rather
  than resolving to one of them. Nothing found anywhere leaves the variables
  unset and says so, which matches the documented default: the ledger is off
  unless `MCP_RECEIPT_LOG` is set. All five paths were exercised against
  synthetic configurations.

## 1.0.1 — 2026-08-22

**Never tagged.** This version was merged to `main` and no release was cut for
it; it has no tag and no DOI.

- **Corrected the national-bibliography data provider ID.** The declared value
  `iss-ndl-opacnational` names no provider; the NDL spells it
  `iss-ndl-opac-national`. SRU matches an unrecognised `dpid` value against
  nothing and returns zero records with no diagnostic, so
  `ndl_search_national_bibliography` reported a well-formed, well-credited and
  entirely credible absence for every query put to it between 19 and 20 August
  2026. The same string appears in the 2026 registration; the set intended was
  always the national bibliography, as named, and only the identifier was wrong.
- **Licence.** Credit lines said CC BY 4.0. The grant is 公共データ利用規約
  （第1.0版）(PDL1.0), which the NDL states to be *compatible with* CC BY 4.0.
  Credit lines and README now say so.
- Docstring, `COVERAGE_NOTE` and README said four declared providers; the
  notification declared five, `ndl-dl-open` included.
- `ndl_search_digital_open` no longer claims `ndl-dl` and `ndl-dl-online`
  require a usage application. They are ○ for 非営利; they are out of scope
  because they were not notified and carry no open licence.
- `install.ps1` pointed `MCP_RECEIPT_LOG` at its own file rather than the shared
  log. A hash chain is per-file, so that would have created a second,
  independent chain. Now defaults to the shared log, with `-ReceiptLog` to
  override.
- **Registration with the NDL is now recommended rather than enforced.** The
  library confirmed in August 2026 that notification of continuous use is no
  longer required, though still welcome. `install.ps1` previously refused to
  register the server without a filing date; it now prints the form, offers to
  open it, records the date when given, and continues either way. The README
  makes the case for registering anyway: a national library that can see
  researchers using its API has an argument for keeping it open.
- `mediation.py` 2.3.0: the envelope reports whether it was deposited.
- httpx request-URL logging muted; a search term travels in that URL.
