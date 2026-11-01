# Changelog

Versions are the thing to cite. A result produced under one release is not
reproducible against another, so the release actually used should be named in
the text and, where a version DOI exists, cited by it.

## 0.2.1 - 2026-11-01

- **A tool that fails inside bibliograph says so.** Only a missing index was caught;
  any other exception reached the client as a bare "Error executing tool", which
  is why the 31 Oct thread fault could not be diagnosed from Claude's side. It
  is now an error-level `SERVER_ERROR` quoting the exception, kept distinct from
  `INDEX_MISSING` so the hint never sends anyone to rebuild a sound index.

## 0.2.0 - 2026-09-23

**First public packaging. Every tool now answers in the shared bibliographic-MCP
family envelope, and a day of driving every tool live against the full index
found and fixed eight defects in name matching and scholar-finding.**

- resolve_name_readings spaces a full-name listing at its surname boundary, found
  from the listing's own reading (成田龍一 -> narita ryūichi, not naritaryūichi),
  and reports the split. A bare surname is never cut (佐藤 stays satō).

- **Family envelope and receipt ledger adopted.** Every tool now returns the
  unified envelope (mediation 2.3.0) that the sibling servers (cinii, jstage,
  ndl, korea-scholarship, openalex, semantic-scholar) return: the query as
  given, typed diagnostics, a receipt hash, an attribution line, and deposit
  through `mediation.emit()`. A dictionary tool's answer is `items[0].extra`,
  unchanged; the people `find_scholar` finds are `items[].extra`, with `plan`
  and `service_errors` kept at the top level so the searched name forms stay
  visible. `ledger.py` is replaced by the family copy (1.1.0), which reads
  `MCP_RECEIPT_DIR` and still honours `MCP_RECEIPT_LOG`.
- **Romaji full names were never paired.** `name_query_variants` returned
  dozens of loose surname and given-name kanji, never the full name, so
  `find_scholar` searched on the first fragment and returned strangers. The
  bundle now carries ranked full-name writings, capped at 12, with the parts
  broken out separately and ranked by how often JMnedict's ~54k person
  entries use that writing as a surname or given name, not by character
  frequency alone.
- **Vowel length, name-type tags, and syllabic-n apostrophes.** Macron and
  wāpuro-style input (Satō / Sato / Satou) is folded to one key and ordered by
  reading fit; the real index's short tags (`masc`, `fem`, `unclass`) are now
  recognised; and the ~8,400 rows that store apostrophes in syllabic-n
  readings (`shin'ichi`) are matched via an indexed apostrophe-variant lookup.
- **Co-author false positives, NDL query shape, and the subject gate.**
  Candidates are no longer admitted on a single shared kanji; Web NDL
  Authorities queries are now built in NDLA's own "surname, given name" /
  "SEI, MEI" shape (the previous form 414'd on long joined names); and
  `find_scholar` now scores each candidate's evidence against the subject
  hint, ranking subject-matching candidates first and capping unmatched ones
  at `low` confidence.
- **Radical forms.** `kanji_by_radical` now maps RADKFILE's stand-in radical
  characters (water = 汁, not 氵; grass = 艾; and so on) instead of only the
  Unicode radical glyphs, and searches 阝 in both its forms.
- **Old/new character forms (J1).** Pure kyūjitai/shinjitai pairs (眞/真,
  國/国, 廣/広, ...) now fold into one representative for clustering and
  expand on lookup, without merging characters that are genuinely distinct
  name choices (龍/竜, 峯/峰, 冨/富).
- **A broad subject is not evidence by itself (J2).** 日本 and its common
  compounds, and "japan"/"japanese", no longer count as subject-matching
  evidence; when two or more candidates still tie on name and subject,
  `plan.notes` says so and asks for a title or period rather than guessing.
- **Non-Japanese names (J3).** Without kanji to check a byline against, a
  kanji creator is now rejected rather than accepted by default, and a
  full-name search uses spaced romaji rather than a lone surname token.
- **Listed names without a surname/given split, and non-Japanese-reading
  surnames (J4).** Where JMnedict lists a full name but not its internal
  boundary, the split is now inferred from the name's own reading; a short,
  deliberately narrow list of surnames that are overwhelmingly Korean or
  Chinese in Japanese academic publishing (姜, etc.) now adds a warning note
  without ever changing a result.
- **Retry policy (J6) and tool descriptions (J7).** `services._get` retries
  once, after a delay, on a dropped connection - never on a timeout or an
  HTTP error, since NDL throttles by stalling and must not be pressed. All
  nine tool descriptions were rewritten to describe the repaired behaviour
  and state each tool's key rule (always pass a subject to `find_scholar`;
  read `subject_match`; a `gloss_term` miss is a soft signal, not proof a
  term does not exist).
- Suite: 77 passed, 5 skipped (skipped tests require live network access or
  `CINII_APPID`).

## 0.1.0 - 2026-08-19

Initial build: Phase 1 names core (`name_query_variants`,
`resolve_name_readings`, `resolve_name_kanji`, `infer_name_order`) against a
JMnedict-only SQLite index, plus Phase 2 (`find_scholar`) wired to live,
no-auth fan-out over J-STAGE, CiNii articles, CiNii KAKEN projects and Web NDL
Authorities, with the NRID researcher directory gated on `CINII_APPID`. Added
JMdict, KANJIDIC2 and KRADFILE/RADKFILE tables and their tools (`gloss_term`,
`kanji_info`, `kanji_by_radical`), and Wiktionary-backed `gloss_archaic` for
archaic and classical senses the modern dictionaries omit. Deterministic
kana-to-romaji conversion (Hepburn macron, Hepburn plain, kunrei) in
`romaji.py`. Data kept permanently outside the Dropbox-synced repository via
`JMNEDICT_DATA_DIR`. 40 tests passed, 5 skipped (skipped = live).
