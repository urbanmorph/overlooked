"""Module 6: species shortlists for taxonomists (docs/plan.md, section 1d).

A model only makes a shortlist. A taxonomist approves every name, on iNaturalist or on the India Biodiversity
Portal. Nothing here posts an identification or changes a status, a count or a label. The output shows bands
and ordered names only, never raw scores.

Per waiting observation, from its candidate scores (one per species of its group) and the group's calibration:
  Quick to confirm   the group passed calibration and this observation's set is short (at most max_size names):
                     the species shortlist is shown.
  For an expert      the group did not pass, has no calibration, or this set is long or empty: no species names,
                     only a genus shortlist (probabilities summed per genus), or the group alone when the genus
                     set is long too. So the guess does not bias the expert.
  Needs a specimen   the group is marked "not identifiable from a photo": no names.

Sets, per group, from held-out photos of the corpus (split by observation and observer: the caller's job):
  conformal   split conformal. The threshold is the k-th largest probability of the true species, with
              k = ceil((n + 1) * target); the set is every candidate at or above it. A name outside the candidate
              list counts as probability 0, so a group that often lacks the right name gets threshold 0 (the
              whole list) and fails.
  fixed_k     the k best names, k the rank of the true species that covers the target (same order statistic).
A group passes when its sets reach the target coverage (less COVERAGE_SLACK when measured on a test split) with
a median size of at most max_size (default 3). Fewer than MIN_N held-out photos: calibration is refused.

Calibration file (JSON, FORMAT_VERSION 1):
  {"format": "overlooked-shortlist-calibration", "version": 1, "calibration_version": "<12 hex>",
   "created": "<UTC>", "groups": {"<group>": <entry>}}
  entry: identifiable (bool); and for identifiable groups: method, target, threshold (null for fixed_k), k,
  genus_threshold, coverage, median_size, p90_size, n, n_test, measured_on ("calibration" or "test"), max_size,
  max_genera, input ("probs" or "logits"), temperature, model_id, corpus_version, date, passed, reason.
  calibration_version is a checksum of the groups, so the same calibration always has the same version.

Score shards (one .npz per group or part of a group, written by the model code in experiments/):
  group (str), model (str, must equal the entry's model_id), names (C,), obs_id (n,), state (n,), and either
  scores (n, C) (probabilities or logits, as the entry's input says) or feats (n, D) with a linear head
  <heads>/<slug(group)>.npz: names (C,), weights (C, D), optional bias (C,), optional scale (logits =
  scale * feats @ weights.T + bias; a CLIP zero-shot head is the normalised text vectors and the logit scale,
  a trained probe is its coefficients). Optional bool (n,) flags: see VALUE_FLAGS.

Output rows (compact JSON, <out>/<shard>.json, one list per shard):
  {"obs", "group", "state", "band", "shortlist": [{"rank", "name"}], "genera": [{"rank", "name"}],
   "model", "calibration", "value"}
<out>/manifest.json records, per shard, the checksums of its inputs and output and the calibration version.
A shard with the same inputs and calibration and an intact output is skipped, so a second run does no work and a
stopped run continues. Rows stay on this machine: no corpus, embeddings or rows leave it before the legal
answers (plan 1d, "Legal questions").

How the model plugs in: model encoding stays in experiments/ (torch, open_clip). That code writes score or
feature shards, and held-out shards for calibration (group, names, scores, true; optional test_scores,
test_true). This module needs numpy only.

Usage:
  python -m pipeline.shortlist calibrate --heldout DIR --model ID --corpus VERSION --out cal.json
         [--method conformal|fixed_k] [--target 0.9] [--max-size 3] [--input probs|logits] [--temperature 1]
         [--not-identifiable GROUP ...]
  python -m pipeline.shortlist score --features DIR --calibration cal.json [--heads DIR] [--out DIR] [--minutes 60]
"""

import argparse
import hashlib
import json
import math
import re
import time
from datetime import date as _date
from pathlib import Path

import numpy as np

