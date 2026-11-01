"""Reference-dictionary lookups: JMdict glosses, KANJIDIC2 kanji facts,
and KRAD/RADK radical lookup. All read tables built by build_index.py; pure
and deterministic given the index.

Tools:
    gloss_term(db, term)              JMdict senses for a modern term
    kanji_info(db, kanji)             KANJIDIC2 facts for one kanji
    kanji_by_radical(db, components)  kanji containing all given shapes
    components_of(db, kanji)          KRADFILE components of a kanji
"""

from __future__ import annotations

import unicodedata

from .db import NamesDB

# RADKFILE files a radical's positional form under a stand-in kanji that
# contains it (氵 is listed as 汁, 亻 as 化, 辶 as 込 ...). Users -- and OCR
# output -- give the radical form, which RADKFILE does not know. Map the
# forms to the stand-ins. Stand-ins verified present in the built radk table.
RADICAL_ALIASES = {
    "亻": "化", "⺅": "化",
    "𠆢": "个",
    "丷": "并", "⺍": "并",
    "刂": "刈", "⺉": "刈",
    "辶": "込", "⻌": "込", "⻍": "込", "⻎": "込",
    "⺌": "尚", "⺐": "尢",
    "忄": "忙", "⺖": "忙", "⺗": "心",
    "扌": "扎", "⺘": "扎",
    "氵": "汁", "⺡": "汁", "氺": "水", "⺢": "水",
    "犭": "犯", "⺨": "犯",
    "艹": "艾", "⺾": "艾", "⺿": "艾", "⻀": "艾",
    "耂": "老", "⺹": "老",
    "灬": "杰", "⺣": "杰",
    "礻": "礼", "⺭": "礼",
    "疒": "疔",
    "衤": "初", "⻂": "初",
    "罒": "買", "⺲": "買", "⺫": "買",
    "禸": "禹",
    "𠂉": "乞",
    "爫": "爪", "⺤": "爪", "⺥": "爪",
    "彐": "ヨ", "⺕": "ヨ", "⺔": "ヨ",
    "丨": "｜", "|": "｜",
    "⺾": "艾",
    "⻊": "足", "⻖": "阡", "⻏": "邦",
    "⺼": "月", "⺝": "月",
    "⺮": "竹", "⺶": "羊", "⺷": "羊", "⺧": "牛", "⺩": "王", "⺪": "疋",
    "⻗": "雨", "⻟": "食", "⻠": "食", "⻞": "食", "⻤": "鬼", "⻣": "骨",
    "⻝": "食", "⺯": "糸", "糹": "糸", "纟": "糸", "訁": "言", "讠": "言",
    "釒": "金", "钅": "金", "飠": "食",
}
# 阝 is two radicals by position: left (阜, filed as 阡) and right (邑, filed
# as 邦). The bare form is searched both ways and the results unioned.
AMBIGUOUS_RADICALS = {"阝": ["阡", "邦"]}


def _canon_component(c: str, known: set | None = None) -> str:
    if known and c in known:
        return c  # the table already knows this form; do not remap it
    c = RADICAL_ALIASES.get(c, c)
    if c in AMBIGUOUS_RADICALS:
        return c
    n = unicodedata.normalize("NFKC", c)  # Kangxi Radicals block -> unified
    return RADICAL_ALIASES.get(n, n)


def _split(s, sep=","):
    return [x for x in (s or "").split(sep) if x]


def gloss_term(db: NamesDB, term: str) -> dict:
    """JMdict senses for a headword (kanji or kana) — a citable modern gloss."""
    rows = db.by_jmdict((term or "").strip())
    senses = []
    for r in rows:
        senses.append({
            "pos": _split(r.get("pos")),
            "gloss": _split(r.get("gloss"), "; "),
            "field": _split(r.get("field")),
            "misc": _split(r.get("misc")),
            "common": bool(r.get("common")),
        })
    return {"term": term, "found": bool(senses), "senses": senses,
            "source": "JMdict (EDRDG)"}


def kanji_info(db: NamesDB, kanji: str) -> dict:
    """KANJIDIC2 facts for a single kanji: stroke count, classical radical,
    on/kun/nanori readings, English meanings, grade/frequency/JLPT, and the
    Spahn-Hadamitzky and SKIP index codes. Adds KRADFILE components."""
    kanji = (kanji or "").strip()
    if len(kanji) != 1:
        return {"kanji": kanji, "found": False,
                "error": "pass exactly one kanji character"}
    r = db.get_kanjidic(kanji)
    if not r:
        return {"kanji": kanji, "found": False}
    comps = db.get_krad(kanji)
    return {
        "kanji": kanji, "found": True,
        "stroke_count": r.get("stroke_count"),
        "radical": r.get("radical"),
        "grade": r.get("grade"),
        "frequency": r.get("frequency"),
        "jlpt": r.get("jlpt"),
        "on": _split(r.get("on_readings")),
        "kun": _split(r.get("kun_readings")),
        "nanori": _split(r.get("nanori")),
        "meanings": _split(r.get("meanings"), "; "),
        "sh_desc": r.get("sh_desc"),
        "skip": r.get("skip"),
        "components": _split(comps, " ") if comps else [],
        "source": "KANJIDIC2 (EDRDG)",
    }


def kanji_by_radical(db: NamesDB, components) -> dict:
    """Kanji containing ALL given component shapes (RADKFILE multi-radical
    lookup). `components` may be a space/comma-separated string or a list."""
    if isinstance(components, str):
        comps = [c for c in components.replace(",", " ").split() if c]
    else:
        comps = [c for c in (components or []) if c]
    if not comps:
        return {"components": [], "found": False,
                "error": "provide one or more component shapes"}
    known = db.radk_components()
    canon = [_canon_component(c, known) for c in comps]
    mapped = {c: k for c, k in zip(comps, canon) if c != k}
    ambiguous = [c for c in canon if c in AMBIGUOUS_RADICALS]
    unknown = [c for c, k in zip(comps, canon)
               if known and k not in known and k not in AMBIGUOUS_RADICALS]
    # expand each ambiguous form into its readings, union the intersections
    combos = [[]]
    for k in canon:
        opts = AMBIGUOUS_RADICALS.get(k, [k])
        combos = [prev + [o] for prev in combos for o in opts]
    kanji = []
    for combo in combos:
        for ch in db.radk_intersect(combo):
            if ch not in kanji:
                kanji.append(ch)
    out = {
        "components": comps,
        "searched_as": canon,
        "unknown_components": unknown,
        "found": bool(kanji),
        "count": len(kanji),
        "kanji": kanji,
        "source": "RADKFILE (EDRDG)",
    }
    if mapped:
        out["mapped"] = mapped
        out["note"] = ("RADKFILE files positional radical forms under a stand-in "
                       "kanji; mapped forms are shown under 'mapped'.")
    if ambiguous:
        out["ambiguous"] = {a: AMBIGUOUS_RADICALS[a] for a in ambiguous}
    return out


def components_of(db: NamesDB, kanji: str) -> dict:
    """KRADFILE component shapes of a kanji."""
    comps = db.get_krad((kanji or "").strip())
    return {"kanji": kanji, "found": comps is not None,
            "components": _split(comps, " ") if comps else [],
            "source": "KRADFILE (EDRDG)"}
