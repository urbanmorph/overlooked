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

## 1b. Module 5: identification backlog (brought forward 16 October 2026)

Question: where do observations wait for a name, and could a "quiet" species be hiding among them?

| Part | Source | How | Requests per month |
|---|---|---|---|
| Backlog by state, group and age | iNaturalist API | For India and each state place, and each iconic group (plus "no taxon"): needs-ID counts by year created (histogram endpoint) and research-grade counts | about 1,100 |
| Active identifiers | iNaturalist API | People who identified each group in India in the last 12 months, and the busiest identifier's count | about 15 |
| Direct check of quiet species | iNaturalist API | For each species quiet in India: match the name to an iNaturalist taxon (cached once), then the latest Indian observation of any quality, with its quality grade and licence | first month about 2 per species, then about 1; at most 9,000 a day, continuing next day if needed |
| Records not named to species | GBIF (query U) | Records with a taxon above species (genus, family...), by group, genus, rank and rounded point, placed in districts | 1 download |
| May be an overlooked species | Query U and the ledger | Records named only to genus in a district, at points with a record since 1980, where a species of that genus has no record in the district since 1980 (or, if none, in the state). The unsurveyed rule holds: the species' group must have a record in that area since 1980 | none |
| Records with no coordinates | GBIF (query L) | Records with no coordinates, by taxon, state text, dataset and kind of record. Placed in a state when the text names one (`pipeline/ref/state_names.csv`); otherwise "no place" | 1 download |

Notes (17 October 2026):
- Query L: about 1.4 million India records have no coordinates. Only about 258,000 carry any state text (GBIF facet, 17 October 2026). The variants table places 94% of those, so about 17% of all such records get a state.
- Old names map to today's state: Orissa, Pondicherry, Uttaranchal, Mysore State, Madras State, NEFA. Records of Jammu and Kashmir from before 2019 stay in Jammu and Kashmir, though the old state included Ladakh. Cities (Bombay, Madras, Mysore alone), regions across states (Bengal, United Provinces, Bombay State) and text naming two states are left unplaced.
- Dataset titles for the top holders come from the GBIF API at build time, one request per dataset not yet cached (`data/cache/gbif_datasets.json` and R2 `cache/`). About 100 requests once, then almost none. A failed lookup leaves the title empty and is tried again next build. This is cheaper for readers than each browser asking GBIF.

Rules:
- iNaturalist limits: at most 60 requests a minute and under 10,000 a day; we use about 1 a second and a daily budget of 9,000.
- An iNaturalist observation that is not in GBIF is never counted as a public record. The ledger shows it as a separate note: "iNaturalist: observed in India on <date> (<quality>, <licence>)".
- iNaturalist results have their own as-of date. They live in a separate, dated layer (`layers/inat/<date>/` in R2), because they can finish after the GBIF snapshot is published, and snapshots never change.
- The India Biodiversity Portal: we do not contact it. Its GBIF dataset is included as it is (records stop in 2024), and the site says so.

## 1c. Master list (17 October 2026)

Question: which species are documented from India, and for each one, is it observed, is it identified, and what is its IUCN category? The same three things per state, where the place is known.

- **Documented:** on the list of any source: ZSI checklists, BSI checklists, Kew WCVP (plants native to India), GBIF, iNaturalist, new species since 2015 (Plazi, BSI Plant Discoveries). A species on a BSI or ZSI checklist counts as documented.
- **Observed:** at least one observation in any source: a GBIF record of any kind (photo, sighting, specimen, sound, DNA sample, record cited from a paper), or an iNaturalist observation of any quality grade.
- **Identified:** at least one observation confirmed to species: a GBIF record named to species (labelled by its basis of record) or an iNaturalist research-grade observation. An iNaturalist "needs ID" observation with a species name proposed is observed, not identified. A checklist entry is not an observation.
- We never write "not recorded since 1980" on these pages. A species is documented, observed or identified.

Labels (several per species; the search filters on them):

| Kind | Labels |
|---|---|
| Identification | research grade (iNaturalist), needs ID (iNaturalist), human observation, specimen, from a paper (GBIF MATERIAL_CITATION), DNA sequence or sample (MATERIAL_SAMPLE), machine observation, other record (GBIF OCCURRENCE: kind not given), checklist only |
| Other | location missing (only records with no coordinates, query L), DNA only, endemic to India (WCVP for plants; ZSI checklists that mark endemics with `*`; BSI checklist status), new species since 2015, name not matched |
| Sources | ZSI, BSI, WCVP, GBIF, iNaturalist, Plazi, IUCN |
| IUCN | CR, EN, VU, NT, LC, DD, EW, EX, or NE (not assessed) |

