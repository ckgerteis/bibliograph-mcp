# jmnedict-mcp

A local MCP server for Japanese research: finding scholars from fuzzy name
input, and looking up names, words, kanji, and radicals across the EDRDG
dictionaries and Wiktionary. **One server, one on-disk index, nine tools.**

Built on Jim Breen's EDRDG data — JMnedict, JMdict, KANJIDIC2, and
KRADFILE/RADKFILE, all from the `scriptin/jmdict-simplified` JSON distribution —
plus Wiktionary (via wiktextract / kaikki.org) for archaic and classical
coverage the modern dictionaries lack.

Design rationale lives in `jmnedict-mcp-scope.md` (one directory up). This README
covers what the server does, how it is built, and how it is installed.

---

## The nine tools

**Names and scholar-finding (JMnedict + live services)**

- `name_query_variants` — one name (English, kana, or kanji) → the full set of
  search strings a Japanese-database search needs: kanji variants (斎/斉/齋
  folded), kana, Hepburn-with-macron, Hepburn-plain, kunrei, and inferred
  surname/given order.
- `resolve_name_readings` — kanji name → candidate readings with name-type tags
  and all three romaji renderings.
- `resolve_name_kanji` — romaji or kana → candidate kanji writings (many-to-one).
- `infer_name_order` — two romaji tokens → surname / given assignment.
- `find_scholar` — a fuzzy name plus a soft disambiguator (subject area, approx.
  title, period) → ranked candidate *people* with evidence, discovered IDs
  (Researcher Number, NDLA, VIAF, DOI, KAKEN), and a match basis. Live parallel
  fan-out over J-Stage, CiNii articles, CiNii KAKEN projects, and Web NDL
  Authorities (no auth); the NRID researcher directory activates when
  `CINII_APPID` is set. The Researcher Number is an **output**, never an input.

**Dictionaries**

- `gloss_term` — JMdict gloss for a modern institutional/technical term: a
  citable, structured set of senses with part-of-speech and field/misc tags.
- `gloss_archaic` — Wiktionary gloss for archaic or classical terms, carrying
  etymology and archaic/classical/obsolete-tagged senses JMdict omits. Archaic
  senses surface first; every result carries a caveat to verify against the
  Nihon Kokugo Daijiten, since Wiktionary is crowd-sourced.

**Kanji**

- `kanji_info` — KANJIDIC2 facts for one kanji: stroke count, classical radical,
  on/kun/nanori readings, English meanings, grade/frequency/JLPT, the
  Spahn-Hadamitzky and SKIP index codes, and KRADFILE components. Authoritative
  structured data — prefer it over reciting kanji facts from memory.
- `kanji_by_radical` — kanji containing ALL given component shapes (RADKFILE
  multi-radical lookup). See "Radical forms" below.

---

## The data — one index, six tables

Everything lives in a single SQLite file in a permanent directory *outside the
code* (`JMNEDICT_DATA_DIR`, default `C:\Tools\jmnedict-data\names.sqlite`), with
raw downloads cached under `raw/` and a `manifest.json` recording each dataset's
source file and build time.

| Table | Source | Rows (2026-07) | Tool |
|---|---|---|---|
| `names` | JMnedict | 745,330 | name & scholar tools |
| `jmdict` | JMdict (eng) | 590,936 | `gloss_term` |
| `kanjidic` | KANJIDIC2 (en) | 10,384 | `kanji_info` |
| `krad` | KRADFILE | 12,156 | `kanji_by_radical`, `components_of` |
| `radk` | RADKFILE | 54,321 | `kanji_by_radical` |
| `wiktionary` | Wiktionary (kaikki) | 235,430 | `gloss_archaic` |

The first five come from one `scriptin/jmdict-simplified` release via a shared
caching downloader; Wiktionary is a separate ~358 MB kaikki JSONL.

---

## Where the data lives (permanent, outside the repo)

The datasets are large and regenerable, and the code lives in Dropbox, so the
index is kept out of the synced tree. The data directory resolves in order:

1. the `JMNEDICT_DATA_DIR` environment variable (set in the MCP config —
   `C:\Tools\jmnedict-data`);
2. otherwise a per-OS default (`%LOCALAPPDATA%\jmnedict-mcp` on Windows).

Raw downloads are cached under `raw/`, so rebuilding reuses them (pass `--force`
to pull a fresh release). The `.venv` and the Python caches are excluded from
Dropbox sync; the datasets never touch Dropbox at all.

## Layout

```
jmnedict-mcp/
  README.md  BUILD_NOTES.md  requirements.txt  conftest.py
  scripts/build_index.py        download/ingest all datasets -> SQLite
  src/jmnedict_mcp/
    server.py                   stdio MCP server (the nine tools)
    names.py  romaji.py         names core + deterministic romanisation
    scholar_finder.py services.py   Phase 2 live fan-out + reconcile/rank
    wiktionary.py               gloss_archaic (archaic/classical)
    refdata.py                  gloss_term, kanji_info, kanji_by_radical
    db.py  paths.py             SQLite layer + permanent-data-dir resolver
    subjects.json               bilingual subject-field table
  config/claude_mcp_config.snippet.json
  data/                         legacy fallback; real data is in JMNEDICT_DATA_DIR
  tests/                        romaji, names, wiktionary, refdata, reconcile,
                                paths, live_services (network-gated)
```

---

## Build

```
set JMNEDICT_DATA_DIR=C:\Tools\jmnedict-data      # permanent data home
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

python scripts/build_index.py                     # names (JMnedict), auto-download
python scripts/build_index.py --refdata           # JMdict + KANJIDIC2 + KRAD + RADK
python scripts/build_index.py --wiktionary raw\kaikki-japanese.jsonl   # archaic glosses
```

