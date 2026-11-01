"""Build the SQLite names index from the JMnedict JSON.

Usage:
    python scripts/build_index.py                 # download latest, build
    python scripts/build_index.py --input FILE     # use a local jmnedict json
    python scripts/build_index.py --demo           # tiny fixture, no download

The JSON is the JMnedict distribution from scriptin/jmdict-simplified:
    https://github.com/scriptin/jmdict-simplified/releases

Each source word looks like:
    {
      "id": "5000000",
      "kanji": [{"text": "斎藤", "tags": []}],
      "kana":  [{"text": "さいとう", "tags": [], "appliesToKanji": ["*"]}],
      "translation": [
        {"type": ["surname"], "related": [], "translation": [{"lang":"eng","text":"Saitou"}]}
      ]
    }

We denormalise to one row per (kanji, kana) pair (kana-only when no kanji),
attaching the union of name-type tags and precomputed romaji columns.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sqlite3
import sys
import tarfile
import zipfile

from .db import CREATE_SQL  # noqa: E402
from .romaji import to_romaji  # noqa: E402
from .wiktionary import ARCHAIC_TAGS  # noqa: E402
from . import paths  # noqa: E402

# The index lives in the permanent data directory (see paths.py), never in the
# repo. Computed at import for defaults; --data-dir in main() overrides via env.
DB_PATH = paths.db_path()
RELEASES_API = "https://api.github.com/repos/scriptin/jmdict-simplified/releases/latest"
ASSET_RE = re.compile(r"jmnedict-all-.*\.json\.(tgz|zip|gz)$")


def _now_iso():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _update_manifest(key: str, info: dict):
    """Record dataset provenance (source file, row count, build time) in
    <data_dir>/manifest.json — a small, honest record of what was built when."""
    path = os.path.join(paths.data_dir(create=True), "manifest.json")
    manifest = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            manifest = {}
    info = dict(info)
    info["built"] = _now_iso()
    manifest[key] = info
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def _download_latest(force: bool = False) -> str:
    """Fetch the latest jmnedict-all JSON into the cached raw dir, returning the
    path to the extracted .json. If an extracted copy is already cached and force
    is False, skip the network entirely — this is what makes rebuilds cheap."""
    import requests

    raw = paths.raw_dir(create=True)
    rel = requests.get(RELEASES_API, timeout=60).json()
    asset = next(
        (a for a in rel.get("assets", []) if ASSET_RE.search(a["name"])), None
    )
    if not asset:
        raise RuntimeError(
            "Could not find a jmnedict-all asset in the latest release. "
            "Download it manually and pass --input."
        )
    name = asset["name"]
    extracted = os.path.join(raw, re.sub(r"\.(tgz|zip|gz)$", "", name))
    if os.path.exists(extracted) and not force:
        print(f"Using cached {os.path.basename(extracted)} (pass --force to re-download)")
        return extracted

    url = asset["browser_download_url"]
    print(f"Downloading {name} ...")
    blob = requests.get(url, timeout=600).content
    if name.endswith(".tgz"):
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            member = next(m for m in tf.getmembers() if m.name.endswith(".json"))
            data = tf.extractfile(member).read()
    elif name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            member = next(n for n in zf.namelist() if n.endswith(".json"))
            data = zf.read(member)
    else:  # .gz
        data = gzip.decompress(blob)
    with open(extracted, "wb") as f:
        f.write(data)
    print(f"Cached extract -> {extracted}")
    return extracted


def _romaji_cols(kana: str):
    return (
        to_romaji(kana, "hepburn_macron"),
        to_romaji(kana, "hepburn_plain"),
        to_romaji(kana, "kunrei"),
    )


def _rows_from_word(word: dict):
    """Yield row tuples for one JMnedict word."""
    kanji_list = [k["text"] for k in word.get("kanji", [])]
    kana_list = word.get("kana", [])
    types = sorted({t for tr in word.get("translation", []) for t in tr.get("type", [])})
    name_types = ",".join(types)
    glosses = [
        g["text"]
        for tr in word.get("translation", [])
        for g in tr.get("translation", [])
        if g.get("lang") == "eng"
    ]
    gloss = "; ".join(glosses)
    entry_id = word.get("id", "")

    for kana_obj in kana_list:
        kana = kana_obj["text"]
        hep, plain, kun = _romaji_cols(kana)
        applies = kana_obj.get("appliesToKanji", ["*"])
        targets = kanji_list if applies == ["*"] else [k for k in kanji_list if k in applies]
        if targets:
            for kanji in targets:
                yield (entry_id, kanji, kana, name_types, gloss, hep, plain, kun)
        else:
            yield (entry_id, None, kana, name_types, gloss, hep, plain, kun)


def build(json_path: str, db_path: str = DB_PATH):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    words = data.get("words", data if isinstance(data, list) else [])
    print(f"Loaded {len(words):,} JMnedict entries from {json_path}")

    # Non-clobbering: ensure schema, clear only the names table so a Wiktionary
    # build in the same file survives a names rebuild and vice versa.
    conn = sqlite3.connect(db_path)
    conn.executescript(CREATE_SQL)
    conn.execute("DELETE FROM names")
    n = 0
    with conn:
        for word in words:
            for row in _rows_from_word(word):
                conn.execute(
                    "INSERT INTO names VALUES (?,?,?,?,?,?,?,?)", row
                )
                n += 1
    conn.close()
    _update_manifest("jmnedict", {"source": os.path.basename(json_path), "rows": n})
    print(f"Indexed {n:,} name rows -> {db_path}")


# ---- Wiktionary (wiktextract / kaikki JSONL) ingestion ----

def _wikt_reading(entry: dict):
    """Best-effort kana reading from a kaikki entry's forms list."""
    for form in entry.get("forms", []) or []:
        tags = {t.lower() for t in form.get("tags", [])}
        if tags & {"hiragana", "kana", "katakana"}:
            return form.get("form")
    return None


