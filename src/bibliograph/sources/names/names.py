"""Names core: the offline logic behind the MCP tools.

Builds on db.NamesDB (lookups) and romaji (deterministic romanisation). No
network, no model calls — everything here is deterministic given the index.

Public functions map 1:1 to the names-core MCP tools:
    resolve_name_readings(db, kanji)
    resolve_name_kanji(db, reading)
    name_query_variants(db, name)
    infer_name_order(db, token_a, token_b)
"""

from __future__ import annotations

import bisect
import math

from .db import NamesDB, PERSON_TYPES, normalize_romaji
from .romaji import romaji_variants

# Common interchangeable surname kanji. JMnedict stores these as distinct
# entries, so a search on one misses records keyed under another. Small and
# curated on purpose — extend as you hit cases. (Maps each char to its cluster.)
SURNAME_VARIANTS = {
    "斎": ["斎", "斉", "齋", "齊"],
    "斉": ["斎", "斉", "齋", "齊"],
    "齋": ["斎", "斉", "齋", "齊"],
    "齊": ["斎", "斉", "齋", "齊"],
    "高": ["高", "髙"],
    "髙": ["高", "髙"],
    "崎": ["崎", "﨑", "嵜"],
    "﨑": ["崎", "﨑", "嵜"],
    "沢": ["沢", "澤"],
    "澤": ["沢", "澤"],
    "辺": ["辺", "邊", "邉"],
    "邊": ["辺", "邊", "邉"],
    "島": ["島", "嶋", "嶌"],
    "嶋": ["島", "嶋", "嶌"],
}


def _is_kanji(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
    )


def _is_kana(ch: str) -> bool:
    code = ord(ch)
    return 0x3040 <= code <= 0x30FF


def detect_script(s: str) -> str:
    """Return 'kanji', 'kana', or 'romaji' for a name token/string."""
    s = s.strip()
    if any(_is_kanji(c) for c in s):
        return "kanji"
    if s and all(_is_kana(c) or c.isspace() for c in s):
        return "kana"
    return "romaji"


def _person_first(rows):
    """Sort rows so person-name types come before place/company/etc."""
    def key(r):
        types = set((r.get("name_types") or "").split(","))
        return (0 if types & PERSON_TYPES else 1, -(len(r.get("kana") or "")))
    return sorted(rows, key=key)


# Old (kyūjitai) and new (shinjitai) forms of the same character, as they occur
# in personal names of any part. A person is catalogued under either: 丸山眞男
# and 丸山真男 are one man, and before this table the server returned him as
# two people and could not reach the NDL authority from the old form. Only
# pure variants of one character belong here. Characters that are used as
# distinct name choices (龍/竜, 峯/峰, 冨/富) are deliberately absent: 成田龍一
# and 成田竜一 are different people.
OLD_NEW_FORMS = {
    "眞": "真", "國": "国", "廣": "広", "實": "実", "惠": "恵", "德": "徳",
    "榮": "栄", "壽": "寿", "豐": "豊", "禮": "礼", "淸": "清", "靜": "静",
    "藏": "蔵", "瀨": "瀬", "濱": "浜", "櫻": "桜", "圓": "円", "萬": "万",
    "與": "与", "會": "会", "學": "学", "經": "経", "將": "将", "條": "条",
    "彌": "弥", "敎": "教", "鐵": "鉄", "關": "関", "黑": "黒", "當": "当",
    "靑": "青", "繪": "絵", "譽": "誉", "兒": "児", "惠": "恵", "晝": "昼",
}

# One interchangeable set per character, for expansion; one representative
# per character, for clustering.
VARIANT_SETS: dict[str, list[str]] = {k: list(v) for k, v in SURNAME_VARIANTS.items()}
for _old, _new in OLD_NEW_FORMS.items():
    VARIANT_SETS[_old] = [_new, _old]
    VARIANT_SETS[_new] = [_new, _old]


def fold_char(ch: str) -> str:
    """The representative form of a character for matching and clustering."""
    return VARIANT_SETS[ch][0] if ch in VARIANT_SETS else ch


def fold_name(s: str) -> str:
    return "".join(fold_char(c) for c in s)


_MAX_KANJI_VARIANTS = 8

# Single-character surnames that in Japanese publishing are overwhelmingly
# Korean (incl. Zainichi) or Chinese. Deliberately short, and it excludes
# characters that are also ordinary Japanese surnames (林, 高, 安, 原, 森). Used
# only to add a warning note, never to change a result: JMnedict renders 姜尚中
# as かんさんじゅ / "Kan Sanju", while he publishes as Kang Sang-jung.
LIKELY_NON_JAPANESE_SURNAMES = set("姜金李朴崔鄭尹韓權権呉徐洪梁盧車魏楊王劉陳張周黄孫馬胡郭蕭")


