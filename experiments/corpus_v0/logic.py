"""Pure logic for corpus v0 (tested in test_logic.py): photo URLs, observer split, capped sampling, when an
observation reached research grade, name matching, and the small classifier and probability helpers."""

import hashlib
import re

import numpy as np
import pandas as pd

OPEN_DATA = "https://inaturalist-open-data.s3.amazonaws.com/photos/{id}/{size}.{ext}"
_PHOTO = re.compile(
    r"^https?://(?:inaturalist-open-data\.s3\.amazonaws\.com|static\.inaturalist\.org)/photos/(\d+)/original\.(\w+)"
)
SPECIES_OR_BELOW = {"species", "subspecies", "variety", "form", "hybrid"}


def open_data_url(url, size="medium"):
    """The iNaturalist open-data bucket URL of a photo at `size`, from the URL GBIF publishes (or None)."""
    m = _PHOTO.match(url or "")
    return OPEN_DATA.format(id=m.group(1), size=size, ext=m.group(2)) if m else None


def hash_unit(name, salt="corpus_v0"):
    """A stable number in [0, 1) for a name (same on every machine and run)."""
    h = hashlib.sha256(f"{salt}:{name}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def observer_split(name, test_share=0.2):
    """'test' for about test_share of observers, else 'train'. An empty name goes to test (never trained on)."""
    if not name:
        return "test"
    return "test" if hash_unit(name) < test_share else "train"


def sample_capped(df, cap, by="species", observer="observer", state="state", seed=0):
    """At most `cap` rows per `by`, spread out: every observer's first row before anyone's second, an
    observer's rows cycling through their states, and ties broken towards states seen less. Deterministic."""
    d = df.sample(frac=1, random_state=seed)
    d["_a"] = d.groupby([by, observer, state], sort=False).cumcount()
    d = d.sort_values([by, observer, "_a"], kind="stable")
    d["_k1"] = d.groupby([by, observer], sort=False).cumcount()
    d["_k2"] = d.groupby([by, state], sort=False).cumcount()
    d = d.sort_values([by, "_k1", "_k2"], kind="stable")
    return d.groupby(by, sort=False).head(cap).drop(columns=["_a", "_k1", "_k2"]).sort_index()


def _ts(s):
    return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s).tz_localize("UTC")


def research_grade_at(identifications, species_id):
    """First time the identifications made `species_id` the community taxon at species level, by iNaturalist's
    rule: at least 2 identifications of the species (or below), and those are more than 2/3 of the
    identifications that count (agreeing + conflicting; coarser ones count against only with an explicit
    disagreement). Each user's latest identification at that moment counts; hidden ones never count. None if never reached."""

    def path(i):  # root to the identification's taxon; the API leaves the taxon itself out of ancestor_ids
        t = i.get("taxon") or {}
        anc = list(t.get("ancestor_ids") or [])
        return anc if anc and anc[-1] == t.get("id") else anc + [t.get("id")]

    lineage = lambda i: set(path(i))
    above = set()  # ancestors of the species, from identifications at the species or below
    for i in identifications:
        p = path(i)
        if species_id in p:
            above |= set(p[: p.index(species_id)])
    active = {}
    shown = [i for i in identifications if not i.get("hidden")]
    for i in sorted(shown, key=lambda i: _ts(i["created_at"])):
        active[(i.get("user") or {}).get("id")] = i
        agree = disagree = 0
        for a in active.values():
            if species_id in lineage(a):
                agree += 1
            elif (a.get("taxon") or {}).get("id") in above:
                disagree += bool(a.get("disagreement"))
            else:
                disagree += 1
        if agree >= 2 and agree > 2 * (agree + disagree) / 3:
            return _ts(i["created_at"])
    return None


def species_of(taxon):
    """The species-level taxon id of an observation's taxon (None above species)."""
    if not taxon or taxon.get("rank") not in SPECIES_OR_BELOW:
        return None
    if taxon.get("rank") == "species":
        return taxon.get("id")
    return taxon.get("min_species_taxon_id")