def _wikt_rows_from_entry(entry: dict):
    """Yield wiktionary table rows from one kaikki JSON entry."""
    word = entry.get("word")
    if not word:
        return
    pos = entry.get("pos")
    etymology = entry.get("etymology_text", "") or ""
    reading = _wikt_reading(entry)
    for i, sense in enumerate(entry.get("senses", []) or []):
        glosses = sense.get("glosses") or sense.get("raw_glosses") or []
        gloss = glosses[0] if glosses else ""
        tags = list(sense.get("tags", []) or []) + list(sense.get("raw_tags", []) or [])
        tags_str = ",".join(tags)
        norm = {t.strip().lower().replace(" ", "-") for t in tags}
        archaic = 1 if (norm & ARCHAIC_TAGS) else 0
        yield (word, reading, pos, i, gloss, tags_str, archaic, etymology)


def build_wiktionary(jsonl_path: str, db_path: str = DB_PATH):
    """Ingest a kaikki.org / wiktextract Japanese JSONL file into the
    wiktionary table. Streams line by line (the file is large)."""
    conn = sqlite3.connect(db_path)
    conn.executescript(CREATE_SQL)
    conn.execute("DELETE FROM wiktionary")
    n = 0
    with conn, open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("lang_code") not in (None, "ja") and entry.get("lang") != "Japanese":
                continue
            for row in _wikt_rows_from_entry(entry):
                conn.execute("INSERT INTO wiktionary VALUES (?,?,?,?,?,?,?,?)", row)
                n += 1
    conn.close()
    _update_manifest("wiktionary", {"source": os.path.basename(jsonl_path), "rows": n})
    print(f"Indexed {n:,} Wiktionary sense rows -> {db_path}")


# ---- EDRDG reference dictionaries (JMdict, KANJIDIC2, KRAD/RADK) ----
# All four are jmdict-simplified release assets, fetched by name prefix.

def _download_asset(prefix: str, force: bool = False) -> str:
    """Fetch a jmdict-simplified release asset by name prefix into raw/, return
    the extracted .json path. Cached: skips the network if already extracted."""
    import requests
    raw = paths.raw_dir(create=True)
    rel = requests.get(RELEASES_API, timeout=60).json()
    pat = re.compile("^" + re.escape(prefix) + r"-\d.*\.json\.(tgz|zip|gz)$")
    asset = next((a for a in rel.get("assets", []) if pat.match(a["name"])), None)
    if not asset:
        raise RuntimeError(f"No '{prefix}' asset in the latest release.")
    name = asset["name"]
    extracted = os.path.join(raw, re.sub(r"\.(tgz|zip|gz)$", "", name))
    if os.path.exists(extracted) and not force:
        print(f"Using cached {os.path.basename(extracted)}")
        return extracted
    print(f"Downloading {name} ...")
    blob = requests.get(asset["browser_download_url"], timeout=600).content
    if name.endswith(".tgz"):
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            m = next(t for t in tf.getmembers() if t.name.endswith(".json"))
            data = tf.extractfile(m).read()
    elif name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            m = next(x for x in zf.namelist() if x.endswith(".json"))
            data = zf.read(m)
    else:
        data = gzip.decompress(blob)
    with open(extracted, "wb") as f:
        f.write(data)
    print(f"Cached extract -> {extracted}")
    return extracted