from pipeline.r2 import sha256
from pipeline.util import dump, log, now

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "shortlist"

QUICK, EXPERT, SPECIMEN = "Quick to confirm", "For an expert", "Needs a specimen"
FORMAT, FORMAT_VERSION = "overlooked-shortlist-calibration", 1
METHODS = ("conformal", "fixed_k")
INPUTS = ("probs", "logits")
MIN_N = 100           # held-out photos a group needs before it is calibrated
MAX_SIZE = 3          # longest species set that is "Quick to confirm"
MAX_GENERA = 5        # longest genus set shown to an expert; longer: the group only
COVERAGE_SLACK = 0.02  # allowed shortfall of coverage measured on a test split
ENTRY_KEYS = ("method", "target", "threshold", "k", "genus_threshold", "coverage", "median_size", "p90_size",
              "n", "measured_on", "max_size", "max_genera", "input", "temperature", "model_id",
              "corpus_version", "date", "passed")

# Value of a confirmation, for the queue order (value x ease). Weights are powers of two in this order, so a
# higher flag always outranks any mix of lower ones: first record in a state > threatened (IUCN CR, EN, VU) >
# endemic to India > on checklists only (no observation). Every observation starts at 1.
VALUE_FLAGS = ("first_in_state", "threatened", "endemic", "listed_only")
EASE = {QUICK: 1.0, EXPERT: 0.25, SPECIMEN: 0.05}


class CalibrationError(ValueError):
    """A calibration file that is not valid."""


class CalibrationTooSmall(ValueError):
    """Too few held-out photos to calibrate a group."""


# --- probabilities ---

def softmax(scores, temperature=1.0):
    s = np.asarray(scores, dtype=np.float64) / temperature
    s = np.exp(s - s.max(axis=-1, keepdims=True))
    return s / s.sum(axis=-1, keepdims=True)


def to_probs(scores, entry):
    """Probabilities from a model's scores: softmax with the entry's temperature for logits, else as given."""
    if entry["input"] == "logits":
        return softmax(scores, entry["temperature"])
    return np.asarray(scores, dtype=np.float64)


def genus(name):
    return str(name).split()[0]


def genus_probs(p, names):
    """Probabilities summed per genus. Returns (genera in first-seen order, array over the last axis)."""
    genera = list(dict.fromkeys(genus(n) for n in names))
    codes = np.array([genera.index(genus(n)) for n in names])
    p = np.asarray(p, dtype=np.float64)
    out = np.zeros(p.shape[:-1] + (len(genera),))
    for j in range(len(genera)):
        out[..., j] = p[..., codes == j].sum(axis=-1)
    return genera, out


# --- sets ---

def _order_stat(n, target):
    """1-based rank k = ceil((n + 1) * target) of split conformal (rounded to avoid 90.00000001)."""
    return math.ceil(round((n + 1) * target, 9))


def conformal_threshold(p_true, target):
    """k-th largest probability of the true class; 0.0 (every candidate) when k > n."""
    p_true = np.asarray(p_true, dtype=np.float64)
    k = _order_stat(len(p_true), target)
    return 0.0 if k > len(p_true) else float(np.sort(p_true)[::-1][k - 1])


def fixed_k(ranks, target):
    """List length that holds the true class for the target share; None when it is not a candidate often enough."""
    ranks = np.asarray(ranks, dtype=np.float64)
    k = _order_stat(len(ranks), target)
    if k > len(ranks):
        return None
    r = np.sort(ranks)[k - 1]
    return None if not np.isfinite(r) else int(r)


def prediction_set(p, threshold=None, k=None):
    """Indices of the set, best first (ties by position): every candidate at or above threshold, or the k best."""
    p = np.asarray(p, dtype=np.float64)
    order = np.argsort(-p, kind="stable")
    if k is not None:
        return [int(i) for i in order[:k]]
    return [int(i) for i in order if p[i] >= threshold]