def waited_record(obs):
    """Created date, research-grade date, waited days and number of identifiers for one iNaturalist
    observation (API v1 JSON)."""
    sp = species_of(obs.get("taxon"))
    created = _ts(obs["created_at"])
    ids = obs.get("identifications") or []
    rg = research_grade_at(ids, sp) if sp else None
    observer = (obs.get("user") or {}).get("id")
    others = {(i.get("user") or {}).get("id") for i in ids if i.get("current", True)} - {observer}
    return {
        "obs_id": obs["id"],
        "quality_grade": obs.get("quality_grade"),
        "final_species_id": sp,
        "taxon_name": (obs.get("taxon") or {}).get("name"),
        "created_at": created.isoformat(),
        "rg_at": rg.isoformat() if rg is not None else None,
        "waited_days": (rg - created).total_seconds() / 86400 if rg is not None else None,
        "n_identifiers": len(others),
    }


def match_name(names, cand, accepted):
    """(candidate, 'exact' | 'synonym') for the first of `names` that is a candidate, else the first whose
    GBIF accepted name is one; (None, None) when none matches."""
    names = [n for n in names if n]
    for n in names:
        if n in cand:
            return n, "exact"
    for n in names:
        a = accepted.get(n)
        if a and a in cand:
            return a, "synonym"
    return None, None


def softmax(x):
    x = np.asarray(x, dtype=np.float64)
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def knn_class_scores(q, train, ytr, n_classes):
    """Best cosine similarity to any training photo of each class (features L2-normalised); -inf for a
    class with no training photo."""
    sim = np.asarray(q, np.float32) @ np.asarray(train, np.float32).T
    out = np.full((len(q), n_classes), -np.inf, dtype=np.float32)
    order = np.argsort(ytr, kind="stable")
    ys = np.asarray(ytr)[order]
    classes, starts = np.unique(ys, return_index=True)
    out[:, classes] = np.maximum.reduceat(sim[:, order], starts, axis=1)
    return out


def fit_temperature(logits, y):
    """Temperature T that minimises the negative log-likelihood of softmax(logits / T) (calibration)."""
    from scipy.optimize import minimize_scalar

    logits = np.asarray(logits, np.float64)
    y = np.asarray(y)

    def nll(log_t):
        z = logits / np.exp(log_t)
        z = z - z.max(axis=1, keepdims=True)
        lse = np.log(np.exp(z).sum(axis=1))
        return float((lse - z[np.arange(len(y)), y]).mean())

    return float(np.exp(minimize_scalar(nll, bounds=(-4, 4), method="bounded").x))


def combine_probs(p_a, p_b, w=0.5):
    """Weighted average of two probability matrices over the same candidate columns."""
    return w * np.asarray(p_a) + (1 - w) * np.asarray(p_b)


def unseen_summary(df):
    """Per group: how often the true species had no training photo, and how the list did then.
    df: group, seen (bool), rank (1-based rank of the true species; inf if not a candidate)."""

    def one(g):
        u, s = g[~g.seen], g[g.seen]
        p = lambda m: round(100 * float(np.mean(m)), 1) if len(m) else None
        return {
            "n": len(g),
            "unseen": len(u),
            "unseen_pct": p(~g.seen),
            "unseen_top1": p(u["rank"] <= 1),
            "unseen_top5": p(u["rank"] <= 5),
            "unseen_top20": p(u["rank"] <= 20),
            "seen_top1": p(s["rank"] <= 1),
            "seen_top5": p(s["rank"] <= 5),
        }

    rows = [{"group": k, **one(g)} for k, g in df.groupby("group")]
    rows.append({"group": "All", **one(df)})
    return pd.DataFrame(rows)


def conformal_threshold(p_true, target):
    """Probability threshold of a split-conformal set (score 1 - p(true)) calibrated on p_true, with the same
    quantile rule as the model check (scoring._conformal). A species is in the set when p >= threshold."""
    p_true = np.asarray(p_true, dtype=np.float64)
    n = len(p_true)
    level = np.ceil((n + 1) * target) / n
    q = 1.0 if level > 1 else np.quantile(1 - p_true, level, method="higher")
    return float(1 - q)


def in_validation(observer, share=0.15):
    """Validation observers inside the training side (a second stable hash, so it is independent of the
    train/test split)."""
    return hash_unit(observer or "", salt="corpus_v0_val") < share


def fixed_k(ranks, target):
    """Smallest list length that holds the right species for `target` of rows (as scoring.shortlist_table);
    None when even the full candidate list does not."""
    r = np.sort(np.asarray(ranks, dtype=float))
    k = r[int(np.ceil(target * len(r))) - 1]
    return int(k) if np.isfinite(k) else None