def _kanji_variants(kanji: str):
    """Expand a kanji string over interchangeable forms (澤/沢, 眞/真 ...).

    Original first, then the all-new-forms writing, then each single-position
    substitution. Capped, so a name with several variable characters cannot
    blow up the query list.
    """
    variants = [kanji]
    folded = fold_name(kanji)
    if folded not in variants:
        variants.append(folded)
    for base in (kanji, folded):
        for idx, ch in enumerate(base):
            for alt in VARIANT_SETS.get(ch, []):
                if alt == ch:
                    continue
                cand = base[:idx] + alt + base[idx + 1:]
                if cand not in variants:
                    variants.append(cand)
    return variants[:_MAX_KANJI_VARIANTS]


def resolve_name_readings(db: NamesDB, kanji: str) -> dict:
    """kanji name -> candidate readings with name-type tags and romaji."""
    # Most-established reading first. Ordering by kana length (the old key)
    # put さいとう ahead of さとう for 佐藤, and that head reading is what
    # citations take their Hepburn from.
    rank = _FreqRanker(db)

    def key(r):
        kana = r.get("kana") or ""
        t = _types(r)
        role = "surname" if t & SURNAME_TYPES else "given"
        attested = max(rank.attestation(kanji, "surname", kana),
                       rank.attestation(kanji, "given", kana)) if kana else 0
        return (0 if t & PERSON_TYPES else 1, -attested, -len(t),
                -rank.reading_popularity(kana, role) if kana else 0, len(kana))
    rows = sorted(db.by_kanji(kanji), key=key)
    readings = []
    seen = set()
    for r in rows:
        kana = r.get("kana") or ""
        if not kana or kana in seen:
            continue
        seen.add(kana)
        # Only a full-name listing (JMnedict "person") has a boundary to find;
        # a bare surname such as 佐藤 must never be cut into 佐 + 藤.
        split = _split_by_reading(db, kanji, kana) if "person" in _types(r) else None
        rv = _spaced_romaji(split[1], split[3]) if split else romaji_variants(kana)
        entry = {
            "kana": kana,
            "name_types": (r.get("name_types") or "").split(",") if r.get("name_types") else [],
            "hepburn_macron": rv["hepburn_macron"],
            "hepburn_plain": rv["hepburn_plain"],
            "kunrei": rv["kunrei"],
        }
        if split:
            entry["split"] = {"surname": split[0], "surname_kana": split[1],
                              "given": split[2], "given_kana": split[3]}
        readings.append(entry)
    return {"kanji": kanji, "found": bool(readings), "readings": readings}


def _split_by_reading(db: NamesDB, kanji: str, kana: str):
    """Surname/given boundary of a full-name listing, read off its own reading.

    Returns (surname, surname_kana, given, given_kana) when a leading part of
    the kanji is listed as a surname whose reading starts the full reading, and
    None otherwise (a bare surname or given name stays joined, as before).
    A boundary the given part confirms with a listed reading wins over one
    only the surname supports; among equals the longer surname wins.
    """
    if len(kanji) < 2 or not all(_is_kanji(c) for c in kanji):
        return None
    best, best_score = None, -1
    for i in range(1, len(kanji)):
        sur, giv = kanji[:i], kanji[i:]
        for r in db.by_kanji(sur):
            sk = r.get("kana") or ""
            if not sk or not (_types(r) & SURNAME_TYPES):
                continue
            if not kana.startswith(sk) or len(sk) >= len(kana):
                continue
            gk = kana[len(sk):]
            confirmed = any((g.get("kana") or "") == gk for g in db.by_kanji(giv))
            score = (2 if confirmed else 1) * 10 + i
            if score > best_score:
                best, best_score = (sur, sk, giv, gk), score
    return best


def resolve_name_kanji(db: NamesDB, reading: str) -> dict:
    """romaji or kana reading -> candidate kanji writings, person-types first."""
    script = detect_script(reading)
    rows = db.by_kana(reading) if script == "kana" else db.by_romaji(reading)
    rank = _FreqRanker(db)

    def key(r):
        is_person = 0 if _types(r) & PERSON_TYPES else 1
        k = r.get("kanji") or ""
        role = "surname" if _types(r) & SURNAME_TYPES else "given"
        return (is_person, -_reading_fit(r.get("kana") or "", reading),
                -rank.attestation(k, role, r.get("kana")) if k else 0, rank(k))
    rows = sorted(rows, key=key)
    candidates = []
    seen = set()
    for r in rows:
        kanji = r.get("kanji")
        if not kanji or kanji in seen:
            continue
        seen.add(kanji)
        candidates.append({
            "kanji": kanji,
            "kana": r.get("kana"),
            "name_types": (r.get("name_types") or "").split(",") if r.get("name_types") else [],
        })
    return {"reading": reading, "found": bool(candidates), "candidates": candidates,
            "ranking": "person-name types first, then exact reading fit "
                       "(macron / wapuro long vowels), then kanji commonness"}