def _species_set(p, entry):
    if entry["method"] == "fixed_k":
        return prediction_set(p, k=entry["k"])
    return prediction_set(p, threshold=entry["threshold"])


# --- one observation ---

def shortlist(scores, names, entry):
    """Band and ordered names for one observation. entry: the group's calibration entry, or None."""
    if len(scores) != len(names):
        raise ValueError(f"{len(scores)} scores for {len(names)} candidate names")
    if entry is None:
        return {"band": EXPERT, "species": [], "genera": []}
    if not entry["identifiable"]:
        return {"band": SPECIMEN, "species": [], "genera": []}
    p = to_probs(scores, entry)
    species = [names[i] for i in _species_set(p, entry)]
    genera, gp = genus_probs(p, names)
    gset = [genera[i] for i in prediction_set(gp, threshold=entry["genus_threshold"])] \
        if entry["genus_threshold"] is not None else []
    if len(gset) > entry["max_genera"]:
        gset = []
    if entry["passed"] and 1 <= len(species) <= entry["max_size"]:
        return {"band": QUICK, "species": species, "genera": gset}
    return {"band": EXPERT, "species": [], "genera": gset}


def value(flags):
    """Value of confirming one observation, from its flags (see VALUE_FLAGS); 1 with no flags."""
    unknown = set(flags) - set(VALUE_FLAGS)
    if unknown:
        raise ValueError(f"unknown value flags: {sorted(unknown)}")
    return 1 + sum(2 ** (len(VALUE_FLAGS) - i) for i, f in enumerate(VALUE_FLAGS) if flags.get(f))


def priority(val, band):
    """Queue order: value times ease of the band (higher first)."""
    return val * EASE[band]


def row(obs_id, group, state, result, entry, calibration_version, flags=None):
    """One row for the site: bands and ranked names only."""
    ranked = lambda xs: [{"rank": i + 1, "name": n} for i, n in enumerate(xs)]
    return {
        "obs": obs_id, "group": group, "state": state, "band": result["band"],
        "shortlist": ranked(result["species"]), "genera": ranked(result["genera"]),
        "model": (entry or {}).get("model_id"), "calibration": calibration_version, "value": value(flags or {}),
    }


# --- calibration ---

def _truth(p, names, true_names):
    """Probability and rank of the true species (0 and inf when it is not a candidate), and the genus probability."""
    pos = {n: i for i, n in enumerate(names)}
    genera, gp = genus_probs(p, names)
    gpos = {g: i for i, g in enumerate(genera)}
    p_true, ranks, g_true = [], [], []
    for pi, gpi, t in zip(p, gp, true_names):
        i = pos.get(t)
        p_true.append(pi[i] if i is not None else 0.0)
        ranks.append(1 + int((pi > pi[i]).sum()) if i is not None else np.inf)
        j = gpos.get(genus(t))
        g_true.append(gpi[j] if j is not None else 0.0)
    return np.array(p_true), np.array(ranks), np.array(g_true)


def specimen_entry(reason):
    """Entry for a group marked not identifiable from a photo."""
    return {"identifiable": False, "reason": reason}