def _jmdict_rows(word):
    kanji = word.get("kanji", [])
    kana = word.get("kana", [])
    forms = [k["text"] for k in kanji] + [k["text"] for k in kana]
    common = {k["text"] for k in kanji if k.get("common")} | \
             {k["text"] for k in kana if k.get("common")}
    seq = word.get("id", "")
    for i, sense in enumerate(word.get("sense", [])):
        pos = ",".join(sense.get("partOfSpeech", []))
        gloss = "; ".join(g["text"] for g in sense.get("gloss", [])
                          if g.get("lang") == "eng")
        field = ",".join(sense.get("field", []))
        misc = ",".join(sense.get("misc", []))
        for form in forms:
            yield (seq, form, i, 1 if form in common else 0, pos, gloss, field, misc)


def _kanjidic_row(ch):
    misc = ch.get("misc", {})
    strokes = misc.get("strokeCounts") or []
    radicals = [r["value"] for r in ch.get("radicals", []) if r.get("type") == "classical"]
    rm = ch.get("readingMeaning") or {}
    on, kun, meanings = [], [], []
    for g in rm.get("groups", []):
        for rd in g.get("readings", []):
            if rd.get("type") == "ja_on":
                on.append(rd["value"])
            elif rd.get("type") == "ja_kun":
                kun.append(rd["value"])
        for m in g.get("meanings", []):
            if m.get("lang") == "en":
                meanings.append(m["value"])
    qc = {q.get("type"): q.get("value") for q in ch.get("queryCodes", [])}
    return (ch["literal"], strokes[0] if strokes else None,
            radicals[0] if radicals else None,
            misc.get("grade"), misc.get("frequency"), misc.get("jlptLevel"),
            ",".join(on), ",".join(kun), ",".join(rm.get("nanori", [])),
            "; ".join(meanings), qc.get("sh_desc"), qc.get("skip"))


def _build_table(json_path, table, rows_iter, label):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    conn = sqlite3.connect(paths.db_path() if json_path is None else _DB_TARGET[0])
    conn.executescript(CREATE_SQL)
    conn.execute(f"DELETE FROM {table}")
    n = 0
    with conn:
        for row in rows_iter(data):
            conn.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)
            n += 1
    conn.close()
    _update_manifest(table, {"source": os.path.basename(json_path), "rows": n})
    print(f"Indexed {n:,} {label} rows -> {_DB_TARGET[0]}")


# _DB_TARGET lets the build_* helpers share the db path chosen in main().
_DB_TARGET = [DB_PATH]


def build_jmdict(json_path, db_path=None):
    _DB_TARGET[0] = db_path or paths.db_path()
    _build_table(json_path, "jmdict",
                 lambda d: (r for w in d.get("words", []) for r in _jmdict_rows(w)),
                 "JMdict sense-form")


def build_kanjidic(json_path, db_path=None):
    _DB_TARGET[0] = db_path or paths.db_path()
    _build_table(json_path, "kanjidic",
                 lambda d: (_kanjidic_row(c) for c in d.get("characters", [])),
                 "KANJIDIC2 kanji")


def build_krad(json_path, db_path=None):
    _DB_TARGET[0] = db_path or paths.db_path()
    _build_table(json_path, "krad",
                 lambda d: ((k, " ".join(v)) for k, v in d.get("kanji", {}).items()),
                 "KRADFILE kanji")


def build_radk(json_path, db_path=None):
    _DB_TARGET[0] = db_path or paths.db_path()
    def rows(d):
        for comp, info in d.get("radicals", {}).items():
            sc = info.get("strokeCount")
            for kanji in info.get("kanji", []):
                yield (comp, sc, kanji)
    _build_table(json_path, "radk", rows, "RADKFILE membership")