SURNAME_TYPES = {"surname"}
# Weighted: an explicit given/masc/fem tag outranks the catch-all unclass tag.
GIVEN_TYPE_WEIGHT = {
    "given": 2, "masculine": 2, "feminine": 2, "masc": 2, "fem": 2,
    "unclassified": 1, "unclass": 1,
}
FULL_NAME_TYPES = {"person"}

_MACRON_FOLD = str.maketrans("âêîôû", "āēīōū")
_MAX_FULL_NAMES = 12      # paired full-name kanji handed to the services
_MAX_PART_CANDIDATES = 15  # per surname / given list
_MAX_SPLIT_SURNAME_READINGS = 4  # readings kept when splitting an unlisted kanji name
_MAX_SPLIT_GIVEN_READINGS = 3
_FREQ_DEFAULT = 2600       # KANJIDIC2 ranks stop at 2501; unranked = rarer


def _types(row) -> set:
    return set((row.get("name_types") or "").split(",")) - {""}


def _rows_for_token(db: NamesDB, tok: str):
    return db.by_kana(tok) if detect_script(tok) == "kana" else db.by_romaji(tok)


def _wapuro(macron: str) -> str:
    return macron.replace("ō", "ou").replace("ū", "uu")


def _reading_fit(kana: str, raw: str) -> int:
    """How exactly a stored kana reading fits the user's romaji/kana token.

    normalize_romaji() folds long vowels, so Satō, Sato, Satou and Satoo all
    retrieve さと, さとう and さとお alike. When the input marks vowel length
    (a macron, or wāpuro ou/uu/oo) we can and should prefer the readings that
    carry it. 2 = exact fit, 1 = retrieved only through the fold.
    """
    raw = raw.strip()
    if detect_script(raw) == "kana":
        return 2 if kana == raw else 1
    r = raw.lower().translate(_MACRON_FOLD).replace("'", "").replace("’", "").replace("-", "")
    rv = romaji_variants(kana)
    mac = rv["hepburn_macron"].replace("'", "")
    forms = {mac, _wapuro(mac), mac.replace("ō", "oo"), rv["kunrei"]}
    marked = any(c in r for c in "āēīōū") or any(d in r for d in ("ou", "uu", "oo"))
    if not marked:
        forms.add(rv["hepburn_plain"].replace("'", ""))
    return 2 if r in forms else 1


