"""Place-name matcher: propose an LGD district (and a point with a radius) from a record's text fields.

No model and no paid service: names from a gazetteer (LGD states, districts, subdistricts, blocks, villages;
protected areas; a short table of old district names), compared after simple normalising and a sound key that
folds common transliteration variants.

Rules:
- Each field is cut into phrases at punctuation and at words such as "near", "from", "of". Words such as
  "District", "Dist.", "Taluk", "WLS", "NP", "Hills" are removed and kept as a hint of the kind of place.
- A whole phrase can match any place; a part of a phrase (1 to 3 words) only a district, an old district name, a
  subdistrict, a block or a protected area, so that common village names inside longer text do not match.
- State text (stateprovince, or a state name in another field) keeps only the places in that state.
- Each matched phrase votes for the districts its places are in. The district with the most votes wins; a tie
  (one name, several districts) gives no district, and the candidates are kept.
- The point is the most specific matched place in the winning district (village, then protected area, then
  subdistrict or block, then district), with its radius.
"""

import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pipeline import unlocated  # noqa: E402

FIELDS = ("stateprovince", "county", "municipality", "locality", "verbatimlocality", "highergeography",
          "island", "islandgroup", "waterbody", "eventremarks")

# Suffixes that name the kind of place, longest first. Value: the hint they give.
SUFFIXES = [
    ("wildlife sanctuary", "pa"), ("bird sanctuary", "pa"), ("tiger reserve", "pa"), ("national park", "pa"),
    ("reserve forest", "pa"), ("reserved forest", "pa"), ("biosphere reserve", "pa"), ("game sanctuary", "pa"),
    ("sanctuary", "pa"), ("wls", "pa"), ("ws", "pa"), ("np", "pa"), ("rf", "pa"), ("tr", "pa"),
    ("forests", "pa"), ("forest", "pa"), ("hills", "pa"), ("hill", "pa"), ("reserve", "pa"), ("ghats", "pa"),
    ("district", "district"), ("dist", "district"), ("distt", "district"), ("dt", "district"),
    ("dstt", "district"), ("distr", "district"),
    ("taluka", "subdistrict"), ("taluk", "subdistrict"), ("tq", "subdistrict"), ("tehsil", "subdistrict"),
    ("tahsil", "subdistrict"), ("mandal", "subdistrict"), ("subdivision", "subdistrict"),
    ("sub division", "subdistrict"), ("block", "subdistrict"), ("range", "subdistrict"),
    ("division", "subdistrict"),
    ("village", "village"), ("vill", "village"), ("town", "village"), ("city", "village"),
    ("state", None), ("area", None), ("region", None), ("environs", None), ("surroundings", None),
]
PREFIXES = ("near", "nr", "the", "vill", "village", "dist", "district", "at")
# Words that split a field into phrases.
CONNECTORS = r"near|nr|from|of|between|and|to|via|towards|toward|on|in|at|along|above|below|behind|off|opp|opposite|around|beyond|en route"
# Tokens that carry no place name (distances, directions, numbers).
NOISE = {"km", "kms", "mi", "miles", "mile", "ft", "feet", "m", "mt", "mts", "alt", "elev", "ca", "c", "approx",
         "n", "s", "e", "w", "ne", "nw", "se", "sw", "nne", "ene", "ese", "sse", "ssw", "wsw", "wnw", "nnw",
         "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "road", "rd"}
# Words that are never a place alone, though some villages have these names.
COMMON = {"forest", "road", "river", "lake", "hill", "hills", "camp", "station", "temple", "garden", "college",
          "school", "university", "india", "village", "town", "city", "farm", "field", "market", "beach", "sea",
          "dam", "valley", "jungle", "park", "nursery", "campus", "estate", "colony", "nagar", "bazar", "pond",
          "stream", "nala", "nallah", "tank", "island", "islands", "bay", "creek", "coast", "plains", "sanctuary",
          "reserve", "unknown", "locality", "data", "none", "not", "sin", "no", "west", "east", "north", "south",
          "central", "upper", "lower", "new", "old", "big", "small", "base", "top", "point", "port", "fort",
          "hospital", "airport", "railway", "bridge", "canal", "wetland", "grassland", "plantation", "mountain",
          "mountains", "peak", "himalaya", "himalayas", "ghats", "western", "eastern", "southern", "northern",
          "mangrove", "mangroves", "backwaters", "cave", "caves", "waterfall", "falls", "spring", "ocean",
          "bengal", "arabian", "deccan", "malabar", "konkan", "coromandel", "terai", "doon", "assam hills",
          "urban", "rural", "pargana", "parganas", "botanic", "botanical", "gardens", "hort", "cult", "cultivated",
          "greenhouse", "herbarium", "institute", "zoo", "district", "range", "division"}

# Older states covered what is now a later state: state text keeps those places too (the answer is still the
# district's present state). J&K had Ladakh (2019), Andhra Pradesh had Telangana (2014), Uttar Pradesh had
# Uttarakhand, Bihar had Jharkhand, Madhya Pradesh had Chhattisgarh (2000), Assam had Meghalaya, Mizoram,
# Nagaland and Arunachal Pradesh (1963-1987), Punjab had Haryana and parts of Himachal Pradesh (1966).
LATER = {1: {37}, 28: {36}, 9: {5}, 10: {20}, 23: {22}, 18: {17, 15, 13, 12}, 3: {6, 2}}
# "60 km SW of X": the place is not X itself. 5 km or more (3 miles) lowers the confidence.
OFFSET = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(km|kms|kilometers|kilometres|mi|miles?)\b")

LEVEL = {"district": 0, "alias": 0, "subdistrict": 1, "block": 1, "pa": 1, "village": 2}
KIND_RANK = {"village": 0, "pa": 1, "subdistrict": 2, "block": 2, "district": 3, "alias": 3}
WEIGHT = {"district": 2.0, "alias": 2.0, "pa": 2.0, "subdistrict": 1.5, "block": 1.5, "village": 1.0}
PART_KINDS = {"district", "alias", "subdistrict", "block", "pa"}
HINT_KINDS = {"district": {"district", "alias"}, "subdistrict": {"subdistrict", "block"}, "pa": {"pa"},
              "village": {"village"}}


def normalise(text):
    """Lower case, accents and punctuation removed, '&' read as 'and', spaces collapsed."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).split())


FOLDS = [("sh", "s"), ("th", "t"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("ph", "p"),
         ("jh", "j"), ("w", "v"), ("ee", "i"), ("oo", "u"), ("aa", "a")]


def sound_key(text):
    """One key for common transliteration variants: case, punctuation, spaces, doubled letters, aa/a, ee/i,
    oo/u, w/v, sh/s, th/t (and other aspirates), final y/i."""
    k = normalise(text).replace(" ", "")
    for a, b in FOLDS:
        k = k.replace(a, b)
    k = re.sub(r"(.)\1+", r"\1", k)
    return k[:-1] + "i" if k.endswith("y") else k


def strip_generic(words, with_hint=False):
    """Remove kind-of-place words ('District', 'Taluk', 'WLS', 'near'...) from a normalised phrase."""
    hint, changed = None, True
    while changed and words:
        changed = False
        for suf, h in SUFFIXES:
            if words == suf:
                break
            if words.endswith(" " + suf):
                words, hint, changed = words[: -len(suf) - 1], hint or h, True
                break
        for pre in PREFIXES:
            if words.startswith(pre + " "):
                words, changed = words[len(pre) + 1:], True
    return (words, hint) if with_hint else words


@dataclass(frozen=True)
class Phrase:
    text: str
    hint: str | None
    part: bool = False  # a part of a longer phrase


def phrases(raw):
    """Phrases of one field: whole pieces (with hints) and, for longer pieces, their parts of 1 to 3 words."""
    out = []
    raw = re.sub(r"(?i)\b(dist|distt|dt|nr|vill|tq)\.", r"\1 ", str(raw))
    for piece in re.split(r"[,;:/()\[\]|\n\t\"]+|\s[-–]\s|\.\s+|\.$", raw):
        for sub in re.split(rf"\b(?:{CONNECTORS})\b", normalise(piece)):
            toks = [t for t in sub.split() if not t.isdigit() and not re.fullmatch(r"\d+(?:km|m|ft|kms)?", t)]
            if not toks or all(t in NOISE for t in toks):
                continue
            core, hint = strip_generic(" ".join(toks), with_hint=True)
            if not core:
                continue
            out.append(Phrase(core, hint))
            words = core.split()
            if len(words) > 1:
                for n in range(min(3, len(words) - 1), 0, -1):
                    for i in range(len(words) - n + 1):
                        part = " ".join(words[i:i + n])
                        if part not in COMMON:
                            out.append(Phrase(part, None, True))
    return out


@dataclass(frozen=True)
class Entry:
    kind: str  # state, district, alias, subdistrict, block, village, pa
    name: str
    state_lgd: int | None
    dist_lgd: int | None
    lat: float | None
    lon: float | None
    radius_km: float | None


class Gazetteer:
    def __init__(self, entries):
        self.index = defaultdict(list)
        for e in entries:
            if e.kind == "state":
                continue
            words = " ".join(t for t in normalise(re.sub(r"\(.*?\)", " ", e.name)).split() if not t.isdigit())
            k = sound_key(strip_generic(words))
            if k:
                self.index[k].append(e)
        # One place may appear twice under a key (official and short name of a protected area): keep one.
        for k, v in self.index.items():
            self.index[k] = list(dict.fromkeys(v))

    def lookup(self, key):
        return self.index.get(key, [])


@dataclass
class Result:
    dist_lgd: int | None = None
    state_lgd: int | None = None
    lat: float | None = None
    lon: float | None = None
    radius_km: float | None = None
    kind: str | None = None
    confidence: str | None = None
    candidates: list = field(default_factory=list)
    matched: str = ""


_STATE_NAMES = None


def default_state_names():
    global _STATE_NAMES
    if _STATE_NAMES is None:
        _STATE_NAMES = unlocated.load_state_names()
    return _STATE_NAMES


def state_evidence(rec, phrase_lists, state_names):
    """States the record's text names: its stateprovince (as query L reads it), a piece of any field that is a
    state name (3 letters or more, so "Goa" but not "UP"), or a state name (4 letters or more) inside a phrase."""
    found = set()
    sp = unlocated.state_of(rec.get("stateprovince") or "", state_names)
    if sp:
        found.add(sp)
    for f, ps in phrase_lists:
        # Pieces as written, so state_of can drop its own words ("Andaman Islands", "State of Kerala").
        pieces = [(t, 3) for t in re.split(r"[,;:/()]", str(rec[f]))]
        pieces += [(p.text, 4) for p in ps if not p.part or len(p.text) >= 5]
        for t, shortest in pieces:
            s = unlocated.state_of(t, state_names) if len(unlocated.key(t)) >= shortest else None
            if s:
                found.add(s)
    return found


def without_states(text, state_names):
    """The text without its pieces that name a state ("Jammu and Kashmir" is not Jammu)."""
    pieces = re.split(r"[,;:/()\[\]|]", str(text))
    return ", ".join(p for p in pieces if not unlocated.state_of(re.sub(r"\d+", " ", p), state_names))


def offset(rec):
    for f in FIELDS:
        for n, unit in OFFSET.findall(str(rec.get(f) or "")):
            if float(n) >= (5 if unit.lower().startswith("k") else 3):
                return True
    return False


def match(rec, gaz, state_names=None):
    """Propose a district (and point) for one record, a dict of text fields (keys as in FIELDS)."""
    state_names = default_state_names() if state_names is None else state_names
    phrase_lists = [(f, phrases(without_states(rec[f], state_names))) for f in FIELDS if rec.get(f)]
    states = state_evidence(rec, phrase_lists, state_names)
    # An old state named with its later part ("Kashmir, Ladakh") means the later state.
    states = {s for s in states if not LATER.get(s, set()) & states}
    allowed = states | {s for st in states for s in LATER.get(st, ())}
    votes = []  # (weight, entries, phrase text)
    seen = set()
    for f, ps in phrase_lists:
        for p in ps:
            key = sound_key(p.text)
            if key in seen or len(key) < 3 or p.text in COMMON:
                continue
            if not p.part and unlocated.key(p.text) in state_names:
                continue
            entries = gaz.lookup(key)
            if p.part:
                entries = [e for e in entries if e.kind in PART_KINDS and len(key) >= 5]
            elif len(key) < 4:
                entries = [e for e in entries if e.kind in PART_KINDS]
            wanted = HINT_KINDS.get(p.hint) or ({"district", "alias"} if f == "county" else None)
            if wanted and any(e.kind in wanted for e in entries):
                entries = [e for e in entries if e.kind in wanted]
            if allowed:
                entries = [e for e in entries if e.state_lgd in allowed]
            if not entries:
                continue
            # A name that is a district (or a subdistrict, block or protected area) means that place, not the
            # villages elsewhere that share the name.
            top = min(LEVEL[e.kind] for e in entries)
            entries = [e for e in entries if LEVEL[e.kind] == top]
            seen.add(key)
            w = max(WEIGHT[e.kind] for e in entries)
            if f == "county" or p.hint == "district":
                w += 1.0
            votes.append((w, entries, p.text, f))
    # A name inside a longer matched name of the same field is not a second place ("Calcutta" in
    # "Botanic Garden Calcutta", "Sikkim" in "East Sikkim").
    votes = [v for v in votes if not any(o[3] == v[3] and o[2] != v[2] and f" {v[2]} " in f" {o[2]} " for o in votes)]
    r = decide([v[:3] for v in votes], states, allowed)
    if r.confidence and offset(rec):
        r.confidence = "low"
    return r


def decide(votes, states, allowed=frozenset()):
    r = Result()
    score, support, strong = defaultdict(float), defaultdict(int), set()
    for w, entries, _ in votes:
        for d in {e.dist_lgd for e in entries if e.dist_lgd is not None}:
            score[d] += w
            support[d] += 1
            if any(e.kind in ("district", "alias") and e.dist_lgd == d for e in entries):
                strong.add(d)
    ranked = sorted(score, key=lambda d: -score[d])
    if ranked and (len(ranked) == 1 or score[ranked[0]] > score[ranked[1]]):
        d = ranked[0]
        inside = [(e, t) for _, entries, t in votes for e in entries if e.dist_lgd == d]
        best = min(KIND_RANK[e.kind] for e, _ in inside)
        pick = [(e, t) for e, t in inside if KIND_RANK[e.kind] == best and e.lat is not None]
        r.dist_lgd, r.state_lgd = d, inside[0][0].state_lgd
        if pick:
            r.kind = pick[0][0].kind
            r.lat = sum(e.lat for e, _ in pick) / len(pick)
            r.lon = sum(e.lon for e, _ in pick) / len(pick)
            spread = max(haversine_km(r.lat, r.lon, e.lat, e.lon) for e, _ in pick)
            r.radius_km = max(1.0, max(e.radius_km or 0 for e, _ in pick) + spread)
            r.matched = "; ".join(dict.fromkeys(t for _, t in pick))
        if d in strong or support[d] >= 2:
            r.confidence = "high"
        elif r.state_lgd in (allowed or states):
            r.confidence = "medium"
        else:
            r.confidence = "low"
        return r
    top = score[ranked[0]] if ranked else None
    r.candidates = [d for d in ranked if score[d] == top][:20]
    if len(states) == 1:
        r.state_lgd = next(iter(states))
    else:
        cand_states = {e.state_lgd for _, entries, _ in votes for e in entries}
        if len(cand_states) == 1:
            r.state_lgd = cand_states.pop()
    return r


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))