# ---- demo fixture: a handful of real entries so the tools work without the download ----

DEMO_WORDS = [
    {"id": "1", "kanji": [{"text": "斎藤"}], "kana": [{"text": "さいとう", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["surname"], "translation": [{"lang": "eng", "text": "Saitou"}]}]},
    {"id": "2", "kanji": [{"text": "斉藤"}], "kana": [{"text": "さいとう", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["surname"], "translation": [{"lang": "eng", "text": "Saitou"}]}]},
    {"id": "3", "kanji": [{"text": "慎一"}], "kana": [{"text": "しんいち", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["masculine"], "translation": [{"lang": "eng", "text": "Shin'ichi"}]}]},
    {"id": "4", "kanji": [{"text": "田中"}], "kana": [{"text": "たなか", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["surname"], "translation": [{"lang": "eng", "text": "Tanaka"}]}]},
    {"id": "5", "kanji": [{"text": "寛"}], "kana": [{"text": "ひろし", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["masculine"], "translation": [{"lang": "eng", "text": "Hiroshi"}]}]},
    {"id": "6", "kanji": [{"text": "佐藤"}], "kana": [{"text": "さとう", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["surname"], "translation": [{"lang": "eng", "text": "Satou"}]}]},
    {"id": "7", "kanji": [{"text": "東京"}], "kana": [{"text": "とうきょう", "appliesToKanji": ["*"]}],
     "translation": [{"type": ["place"], "translation": [{"lang": "eng", "text": "Toukyou"}]}]},
]


# A few Wiktionary-shaped (kaikki) entries so gloss_archaic works in --demo.
DEMO_WIKT = [
    {"word": "つとめて", "pos": "noun", "etymology_text": "From Old Japanese.",
     "forms": [{"form": "つとめて", "tags": ["hiragana"]}],
     "senses": [{"glosses": ["(archaic) early morning; the morning after"],
                 "tags": ["archaic"]}]},
    {"word": "いと", "pos": "adverb", "etymology_text": "Classical intensifier.",
     "senses": [{"glosses": ["(archaic) very; greatly"],
                 "tags": ["archaic", "classical"]}]},
    {"word": "本", "pos": "noun", "etymology_text": "From Middle Chinese.",
     "senses": [{"glosses": ["book"], "tags": []},
                {"glosses": ["(counter) long, cylindrical objects"], "tags": []}]},
]


def build_demo(db_path: str = None):
    # Demo writes to a SEPARATE file (demo.sqlite) so it never clobbers a real
    # names.sqlite index in the permanent data directory.
    if db_path is None:
        db_path = os.path.join(paths.data_dir(create=True), "demo.sqlite")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(CREATE_SQL)
    n = w = 0
    demo_jmdict = [
        {"id": "1", "kanji": [{"text": "和", "common": True}], "kana": [{"text": "わ", "common": True}],
         "sense": [{"partOfSpeech": ["n"], "field": [], "misc": [],
                    "gloss": [{"lang": "eng", "text": "harmony"}, {"lang": "eng", "text": "peace"}]}]},
        {"id": "2", "kanji": [{"text": "政府", "common": True}], "kana": [{"text": "せいふ", "common": True}],
         "sense": [{"partOfSpeech": ["n"], "field": [], "misc": [],
                    "gloss": [{"lang": "eng", "text": "government"}]}]},
    ]
    demo_kanjidic = [
        {"literal": "漢", "radicals": [{"type": "classical", "value": 85}],
         "misc": {"grade": 3, "strokeCounts": [13], "frequency": 1487, "jlptLevel": 2},
         "queryCodes": [{"type": "sh_desc", "value": "3a10.11"}, {"type": "skip", "value": "1-3-10"}],
         "readingMeaning": {"groups": [{"readings": [{"type": "ja_on", "value": "カン"}],
                                        "meanings": [{"lang": "en", "value": "Sino-"}, {"lang": "en", "value": "China"}]}],
                            "nanori": []}},
    ]
    demo_krad = {"漢": ["氵", "廿", "口", "夫"], "和": ["禾", "口"]}
    # Real RADKFILE files 氵 under the stand-in 汁 (see refdata.RADICAL_ALIASES);
    # the fixture mirrors that so the alias path is what the tests exercise.
    demo_radk = {"汁": {"strokeCount": 3, "kanji": ["漢"]},
                 "口": {"strokeCount": 3, "kanji": ["漢", "和"]},
                 "廿": {"strokeCount": 3, "kanji": ["漢"]},
                 "夫": {"strokeCount": 4, "kanji": ["漢"]},
                 "禾": {"strokeCount": 5, "kanji": ["和"]}}
    with conn:
        for word in DEMO_WORDS:
            for row in _rows_from_word(word):
                conn.execute("INSERT INTO names VALUES (?,?,?,?,?,?,?,?)", row)
                n += 1
        for entry in DEMO_WIKT:
            for row in _wikt_rows_from_entry(entry):
                conn.execute("INSERT INTO wiktionary VALUES (?,?,?,?,?,?,?,?)", row)
                w += 1
        for word in demo_jmdict:
            for row in _jmdict_rows(word):
                conn.execute("INSERT INTO jmdict VALUES (?,?,?,?,?,?,?,?)", row)
        for ch in demo_kanjidic:
            conn.execute("INSERT INTO kanjidic VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", _kanjidic_row(ch))
        for k, v in demo_krad.items():
            conn.execute("INSERT INTO krad VALUES (?,?)", (k, " ".join(v)))
        for comp, info in demo_radk.items():
            for kanji in info["kanji"]:
                conn.execute("INSERT INTO radk VALUES (?,?,?)", (comp, info["strokeCount"], kanji))
    conn.close()
    print(f"Built demo index: {n} names, {w} wiktionary, +jmdict/kanjidic/krad/radk -> {db_path}")