class _FreqRanker:
    """Mean KANJIDIC2 newspaper-frequency rank of a writing's characters.

    JMnedict carries no frequency of its own, so the commonness of the
    characters is the best available proxy for how likely a writing is. Lower
    is more common. Degrades to a constant when the kanjidic table is absent.
    """

    def __init__(self, db: NamesDB):
        self.db = db
        self.cache: dict[str, int] = {}
        self._persons = None
        self._pcache: dict[tuple, int] = {}

    def _person_names(self):
        # JMnedict's ~54k 'person' entries are full names of real people. How
        # many of them begin with a surname writing *read the same way* (or end
        # with a given-name writing read the same way) is the best in-data proxy
        # for how common that writing-and-reading is as a name -- far better
        # than character frequency (東 is commoner than 藤, but 佐藤 is the
        # commoner surname; 佐藤 read さいとう is rare, read さとう is not).
        if self._persons is None:
            try:
                cur = self.db.conn.execute(
                    "SELECT DISTINCT kanji, kana FROM names WHERE kanji IS NOT NULL "
                    "AND (',' || name_types || ',') LIKE '%,person,%'")
                rows = [(k, kn or "") for k, kn in cur.fetchall()]
            except Exception:  # noqa: BLE001
                rows = []
            fwd = sorted(rows)
            rev = sorted((k[::-1], kn[::-1]) for k, kn in rows)
            self._persons = (fwd, rev)
        return self._persons

    @staticmethod
    def _block(sorted_rows, prefix: str):
        lo = bisect.bisect_left(sorted_rows, (prefix,))
        hi = bisect.bisect_left(sorted_rows, (prefix + "\U0010ffff",))
        return sorted_rows[lo:hi]

    def attestation(self, writing: str, role: str, kana: str | None = None) -> int:
        """Person entries containing `writing` as surname (prefix) or given
        name (suffix), longer than the writing itself, optionally only those
        whose reading carries `kana` in the same position."""
        key = (writing, role, kana)
        if key not in self._pcache:
            fwd, rev = self._person_names()
            if role == "surname":
                block = self._block(fwd, writing)
                n = sum(1 for k, kn in block if k != writing
                        and (kana is None or (kn.startswith(kana) and kn != kana)))
            else:
                w, kv = writing[::-1], (kana[::-1] if kana else None)
                block = self._block(rev, w)
                n = sum(1 for k, kn in block if k != w
                        and (kv is None or (kn.startswith(kv) and kn != kv)))
            self._pcache[key] = n
        return self._pcache[key]

    def kana_position(self, kana: str) -> tuple[int, int]:
        """Person entries whose full reading begins with `kana` (surname position)
        and ends with it (given-name position), the entry being longer than `kana`.

        JMnedict's person entries are real people written surname first, so where
        a reading sits inside them is direct evidence of which part it usually is.
        """
        key = ("pos", kana)
        if key not in self._pcache:
            if not hasattr(self, "_kana_idx"):
                fwd, _rev = self._person_names()
                kanas = sorted({kn for _k, kn in fwd if kn})
                self._kana_idx = (kanas, sorted(k[::-1] for k in kanas))
            kf, kr = self._kana_idx
            def count(rows, prefix):
                lo = bisect.bisect_left(rows, prefix)
                hi = bisect.bisect_left(rows, prefix + "\U0010ffff")
                return sum(1 for x in rows[lo:hi] if x != prefix)
            self._pcache[key] = (count(kf, kana), count(kr, kana[::-1]))
        return self._pcache[key]

    def reading_popularity(self, kana: str, role: str) -> int:
        """Name entries of any writing that carry this reading in this role."""
        key = ("pop", kana, role)
        if key not in self._pcache:
            n = 0
            for r in self.db.by_kana(kana):
                t = _types(r)
                if (role == "surname" and t & SURNAME_TYPES) or (
                        role != "surname" and any(GIVEN_TYPE_WEIGHT.get(x, 0) for x in t)):
                    n += 1
            self._pcache[key] = n
        return self._pcache[key]

    def char(self, ch: str) -> int:
        if ch not in self.cache:
            rec = self.db.get_kanjidic(ch) if _is_kanji(ch) else None
            self.cache[ch] = (rec or {}).get("frequency") or _FREQ_DEFAULT
        return self.cache[ch]

    def __call__(self, writing: str) -> float:
        chars = [c for c in writing if _is_kanji(c)]
        if not chars:
            return float(_FREQ_DEFAULT)
        return sum(self.char(c) for c in chars) / len(chars)


def _part_candidates(db: NamesDB, tok: str, role: str, rank: _FreqRanker):
    """Kanji writings of one name part, filtered to the role and ranked.

    Returns [{kanji, kana, fit, weight}] best first: exact reading fit, then
    tag weight, then character commonness.
    """
    best: dict[str, dict] = {}
    for r in _rows_for_token(db, tok):
        k, kana = r.get("kanji"), r.get("kana")
        if not k or not kana:
            continue
        t = _types(r)
        if role == "surname":
            if not t & SURNAME_TYPES:
                continue
            weight = 2
        else:
            weight = max((GIVEN_TYPE_WEIGHT.get(x, 0) for x in t), default=0)
            if not weight:
                continue
        cand = {"kanji": k, "kana": kana, "fit": _reading_fit(kana, tok), "weight": weight}
        prev = best.get(k)
        if prev is None or (cand["fit"], cand["weight"]) > (prev["fit"], prev["weight"]):
            best[k] = cand
    for c in best.values():
        c["attested"] = rank.attestation(c["kanji"], role, c["kana"])
        c["breadth"] = _surname_breadth(db, c["kanji"]) if role == "surname" else 0
    return sorted(best.values(),
                  key=lambda c: (-c["fit"], -c["weight"], -c["attested"], -c["breadth"],
                                 rank(c["kanji"]), c["kanji"]))


def _surname_breadth(db: NamesDB, writing: str) -> int:
    """How many JMnedict entries list this writing as a surname or a place name.

    A tie-breaker for surnames no listed person carries (attestation 0). A writing
    JMnedict records under several readings, and as a place, is a widespread
    toponymic surname (打越: eight entries, surname and place); a writing with a
    single surname entry is rarer (内越: one). Character commonness, the next key,
    would otherwise favour 内 over 打 and put the rarer surname first.
    """
    n = 0
    for r in db.by_kanji(writing):
        if _types(r) & (SURNAME_TYPES | {"place"}):
            n += 1
    return n


