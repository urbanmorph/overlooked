# Overlooked

A national monitor of the gaps in India's public biodiversity data. It updates itself each month.

**Site:** https://overlooked-india.pages.dev

Overlooked holds no sightings and takes no user input. Each month it builds a new dated snapshot from
public sources and computes every figure again. Every figure links back to its source and snapshot.
It follows the data story [The Overlooked Species](https://overlooked-species.surge.sh).

## Modules

| # | Module | Question | Page |
|---|---|---|---|
| 1 | Last-seen ledger | For each species and district, when was the latest public record? Which species have no public record since 1980? | `/ledger`, `/species` |
| 2 | Change feed | What changed since last month? | `/changes` |
| 3 | Follow-up on new species | Species described from India since 2015: is there a public record after the description? | `/new-species` |
| 5 | Waiting for a name | Where do observations wait for a species name, and who identifies them? | `/backlog` |

Later: official checklists against public records (module 4), and where the data flow stops (module 6).

## The monthly run

Three GitHub Actions workflows build the GBIF snapshot. Two more build dated layers next to it.

| Workflow | When (UTC) | What it does |
|---|---|---|
| `request.yml` | 02:17 on the 1st, and by hand | Checks every source. Sends the first GBIF download request. Commits the run state to `runs/<YYYY-MM>.json`. |
| `build.yml` | Every 6 hours on days 1 to 10 (at :47), and by hand | Checks the sources. Sends the next GBIF download when the last one is ready (GBIF allows few downloads at a time). When all downloads are ready: builds, checks and publishes the snapshot to R2. Commits the run state. |
| `checks.yml` | Every push and pull request | Runs the tests. |
| `inat.yml` | 05:23 daily, and by hand | iNaturalist layer (module 5): backlog by state and group, identifiers, and a direct check of species not recorded since 1980. At most 9,000 requests a day; it continues the next day until the month is done. |
| `newspecies.yml` | 06:41 daily, and by hand | New species layer (module 3): names from Plazi and BSI Plant Discoveries, two GBIF downloads, matching, and the status of each species. |

Scheduled runs need the repository variable `PIPELINE_ENABLED=true`. Runs started by hand always work.

### Steps of a snapshot

1. **Check the sources.** One request to each source (`pipeline/health.py`). If GBIF or R2 does not answer, the run stops and opens an issue. If another source does not answer, that source keeps last month's data.
2. **Download.** Four GBIF SQL downloads, one after another, each with its own DOI:
   - A, `ledger_cube`: species at each point (coordinates rounded to 3 decimals), first and latest year, records.
   - C, `species_history`: names, classification, and records by decade and kind of record.
   - U, `unresolved_cube`: records named only to genus, family or higher, with the genus.
   - L, `unlocated_cube`: records with no coordinates, by taxon, state as written, dataset and kind of record.
3. **Place.** Each point goes to its LGD district. A point less than 5 km from land goes to the nearest district; a point farther out is offshore. A record with no coordinates goes to a state when its state text names one (old names too, such as Orissa). If not, it has no place.
4. **Compute.** The ledger, the page data (small JSON files per area), the species files, the records with no species name, and the change feed against the previous snapshot. Also:
   - `candidates.json`: records named only to genus in a district where a species of that genus has no record since 1980 (in the district, or else in the state). They may be an overlooked species.
   - `unlocated.json`: records with no coordinates by state and group, the datasets that hold most of them (titles from the GBIF API, cached), and species known in India only from such records.
5. **Check.** Every download has a DOI; the ledger is not empty; species and ledger rows did not change by more than 20% from last month. Records with no coordinates and candidates are not empty, and did not change by more than 20% if last month has them.
6. **Publish.** Files go to R2 under `snapshots/<YYYY-MM>/`, the manifest last, then `latest.json`. The site reads them through the `/data/*` Pages Function.

### Safe to run again

- A finished step is not done again. Download keys and downloaded files are reused.
- A build is skipped if a snapshot from the same inputs (download keys and boundary checksum) exists.
- R2 uploads skip files that are already there with the same SHA-256, so a stopped upload continues.
- A published snapshot never changes. Files derived later from a published snapshot are added as new files only (`scripts/backfill_derived.py`).
- If GBIF reports no India record added, changed or re-processed since the last published run, the month downloads nothing.

### Run it yourself

```
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
.venv/bin/python -m pipeline.health                      # check every source
.venv/bin/python -m pipeline.run request --state Kerala   # a test run for one state (never published)
.venv/bin/python -m pipeline.run build --run-id <YYYY-MM>-kerala
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
