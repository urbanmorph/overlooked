# Plan: modules 1 to 3

Approved 16 October 2026.

## 1. Scope

| # | Module | Question | First release shows |
|---|---|---|---|
| 1 | Last-seen ledger | For each species and LGD district: the first and latest year of a public record. Which species are quiet since a chosen year? | District map, district summary, species table, species page |
| 2 | Change feed | What changed since last month? | Monthly list of changes, with the reason for each |
| 3 | Follow-up on new species | Species described from India since 2015: any public record since the paper? | Shares by group, table of species, how each was matched |

Out of scope for now: modules 4 to 6, user accounts, any user input, IUCN categories (section 11).

Definitions (shown on the site):

- **Public record:** a GBIF occurrence in India that passes the filters in section 3.
- **Quiet:** a species with records in an area, but none since the chosen year. Default 1980. The ledger lets the reader pick 1980, 1990, 2000 or 2010.
- **Unsurveyed:** a district with no records of the species' whole group since the chosen year. A species in an unsurveyed district is marked, not counted as quiet. This separates "nobody looked" from "nobody found it" (the B-Cubed effort idea).
- **Now quiet** (change feed only): a species whose latest record in India is now more than 30 years old.
- We never say "lost", "missing" or "extinct". Re:wild and IUCN call a species lost after 10 years without a documented record; the method page says how our terms differ.

## 2. Architecture

```
GitHub Actions (monthly)
  GBIF SQL downloads ─┐
  Plazi, IPNI, Index Fungorum, GBIF name lookups (cached) ─┤
  Catalogue of Life XR, LGD districts (bharatlas) ─┘
        │  Python + DuckDB
        ▼
  R2 (private): snapshots/YYYY-MM/*.parquet + manifest.json
        │  commit site/data/latest.json
        ▼
  Cloudflare Pages: overlooked-india.pages.dev
    static pages  +  Pages Function /data/* (reads R2 through a binding, supports Range)
        │  DuckDB-WASM reads Parquet from /data/... by HTTP range requests
        ▼
  Reader's browser
```

No application server and no database. The one Pages Function only streams files from R2. Every figure is computed from one dated snapshot.

- **Address:** `overlooked-india.pages.dev` (free as of 16 October 2026; `overlooked.pages.dev` is taken). A custom domain can be added later without code changes.
- **Data on the same origin:** the bucket stays private. The function answers `GET` and `HEAD` with `Range`, `ETag` and long cache headers for `snapshots/` (files never change), short cache for `latest.json`. No CORS needed, and the rate-limited `r2.dev` URL is not used. Requests count toward the Workers allowance of the paid plan.
- **Local work:** `wrangler pages dev` with the R2 binding, or Parquet files on disk.

## 3. Data from GBIF

GBIF SQL downloads allow one table, SELECT and GROUP BY, and no joins. Admin columns are GADM, not LGD. So we group by rounded coordinates and place the points in LGD districts ourselves.

Filters on every query (ported from fnf `01_gbif_download.py`): country IN, has coordinates, no geospatial issue, occurrence status PRESENT, coordinate uncertainty 25 km or less (or empty), no FOSSIL_SPECIMEN or LIVING_SPECIMEN, the fnf excluded datasets.

| Query | Groups by | Measures | Feeds |
|---|---|---|---|
| A. Ledger cube | speciesKey, ROUND(lat, 3), ROUND(lon, 3) | MIN(year), MAX(year), COUNT(*) | Ledger, change feed |
| C. Species history and names | speciesKey, kingdom to species, FLOOR(year / 10) * 10, basisOfRecord | COUNT(*) | Species table, species page chart |

- **Dropped, 16 October 2026:** query B (records since 1980) and query D (taxonomy). Effort comes from the ledger: a group with no species recorded in an area since the chosen year marks the area unsurveyed for that group. Names and classification come with query C.
- **Species keys are Catalogue of Life IDs** (text, for example `5VKF2`), because GBIF SQL downloads use the COL taxonomy.

