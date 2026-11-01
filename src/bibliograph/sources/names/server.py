"""jmnedict-mcp — stdio MCP server over JMnedict, JMdict, Wiktionary and KANJIDIC2.

Names:      name_query_variants · resolve_name_readings · resolve_name_kanji ·
            infer_name_order
Authority:  name_authority (live: Web NDL Authorities)
Vocabulary: gloss_term (JMdict) · gloss_archaic (Wiktionary)
Kanji:      kanji_info (KANJIDIC2) · kanji_by_radical (RADKFILE)
Index:      names_index (status of the local index; builds it on request)

Run:
    python -m jmnedict_mcp.server            # stdio server (for Claude)
    python -m jmnedict_mcp.server --selftest # build demo index + exercise tools

See BUILD_NOTES.md for the repair history and the behaviour each tool promises.
"""

from __future__ import annotations

import sys

try:  # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp SDK 2.x removed mcp.server.fastmcp
    from mcp.server.mcpserver import MCPServer as FastMCP

from . import names as names_core
from .db import NamesDB, DEFAULT_DB
from . import authorities
from . import wiktionary as wiktionary_core
from . import refdata
from . import __version__

try:  # mcp SDK versions that accept a `version` kwarg report it in `initialize`
    mcp = FastMCP("jmnedict", version=__version__)
except TypeError:  # older/newer SDKs without that kwarg: set it on the
    # underlying low-level server instead. mcp.server.lowlevel.server.Server
    # falls back to the installed `mcp` package's own version when
    # self.version is falsy, so this is the only way to report *our* version
    # on those SDKs.
    mcp = FastMCP("jmnedict")
    inner = getattr(mcp, "_mcp_server", None)
    if inner is not None and hasattr(inner, "version"):
        inner.version = __version__

# --- responses --------------------------------------------------------------
# Every tool answers in the family envelope (see envelope.py) and deposits a
# receipt through mediation.emit() when MCP_RECEIPT_DIR or MCP_RECEIPT_LOG is set.

from .envelope import respond

_DB = None


def _db() -> NamesDB:
    """Lazy-open the index so the server starts even before it is built."""
    global _DB
    if _DB is None:
        _DB = NamesDB(DEFAULT_DB)
    return _DB


def _gloss_term(term: str) -> dict:
    res = refdata.gloss_term(_db(), term)
    if not res["found"]:
        # Only blame the build when the table is really missing: an absent
        # headword in a built table is the common case (少年非行 is a real
        # compound JMdict simply does not list).
        try:
            built = _db().conn.execute("SELECT 1 FROM jmdict LIMIT 1").fetchone() is not None
        except Exception:  # noqa: BLE001
            built = False
        res["hint"] = ("No JMdict headword for this term. That is a soft signal: real "
                       "compounds are often absent. Verify the term another way."
                       if built else
                       "The JMdict table is not built. Check with names_index; build with the user's agreement.")
    return res


def _gloss_archaic(term: str, only_archaic: bool) -> dict:
    res = wiktionary_core.gloss_archaic(_db(), term, only_archaic=only_archaic)
    if not res["found"]:
        res["hint"] = (
            "No Wiktionary entry for this term (or the table is not built: "
            "bibliograph-build-names --wiktionary <kaikki-japanese.jsonl>; see the README)."
        )
    return res


def _name_authority(name: str) -> dict:
    variants = names_core.name_query_variants(_db(), name)
    records = authorities.search_ndl_authorities(variants)
    return {"variants": variants, "records": records}


# ----------------------------- Phase 1 tools -----------------------------

@mcp.tool()
def name_query_variants(name: str) -> str:
    """Turn one Japanese name into the strings an author search needs.

Accepts romaji (either order, macrons optional), kana, or kanji (joined or
spaced). Read the result like this:
- kanji: ranked FULL-NAME writings, capped at 12. attested_full_names (people
  JMnedict lists) come first, with old/new and surname-variant forms (眞/真,
  澤/沢). Anything after them is a composed pairing: a lead, not an
  identification. notes says which kind the list holds.
- surname_kanji / given_kanji: the parts; kana_split: [surname, given] kana.
- hepburn_macron / hepburn_plain / kunrei: spaced, surname first.
  inverted: Given Surname order.
- name_shape: "full" (match whole names) or "single" (surname-only search).
Readings of a split, unlisted kanji name are candidates: confirm against the
source before citing. A Korean or Chinese name in romaji gets no kanji here;
notes says so. Search the leading kanji and the spaced romaji, and tell the
user which forms were searched."""
    return respond('name_query_variants', {"name": name}, lambda: names_core.name_query_variants(_db(), name))


@mcp.tool()
def resolve_name_readings(kanji: str) -> str:
    """Readings of a kanji name, best-attested first, with JMnedict
name-type tags and all three romanisations.

The first reading is the most established, not a verified one (佐藤 → satō,
then saitō). Confirm it against the source before it enters a citation."""
    return respond('resolve_name_readings', {"kanji": kanji}, lambda: names_core.resolve_name_readings(_db(), kanji))


@mcp.tool()
def resolve_name_kanji(reading: str) -> str:
    """Kanji writings for a romaji or kana reading.

Ranked: person-name types, then exact reading fit (a macron or wāpuro long
vowel ranks readings that carry it: Satō → さとう before さと), then how common
the writing is as a name. Many-to-one: read the list, do not take its head as
the answer."""
    return respond('resolve_name_kanji', {"reading": reading}, lambda: names_core.resolve_name_kanji(_db(), reading))


