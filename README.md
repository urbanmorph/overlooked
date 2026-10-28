# Overlooked

The master list of India's species, and what changes in it each week.

**Site:** https://overlooked-india.pages.dev

Overlooked joins every public source on India's species into one list: GBIF, iNaturalist, the Zoological and
Botanical Surveys of India (checklists and annual discoveries), Kew WCVP, Catalogue of Life and the IUCN Red List. For
each species, group and state it shows whether the species has an open record (a specimen, photo or sighting anyone
can check online), how many observations of it wait for a name, and its IUCN status. Each week it builds a new dated list from the sources and compares it with the week before. It
holds no sightings and takes no user input; every figure links back to its source. The larger aim is to track the
health of India's species over time. It follows the data story
[The Overlooked Species](https://overlooked-species.surge.sh).

## Pages

| Page | What it shows | Reads |
|---|---|---|
| `/` Explore | Species of India by group and state: open records, observations that wait for a name, IUCN status; search; and the records to fix (GBIF records with no exact place or no species name, by dataset) | `layers/master/<week>/` |
| `/species` | One species: its sources, districts, records by decade, IUCN status, observations that wait for a name | `layers/master/<week>/`, snapshot files |
| `/changes` | The totals by week as tiles and a chart (`history.json`), then what moved since last week: IUCN category changed; a first open record in India or in a state, added to or taken off the list | `layers/master/<week>/changes.json` |
| `/shortlist` | Experimental. Observations on iNaturalist that wait for a name, each with a short list of names from a model, for a person to check on iNaturalist | `layers/shortlist/` |
| `/method` | Sources, credit, method, health of the sources at the last run, downloads | snapshot manifest and summary |

## How the parts connect

```
GitHub Actions (weekly / daily)                      R2 overlooked-data          Cloudflare Pages
  request.yml + build.yml  -> GBIF snapshot      ->   snapshots/<week>/      \
  inat.yml                 -> iNaturalist layer  ->   layers/inat/<week>/     |
  newspecies.yml           -> new-species layer  ->   layers/newspecies/<week>/  -> master.yml -> layers/master/<week>/ -> /data/* -> pages
  (BSI, ZSI, Kew, CoL, IUCN read by master.py)                                /
This machine (India)
  experiments/corpus_v0    -> shortlists (model, corpus, photos stay here) -> layers/shortlist/<run>/ (JSON only)
```

- **Master list** (`pipeline/master.py`, `master.yml`, daily): reads the newest GBIF snapshot and the iNaturalist and
  new-species layers, plus BSI, ZSI, Kew, Catalogue of Life and IUCN, and writes `layers/master/<week>/<build>/`: one folder
  per build, never changed after. Every file goes up first, then `<week>/current.json` and `latest.json` name the new
  build, so the site reads one build or the other, never a mix; older builds of the week beyond the one before are
  deleted. A second run in the same week adds a build. It compares with the previous published list (`latest.json`
  names it).
- **Shortlists** are made on this machine, not on GitHub Actions: the corpus, the image features and the model stay in
  India. Only the JSON rows go to R2 (`experiments/corpus_v0/publish_live.py`, run by hand). Contract:
  [docs/shortlist_data.md](docs/shortlist_data.md).
- **The site** is static HTML and JavaScript in `site/`. `functions/data/[[path]].js` serves R2 at `/data/<key>`.
  `functions/go/inat/[id].js` sends a Shortlists link on to iNaturalist and counts it. `functions/_middleware.js`
  keeps aggregate daily counts in D1 (no IP, no cookies): [docs/metrics.md](docs/metrics.md).
- A week is named by its Monday in UTC (`2026-10-26`). Lists before 27 October 2026 were monthly (`2026-10`).

## The weekly run

| Workflow | When (UTC) | What it does |
|---|---|---|
| `request.yml` | 02:17 on Mondays, and by hand | Checks every source. Sends the first GBIF download request. Commits the run state to `runs/<week>.json`. |
| `build.yml` | Every 6 hours, Monday to Thursday (at :47), and by hand | Sends the next GBIF download when the last one is ready (GBIF allows few downloads at a time). When all are ready: builds, checks and publishes the snapshot to R2. |
| `inat.yml` | 05:23 daily, and by hand | iNaturalist layer: species per state, research grade and needs ID (about 1,400 requests a week, under 9,000 a day). |
| `newspecies.yml` | 06:41 daily, and by hand | New-species layer: names from Plazi, BSI Plant Discoveries and ZSI Animal Discoveries, two GBIF downloads, matching. |
| `master.yml` | 10:37 daily, and by hand | Master list and the change feed. |
| `checks.yml` | Every push and pull request | Runs the tests. |

Scheduled runs need the repository variable `PIPELINE_ENABLED=true`. Runs started by hand always work.

### Steps of a snapshot

1. **Check the sources.** One request to each source (`pipeline/health.py`). If GBIF or R2 does not answer, the run stops and opens an issue. If another source does not answer, that source keeps the data of the last run.
2. **Download.** Four GBIF SQL downloads, one after another, each with its own DOI:
   - A, `ledger_cube`: species at each point (coordinates rounded to 3 decimals), first and latest year, records.
   - C, `species_history`: names, classification, and records by decade and kind of record.
   - U, `unresolved_cube`: records named only to genus, family or higher, with the genus.
   - L, `unlocated_cube`: records with no coordinates, by taxon, state as written, dataset and kind of record.
3. **Place.** Each point goes to its LGD district. A point less than 5 km from land goes to the nearest district; a point farther out is offshore. A record with no coordinates goes to a state when its state text names one (old names too, such as Orissa). If not, it has no place.
4. **Compute.** The ledger, the page data (small JSON files per area), the species files, the records with no species name, and the change feed against the previous snapshot. Also:
   - `unlocated.json`: records with no coordinates by state and group, the datasets that hold most of them (titles from the GBIF API, cached), and species known in India only from such records.
5. **Check.** Every download has a DOI; the ledger is not empty; species and ledger rows did not change by more than 20% from the last run. Records with no coordinates are not empty, and did not change by more than 20% if the last run has them.
6. **Publish.** Files go to R2 under `snapshots/<week>/`, the manifest last, then `latest.json`. The site reads them through the `/data/*` Pages Function.

### Safe to run again

- A finished step is not done again. Download keys and downloaded files are reused.
- A build is skipped if a snapshot from the same inputs (download keys and boundary checksum) exists.
- R2 uploads skip files that are already there with the same SHA-256, so a stopped upload continues.
- A published snapshot never changes. Files derived later from a published snapshot are added as new files only (`scripts/backfill_derived.py`).
- If GBIF reports no India record added, changed or re-processed since the last published run, the week downloads nothing.

### Run it yourself

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/python -m pipeline.health                      # check every source
.venv/bin/python -m pipeline.run request --state Kerala   # a test run for one state (never published)
.venv/bin/python -m pipeline.run build --run-id <week>-kerala
.venv/bin/python scripts/serve.py                         # the site at http://127.0.0.1:8790/
.venv/bin/python scripts/pages.py                         # after editing site-parts/ (shared head, header, footer)
```

Secrets go in `.env` (never committed): `GBIF_USER`, `GBIF_PASSWORD`, `GBIF_EMAIL`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET`. GitHub Actions has the same names as repository secrets.

## Sources

GBIF, Catalogue of Life, Local Government Directory (via bharatlas), iNaturalist, Plazi, the Botanical
Survey of India and others. Limits, terms and how each source is used: [docs/sources.md](docs/sources.md).
Plan and decisions: [docs/plan.md](docs/plan.md). Progress: [docs/progress.md](docs/progress.md).

## Licence

Code: MIT. Data and text on the site: CC BY 4.0, Sathya Sankaran.
Each source keeps its own licence and is credited on the site.