def calibrate(scores, names, true_names, *, model_id, corpus_version, date=None, method="conformal",
              target=0.9, max_size=MAX_SIZE, max_genera=MAX_GENERA, input="probs", temperature=1.0,
              test=None, min_n=MIN_N):
    """Calibration entry for one group from held-out scores (n, C) and the true names. With test=(scores, names),
    coverage and set sizes are measured there; else on the calibration photos."""
    if method not in METHODS:
        raise ValueError(f"method {method!r}: use one of {METHODS}")
    n = len(true_names)
    if n < min_n:
        raise CalibrationTooSmall(f"{n} held-out photos; at least {min_n} needed")
    meta = {"input": input, "temperature": temperature}
    p = to_probs(scores, meta)
    p_true, ranks, g_true = _truth(p, names, true_names)
    thr = conformal_threshold(p_true, target) if method == "conformal" else None
    k = fixed_k(ranks, target)
    entry = {"identifiable": True, "method": method, "target": target, "threshold": thr, "k": k,
             "genus_threshold": conformal_threshold(g_true, target), "n": n, "n_test": 0,
             "measured_on": "calibration", "max_size": max_size, "max_genera": max_genera, **meta,
             "model_id": model_id, "corpus_version": corpus_version,
             "date": date or _date.today().isoformat()}
    if test is not None:
        p, true_names = to_probs(test[0], meta), test[1]
        p_true, ranks, _ = _truth(p, names, true_names)
        entry.update(n_test=len(true_names), measured_on="test")
    if method == "fixed_k" and k is None:
        covered, sizes = np.zeros(len(p), bool), np.full(len(p), len(names))
    elif method == "fixed_k":
        covered, sizes = ranks <= k, np.full(len(p), min(k, len(names)))
    else:
        covered, sizes = p_true >= thr, (p >= thr).sum(axis=1)
        covered &= p_true > 0
    entry.update(coverage=round(float(covered.mean()), 4), median_size=int(np.median(sizes)),
                 p90_size=int(np.percentile(sizes, 90)))
    slack = COVERAGE_SLACK if entry["measured_on"] == "test" else 0.0
    reasons = []
    if method == "fixed_k" and k is None:
        reasons.append(f"the right name is a candidate for under {target:.0%} of photos")
    elif entry["coverage"] < target - slack:
        reasons.append(f"coverage {entry['coverage']:.1%} under the target {target:.0%}")
    if entry["median_size"] > max_size:
        reasons.append(f"median set of {entry['median_size']} names, more than {max_size}")
    reason = "; ".join(reasons) or None
    entry.update(passed=reason is None, reason=reason)
    return entry


def calibrate_groups(data, **kw):
    """data: {group: (scores, names, true_names[, test])}. Returns ({group: entry}, {group: why refused})."""
    groups, refused = {}, {}
    for g, args in data.items():
        scores, names, true_names, *rest = args
        try:
            groups[g] = calibrate(scores, names, true_names, test=rest[0] if rest else None, **kw)
        except CalibrationTooSmall as e:
            refused[g] = str(e)
            log(f"  {g}: not calibrated: {e}")
    return groups, refused


def make_calibration(groups, created=None, version=None):
    """The calibration document. Its version is a checksum of the groups unless given."""
    body = json.dumps(groups, sort_keys=True, separators=(",", ":"))
    return {"format": FORMAT, "version": FORMAT_VERSION,
            "calibration_version": version or hashlib.sha256(body.encode()).hexdigest()[:12],
            "created": created or now(), "groups": groups}


def _check(ok, msg):
    if not ok:
        raise CalibrationError(msg)


def validate(doc):
    """Raise CalibrationError unless doc is a calibration this code can use."""
    _check(isinstance(doc, dict) and doc.get("format") == FORMAT, "not a shortlist calibration file")
    _check(doc.get("version") == FORMAT_VERSION, f"calibration format version {doc.get('version')!r} not supported")
    _check(isinstance(doc.get("calibration_version"), str), "no calibration_version")
    _check(isinstance(doc.get("groups"), dict), "no groups")
    for g, e in doc["groups"].items():
        where = f"group {g!r}:"
        _check(isinstance(e, dict) and isinstance(e.get("identifiable"), bool), f"{where} identifiable must be true or false")
        if not e["identifiable"]:
            continue
        missing = [k for k in ENTRY_KEYS if k not in e]
        _check(not missing, f"{where} missing {missing}")
        _check(e["method"] in METHODS, f"{where} method {e['method']!r}")
        _check(e["input"] in INPUTS, f"{where} input {e['input']!r}")
        _check(isinstance(e["temperature"], (int, float)) and e["temperature"] > 0, f"{where} temperature must be > 0")
        _check(isinstance(e["target"], (int, float)) and 0 < e["target"] < 1, f"{where} target must be in (0, 1)")
        if e["method"] == "conformal":
            _check(isinstance(e["threshold"], (int, float)) and 0 <= e["threshold"] <= 1, f"{where} threshold in [0, 1]")
        else:
            _check(e["k"] is None or (isinstance(e["k"], int) and e["k"] >= 1), f"{where} k must be >= 1")
        _check(isinstance(e["n"], int) and e["n"] >= MIN_N, f"{where} n {e['n']!r} under {MIN_N}")
        _check(isinstance(e["passed"], bool), f"{where} passed must be true or false")
        _check(not e["passed"] or e["median_size"] <= e["max_size"], f"{where} passed with a median set over max_size")
        _check(not (e["passed"] and e["method"] == "fixed_k" and e["k"] is None), f"{where} passed with no k")
    return doc