def main():
    ap = argparse.ArgumentParser(description="Build the JMnedict / Wiktionary SQLite index.")
    ap.add_argument("--input", help="path to a local jmnedict json file")
    ap.add_argument("--wiktionary", help="path to a kaikki.org Japanese JSONL file "
                                         "(archaic-term glossing); builds the wiktionary table")
    ap.add_argument("--demo", action="store_true", help="build a tiny fixture (demo.sqlite), no download")
    ap.add_argument("--data-dir", help="permanent data directory (overrides JMNEDICT_DATA_DIR "
                                       "and the per-OS default)")
    ap.add_argument("--force", action="store_true", help="re-download even if a raw copy is cached")
    ap.add_argument("--refdata", action="store_true",
                    help="download + build JMdict, KANJIDIC2, KRADFILE, RADKFILE")
    ap.add_argument("--jmdict", help="local jmdict-eng json (else use --refdata)")
    ap.add_argument("--kanjidic", help="local kanjidic2 json")
    ap.add_argument("--krad", help="local kradfile json")
    ap.add_argument("--radk", help="local radkfile json")
    ap.add_argument("--db", help="explicit output sqlite path (default: <data-dir>/names.sqlite)")
    ap.add_argument("--all", action="store_true",
                    help="names and the reference data in one run (what names_index builds)")
    args = ap.parse_args()
    if args.all:
        args.refdata = True

    # Honour --data-dir before any path is resolved.
    if args.data_dir:
        os.environ["JMNEDICT_DATA_DIR"] = os.path.abspath(args.data_dir)
    print(f"Data directory: {paths.data_dir(create=True)}")

    if args.demo:
        demo_db = args.db or os.path.join(paths.data_dir(create=True), "demo.sqlite")
        build_demo(demo_db)
        return

    db = args.db or paths.db_path()
    other = (args.wiktionary or args.refdata or args.jmdict or args.kanjidic
             or args.krad or args.radk)

    # names build: explicit --input, or the default download unless the run only
    # targets the other datasets.
    if args.input:
        build(args.input, db)
    elif args.all or not other:
        build(_download_latest(force=args.force), db)

    if args.wiktionary:
        build_wiktionary(args.wiktionary, db)

    if args.refdata:
        build_jmdict(_download_asset("jmdict-eng", args.force), db)
        build_kanjidic(_download_asset("kanjidic2-en", args.force), db)
        build_krad(_download_asset("kradfile", args.force), db)
        build_radk(_download_asset("radkfile", args.force), db)
    if args.jmdict:
        build_jmdict(args.jmdict, db)
    if args.kanjidic:
        build_kanjidic(args.kanjidic, db)
    if args.krad:
        build_krad(args.krad, db)
    if args.radk:
        build_radk(args.radk, db)


if __name__ == "__main__":
    main()