# --- queue check ----------------------------------------------------------------------------------------

QUICK, GENUS_FIRST, EXPERT, NOT_ENOUGH = "Quick to confirm", "Genus first", "For an expert", "not enough data"
GATE_MIN_N, GATE_COV, GATE_MEDIAN, GATE_TOP1 = 100, 88.0, 2, 80.0
OVERLAP_MIN_N, OVERLAP_COV = 40, 85.0


def gate(r):
    """Verdict of one group by the rules fixed in the README ("Queue check"). r: n, sp_cov, sp_median, top1,
    g_cov, g_median (coverage and top-1 in %), and for rows confirmed in 2025 or later: new_n, new_sp_cov, new_g_cov."""
    if r["n"] < GATE_MIN_N:
        return NOT_ENOUGH
    if r["sp_cov"] >= GATE_COV and r["sp_median"] <= GATE_MEDIAN and r["top1"] >= GATE_TOP1:
        level, check = QUICK, r["new_sp_cov"]
    elif r["g_cov"] >= GATE_COV and r["g_median"] <= GATE_MEDIAN:
        level, check = GENUS_FIRST, r["new_g_cov"]
    else:
        return EXPERT
    if r["new_n"] >= OVERLAP_MIN_N and check < OVERLAP_COV:
        return GENUS_FIRST if level == QUICK else EXPERT
    return level