The kaikki Japanese JSONL (~358 MB) comes from
https://kaikki.org/dictionary/Japanese ; the other five datasets download
automatically from the jmdict-simplified release and are cached under `raw/`.
Each build touches only its own table, so they compose freely and rebuilding one
never disturbs the others.

Verify and smoke-test:

```
python -m pytest tests/ -q                # 40 passed, 5 skipped (skipped = live)
python -m jmnedict_mcp.server --selftest  # exercises tools on a throwaway demo DB
```

## Install

```
pip install "jmnedict-mcp @ git+https://github.com/ckgerteis/jmnedict-mcp@v0.2.0"
```

(or clone the tag and `pip install .`) once a `v0.2.0` release exists. This
installs the server and its console scripts (`jmnedict-mcp`,
`jmnedict-mcp-ledger`) but **no dictionary data** — the package is code only.
Build your own index before the first run:

```
set JMNEDICT_DATA_DIR=C:\Tools\jmnedict-data
python scripts/build_index.py                     # names (JMnedict)
python scripts/build_index.py --refdata            # JMdict + KANJIDIC2 + KRAD + RADK
python scripts/build_index.py --wiktionary raw\kaikki-japanese.jsonl   # optional, archaic glosses
```

`scripts/build_index.py` is not installed as a console script — run it from a
checkout, or copy it — since it is a one-time setup step, not part of the
running server. See "Build" above for the fuller version of these steps.

Environment variables the server reads at startup:

- `JMNEDICT_DATA_DIR` — where the built index lives (see "Where the data
  lives" above). Required in practice; without it the server falls back to a
  per-OS default and most tools answer `INDEX_MISSING`.
- `CINII_APPID` — your registered CiNii/NRID application id. Enables the NRID
  researcher-directory step in `find_scholar` (Researcher Numbers); every
  other live service runs without it. Without it, NRID rate-limits to HTTP
  403 and `find_scholar` skips it cleanly (see `service_errors`).
- `MCP_RECEIPT_DIR` (or the legacy `MCP_RECEIPT_LOG`) — a folder to deposit an
  append-only, hash-chained receipt for every query-answering tool call. Unset
  by default; see "Response format" below for the diagnostic codes this
  produces.
- `MCP_RECEIPT_SESSION` — an optional session id recorded in each receipt, so
  receipts from one conversation or run can be grouped and verified together.

## Register with Claude Desktop

Add the entry from `config/claude_mcp_config.snippet.json` to your Claude
desktop config `mcpServers` block (fixing the absolute paths), then **restart
Claude to activate**. The env block carries `PYTHONPATH`, `JMNEDICT_DATA_DIR`,
and — for the NRID researcher directory in `find_scholar` — `CINII_APPID`. NRID
rate-limits to HTTP 403 without a registered application id, so set your appid
there; every other service runs without auth.

## Response format

Every tool answers in the family's typed JSON envelope (`envelope.py`,
shared with the other bibliographic MCP servers in this family): the query as
given, a matching mode, typed diagnostics, an attribution line, and — when
`MCP_RECEIPT_DIR` or `MCP_RECEIPT_LOG` is set — a deposited receipt hash.

- **A dictionary tool's answer is `items[0].extra`.** `name_query_variants`,
  `resolve_name_readings`, `resolve_name_kanji`, `infer_name_order`,
  `gloss_term`, `gloss_archaic`, `kanji_info` and `kanji_by_radical` each
  return exactly one item; everything the tool used to return as a bare dict
  is unchanged, one level down, in `extra`.
- **`find_scholar`'s candidates are `items[].extra`, one item per person**
  (`record_type: "person"`), with `plan` and `service_errors` kept at the
  envelope's top level — not nested under an item — so the searched name
  forms and any live-service failures stay visible without digging into a
  candidate.
- **Diagnostics** (`diagnostics[].code`): `OK` (the tool answered), `NOTE` (a
  caveat attached to the answer — a lead, not a fact), `ZERO_RESULTS` (no
  entry for the term; for `gloss_term` this is a soft signal, not proof the
  term does not exist), `INDEX_MISSING` (the local SQLite index is not
  built — run `scripts/build_index.py`), and `SERVICE_ERROR` (one live
  service in `find_scholar` did not answer; the other candidates' ranking
  still holds), and `SERVER_ERROR` (the tool failed inside bibliograph; the
  message quotes the exception — a fault to report, not an absence of data).
- **Receipt diagnostics**, from the shared ledger module: `RECEIPT_NOT_DEPOSITED`
  (neither `MCP_RECEIPT_DIR` nor `MCP_RECEIPT_LOG` is set, so nothing was
  written) and `RECEIPT_WRITE_FAILED` (the folder was set but the write
  failed — check it is writable and has space).

## Radical forms (KRAD / RADK)

KRADFILE and RADKFILE use their own representative characters for radicals, not
the Unicode radical glyphs: water is `汁` (not `氵`), grass is `艾`, and so on.
`kanji_by_radical` lists any unrecognised input under `unknown_components`, and
`components_of(kanji)` returns the exact forms to feed back in.

## Licence / attribution

JMnedict, JMdict, KANJIDIC2, and KRAD/RADKFILE are property of the Electronic
Dictionary Research and Development Group (EDRDG), used under CC BY-SA. Wiktionary
data is CC BY-SA via wiktextract (cite Ylonen, LREC 2022). The derived SQLite
index carries the same attribution; do not redistribute it without.

- EDRDG: https://www.edrdg.org/  ·  JSON: https://github.com/scriptin/jmdict-simplified
- Wiktionary data: https://kaikki.org/  ·  https://github.com/tatuylonen/wiktextract