def _top_kanas(cands, n=3):
    out = []
    for c in cands:
        if c["fit"] == cands[0]["fit"] and c["kana"] not in out:
            out.append(c["kana"])
    return out[:n] or [c["kana"] for c in cands[:1]]


def _spaced_romaji(sur_kana: str, giv_kana: str) -> dict:
    a, b = romaji_variants(sur_kana), romaji_variants(giv_kana)
    return {k: f"{a[k]} {b[k]}" for k in ("hepburn_macron", "hepburn_plain", "kunrei")}


def _cap(word: str) -> str:
    # not str.title(): that would give Shin'Ichi
    return word[:1].upper() + word[1:]


def _add(bundle, col, val):
    if val and val not in bundle[col]:
        bundle[col].append(val)


def _pair_parts(db, bundle, sur_tok, giv_tok, rank):
    """Build ranked full-name kanji from a surname token and a given token.

    Attested full names (JMnedict 'person' entries whose reading equals
    surname-reading + given-reading) come first; they are the only pairings
    that are evidence rather than combinatorics. Composed pairings follow,
    ranked by reading fit and character commonness, capped.
    """
    surs = _part_candidates(db, sur_tok, "surname", rank)
    givs = _part_candidates(db, giv_tok, "given", rank)
    bundle["surname_kanji"] = [c["kanji"] for c in surs[:_MAX_PART_CANDIDATES]]
    bundle["given_kanji"] = [c["kanji"] for c in givs[:_MAX_PART_CANDIDATES]]
    if not surs or not givs:
        if surs:
            # Fall back to a surname search: better a broad match on the part we
            # can resolve than no search at all.
            bundle["kanji"] = bundle["surname_kanji"][:_MAX_FULL_NAMES]
            bundle["name_shape"] = "single"
            for k in _top_kanas(surs):
                _add(bundle, "kana", k)
        bundle["notes"].append(
            "Could not find both parts in JMnedict as surname and given name; "
            "no paired kanji produced" + ("; searching on the surname only." if surs else "."))
        if not surs and not givs:
            bundle["notes"].append(
                "Neither part is a Japanese name JMnedict knows. If the name is Korean or "
                "Chinese, its kanji cannot be generated here: the author's own "
                "romanisation governs, and the kanji must come from the source or from "
                "an authority record (name_authority; or cinii_search_researchers "
                "under the katakana reading).")
        return

    sur_kanas, giv_kanas = _top_kanas(surs), _top_kanas(givs)
    sur_set = {c["kanji"] for c in surs}
    attested = []
    for sk in sur_kanas:
        for gk in giv_kanas:
            _add(bundle, "kana", sk + gk)
            _add(bundle, "kana_split", [sk, gk])
            for key, val in _spaced_romaji(sk, gk).items():
                _add(bundle, key, val)
            for r in db.by_kana(sk + gk):
                k = r.get("kanji")
                if not k or not (_types(r) & FULL_NAME_TYPES):
                    continue
                # keep only pairings consistent with a surname writing we know
                if any(k.startswith(s) for s in sur_set) and k not in attested:
                    attested.append(k)
    attested.sort(key=rank)

    composed = []
    top_s = [c for c in surs if c["kana"] in sur_kanas][:6]
    top_g = [c for c in givs if c["kana"] in giv_kanas][:5]
    for s in top_s:
        for g in top_g:
            composed.append((s["weight"] + g["weight"],
                             math.log1p(s["attested"]) + math.log1p(g["attested"]),
                             s.get("breadth", 0),
                             rank(s["kanji"] + g["kanji"]), s["kanji"] + g["kanji"]))
    composed.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3]))

    full = []
    for k in attested:
        for kv in _kanji_variants(k):
            if kv not in full:
                full.append(kv)
    for *_, k in composed:
        if len(full) >= _MAX_FULL_NAMES:
            break
        if k not in full:
            full.append(k)
    bundle["kanji"] = full[:_MAX_FULL_NAMES]
    bundle["attested_full_names"] = attested
    if attested:
        bundle["notes"].append(
            f"JMnedict lists {len(attested)} full name(s) with this reading: "
            f"{', '.join(attested[:5])}. These lead the kanji list.")
    else:
        bundle["notes"].append(
            "No JMnedict full-name entry for this reading; kanji pairings are "
            "composed from the parts and ranked by how often JMnedict's person entries use each part with this reading — leads, "
            "not identifications.")