- **Rounded points, not grid cells:** coordinates rounded to 3 decimals (about 110 m). The grid test (`scripts/grid_test.py`, on 2.49 million fnf records) compared each method with exact points:

  | Method | Records in a different district | Species x district rows lost | Rows |
  |---|---|---|---|
  | EQDGC grid, about 1.7 km | 1.6% | 2.6% | 0.86 M |
  | EQDGC grid, about 0.9 km | 1.0% | 1.2% | 0.93 M |
  | Rounded to 3 decimals | 0.2% | 0.15% | 1.10 M |

- **Shore and islands:** district outlines are simplified, so some shore and island points fall just outside. A point within 5 km of a district takes the nearest one; further out it is offshore and left out of the ledger (1.1% of records in the test). The method page reports both counts.
- **Records with no year** have a place but no date (3.1% in the test). They count as records, but never as the latest year.
- **Size check first:** run A on one state (Kerala) before the national run, to confirm the query works and to see how much birds add to the row count.
- Each download has its own DOI. The manifest lists all of them.

## 4. Names and new species

- Taxonomy comes from GBIF's backbone columns. Catalogue of Life XR (monthly ColDP release) supplies synonyms.
- **New species list (module 3):**
  - Plazi TreatmentBank `srsStats`: species with an Indian holotype, published 2015 onward. About 2,777 names as of 16 October 2026. CC0.
  - IPNI: plant names by year, filtered to India on our side.
  - Index Fungorum: fungus names by date range, filtered on type locality text.
  - Not used: ZooBank (blocks automated access), BSI publications (handoff rule).
  - The site names the journals each source covers. Known gaps: Journal of Threatened Taxa after 2020, JBNHS, Taiwania, Nelumbo, Bionotes.
- **Follow-up check** (ported from fnf `21_discoveries_recheck.py`): exact name, then COL synonyms, then GBIF records by verbatim name. A GBIF hit counts only when the record carries the name itself. A record counts as a follow-up only when its date is after the publication date and it is not the type material.
- Name lookups go to the GBIF API, one request at a time, 1 to 1.5 s apart, cached in R2 `cache/`. Each month only names not yet followed up are checked again.

## 5. Snapshot files in R2

Bucket `overlooked-data`, private. The site reads the public paths through `/data/`, for example `/data/snapshots/2026-11/ledger.parquet`. The function refuses `cache/`.

```
latest.json                          { "month": "YYYY-MM", "built": "...", "manifest": "snapshots/YYYY-MM/manifest.json" }
snapshots/YYYY-MM/
  manifest.json                      dates, DOIs, source versions, row counts, code commit, filters
  species.parquet                    one row per species
  ledger.parquet                     one row per species x district
  district_group.parquet             one row per district x group (effort)
  species_decade.parquet             one row per species x decade x basis of record
  new_species.parquet                one row per new species
  changes.parquet                    one row per change since last month
  summary.json                       the overview figures, small, for fast first paint
boundaries/lgd-YYYY-MM/
  districts.pmtiles                  map tiles
  districts.parquet                  LGD codes and names
cache/                               name lookups, Plazi and IPNI responses (not public)
```

Main columns:

- `species`: species_key, name, author, group, kingdom, phylum, class, order, family, genus, year_described (where known), endemic_india (Kew, plants).
- `ledger`: species_key, district_lgd, state_lgd, first_year, last_year, n_records, n_since_1980, n_records_near_shore. Sorted by state and district, so the browser reads only the row groups it needs.
- `district_group`: district_lgd, group, n_records_since_1980, n_species_since_1980.
- `new_species`: name, species_key (if matched), group, published_date, journal, doi, type_state, source, matched_by (exact, synonym, verbatim), first_record_after (date), status (recorded, only in later papers, no public record since), years_waited.
- `changes`: change_type (recorded_again, first_in_state, new_species_followed_up, now_quiet), species_key, area, previous_value, new_value, record_date, reason (new record, or older record newly published).

Snapshots are never overwritten. A failed run publishes nothing, and the site keeps showing the last good month.

## 6. Change feed rules

Computed by comparing this month's Parquet with last month's.

- **Recorded again:** a species x district pair was quiet last month and has a record since 1980 now.
- **First in a state:** a species x state pair that did not exist last month.
- **New species followed up:** status moved to "recorded".
- **Now quiet:** the latest record in India passed 30 years.
- **Reason:** if the new record is dated before last month's run, it is "older record, newly published". Otherwise "new record".
- The first run is the baseline and has no feed. The feed starts with the second run.

