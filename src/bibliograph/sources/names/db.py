"""SQLite access layer for the JMnedict names index.

Schema (one row per kanji/kana writing pair of a name entry):

    names(
        entry_id   TEXT,    -- JMnedict id
        kanji      TEXT,    -- kanji writing (NULL for kana-only names)
        kana       TEXT,    -- kana reading
        name_types TEXT,    -- comma-joined type tags (surname, given, place, ...)
        gloss      TEXT,    -- romanised/English gloss from the source
        rom_hepburn TEXT,   -- Hepburn with macrons
        rom_plain   TEXT,   -- Hepburn, macron-stripped
        rom_kunrei  TEXT    -- Kunrei-shiki, diacritic-free
    )

Indexes on kanji, kana, rom_plain, rom_kunrei make both directions fast.

The schema is created by build_index.py (bibliograph-build-names); this module only reads.
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata

from . import paths

# The built index lives in the permanent data directory (see paths.py), not in
# the code repo, so reinstalling the code never disturbs it.
DEFAULT_DB = paths.db_path()

# Name-type tags JMnedict uses for *people* (as opposed to places, products, ...).
# JMnedict (jmdict-simplified) ships the short tags masc / fem / unclass; the
# demo fixture uses the long forms. Accept both, or given names go uncounted.
PERSON_TYPES = {
    "surname", "given", "masculine", "feminine", "person", "unclassified",
    "masc", "fem", "unclass",
}

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS names (
    entry_id    TEXT,
    kanji       TEXT,
    kana        TEXT,
    name_types  TEXT,
    gloss       TEXT,
    rom_hepburn TEXT,
    rom_plain   TEXT,
    rom_kunrei  TEXT
);
CREATE INDEX IF NOT EXISTS idx_kanji  ON names(kanji);
CREATE INDEX IF NOT EXISTS idx_kana   ON names(kana);
CREATE INDEX IF NOT EXISTS idx_plain  ON names(rom_plain);
CREATE INDEX IF NOT EXISTS idx_kunrei ON names(rom_kunrei);

CREATE TABLE IF NOT EXISTS wiktionary (
    word        TEXT,   -- headword (kanji or kana)
    reading     TEXT,   -- kana reading if recoverable, else NULL
    pos         TEXT,   -- part of speech
    sense_index INTEGER,
    gloss       TEXT,   -- English gloss for this sense
    tags        TEXT,   -- comma-joined sense tags (archaic, obsolete, ...)
    archaic     INTEGER,-- 1 if this sense carries an archaic-family tag
    etymology   TEXT    -- entry-level etymology text
);
CREATE INDEX IF NOT EXISTS idx_wk_word    ON wiktionary(word);
CREATE INDEX IF NOT EXISTS idx_wk_reading ON wiktionary(reading);

CREATE TABLE IF NOT EXISTS jmdict (
    seq         TEXT,
    form        TEXT,    -- a kanji or kana headword form
    sense_index INTEGER,
    common      INTEGER, -- 1 if this form is tagged common
    pos         TEXT,    -- comma-joined part-of-speech codes
    gloss       TEXT,    -- '; '-joined English glosses for this sense
    field       TEXT,    -- comma-joined field tags (math, ling, ...)
    misc        TEXT     -- comma-joined misc tags (arch, hon, ...)
);
CREATE INDEX IF NOT EXISTS idx_jm_form ON jmdict(form);

CREATE TABLE IF NOT EXISTS kanjidic (
    literal      TEXT PRIMARY KEY,
    stroke_count INTEGER,
    radical      INTEGER, -- classical radical number (1-214)
    grade        INTEGER,
    frequency    INTEGER, -- newspaper frequency rank (1=most)
    jlpt         INTEGER,
    on_readings  TEXT,    -- comma-joined
    kun_readings TEXT,    -- comma-joined
    nanori       TEXT,    -- comma-joined name readings
    meanings     TEXT,    -- '; '-joined English meanings
    sh_desc      TEXT,    -- Spahn-Hadamitzky descriptor
    skip         TEXT     -- SKIP code
);

CREATE TABLE IF NOT EXISTS krad (
    kanji      TEXT PRIMARY KEY,
    components TEXT        -- space-joined component shapes
);

CREATE TABLE IF NOT EXISTS radk (
    component    TEXT,
    stroke_count INTEGER,
    kanji        TEXT      -- one row per (component, kanji) membership
);
CREATE INDEX IF NOT EXISTS idx_radk_comp  ON radk(component);
CREATE INDEX IF NOT EXISTS idx_radk_kanji ON radk(kanji);
"""