@mcp.tool()
def infer_name_order(token_a: str, token_b: str) -> str:
    """Decide which of two romaji/kana tokens is the surname and which the
given name, from JMnedict surname/given tags. Returns the assignment, a
confidence flag and the hit counts behind it. Low confidence means the tokens
are not clearly Japanese name parts."""
    return respond('infer_name_order', {"token_a": token_a, "token_b": token_b}, lambda: names_core.infer_name_order(_db(), token_a, token_b))


# ------------------------------ vocabulary and kanji ------------------------------

@mcp.tool()
def gloss_term(term: str) -> str:
    """JMdict English gloss for a JAPANESE headword: a citable rendering
of an institutional or technical term.

Direction matters: this verifies a Japanese term you already have; it does not
translate an English topic into Japanese. found=false is a soft signal (real
compounds such as 少年非行 are often absent), not proof the term is wrong. For
archaic or classical vocabulary use gloss_archaic."""
    return respond('gloss_term', {"term": term}, lambda: _gloss_term(term))


@mcp.tool()
def gloss_archaic(term: str, only_archaic: bool = False) -> str:
    """Archaic and classical senses of a Japanese term from Wiktionary
(wiktextract/kaikki), with etymology, archaic senses first; only_archaic=True
returns just those.

Wiktionary is crowd-sourced: treat every gloss as a lead to check against the
Nihon Kokugo Daijiten (JapanKnowledge), not a settled reading."""
    return respond('gloss_archaic', {"term": term, "only_archaic": only_archaic}, lambda: _gloss_archaic(term, only_archaic))


@mcp.tool()
def kanji_by_radical(components: str) -> str:
    """Find kanji containing ALL the given component shapes (space- or
comma-separated), for a character OCR hands you that you cannot type.

Radical forms are accepted as written (氵 亻 辶 艹 忄 扌, Kangxi-block forms);
RADKFILE files them under stand-in kanji, and mapped / searched_as show the
translation. 阝 is searched both as left and right radical."""
    return respond('kanji_by_radical', {"components": components}, lambda: refdata.kanji_by_radical(_db(), components))


@mcp.tool()
def kanji_info(kanji: str) -> str:
    """KANJIDIC2 facts for a single kanji: stroke count, classical radical,
    on/kun/nanori readings, English meanings, grade/frequency/JLPT, the
    Spahn-Hadamitzky and SKIP index codes, and KRADFILE components. Authoritative
    structured data — prefer this over reciting kanji facts from memory."""
    return respond('kanji_info', {"kanji": kanji}, lambda: refdata.kanji_info(_db(), kanji))


# --------------------------------- name authority ---------------------------------

@mcp.tool()
def name_authority(name: str) -> str:
    """Web NDL Authorities personal-name headings for a name: the NDL's
authorised heading, its reading (カタカナ), life dates and NDLA identifier,
looked up under the name forms name_query_variants produces.

Prefer this reading to JMnedict's for a citation when a heading exists: it is
catalogue-verified. Pen names, art names and other related names appear only
when the authority record lists them. An empty result means no heading was
found under the forms searched, not that the person has none; the forms are
in plan.query_forms."""
    return respond('name_authority', {"name": name}, lambda: _name_authority(name))


# --------------------------------- the index itself ---------------------------------

def _names_index(action: str) -> dict:
    global _DB
    from . import firstrun
    if action == "status":
        return firstrun.index_state()
    if action == "build":
        if _DB is not None:  # let a rebuild replace the file (Windows locks open files)
            try:
                _DB.close()
            except Exception:  # noqa: BLE001
                pass
            _DB = None
        return firstrun.start_build()
    return {"found": False, "hint": "action must be 'status' or 'build'."}


@mcp.tool()
def names_index(action: str = "status") -> str:
    """Check, or build, the local dictionary index the other name tools read.

action="status" (the default) reports whether the index is built, where it is
stored, how many entries each table holds, and the progress of any build. It
downloads nothing. Call it when a name tool answers INDEX_MISSING.

action="build" downloads the EDRDG dictionary data (JMnedict, JMdict,
KANJIDIC2, KRADFILE, RADKFILE, via jmdict-simplified on GitHub) and builds the
index in the background; the call returns at once. Only call it after telling
the user what will be downloaded and where it will be stored (the status
answer gives both) and after they agree in this conversation. Then check with
action="status" until the build reports done. gloss_archaic needs a separate
Wiktionary table that this build does not fetch."""
    return respond('names_index', {"action": action}, lambda: _names_index(action))


# --------------------------------- entry ---------------------------------

def _selftest():
    """Exercise the Phase 1 tools without Claude.

    Builds the demo fixture into a TEMP database and runs against that, so it
    never overwrites a real ``data/names.sqlite`` you have built — running the
    selftest must be safe even on a production index.
    """
    import json
    import os
    import tempfile
    from . import build_index
    tmp = os.path.join(tempfile.gettempdir(), "jmnedict_selftest.sqlite")
    build_index.build_demo(tmp)
    db = NamesDB(tmp)
    try:
        print("\nname_query_variants('Saito Shinichi'):")
        print(json.dumps(names_core.name_query_variants(db, "Saito Shinichi"),
                         ensure_ascii=False, indent=2))
        print("\nresolve_name_kanji('Satō'):")
        print(json.dumps(names_core.resolve_name_kanji(db, "Satō"),
                         ensure_ascii=False, indent=2))
    finally:
        db.close()


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    mcp.run()


if __name__ == "__main__":
    main()