def _split_kanji_full_name(db, name, rank):
    """Split an unlisted kanji full name into surname + given by lookup.

    Tries every split point; keeps those where the head is a JMnedict surname
    and the tail a given name, preferring the split whose readings are best
    attested. Returns [(surname, given, sur_kana, giv_kana)] best first.
    """
    splits = []
    for i in range(1, len(name)):
        head, tail = name[:i], name[i:]
        s_rows = [r for hv in _kanji_variants(head) for r in db.by_kanji(hv)
                  if _types(r) & SURNAME_TYPES]
        g_rows = [r for r in db.by_kanji(tail)
                  if any(GIVEN_TYPE_WEIGHT.get(t, 0) for t in _types(r))]
        if s_rows and g_rows:
            # Order readings by (1) person entries attesting this writing with
            # this reading, (2) how many name types JMnedict gives the pair (a
            # reading that is also a place name is an established one), (3) how
            # many surname/given entries of any writing share the reading.
            # Without (2) and (3) unattested readings came out in arbitrary
            # order, and 打越's うちこし fell outside the kept set.
            s_types = {}
            for r in s_rows:
                s_types.setdefault(r["kana"], set()).update(_types(r))
            g_types = {}
            for r in g_rows:
                g_types.setdefault(r["kana"], set()).update(_types(r))
            s_k = sorted(s_types, key=lambda kn: (
                -max(rank.attestation(hv, "surname", kn) for hv in _kanji_variants(head)),
                -len(s_types[kn]), -rank.reading_popularity(kn, "surname"), kn))
            g_k = sorted(g_types, key=lambda kn: (
                -rank.attestation(tail, "given", kn),
                -len(g_types[kn]), -rank.reading_popularity(kn, "given"), kn))
            score = (max(rank.attestation(hv, "surname") for hv in _kanji_variants(head))
                     + rank.attestation(tail, "given"))
            splits.append((score, head, tail, s_k, g_k))
    splits.sort(key=lambda x: -x[0])
    return [(h, t, sk, gk) for _, h, t, sk, gk in splits]


def infer_name_order(db: NamesDB, token_a: str, token_b: str) -> dict:
    """Decide which of two romaji/kana tokens is surname, which is given.

    Tests both tokens against JMnedict surname vs given tags. Returns the more
    likely assignment with a confidence note. Never errors on ambiguity — it
    returns its best guess and flags low confidence.
    """
    def type_scores(tok):
        surname = given = 0
        for r in _rows_for_token(db, tok):
            types = _types(r)
            if types & SURNAME_TYPES:
                surname += 1
            if any(GIVEN_TYPE_WEIGHT.get(t, 0) == 2 for t in types):
                given += 1
        return surname, given

    a_sur, a_giv = type_scores(token_a)
    b_sur, b_giv = type_scores(token_b)

    # Primary evidence: where each token's readings sit inside JMnedict's
    # person entries (surname first). Counting distinct writings tagged surname
    # or given, the older method, is kept as the fallback: it misreads short
    # readings with many given-name writings (さと: 里, 郷, 聖 ...) and put
    # "Sato Taro" the wrong way round.
    rank = _FreqRanker(db)

    def position(tok):
        kanas = {r.get("kana") for r in _rows_for_token(db, tok) if r.get("kana")}
        if detect_script(tok) == "kana":
            kanas.add(tok)
        pre = suf = 0
        for k in kanas:
            p_, s_ = rank.kana_position(k)
            pre, suf = max(pre, p_), max(suf, s_)
        return pre, suf

    a_pre, a_suf = position(token_a)
    b_pre, b_suf = position(token_b)
    pos_ab, pos_ba = a_pre + b_suf, b_pre + a_suf
    if pos_ab + pos_ba >= 10 and pos_ab != pos_ba:
        order_ab, order_ba = pos_ab, pos_ba
        basis = "person entries"
        big, small = max(pos_ab, pos_ba), min(pos_ab, pos_ba)
        strength = big / max(small, 1)
    else:
        order_ab = a_sur + b_giv      # a=surname, b=given
        order_ba = b_sur + a_giv      # b=surname, a=given
        basis = "name tags"
        strength = None
    if order_ab >= order_ba:
        result = {"surname": token_a, "given": token_b}
        margin = order_ab - order_ba
    else:
        result = {"surname": token_b, "given": token_a}
        margin = order_ba - order_ab
    if strength is not None:
        result["confidence"] = "high" if strength >= 3 else ("moderate" if strength >= 1.5 else "low")
    else:
        result["confidence"] = "high" if margin >= 2 else ("low" if margin == 0 else "moderate")
    result["basis"] = basis
    result["evidence"] = {
        token_a: {"surname_hits": a_sur, "given_hits": a_giv,
                  "person_entries_as_surname": a_pre, "person_entries_as_given": a_suf},
        token_b: {"surname_hits": b_sur, "given_hits": b_giv,
                  "person_entries_as_surname": b_pre, "person_entries_as_given": b_suf},
    }
    return result