def normalize_romaji(s: str) -> str:
    """Normalise a romaji query for matching against rom_plain / rom_kunrei.

    Lowercases, strips macrons to base vowels, drops apostrophes/hyphens/spaces,
    and collapses kept long vowels (satou -> sato, yuuki -> yuki) so wāpuro-style
    input matches the macron-stripped stored form.
    """
    s = unicodedata.normalize("NFD", s.strip().lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # drop combining marks
    for ch in ("'", "’", "-", " ", "."):
        s = s.replace(ch, "")
    # collapse kept long vowels
    out, i, n = [], 0, len(s)
    while i < n:
        two = s[i:i + 2]
        if two in ("ou", "oo", "uu"):
            out.append(s[i])
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def apostrophe_forms(norm: str, max_sites: int = 3) -> list[str]:
    """The stored romaji keeps the syllabic-n apostrophe (しんいち is stored
    as shin'ichi, ~8,400 rows), but normalize_romaji() strips apostrophes from
    the query, so "Shinichi" and "Shin'ichi" both missed. Generate the forms
    with an apostrophe at each n+vowel/y site (capped) so the indexed IN
    lookup still finds them."""
    sites = [i + 1 for i in range(len(norm) - 1)
             if norm[i] == "n" and norm[i + 1] in "aiueoy"][:max_sites]
    forms = [norm]
    for mask in range(1, 1 << len(sites)):
        out, last = [], 0
        for b, pos in enumerate(sites):
            if mask >> b & 1:
                out.append(norm[last:pos] + "'")
                last = pos
        out.append(norm[last:])
        forms.append("".join(out))
    return forms


class NamesDB:
    def __init__(self, path: str = DEFAULT_DB):
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"names index not found at {path}. Build it with names_index(action='build') or bibliograph-build-names --all."
            )
        # The server caches one NamesDB and FastMCP runs sync tools on worker
        # threads, so the connection must be usable from a thread other than
        # the one that opened it. Every query here is a read; the index is
        # written only by the build path, on its own connection. (31 Oct 2026:
        # every names tool failed after the first call from a new thread.)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def by_kanji(self, kanji: str):
        cur = self.conn.execute(
            "SELECT * FROM names WHERE kanji = ?", (kanji,)
        )
        return [dict(r) for r in cur.fetchall()]

    def by_kana(self, kana: str):
        cur = self.conn.execute(
            "SELECT * FROM names WHERE kana = ?", (kana,)
        )
        return [dict(r) for r in cur.fetchall()]

    def by_romaji(self, romaji: str):
        """Reverse lookup: romanised reading -> rows. Matches the normalised
        plain and kunrei columns, so Hepburn or kunrei input both resolve."""
        forms = apostrophe_forms(normalize_romaji(romaji))
        qs = ",".join("?" * len(forms))
        cur = self.conn.execute(
            f"SELECT * FROM names WHERE rom_plain IN ({qs}) OR rom_kunrei IN ({qs})",
            (*forms, *forms),
        )
        return [dict(r) for r in cur.fetchall()]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM names").fetchone()[0]

    def by_wiktionary(self, term: str):
        """Look up a Wiktionary headword by written form or kana reading.

        Returns sense rows ordered so archaic-family senses surface first.
        Empty list if the wiktionary table is absent or has no match.
        """
        try:
            cur = self.conn.execute(
                "SELECT * FROM wiktionary WHERE word = ? OR reading = ? "
                "ORDER BY archaic DESC, sense_index ASC",
                (term, term),
            )
        except sqlite3.OperationalError:
            return []  # wiktionary table not built yet
        return [dict(r) for r in cur.fetchall()]

    def by_jmdict(self, form: str):
        """JMdict senses for a headword form (kanji or kana)."""
        try:
            cur = self.conn.execute(
                "SELECT * FROM jmdict WHERE form = ? ORDER BY sense_index", (form,))
        except sqlite3.OperationalError:
            return []
        return [dict(r) for r in cur.fetchall()]

    def get_kanjidic(self, literal: str):
        """KANJIDIC2 record for one kanji, or None."""
        try:
            cur = self.conn.execute(
                "SELECT * FROM kanjidic WHERE literal = ?", (literal,))
        except sqlite3.OperationalError:
            return None
        row = cur.fetchone()
        return dict(row) if row else None

    def get_krad(self, kanji: str):
        """Space-joined component shapes of a kanji (KRADFILE), or None."""
        try:
            cur = self.conn.execute(
                "SELECT components FROM krad WHERE kanji = ?", (kanji,))
        except sqlite3.OperationalError:
            return None
        row = cur.fetchone()
        return row["components"] if row else None

    def radk_intersect(self, components: list):
        """Kanji containing ALL given components (RADKFILE multi-radical lookup)."""
        comps = list({c for c in components if c})
        if not comps:
            return []
        try:
            qs = ",".join("?" * len(comps))
            cur = self.conn.execute(
                f"SELECT kanji FROM radk WHERE component IN ({qs}) "
                "GROUP BY kanji HAVING COUNT(DISTINCT component) = ?",
                (*comps, len(comps)))
        except sqlite3.OperationalError:
            return []
        return [r["kanji"] for r in cur.fetchall()]

    def radk_components(self) -> set:
        """All known radical components (to flag unknown input)."""
        try:
            cur = self.conn.execute("SELECT DISTINCT component FROM radk")
        except sqlite3.OperationalError:
            return set()
        return {r["component"] for r in cur.fetchall()}
