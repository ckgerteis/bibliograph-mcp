"""Wiktionary lookup — archaic and classical term glossing.

Backed by the machine-readable Wiktionary extraction (wiktextract / kaikki.org),
ingested by build_index.py into the ``wiktionary`` table. This is the one
directly-connectable route to vocabulary beyond the modern register: it carries
etymology and archaic/classical/obsolete-tagged senses that JMdict omits.

Standing caveat, surfaced in every response: Wiktionary is crowd-sourced and
uneven. Treat a gloss here as a lead to verify (against the Nihon Kokugo
Daijiten via JapanKnowledge), never as a settled finding. The gold-standard
historical dictionary is not connectable; this is the connectable substitute,
and it is explicitly second-class.
"""

from __future__ import annotations

from .db import NamesDB

# Tags (from wiktextract) that mark a sense as belonging to an older register.
# Matching is case-insensitive and also checks hyphen/space variants.
ARCHAIC_TAGS = {
    "archaic", "obsolete", "dated", "historical", "literary", "rare",
    "classical", "classical-japanese", "old", "poetic",
}


def _is_archaic(tags_str: str) -> bool:
    if not tags_str:
        return False
    toks = {t.strip().lower().replace(" ", "-") for t in tags_str.split(",")}
    return bool(toks & ARCHAIC_TAGS)


def gloss_archaic(db: NamesDB, term: str, only_archaic: bool = False) -> dict:
    """Return Wiktionary senses for a term, archaic senses surfaced first.

    Parameters
    ----------
    term : the headword (kanji or kana) or a kana reading.
    only_archaic : if True, return only senses carrying an archaic-family tag.

    Output flags whether any archaic sense exists, includes entry etymology,
    and always carries the verify-against-NKD caveat.
    """
    rows = db.by_wiktionary(term)
    etymology = ""
    senses = []
    for r in rows:
        tags = r.get("tags") or ""
        archaic = bool(r.get("archaic")) or _is_archaic(tags)
        if only_archaic and not archaic:
            continue
        if not etymology and r.get("etymology"):
            etymology = r["etymology"]
        senses.append({
            "pos": r.get("pos"),
            "gloss": r.get("gloss"),
            "tags": [t.strip() for t in tags.split(",") if t.strip()],
            "archaic": archaic,
            "reading": r.get("reading"),
        })

    archaic_present = any(s["archaic"] for s in senses)
    return {
        "term": term,
        "found": bool(senses),
        "archaic_senses_present": archaic_present,
        "etymology": etymology,
        "senses": senses,
        "source": "Wiktionary (wiktextract/kaikki)",
        "caveat": (
            "Wiktionary is crowd-sourced and uneven. Treat this as a lead to "
            "verify against the Nihon Kokugo Daijiten (JapanKnowledge), not a "
            "settled reading — especially for period-specific senses."
        ),
    }
