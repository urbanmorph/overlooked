# Shortlist data (experimental page)

The contract between the shortlist job (made on this machine: the model and corpus stay in India) and the page
`site/shortlist.html`. Only these files go to R2. Plan section 1d.

## Rules

- A shortlist is a suggestion for a person who identifies. A taxonomist approves every name, on iNaturalist.
  Nothing is posted to iNaturalist.
- Only groups with the gate verdict "Quick to confirm" or "Genus first" (`experiments/corpus_v0/results/gate.csv`).
- Never an observation of the frozen test (`data/corpus_v0/frozen_*.parquet`): if the page shows them, the test
  measures the page, not the model.
- Bands and an order of names, not raw probabilities.
- The photo is not copied: the page shows iNaturalist's own photo URL with its licence and attribution text.

## Files (R2, served at `/data/<key>`)

`layers/shortlist/latest.json`

```json
{"run": "2026-10-21", "built": "2026-10-21T10:00:00Z",
 "model": "BioCLIP 2.5 + corpus v0 classifier", "corpus": "v0", "calibration": "ce7c9b55be8e",
 "rows": 12345,
 "groups": [{"key": "true-bugs", "name": "True bugs", "verdict": "Quick to confirm", "rows": 950, "pages": 2,
             "t1": {"n": 121, "top1": 90.1, "cov90": 94.0}}]}
```

`layers/shortlist/<run>/g/<group key>.json`: the rows of one group, sorted by priority (most useful first).

```json
{"group": "true-bugs", "rows": [
  {"id": 123456789, "url": "https://www.inaturalist.org/observations/123456789",
   "photo": "https://inaturalist-open-data.s3.amazonaws.com/photos/1/medium.jpg",
   "attribution": "(c) name, some rights reserved (CC BY)", "licence": "cc-by",
   "observed": "2026-09-30", "place": "Kodagu, Karnataka", "state": "29",
   "now": {"name": "Halyomorpha", "rank": "genus"},
   "band": "quick", "names": ["Halyomorpha halys", "Halyomorpha picus"], "genera": ["Halyomorpha"]}]}
```

- **Pages.** A group file stays under 300 KB. A larger group is split in priority order: page 1 is
  `<run>/g/<key>.json`, page n is `<run>/g/<key>.<n>.json` (n = 2, 3, ...). When a group has more than one page,
  each page file also has `"page": n` and `"pages": N` before `"rows"`. latest.json gives `pages` per group (1 when
  not split). At about 450 bytes a row, a page holds about 650 rows.
- `band`: `quick` (Quick to confirm: up to 3 species) or `genus` (Genus first: up to 5 genera). Rows with no
  usable list (band "For an expert") are not published. A group's `rows` in latest.json counts published rows.
- A pruned run (`live.py prune <sample run> <date>`, after `recheck.py --shown` on that date) is the sample run
  without the observations now research grade, casual or gone. Its latest.json adds `sample` (the run it was cut
  from), `checked` (the date of the check) and `removed` (rows left out). It has no shown.parquet: the measure
  always uses the sample run's shown set.
- `t1.cov90`: coverage of the 90% set at the group's level: species for Quick to confirm, genus for Genus first.
- `names`: the species shortlist in order, at most 3; empty for `genus`. `genera`: at most 5.
- `state`: LGD state code when known (from the observation's place), else null.
- Group keys: lower case, words joined by `-` (for example `bees-wasps-ants`).

## Measure of use

- The page links each observation through `/go/inat/<id>`, which redirects to iNaturalist and adds one to an
  aggregate daily counter (`dim` `inat_out`, key: group). No visitor data.
- `experiments/corpus_v0/recheck.py --shown <run>` scores the shown rows later, as for the frozen test: how many got
  a confirmed name, and how often that name was on the shortlist. Shown rows against frozen rows is the effect of
  the page.