How it is built (`pipeline/master.py`, a dated layer like the iNaturalist and new species layers; no GBIF download):

1. Inputs: the latest published snapshot (species, ledger, species by decade and kind of record; records with no coordinates and candidates when the snapshot has them); ZSI checklists (fnf, 98,703 names) and WCVP India (fnf, 19,045 species), copied to R2 `cache/master/` with `python -m pipeline.master seed` because they are not in git; the BSI checklist (`data/bsi/bsi_checklist.csv` or R2 `cache/bsi/`, optional; accepted names only, a synonym is not a second species); iNaturalist species lists per state (`layers/inat/<month>/species_counts.json`); new species (`layers/newspecies/`); IUCN (below).
2. Names to the Catalogue of Life (eXtended Release, the taxonomy of GBIF's SQL downloads): GBIF keys as they are; ZSI's own match (fnf, same release; names held for review are not trusted); then exact names; then GBIF's name match (`/v2/species/match`, `checklistKey` COL XR), one request a second, cached in R2 `cache/master/gbif_match.json`, with a time limit per run. iNaturalist names go first, then WCVP and BSI. ZSI names are not sent again. Subspecies count as their species. A name with no match stays on the list under its own name, labelled "name not matched".
3. One species per key. Keys that share a name and kingdom are folded into one (GBIF's key first), as `names.merge_duplicates` does for GBIF; two GBIF keys are never merged here.
4. Group: GBIF's classification; else the GBIF match's; else IUCN's; else the genus or family as known from GBIF and IUCN (same kingdom only); else a hint from the source (ZSI checklist name, iNaturalist iconic group, WCVP = vascular plants).
5. IUCN: by name, the assessed name first, then IUCN synonyms; same kingdom.

Output (`layers/master/<month>/`, published with `--publish`, then `layers/master/latest.json`):

| File | Content |
|---|---|
| `master.parquet` | key, name, group, sources[], observed, identified, iucn, labels[], states_observed[], states_identified[] |
| `master_state.parquet` | species x state: GBIF with and without coordinates, iNaturalist research grade and needs ID, observed, identified |
| `summary.json` | sources, labels, IUCN categories, groups, states (bit order for the masks); India by group: documented, observed, identified, IUCN counts, threatened and observed; by state x group: observed, identified, threatened and observed; totals; notes on what is incomplete |
| `g/<gi>.json` | every species of a group: [key, name, sources mask, status (0 documented, 1 observed, 2 identified), IUCN index, labels mask, states observed mask, states identified mask] |
| `search/<p>.json` | search index: one file per first two letters of the name (other characters `_`), sorted by name: [name, key, group, status, IUCN index, sources mask, labels mask]. Largest file about 46 KB compressed; median about 1.5 KB |
| `search/places.json` | LGD states and districts: [name, "state" or "district", code, state code] |

- Runs daily after the iNaturalist layer (`.github/workflows/master.yml`), within a time limit for name matching. A run with the same inputs (file checksums, layer files, match cache, IUCN ETag) and no names left to match does nothing.
- Approximate: "DNA only" comes from the kind of record (all MATERIAL_SAMPLE) until a snapshot's ledger marks DNA sequences; then also from the ledger. ZSI endemics come from the `*` mark in the checklists that use it. iNaturalist lists can shift a little between pages while they are fetched.


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

Filters on every query (ported from fnf `01_gbif_download.py`): country IN, has coordinates, no geospatial issue, occurrence status PRESENT, coordinate uncertainty 25 km or less (or empty), no FOSSIL_SPECIMEN or LIVING_SPECIMEN, the fnf excluded datasets. Query L is the exception: it takes the records with no coordinates, so the coordinate filters do not apply.

The monthly run downloads A, C, U and L, one after another, in that order.

| Query | Groups by | Measures | Feeds |
|---|---|---|---|
| A. Ledger cube | speciesKey, ROUND(lat, 3), ROUND(lon, 3) | MIN(year), MAX(year), COUNT(*) | Ledger, change feed |
| C. Species history and names | speciesKey, kingdom to species, FLOOR(year / 10) * 10, basisOfRecord | COUNT(*) | Species table, species page chart |
| U. Records not named to species | kingdom to family, genus, taxonRank, ROUND(lat, 3), ROUND(lon, 3) | MIN(year), MAX(year), COUNT(*) | Waiting for a name, may be an overlooked species |
| L. Records with no coordinates | speciesKey, species, genus, taxonRank, kingdom to family, stateProvince (as published), datasetKey, basisOfRecord | MIN(year), MAX(year), COUNT(*) | Records with no coordinates by state, holders, species known only from them |

- Query L size: species and classification depend on speciesKey, so rows are about species x state text x dataset x kind of record. Expected a few hundred thousand rows, well below query A (11.8 million). A test run selects L by the state text, because records with no coordinates have no GADM name.
- Downloads made before genus was added to U still build: genus is empty, and the candidates step is skipped. A run started before L was added downloads it after the others.

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
  - BSI Plant Discoveries (annual, new species and new records for India): the listing page is checked monthly and new PDFs are parsed, with prominent acknowledgement. BSI's Indian Virtual Herbarium (type specimens, found by barcode prefix) is a separate source, shown next to GBIF. Details and limits: `docs/sources.md`.
  - Not used: ZooBank (blocks automated access with a captcha).
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
  unresolved.parquet                 records not named to species, per district x group x genus x rank
  candidates.parquet                 may be an overlooked species: one row per district x genus
  unlocated.parquet                  records with no coordinates, per taxon x state text x dataset x kind
  summary.json                       the overview figures, small, for fast first paint
  unresolved.json                    records not named to species, by area, group and rank
  candidates.json                    totals by group and state, top 2,000 rows
  unlocated.json                     by state (or no place) x group: records and species; top dataset
                                     holders with titles; species known only from records with no coordinates
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
- `unresolved`: district_lgd, state_lgd, grp, genus, taxonrank, n_records, n_records_since_1980 (records at points whose latest record is 1980 or later), first_year, last_year.
- `candidates`: district_lgd, state_lgd, grp, genus, tier (district or state), n_records_unnamed, n_species_not_recorded, examples, example_keys, last_year_unnamed.
- `unlocated`: species_key (empty above species), name, genus, taxonrank, grp, stateprovince (as published), state_lgd (empty for no place), datasetkey, basis, first_year, last_year, n_records.
- "Known only from records with no coordinates": a species in L with no row in the ledger or the species table. A species whose only records with coordinates failed the filters (for example, uncertainty over 25 km) also counts here.

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
| `request.yml` | 1st of the month, 02:00 UTC, and by hand | Submits the first GBIF download (A); C, U and L follow one at a time from `build.yml`. Writes the keys to `runs/YYYY-MM.json` and commits it. |
| `build.yml` | Every 6 hours on days 1 to 10, and by hand | If downloads are pending, polls GBIF. When all are ready: builds, checks, uploads to R2, writes `latest.json`, commits `site/data/latest.json`. The commit triggers the Pages build. |
| `checks.yml` | On pull requests | Tests and a small sample build. |

- One build at a time (`concurrency` group). Jobs stop at 6 hours; a build resumes from the download keys.
- **Idempotent and incremental (16 October 2026):** every step can run again safely. Download keys and fetched files are reused; a build is skipped when a snapshot from the same inputs (download keys and boundary checksum) exists; R2 uploads skip files already there with the same SHA-256, so an interrupted upload continues; the manifest and `latest.json` go last. If GBIF reports no India record added, changed or re-processed since the last published run, the month downloads nothing. GBIF itself is re-summarised each month: about 5% of India records are re-processed monthly and GBIF publishes no deletions, so adding only changed records to the totals would drift.
- **Source health at every refresh:** `pipeline/health.py` sends one request to each source (GBIF API and downloads, R2, LGD boundaries, Plazi, IPNI, Index Fungorum, iNaturalist, the India Biodiversity Portal's GBIF dataset, Kew WCVP, BSI Plant Discoveries and IVH). A critical failure (GBIF, R2) stops the run and opens an issue; any other failure is a warning, and that source keeps last month's data. Results are kept in the run state and the manifest.
- Checks before publishing: row counts within a set range of last month, no district codes outside LGD, every figure has a DOI. Records with no coordinates and candidates are not empty when built, and within 20% of last month when last month has them. If a check fails, the job stops and opens a GitHub issue.
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
3. **IUCN.** Left out of the first release. Its terms forbid bulk redistribution, and our Parquet files are public downloads. **Update 17 October 2026:** the master list takes categories from the Red List checklist that IUCN publishes on GBIF, which GBIF lists under CC BY 4.0 (see `docs/sources.md`). The IUCN API (token) is not used. To confirm before publishing: that the CC BY 4.0 copy on GBIF covers our public files, given the IUCN website terms.
4. **Groups.** Reuse the fnf group definitions (`09_attention.py`) as they are.
5. **Placement.** Coordinates rounded to 3 decimals instead of a grid, after the grid test. Points within 5 km of land take the nearest district.