def conformal_rows(p_true, has, P, obs, target, n_splits=20, seed=0):
    """Split conformal for one group, exactly as model check scoring._conformal, but per row: how often each row
    was in a test half and covered. Returns (covered counts, tested counts, all test set sizes)."""
    rng = np.random.default_rng(seed)
    p_true, has, obs = np.asarray(p_true, float), np.asarray(has, bool), np.asarray(obs)
    covered, tested, sizes = np.zeros(len(obs), int), np.zeros(len(obs), int), []
    rows = np.arange(len(obs))
    for _ in range(n_splits):
        ids = rng.permutation(np.unique(obs))
        cal_ids = set(ids[: len(ids) // 2])
        cal = np.array([o in cal_ids for o in obs])
        c, te = rows[cal], rows[~cal]
        if len(c) == 0 or len(te) == 0:
            continue
        level = np.ceil((len(c) + 1) * target) / len(c)
        q = 1.0 if level > 1 else np.quantile(1 - p_true[c], level, method="higher")
        thr = 1 - q
        for i in te:
            tested[i] += 1
            covered[i] += bool(has[i] and p_true[i] >= thr)
            sizes.append(int((P[i] >= thr).sum()))
    return covered, tested, sizes


def next_sample_size(n_sampled, n_qualify, pool, target=100, cap=4000, min_step=200):
    """How many observations of a group to have sampled after the next round: enough (by the rate so far, with a
    20% margin) to reach `target` qualifying rows, at least `min_step` more, never above the cap or the pool."""
    limit = min(cap, pool)
    if n_qualify >= target or n_sampled >= limit:
        return n_sampled
    rate = max(n_qualify, 1) / n_sampled
    need = int(np.ceil((target - n_qualify) / rate * 1.2))
    return min(limit, n_sampled + max(min_step, need))


_API_PHOTO = re.compile(
    r"^https?://(?:inaturalist-open-data\.s3\.amazonaws\.com|static\.inaturalist\.org)/photos/(\d+)/\w+\.(\w+)"
)


def medium_from_api_url(url, size="medium"):
    """Open-data bucket URL at `size` from a photo URL the iNaturalist API gives (any size), or None."""
    m = _API_PHOTO.match(url or "")
    return OPEN_DATA.format(id=m.group(1), size=size, ext=m.group(2)) if m else None


def queue_match(group, taxon_name, rank, by_group, genera, accepted):
    """(candidate species or genus, 'species' | 'genus') for a waiting observation's current taxon, if it is a
    candidate species of its group (exact, then GBIF synonym) or a genus with a candidate species; else (None, None)."""
    if rank in SPECIES_OR_BELOW:
        name, _ = match_name([" ".join(str(taxon_name).split()[:2])], by_group.get(group, set()), accepted)
        return (name, "species") if name else (None, None)
    if rank == "genus" and taxon_name in genera.get(group, set()):
        return taxon_name, "genus"
    return None, None


def recheck_outcome(frozen, now, final_species):
    """What happened to one frozen observation. frozen: its frozen row (names joined by "|"); now: the slimmed
    API answer; final_species: its current species matched to the group's candidates, or None. Shortlist hits are
    None unless it reached research grade."""
    split = lambda s: [x for x in str(s or "").split("|") if x]
    if now.get("missing"):
        return {"reached_rg": False, "changed_taxon": None, "final_species": None, "in_shown": None,
                "in_set90": None, "first": None, "in_top5": None, "genus_in_shown": None}  # fmt: skip
    rg = now.get("quality_grade") == "research"
    out = {"reached_rg": rg, "changed_taxon": now.get("taxon_id") != frozen["taxon_id"], "final_species": None}
    if not rg:
        return {**out, "in_shown": None, "in_set90": None, "first": None, "in_top5": None, "genus_in_shown": None}
    top = split(frozen["top_names"])
    g = final_species.split()[0] if final_species else None
    return {
        **out,
        "final_species": final_species,
        "in_shown": final_species in split(frozen["shown_species"]),
        "in_set90": final_species in split(frozen["set90"]),
        "first": bool(top) and final_species == top[0],
        "in_top5": final_species in top[:5],
        "genus_in_shown": g in split(frozen["shown_genera"]),
    }


# --- live shortlist files (docs/shortlist_data.md) ------------------------------------------------------

MAX_NAMES, MAX_GENERA_SHOWN = 3, 5
EASE_OF = {"quick": "Quick to confirm", "genus": "For an expert", "expert": "For an expert"}  # shortlist.EASE keys


def compact(obj):
    """Compact JSON, keys in insertion order, UTF-8 kept: the same object always gives the same bytes."""
    import json

    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def public_row(o, band, names, genera, state):
    """One row of a group file, as the contract: no coordinates, no probabilities. o: the iNaturalist API
    observation; state: its LGD state code (dropped when the location is obscured)."""
    ph, t = (o.get("photos") or [{}])[0], o.get("taxon") or {}
    return {
        "id": o["id"],
        "url": f"https://www.inaturalist.org/observations/{o['id']}",
        "photo": medium_from_api_url(ph.get("url")),
        "attribution": ph.get("attribution"),
        "licence": ph.get("license_code"),
        "observed": o.get("observed_on"),
        "place": o.get("place_guess"),
        "state": None if o.get("obscured") else state,
        "now": {"name": t.get("name"), "rank": t.get("rank")},
        "band": band,
        "names": list(names)[:MAX_NAMES] if band == "quick" else [],
        "genera": list(genera)[:MAX_GENERA_SHOWN],
    }


def live_order(rows):
    """Most useful first: pipeline.shortlist priority (value with no flags is 1, so the band's ease: quick before
    genus), then the longest waiting (oldest created), then id."""
    from pipeline.shortlist import priority, value

    return sorted(rows, key=lambda r: (-priority(value({}), EASE_OF[r["band"]]), r["created_at"], r["id"]))


def paginate(rows, encode, max_bytes):
    """Split rows in order into pages whose encoded size is at most max_bytes (a row alone may exceed it).
    encode(rows) must embed the rows as one compact JSON list, so a page's size is the size of encode([]) plus
    each row's compact size plus one comma between rows (exact, no re-encoding)."""
    base = len(encode([]).encode())
    pages, cur, size = [], [], base
    for r in rows:
        n = len(compact(r).encode())
        if cur and size + n + 1 > max_bytes:
            pages.append(cur)
            cur, size = [], base
        size += n + (1 if cur else 0)
        cur.append(r)
    pages.append(cur)
    return pages


def done_ids(answers, shown):
    """Shown observations a person no longer needs to look at: research grade or casual on iNaturalist now, or not
    returned at all (deleted or made private). answers: the observation records of a re-check."""
    now = {int(a["id"]): a.get("quality_grade") for a in answers}
    return {int(i) for i in shown if now.get(int(i), "gone") in ("research", "casual", "gone")}


def page_name(key, n):
    """File name of page n of a group (docs/shortlist_data.md): the first page has no number."""
    return f"{key}.json" if n == 1 else f"{key}.{n}.json"