## 7. Monthly schedule (GitHub Actions)

| Workflow | When | Does |
|---|---|---|
| `request.yml` | 1st of the month, 02:00 UTC, and by hand | Submits GBIF downloads A to D. Writes the keys to `runs/YYYY-MM.json` and commits it. |
| `build.yml` | Every 6 hours on days 1 to 10, and by hand | If downloads are pending, polls GBIF. When all are ready: builds, checks, uploads to R2, writes `latest.json`, commits `site/data/latest.json`. The commit triggers the Pages build. |
| `checks.yml` | On pull requests | Tests and a small sample build. |

- One build at a time (`concurrency` group). Jobs stop at 6 hours; a build resumes from the download keys.
- Checks before publishing: row counts within a set range of last month, no district codes outside LGD, every figure has a DOI. If a check fails, the job stops and opens a GitHub issue.
- The monthly commits keep the repository active, so GitHub does not turn off the schedules.
- Secrets in Actions: GBIF account and R2 keys (scoped to `overlooked-data`). The site builds through Cloudflare's GitHub integration, so Actions holds no Cloudflare API token. The broader Cloudflare token stays local.

## 8. Site

- Static HTML and plain JavaScript modules. No build step, no framework.
- **Built for speed (16 October 2026):** no database and no map library in the browser.
  - The pipeline writes small JSON files (`pipeline/site_data.py`): `summary.json`, `map_stats.json` (per district and state, per group, quiet counts for 1980, 1990, 2000 and 2010), and one ledger file per district (all species), per state and for India (quiet species only).
  - The district map is pre-simplified SVG (`pipeline/boundaries.py`): 785 districts in about 70 KB compressed, coloured in the browser.
  - Measured on the development data: the overview loads 8 files, 135 KB compressed in all. A district file is about 4 KB (median). Lighthouse (mobile): 100 for accessibility, best practices and SEO on both pages, no layout shift.
  - Parquet files stay in each snapshot for download. DuckDB-WASM may come back later for free-form queries, loaded only on demand.
- Pages: Overview, Last seen, Species (`species.html?key=`), Changes, New species, Sources and method. Layout as in the design canvas.
- Every table offers CSV download. Every figure shows its snapshot date and DOI.
- Links out: iNaturalist (`observations?place_id=6681&taxon_id=`), India Biodiversity Portal, GBIF species and occurrence pages.
- Copy follows the handoff rules: plain short sentences, no em-dashes, "no public record since".

## 9. Repository layout

```
functions/data/      Pages Function that serves R2 files with Range support
pipeline/            Python package: gbif.py, names.py, districts.py, ledger.py, newspecies.py, changes.py, publish.py, checks.py
pipeline/queries/    SQL for downloads A to D
site/                static site
.github/workflows/   request.yml, build.yml, checks.yml
runs/                download keys per month
tests/
docs/                this plan, method notes
```

## 10. Build order

1. Test query A and row counts on one state (Kerala).
2. LGD districts from bharatlas: points to districts.
3. Ledger and effort tables, built locally from a national download.
4. Site: overview, ledger, species page, reading from local Parquet.
5. R2 upload, `latest.json`, Actions workflows. First published snapshot (baseline).
6. Module 3: Plazi, IPNI and Index Fungorum lists, follow-up check.
7. Module 2: change feed, live after the second monthly run.

## 11. Decisions (16 October 2026)

1. **Address.** `overlooked-india.pages.dev`, with data served from the same origin through `/data/*`. No custom domain for now.
2. **Thresholds.** Default quiet year 1980, with a picker for 1990, 2000 and 2010. "Now quiet" in the feed at 30 years.
3. **IUCN.** Left out of the first release. Its terms forbid bulk redistribution, and our Parquet files are public downloads.
4. **Groups.** Reuse the fnf group definitions (`09_attention.py`) as they are.
5. **Placement.** Coordinates rounded to 3 decimals instead of a grid, after the grid test. Points within 5 km of land take the nearest district.