def save_calibration(doc, path: Path):
    validate(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")


def load_calibration(path: Path):
    try:
        doc = json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise CalibrationError(f"{path}: not JSON ({e})") from e
    return validate(doc)


# --- score run ---

def slug(group):
    return re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-")


def _scalar(a):
    return str(a[()]) if a.shape == () else str(a)


def _head_path(d, heads):
    """The group's linear head for a shard with features instead of scores; None for a shard with scores."""
    if "scores" in d:
        return None
    if heads is None:
        raise ValueError("shard has features but no --heads was given")
    return Path(heads) / f"{slug(_scalar(d['group']))}.npz"


def _shard_scores(d, head, entry_input):
    """Scores of one shard: as stored, or logits = scale * feats @ weights.T + bias through its head."""
    if head is None:
        return d["scores"]
    if entry_input == "probs":
        raise ValueError(f"{head.name}: a head gives logits, but the calibration expects probabilities")
    with np.load(head, allow_pickle=False) as h:
        if list(h["names"]) != list(d["names"]):
            raise ValueError(f"{head.name}: head names differ from the shard's")
        logits = d["feats"] @ h["weights"].T
        if "scale" in h:
            logits = float(h["scale"]) * logits
        if "bias" in h:
            logits = logits + h["bias"]
    return logits


def _write_atomic(obj, path: Path):
    tmp = path.with_name(path.name + ".part")
    dump(obj, tmp)
    tmp.replace(path)


def score(features, calibration, out=OUT, heads=None, minutes=None):
    """Rows for every shard in features/*.npz. Skips shards already done with the same inputs and calibration;
    stops before a new shard once `minutes` have passed (the next run continues)."""
    features, out = Path(features), Path(out)
    cal = load_calibration(calibration)
    version = cal["calibration_version"]
    out.mkdir(parents=True, exist_ok=True)
    mpath = out / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {"shards": {}}
    shards = sorted(features.glob("*.npz"))
    stats = {"done": 0, "skipped": 0, "rows": 0}
    start = time.monotonic()
    log(f"shortlist: {len(shards)} shards, calibration {version}")
    for i, shard in enumerate(shards, 1):
        t = time.monotonic()
        if minutes is not None and t - start > minutes * 60:
            log(f"shortlist: time limit of {minutes} min reached; {len(shards) - i + 1} shards left for the next run")
            break
        dest = out / f"{shard.stem}.json"
        with np.load(shard, allow_pickle=False) as d:
            d = dict(d)
        group, model = _scalar(d["group"]), _scalar(d["model"])
        entry = cal["groups"].get(group)
        usable = entry is not None and entry["identifiable"]
        if usable and model != entry["model_id"]:
            raise ValueError(f"{shard.name}: scores from {model}, calibration for {entry['model_id']}")
        head = _head_path(d, heads)
        key = {"input": sha256(shard), "head": sha256(head) if head else None, "calibration": version}
        done = manifest["shards"].get(shard.name)
        if done and {k: done.get(k) for k in key} == key and dest.exists() and sha256(dest) == done.get("output"):
            stats["skipped"] += 1
            continue
        scores = _shard_scores(d, head, entry["input"] if usable else None)
        names = [str(n) for n in d["names"]]
        flags = {f: d[f] for f in VALUE_FLAGS if f in d}
        rows = []
        for j, (obs, state) in enumerate(zip(d["obs_id"], d["state"])):
            res = shortlist(scores[j], names, entry)
            rows.append(row(obs.item(), group, str(state), res, entry, version,
                            {f: bool(v[j]) for f, v in flags.items()}))
        _write_atomic(rows, dest)
        bands = {b: sum(r["band"] == b for r in rows) for b in (QUICK, EXPERT, SPECIMEN)}
        manifest["shards"][shard.name] = {**key, "output": sha256(dest), "rows": len(rows), "bands": bands}
        manifest["updated"] = now()
        _write_atomic(manifest, mpath)  # after every shard, so a stopped run keeps what it did
        stats["done"] += 1
        stats["rows"] += len(rows)
        log(f"  {i}/{len(shards)} {shard.name} ({group}): {len(rows)} rows, "
            + ", ".join(f"{b} {c}" for b, c in bands.items() if c) + f"; {time.monotonic() - start:.0f}s")
    log(f"shortlist: {stats['done']} shards done, {stats['skipped']} unchanged, {stats['rows']} rows")
    return stats


def calibrate_dir(heldout, *, not_identifiable=(), **kw):
    """Calibration document from held-out shards (group, names, scores, true; optional test_scores, test_true)."""
    data = {}
    for path in sorted(Path(heldout).glob("*.npz")):
        with np.load(path, allow_pickle=False) as d:
            names = [str(n) for n in d["names"]]
            test = (d["test_scores"], [str(t) for t in d["test_true"]]) if "test_scores" in d else None
            data[_scalar(d["group"])] = (d["scores"], names, [str(t) for t in d["true"]], test)
    groups, refused = calibrate_groups(data, **kw)
    for g in not_identifiable:
        groups[g] = specimen_entry("not identifiable from a photo")
    for g, e in groups.items():
        log(f"  {g}: " + ("needs a specimen" if not e["identifiable"] else
                          f"{'passed' if e['passed'] else 'failed'} (coverage {e['coverage']:.1%}, "
                          f"median {e['median_size']}, p90 {e['p90_size']}, n {e['n']})"
                          + (f": {e['reason']}" if e["reason"] else "")))
    return make_calibration(groups), refused


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline.shortlist", description="Species shortlists (module 6)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate", help="calibration file from held-out scores")
    c.add_argument("--heldout", required=True, type=Path)
    c.add_argument("--model", required=True)
    c.add_argument("--corpus", required=True)
    c.add_argument("--out", required=True, type=Path)
    c.add_argument("--method", choices=METHODS, default="conformal")
    c.add_argument("--target", type=float, default=0.9)
    c.add_argument("--max-size", type=int, default=MAX_SIZE)
    c.add_argument("--input", choices=INPUTS, default="probs")
    c.add_argument("--temperature", type=float, default=1.0)
    c.add_argument("--not-identifiable", action="append", default=[], metavar="GROUP")
    s = sub.add_parser("score", help="site rows from score or feature shards")
    s.add_argument("--features", required=True, type=Path)
    s.add_argument("--calibration", required=True, type=Path)
    s.add_argument("--heads", type=Path)
    s.add_argument("--out", type=Path, default=OUT)
    s.add_argument("--minutes", type=float)
    a = ap.parse_args(argv)
    if a.cmd == "calibrate":
        doc, refused = calibrate_dir(a.heldout, not_identifiable=a.not_identifiable, model_id=a.model,
                                     corpus_version=a.corpus, method=a.method, target=a.target,
                                     max_size=a.max_size, input=a.input, temperature=a.temperature)
        save_calibration(doc, a.out)
        log(f"calibration {doc['calibration_version']}: {len(doc['groups'])} groups -> {a.out}"
            + (f"; refused: {', '.join(refused)}" if refused else ""))
    else:
        score(a.features, a.calibration, a.out, heads=a.heads, minutes=a.minutes)


if __name__ == "__main__":
    main()