def name_query_variants(db: NamesDB, name: str) -> dict:
    """Turn one name into the full search bundle for the retrieval services.

    Accepts a single token, a two-token "surname given" (either order) in
    romaji or kana, or a kanji string with or without a space. For a full name
    the `kanji` list holds ranked FULL-NAME writings (attested first, capped),
    never a pool of parts; the parts are returned separately as
    `surname_kanji` / `given_kanji`. `name_shape` tells the services whether
    to match creators on the full name or on the surname only.
    """
    name = " ".join(name.strip().split())
    script = detect_script(name)
    tokens = name.split()
    rank = _FreqRanker(db)
    dropped = []
    if script != "kanji" and len(tokens) > 2:
        # "Seiichirō Yoshizawa Jr", "Prof. Ōe Kenzaburō": drop tokens JMnedict
        # does not know, so two real name parts can still be paired.
        kept = [t for t in tokens if _rows_for_token(db, t)]
        if len(kept) == 2:
            dropped = [t for t in tokens if t not in kept]
            tokens = kept

    bundle = {
        "input": name,
        "script": script,
        "name_shape": "full" if len(tokens) >= 2 else "single",
        "kanji": [],
        "surname_kanji": [],
        "given_kanji": [],
        "attested_full_names": [],
        "kana": [],
        "kana_split": [],
        "hepburn_macron": [],
        "hepburn_plain": [],
        "kunrei": [],
        "inverted": [],
        "notes": [],
    }
    if dropped:
        bundle["notes"].append(
            f"Ignored token(s) not found in JMnedict: {', '.join(dropped)}.")

    def add_readings_from_kanji(k):
        for rd in resolve_name_readings(db, k)["readings"]:
            for col in ("kana", "hepburn_macron", "hepburn_plain", "kunrei"):
                _add(bundle, col, rd[col])

    if script == "kanji":
        joined = name.replace(" ", "")
        for kv in _kanji_variants(joined):
            _add(bundle, "kanji", kv)
        add_readings_from_kanji(joined)
        attested = [kv for kv in _kanji_variants(joined)
                    if any(_types(r) & FULL_NAME_TYPES for r in db.by_kanji(kv))]
        persons = [r for r in db.by_kanji(joined) if _types(r) & FULL_NAME_TYPES]
        if attested:
            bundle["name_shape"] = "full"
            bundle["attested_full_names"] = attested
            if not bundle["kana"]:
                for kv in attested:
                    add_readings_from_kanji(kv)
        if len(tokens) == 2:
            bundle["name_shape"] = "full"
            bundle["surname_kanji"], bundle["given_kanji"] = [tokens[0]], [tokens[1]]
            attested_kana = list(bundle["kana"])
            s_kana = list(dict.fromkeys(r["kana"] for r in db.by_kanji(tokens[0])))
            g_kana = list(dict.fromkeys(r["kana"] for r in db.by_kanji(tokens[1])))
            for sk in s_kana[:_MAX_SPLIT_SURNAME_READINGS]:
                for gk in g_kana[:_MAX_SPLIT_GIVEN_READINGS]:
                    if attested_kana and sk + gk not in attested_kana:
                        continue  # the full name is listed: keep its own reading
                    _add(bundle, "kana", sk + gk)
                    _add(bundle, "kana_split", [sk, gk])
        elif len(joined) >= 3:
            splits = _split_kanji_full_name(db, joined, rank)
            if persons and bundle["kana"]:
                # attested: keep only the split whose readings concatenate to it
                splits = [(h, t, [sk for sk in sks for gk in gks
                                  if sk + gk in bundle["kana"]][:1],
                           [gk for sk in sks for gk in gks
                            if sk + gk in bundle["kana"]][:1])
                          for h, t, sks, gks in splits]
                splits = [x for x in splits if x[2] and x[3]]
            if splits:
                h, t, sks, gks = splits[0]
                bundle["name_shape"] = "full"
                bundle["surname_kanji"], bundle["given_kanji"] = [h], [t]
                # Readings of an unlisted name are guesses: keep enough of them
                # that the right one is usually present (打越 is だごし, だこし
                # and うちこし), best-attested first, rather than a tight cut.
                for sk in sks[:_MAX_SPLIT_SURNAME_READINGS]:
                    for gk in gks[:_MAX_SPLIT_GIVEN_READINGS]:
                        _add(bundle, "kana_split", [sk, gk])
                        if not persons:
                            _add(bundle, "kana", sk + gk)
                if not persons:
                    bundle["notes"].append(
                        f"No JMnedict entry for the full string; split as surname {h} + "
                        f"given {t} from part entries. The readings are candidates "
                        f"ranked by attestation, not facts: confirm against the source.")
        if attested and bundle["kana"] and not bundle["kana_split"]:
            # A listed full name whose given part is not itself in JMnedict
            # (姜尚中): find the boundary from the name's own reading, by the
            # longest surname writing whose reading begins it.
            full_kana = bundle["kana"][0]
            for i in range(len(joined) - 1, 0, -1):
                head = joined[:i]
                hits = [r["kana"] for hv in _kanji_variants(head) for r in db.by_kanji(hv)
                        if _types(r) & SURNAME_TYPES and r.get("kana")
                        and full_kana.startswith(r["kana"]) and len(r["kana"]) < len(full_kana)]
                if hits:
                    sk = max(hits, key=len)
                    bundle["surname_kanji"], bundle["given_kanji"] = [head], [joined[i:]]
                    _add(bundle, "kana_split", [sk, full_kana[len(sk):]])
                    break
        if joined[:1] in LIKELY_NON_JAPANESE_SURNAMES and (
                len(joined) >= 3 or bundle["surname_kanji"] == [joined[:1]]):
            bundle["notes"].append(
                f"{joined[:1]} is far more common as a Korean or Chinese surname than a "
                "Japanese one. JMnedict's reading (and the romaji built from it) is the "
                "Japanese katakana rendering, which is not how such authors are "
                "catalogued in English: the author's own romanisation governs.")
        if bundle["kana_split"]:
            # A known surname/given boundary: give catalogue-ready spaced romaji
            # and the inverted Given Surname order, not one joined string.
            for col in ("hepburn_macron", "hepburn_plain", "kunrei"):
                bundle[col] = []
            for sk, gk in bundle["kana_split"]:
                sp = _spaced_romaji(sk, gk)
                for key, val in sp.items():
                    _add(bundle, key, val)
                sur, giv = sp["hepburn_macron"].split(" ", 1)
                _add(bundle, "inverted", f"{_cap(giv)} {_cap(sur)}")
        if not bundle["kana"]:
            bundle["notes"].append(
                "No JMnedict reading found for this kanji string or its parts.")
    elif len(tokens) == 2:
        order = infer_name_order(db, tokens[0], tokens[1])
        for t in tokens:
            if script == "kana":
                _add(bundle, "kana", t)
            else:
                _add(bundle, "hepburn_plain", normalize_romaji(t))
        _pair_parts(db, bundle, order["surname"], order["given"], rank)
        _add(bundle, "hepburn_plain",
             f"{normalize_romaji(order['surname'])} {normalize_romaji(order['given'])}")
        if bundle["kana_split"]:
            # From the best reading, so the macron survives (Ryūichi Narita),
            # not from the tokens as typed.
            sur, giv = _spaced_romaji(*bundle["kana_split"][0])["hepburn_macron"].split(" ", 1)
            bundle["inverted"].append(f"{_cap(giv)} {_cap(sur)}")
        else:
            bundle["inverted"].append(f"{order['given']} {order['surname']}")
        bundle["notes"].append(
            f"Inferred order: surname={order['surname']}, given={order['given']} "
            f"(confidence {order['confidence']}).")
    elif script == "kana":
        _add(bundle, "kana", name)
        rv = romaji_variants(name)
        for col in ("hepburn_macron", "hepburn_plain", "kunrei"):
            _add(bundle, col, rv[col])
        for cand in resolve_name_kanji(db, name)["candidates"][:_MAX_PART_CANDIDATES * 2]:
            _add(bundle, "kanji", cand["kanji"])
    else:  # single romaji token (or 3+ tokens: treated token by token)
        for tok in tokens or [name]:
            _add(bundle, "hepburn_plain", normalize_romaji(tok))
            cands = resolve_name_kanji(db, tok)["candidates"]  # already ranked
            best_fit = _reading_fit(cands[0]["kana"], tok) if cands else 0
            for cand in cands[:_MAX_PART_CANDIDATES * 2]:
                _add(bundle, "kanji", cand["kanji"])
                if _reading_fit(cand["kana"], tok) == best_fit:
                    _add(bundle, "kana", cand["kana"])
                    rv = romaji_variants(cand["kana"])
                    _add(bundle, "hepburn_macron", rv["hepburn_macron"])
                    _add(bundle, "kunrei", rv["kunrei"])
        if len(tokens) > 2:
            bundle["name_shape"] = "single"  # no full name to match on
            bundle["notes"].append("Three or more tokens: parts looked up separately, not paired.")
    return bundle
