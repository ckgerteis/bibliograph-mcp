# bibliograph-mcp

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22307233.svg)](https://doi.org/10.5281/zenodo.22307233)

bibliograph is one Model Context Protocol server for scholarly search, Japan
and Korea first. It gathers Japan-studies bibliographic and archival search: the National Diet Library's catalogue,
national bibliography, magazine index and Digital Collections (metadata and
OCR full text), the WARP web archive, CiNii Research (articles, books,
dissertations, KAKEN and researchers), J-STAGE, the JDCat humanities and
social-science data catalogue, OpenAlex, Semantic Scholar, Crossref, and Japanese name
and authority resolution; and, through korea-scholarship-mcp, the Korea Citation
Index (KCI) and Open Access Korea.

**New to this, and using Claude Desktop?** Start with
[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md): install from one file,
no command line. The rest of this README is the technical reference.

## One server since 2.0.0

Until 1.x, bibliograph-mcp was a suite: a package pinning six separate servers
(cinii-mcp, jstage-mcp, ndl-mcp, korea-scholarship-mcp, openalex-mcp,
semantic-scholar-mcp), each registered in Claude Desktop on its own. From 2.0.0
it is one server, `bibliograph-mcp`, that holds every source in one process,
including sources that never had a repository of their own: NDL Digital
Collections full text, the WARP web archive, JDCat, Crossref, Japanese name
resolution and open-access PDF fetching. korea-scholarship-mcp is a dependency
and is loaded by default. The six separate repositories stay published and
citable at their own releases, but they are no longer what this package installs.

Moving from 1.x: install 2.0.0, run `bibliograph install`, and remove the six
old entries (`cinii`, `jstage`, `ndl`, `korea_scholarship`, `openalex`,
`semantic_scholar`) from Claude Desktop's config, which the installer names but
does not delete. Tool names are unchanged.

### The family, by language

bibliograph is developed in the open from a Japan-studies core, alongside
area-studies servers for other languages:

| Name | Area | Status |
|---|---|---|
| 書誌 bibliograph | Japan studies | this repository |
| 서지 seoji | Korean studies | `korea-scholarship-mcp`, loaded here by default |
| 书志 shuzhi | Chinese studies | planned |

Each keeps its own sources and its own rate limits and credit lines, and
each answers in the same typed envelope so a client or a receipts folder
spanning several of them does not have to reconcile different shapes. See
`docs/CONTRACT.md` for what an outside package must honour to be loaded
with `--with`.

## Why this exists

> A search you cannot re-run is a claim your reader cannot check.

When a footnote rests on a database query — that no article in an index
uses a term before a certain year, that a name returns no researcher
record — the reader is normally asked to take the search on trust: which
term, in which script, on what date, against which index and which version
of it, how far down the results the author went. Ordinary searching leaves
none of that behind.

Every tool in bibliograph answers with the query as actually sent (term and
script), how the source matched it, typed diagnostics rather than prose
standing in for an error, and a receipt hash fixing the whole exchange.
With a receipts folder named (`MCP_RECEIPT_DIR`), that receipt is appended
to a per-source, hash-chained ledger file: a line cannot be altered,
removed or reordered afterwards without the verifier saying so. That gives:

- **A citable search.** Name the receipt in a footnote (session slug,
  source, date, line hash) and a reader can see exactly what was asked and
  run it again against the same release.
- **Negative findings that carry weight.** "Not found" is evidence only if
  the search that produced it is on record, with its term, script and
  breadth.
- **A method section drawn from the record.** `bibliograph-mcp-ledger manifest
  <folder>` summarises every query a project made, by source, script and
  session.
- **A record of AI-mediated research.** When an assistant chose the search
  term, the receipt shows the term it chose and what came back — the thing
  to disclose about work done with one.
- **Nothing interpreted.** The receipt is a source's own answer with
  credentials removed. bibliograph does not summarise, rank by relevance of its
  own, or invent; it reports what a source returned and how it matched.

## Sources

| Key | Provider | What it searches | Tools |
|---|---|---|---|
| `ndl` | National Diet Library, NDL Search | General holdings catalogue, the Japanese National Bibliography, the magazine/periodicals article index, the ISSN register of online journals, WARP's own catalogue of archived sites, and Digital Collections metadata | `ndl_search_books`, `ndl_search_national_bibliography`, `ndl_search_articles`, `ndl_search_online_journals`, `ndl_search_digital`, `ndl_search_digital_open`, `ndl_search_warp`, `ndl_search_all`, `ndl_get_record` |
| `ndl_dl` | NDL Digital Collections, via NDL Lab | OCR full text of the NDL's public-domain digitised holdings (次世代デジタルライブラリー), with located snippets and page images | `ndl_dl_fulltext_search`, `ndl_dl_book_fulltext`, `ndl_dl_page_image` |
| `warp` | NDL Web Archiving Project | Captures of Japanese government, public-corporation and national-university websites, by exact URL | `warp_list_captures`, `warp_nearest_capture`, `warp_read_capture` |
| `cinii` | National Institute of Informatics, CiNii Research | Japanese-language journal articles, books and monographs, doctoral dissertations, research data, KAKEN grant projects, and researcher profiles (with Researcher Numbers where available); NACSIS-CAT library holdings by NCID | `cinii_search_articles`, `cinii_search_books`, `cinii_search_dissertations`, `cinii_search_kaken`, `cinii_search_all`, `cinii_search_data`, `cinii_search_projects_and_products`, `cinii_search_researchers`, `cinii_get_record`, `cinii_get_holdings`, `cinii_search_libraries` |
| `jstage` | Japan Science and Technology Agency, J-STAGE | Full text of journals published by Japanese learned societies | `jstage_search_articles`, `jstage_get_article_by_doi`, `jstage_list_issues` |
| `jdcat` | JSPS and NII, JDCat 人文学・社会科学総合データカタログ | Metadata for humanities and social-science research data: Kobe's 新聞記事文庫 clippings, Hitotsubashi's imperial statistical-yearbook tables, SSJDA survey studies, 史料編纂所 materials and Nara mokkan, with facet counts by distributor, data type, topic, place and period | `jdcat_search`, `jdcat_get_record` |
| `openalex` | OurResearch, OpenAlex | The worldwide scholarly citation graph: works, authors, sources and institutions | `oa_search_works`, `oa_get_work`, `oa_search_authors`, `oa_get_author`, `oa_search_sources`, `oa_search_institutions`, `oa_cited_by`, `oa_author_works` |
| `semantic_scholar` | Allen Institute for AI, Semantic Scholar | The worldwide Academic Graph: papers, authors, citations and references, batch lookup, recommendations | `s2_search_papers`, `s2_get_paper`, `s2_batch_papers`, `s2_citations`, `s2_search_authors`, `s2_get_author`, `s2_author_papers`, `s2_recommend_single`, `s2_recommend_multi` |
| `crossref` | Crossref | Metadata publishers deposit when registering DOIs: mainly English-language journals and press books; free, no key. Search, DOI lookup, and matching a reference as written to candidate records | `cr_search_works`, `cr_get_work`, `cr_match_citation` |
| `names` | EDRDG (JMnedict/JMdict/KANJIDIC2), National Diet Library (Web NDL Authorities) | Japanese name and term resolution from a locally built index, plus catalogue-verified personal-name headings | `name_query_variants`, `resolve_name_readings`, `resolve_name_kanji`, `infer_name_order`, `gloss_term`, `gloss_archaic`, `kanji_by_radical`, `kanji_info`, `name_authority`, `names_index` |
| `fetch` | The open-access copy a source names, or an address you supply | Downloads one open-access PDF into a folder you name, with a provenance file and a receipt carrying the file's SHA-256, and reads its text layer by page; pages without one, and scans carrying someone else's OCR, are named for an OCR server | `fetch_pdf`, `fetch_pdf_text` |

Plus `bibliograph_status`, added automatically, which reports which sources
loaded, each with its own version and tool list, and any source that was
skipped with the reason.

The `names` source needs a locally built dictionary index — see
"Configuration" below and `src/bibliograph/sources/names/build_index.py --help`.
`ndl` and `ndl_dl` need a usage notification filed with the NDL — see
"Usage notices" below.

## Install

Pinned to a tag (recommended: a citable, reproducible install):

```
pip install "bibliograph-mcp @ git+https://github.com/ckgerteis/bibliograph-mcp@v2.0.0"
```

This installs the console scripts `bibliograph-mcp` (the server), `bibliograph`
(the installer), `bibliograph-mcp-ledger` and `bibliograph-build-names`. Then
`bibliograph install` registers the server in Claude Desktop, asking once for
each credential and for a receipts folder; `bibliograph doctor` starts it and
lists its tools. For the `names` source also install the `names`
extra: `pip install "bibliograph-mcp[names] @ git+...@v2.0.0"`.

Or, from a release's assets: the `.mcpb` bundle for Claude Desktop
(Extensions → Install from file), which builds its own environment with
`uv` at install time and needs no Python of your own.

### Claude Desktop config (pip install)

```json
{
  "mcpServers": {
    "bibliograph": {
      "command": "<venv>\\Scripts\\bibliograph-mcp.exe",
      "env": {
        "CINII_APPID": "<your NII appid>",
        "OPENALEX_API_KEY": "<free key; strongly recommended>",
        "SEMANTIC_SCHOLAR_API_KEY": "<optional>",
        "CROSSREF_MAILTO": "<you@example.org>",
        "JMNEDICT_DATA_DIR": "C:\\Tools\\jmnedict-data",
        "MCP_RECEIPT_DIR": "<receipts folder>",
        "MCP_RECEIPT_SESSION": "<project slug>",
        "BIBLIOGRAPH_DOWNLOAD_DIR": "<download folder>"
      }
    }
  }
}
```

Load a subset with `--only` in `args` (or `BIBLIOGRAPH_ONLY` in `env`) — e.g.
`"args": ["--only", "ndl,ndl_dl,cinii"]` for a Japan-studies session that
does not need the two worldwide indexes.

### Building the names index

The `names` tools read a dictionary index built on your own machine from
EDRDG data (see NOTICE). Nothing is bundled. Until it is built they answer
`INDEX_MISSING`.

**From Claude (no command line).** Ask Claude to check the names index. It
calls `names_index`, which reports where the index would be stored and what
it would download, and builds it in the background once you agree: about
25 MB downloaded, about 185 MB on disk, one to two minutes on a typical
connection (95 seconds when measured on 25 September 2026). Claude then
checks progress with the same tool.

**From a shell.**

```
set JMNEDICT_DATA_DIR=C:\Tools\jmnedict-data     (optional; see below)
bibliograph-build-names --all                          # names + JMdict + KANJIDIC2 + KRAD/RADK
bibliograph-build-names --wiktionary raw\kaikki-japanese.jsonl   # optional, archaic glosses
```

Without `JMNEDICT_DATA_DIR` the index goes to a per-user folder:
`%LOCALAPPDATA%\bibliograph-names` on Windows, `~/Library/Application
Support/bibliograph-names` on macOS, `~/.local/share/bibliograph-names` on Linux. An
index already built under the older `jmnedict-mcp` folder is found and used.
`gloss_archaic` needs the Wiktionary table, which only the shell route builds.

## Configuration

| Variable | Source(s) | Notes |
|---|---|---|
| `CINII_APPID` | `cinii` | Your own NII CiNii/NRID application id. Enables the researcher-number (NRID) step; every other CiNii Research call runs without it. |
| `OPENALEX_API_KEY` | `openalex` | Strongly recommended. Since 2026 OpenAlex meters use in dollars: a free key has its own $1 a day; without one, everyone on the same network address shares $0.10 a day. `bibliograph_status` reports the day's balance. |
| `OPENALEX_EMAIL` | `openalex`, `crossref` | OpenAlex no longer reads it (its polite pool was retired in February 2026). `crossref` uses it as its contact address when `CROSSREF_MAILTO` is unset. |
| `CROSSREF_MAILTO` | `crossref` | Optional but recommended: a contact address moves requests to Crossref's faster polite pool. |
| `CROSSREF_PLUS_TOKEN` | `crossref` | Optional Crossref Metadata Plus token (a paid service). |
| `SEMANTIC_SCHOLAR_API_KEY` | `semantic_scholar` | Optional but recommended; keyless calls share one throttled pool. |
| `JMNEDICT_DATA_DIR` | `names` | Where the locally built index lives. Optional: without it the index goes to the per-user `bibliograph-names` folder (see *Building the names index*). |
| `MCP_RECEIPT_DIR` | all | Folder to deposit an append-only, hash-chained receipt per source (`<dir>/<source>.jsonl`) for every query-answering tool call. |
| `MCP_RECEIPT_SESSION` | all | An optional session/project slug recorded in each receipt. |
| `MCP_RECEIPT_STRICT` | all | `1` makes a receipt write failure raise instead of passing silently. |
| `BIBLIOGRAPH_ONLY` | server | Comma-separated source keys to load instead of all of them (same as `--only`). |
| `BIBLIOGRAPH_DOWNLOAD_DIR` | `fetch` | Folder `fetch_pdf` saves PDFs to and `fetch_pdf_text` reads from. Unset, both refuse and nothing is written. |
| `BIBLIOGRAPH_WITH` | server | Comma-separated outside modules to also load (same as `--with`); see `docs/CONTRACT.md`. |
| `BIBLIOGRAPH_NOTICES_DIR` | `ndl`, `ndl_dl` | Where usage-notification marker files are looked for; see "Usage notices" below. |

## Usage notices

The NDL asks continuous users of its Search API to tell it who they are and
how they use the service (section 17 of the NDL Search API help, covering
`ndl`). That obligation falls on each user, not on this package, so bibliograph
cannot file it for anyone — but it will not hide whether a filing is on record.

A filing is recorded by placing a marker file, after you file it yourself,
holding the date and what you declared:

```
BIBLIOGRAPH_NOTICES_DIR\NDL-API-NOTIFICATION.txt
```

`BIBLIOGRAPH_NOTICES_DIR` defaults to `%APPDATA%\bibliograph\notices` on Windows or
`~/.config/bibliograph/notices` elsewhere; `BIBLIOGRAPH_NDL_NOTIFICATION_FILE` can name
the marker file directly instead. Until a marker exists, `ndl` responses carry
`NOTIFICATION_NOT_RECORDED`; the searches still run. The check touches only
`ndl`, so a missing marker never affects any other source.

NDL Lab's full-text service (`ndl_dl`) asks for no application for
non-commercial use (its ご利用に当たって section: 営利目的かつ継続的な利用を除き、
申請不要), so `ndl_dl` has no notice and no marker. Commercial, continuous use of
it should be raised with NDL Lab directly.

## WARP terms

WARP's own FAQ says it offers no API and no bulk download — browser
viewing is the expected way to use it — and asks users to refrain from
large-scale automated access, which the NDL may block. Its site policy
says archived content stays under its original publisher's copyright: reuse
needs that rights holder's permission, not WARP's or this server's.

`warp` is built to those terms: one URL at a time, requests serialised and
spaced at least three seconds apart, no tool that takes more than one URL,
nothing listed across many URLs, nothing harvested or stored beyond the
optional receipt line. Finding a site by subject is a separate, explicitly
licensed route through `ndl_search_warp` (NDL Search's own catalogue of
archived sites, covered by the `ndl` usage filing), not through `warp`
itself. See `docs/sources/warp/README.md` for the full terms and the
`warp` diagnostic-code registry.

## JDCat access

**Off by default in bibliograph.** The `jdcat` tools load only when you name
the source (`--only jdcat,...`) or set `BIBLIOGRAPH_ENABLE_JDCAT=1` (in the
Claude Desktop bundle: *Enable JDCat*). `bibliograph_status` lists it as
skipped otherwise, with the reason. The decision to send requests JDCat's
robots.txt asks automated agents not to send is the user's to make, not
this package's.

JDCat asks for no application and publishes its metadata under CC0, but its
robots.txt disallows `/api/` and `/oai` to automated agents. `jdcat` is
therefore built on the `warp` model: person-initiated queries only, serial
requests at least three seconds apart, at most 50 records a search, no
auto-pagination and no harvest tool, with the robots.txt position stated in
every envelope's coverage note. See `docs/sources/jdcat/README.md`.

## Response format

Every tool answers with one typed JSON envelope (`src/bibliograph/mediation.py`):
the query as given, `matching_mode`, graduated `result.breadth`, `items[]`
with per-item `matched_in`, typed `diagnostics[]`, a `receipt`, and an
`attribution` line naming the provider. Search tools also carry
`searched_for`, the term actually sent and its script.

- **`name_match`.** Where a result's identity with the name searched for is
  inferred rather than exact — a reading match, a fuzzy match — the item
  says so under `extra.name_match` instead of being silently dropped or
  silently treated as certain.
- **Diagnostic codes** are typed (`{level, code, message, hint}`), never
  free prose standing in for an error: `ZERO_RESULTS`, `NOT_FOUND`,
  `PARTIAL_NOT_FOUND`, `RATE_LIMITED`, `API_ERROR`, `TRANSPORT_ERROR`,
  `INDEX_MISSING` (names), `NOTIFICATION_NOT_RECORDED` (`ndl`/`ndl_dl`),
  `NRID_NOT_IN_SEARCH_RESULT` (cinii), and the `warp`-specific codes listed
  in `docs/sources/warp/README.md`, among others — see
  `tests/response-schema.json` for the full registry.
- **Receipts.** `RECEIPT_NOT_DEPOSITED` (no `MCP_RECEIPT_DIR` set) and
  `RECEIPT_WRITE_FAILED` (the folder was set but the write failed) report
  the deposit outcome inside the same envelope. Verify a chain with
  `bibliograph-mcp-ledger verify <file>`.

See `docs/sources/<source>/README.md` for each source's own field mapping
and diagnostic registry, and `tests/response-schema.json` for the shared
schema.

## Outside packages

`bibliograph-mcp --with PKG.MODULE` (or `BIBLIOGRAPH_WITH`) loads a server that ships
in a separate package into the same process. korea-scholarship-mcp is loaded
this way by default (set `BIBLIOGRAPH_NO_DEFAULT_WITH=1` to leave it out). An
outside package is loaded provided it
honours the contract in `docs/CONTRACT.md`: one MCP server object, a
declared `__version__`, tool names that do not collide with a built-in
source's prefix, the shared envelope and ledger versions, and typed
diagnostics.

## Citing

Cite the release actually used, by its version DOI once one is minted (see
`CITATION.cff`); the repository's concept DOI resolves to the latest
version. Name each loaded source's own version too — `bibliograph_status`
reports them, and a count is reproducible only against the release that
made it.

## Licence and NOTICE

Code: MIT (see `LICENSE`). bibliograph speaks to several providers under their
own terms and, for the `names` source, builds a local index from
third-party dictionary data it does not distribute — see `NOTICE` for the
licence of each source's data and services.
