# Progress

Newest first. Updated as work happens.

## Status (16 October 2026)

| Area | State |
|---|---|
| Repository, licence, secrets | Done. Public repo `urbanmorph/overlooked` (MIT). Actions secrets: GBIF and bucket-scoped R2 keys only. |
| Cloudflare | **Live: https://overlooked-india.pages.dev** (16 October 2026). R2 bucket `overlooked-data` holds snapshot `2026-10`. |
| Plan | `docs/plan.md`, approved 16 October 2026, updated as decisions change. |
| Module 1: last-seen ledger | **Live** on the first all-India snapshot (2026-10). |
| Module 2: change feed | Built and live; shows its first changes after the 1 November run. |
| Module 5: identification backlog | Brought forward. iNaturalist layer (backlog by state and group, identifiers, direct check of quiet species) and GBIF query U built; backlog page and ledger note built; testing. |
| Module 3: new species | **Live.** 4,157 species described from India since 2015; 390 recorded again after the description; 3,760 (90%) with no public record since; 2,066 (50%) with any public record in India, often only the type material. |
| Monthly run (GitHub Actions) | Workflows in place, tested end to end on Kerala. Schedules off until `PIPELINE_ENABLED` is set. |
| Source limits | Documented in `docs/sources.md`. Pipeline follows them (GBIF downloads one at a time, crons off the hour). |

## Log

### 18 October 2026

- Wait for a name: the master list now writes `w/<group>.json` and `summary.waiting` from the iNaturalist
  needs-ID species lists. 9,76,938 observations of 34,866 species wait for a name (named to species by the
  observer, not confirmed; fnf counted 9,74,192). For 12,654 of these species one confirmation gives the
  first identification in India. The Identified view lists them per group and state, most useful first
  (no identification here yet, threatened, endemic), each with a link to iNaturalist's Identify page.
- Same menu on every page; Search Console verified, sitemap submitted.

### 17 October 2026

- Master list (`pipeline/master.py`, plan section 1c): every species documented from India across ZSI,
  BSI, WCVP, GBIF, iNaturalist, Plazi, with observed, identified and IUCN category per species and per
  state, labels for search, and a search index sharded by two-letter prefix. Layer `layers/master/<month>/`,
  built on the published snapshot without GBIF downloads; daily workflow `master.yml`. iNaturalist species
  lists per state added to the iNaturalist layer (651 requests for all states and India, research grade and
  needs ID). IUCN categories from the Red List checklist on GBIF (CC BY 4.0), no token. ZSI and WCVP inputs
  copied to R2 `cache/master/`. First local build on snapshot 2026-10 (not published): 152,983 species
  documented, 74,023 observed, 61,333 identified; 2,204 assessed CR, EN or VU, of which 1,638 observed;
  15,372 names not matched to the Catalogue of Life (12,000 of them ZSI names fnf could not match).
  GBIF name matching of about 22,200 names (mostly iNaturalist names not in GBIF's India list) took
  about 2 hours at 4 requests at once (about 11,000 names an hour); later runs only match new names.

- Pipeline, from the next snapshot: query U keeps the genus; new candidates.json (records named only
  to genus, from 1980 or later, where a species of that genus has no public record since 1980 in the
  district, else the state); new query L (records with no coordinates) placed at state level from the
  state text (pipeline/ref/state_names.csv), with unlocated.json (by state and "no place", top
  holders, species known only from such records). Both queries pass GBIF's validator.
- Audit items done: no layout shift on New species and Species, new species file 1.55 MB -> 0.34 MB
  (format 2, the page reads both), tap to select on the maps, histogram labels on phones, one-row nav
  on phones (header 199 -> 107 px), self-hosted IBM Plex fonts with a one-year cache.
- Front page prototype (design canvas, option E): map first, group cards, three views (not recorded
  since 1980, waiting for a name, no location), wired both ways with the state.
- Duplicate Catalogue of Life keys: 103 species names had two keys with the same classification, so
  23 species looked not recorded since 1980 while their recent records sat under the other key. The
  build now merges them (most records wins; homonyms stay apart). From the next snapshot: 6,990 -> 6,967.
- Site copy: "quiet" replaced by "not recorded since <year>" / "no public record since <year>".
- Mobile and performance audit; fixed: page wider than a phone (selects), number cards overflowing,
  stretched side cards, small sort buttons, robots.txt and a real 404 page. Open: layout shift on
  New species and Species, the 1.5 MB new-species file, map use on phones, decade chart labels on
  phones, nav height on phones, self-hosted fonts. Redesign options are on a design canvas.
- iNaturalist layer: the first run was cancelled at the 5-hour job limit. Its cache went to R2 only at
  the end, so the work was lost. The run now stops itself after 240 minutes and publishes what it has, and
  saves the cache to R2 every 10 minutes and on any exit. Checked on Actions: after 10 minutes, 255 of 518
  backlog rows were in R2.
- New species layer checked against the same rule (cache, restart, safe to run again): Plazi fetched one
  year at a time and saved; GBIF zips written to a temporary file and renamed when complete (also for the
  monthly snapshot); name matching has its own time limit and saves its cache every 10 minutes and on exit;
  the month is marked done only after the result is published. Rebuilt on Actions: same figures (4,157
  species).
- Tests for these (16 in all). pyflakes runs in CI.

### 16 October 2026

- Module 3 live (GBIF doi:10.15468/dl.rhshrn and doi:10.15468/dl.yccnbk). The fnf story's 77% counted any record including type material; Overlooked counts only records after the description year, and shows both figures. Groups for species with no India records now come from GBIF's classification ("Not matched yet" 1,198 → 193).
- README now documents the monthly run: workflows and schedules, steps, safety, running locally.
- Module 3 built: BSI Plant Discoveries parser ported from fnf with a monthly sync (listing page, new editions only, parsed once and cached in R2; 2025 edition parsed: 328 entries, 207 new species). New species layer (`layer_newspecies.py`, daily workflow): names from Plazi and BSI, GBIF queries Y (records since 2015 by species, year and kind) and V (names as published), matching by exact name, GBIF/Catalogue of Life synonyms and published names. New species page live; first results when the layer finishes.
- Overview module cards now link to all five live modules.
- Scheduled runs switched on (`PIPELINE_ENABLED=true`): downloads on the 1st, builds every 6 hours on days 1 to 10, iNaturalist layer daily.
- New pages live: Sources and method (run steps, definitions, DOIs, health of each source, credits including BSI and ZSI acknowledgement, downloads); Changes (module 2; first changes after the November run); Species (`/species?key=`, latest record, districts, history by decade, links onward). Ledger and Changes link species names to the species page.
- Species data split into 512 files by key hash (about 10 KB each). Added to snapshot 2026-10 as new derived files only (`scripts/backfill_derived.py`); no published file changed.
- **Public launch.** First all-India snapshot `2026-10` published (doi:10.15468/dl.hbk62c, doi:10.15468/dl.c8fw5y, doi:10.15468/dl.hsmcmy): 53,445 species, 63.8 million records, 784 districts, 549,804 ledger rows; 6,990 species with no public record in India since 1980; 651 districts with quiet species; 419,594 records not named to species. Production deploys on; https://overlooked-india.pages.dev live. Live overview: first paint 444 ms, 8 requests, 198 KB. iNaturalist layer workflow started.
- Fixed: `.gitignore` rule `data/` also matched `functions/data/` and `site/data/`, so the data function had never been committed. Rules now apply to the top-level folders only.
- Rerunning the publish was a no-op for R2 (same inputs) and recorded the run as published; `latest.json` now keeps the original snapshot time.
- All-India run: species history ready at 20:23 IST (146,689 rows); query U submitted (`0030871-260928105237408`). GBIF and GitHub work went on while the laptop slept; only local helpers paused.
- Module 5 checked in the browser on test data: 2,955,818 iNaturalist observations from India wait for a name (54% of verifiable ones; 76% added before 2026). Fungi: 95% waiting, 865 identifiers in 12 months. Ledger notes work; the iNaturalist request budget stops cleanly and continues next run.
- All-India run `2026-10`: ledger download ready at 19:44 (11.8 million rows, 311 MB, key `0030725-260928105237408`). Build on Actions passed the health check and submitted species history (`0030812-260928105237408`); query U follows.
- Module 5 brought forward. The India Biodiversity Portal is not contacted; its GBIF dataset is used as it is.
- iNaturalist layer: all 36 states mapped to iNaturalist places (two manual matches: Ladakh; Dadra, Nagar Haveli, Daman & Diu). Backlog by state, group and year; identifiers per group; direct check of quiet species with a 9,000-request daily budget that continues next day. Stored apart from the GBIF snapshot, with its own date. First sample: of 10 fish quiet in Kerala since 1980, 7 have recent research-grade iNaturalist observations in India, several without an open licence.
- GBIF query U (records not named to species) added; runs already started pick it up after their other downloads.
- New page: Waiting for a name (`/backlog`). Ledger shows "iNaturalist: seen in India <date>" next to quiet species.
- Runs are now idempotent and incremental (see plan section 7): rebuild with the same inputs skipped (tested), R2 uploads resume and skip identical files (tested), month skipped if GBIF reports no change. Health check of 12 sources at every refresh: all working on 16 October.
- Fixed: locally, inherited shell variables from another project overrode this project's R2 keys. `.env` now takes priority (GitHub Actions was not affected).
- iNaturalist reaches us through GBIF (1.71 million India records, updated weekly), but about 0.8 million research-grade observations without an open licence and about 3 million awaiting identification do not. The India Biodiversity Portal's GBIF dataset stops in 2024. Options put to the owner: direct iNaturalist check for quiet species; ask the Portal to republish; bring module 5 (identification backlog) forward.
- End-to-end test passed on both Kerala downloads (doi:10.15468/dl.6mfzfh, doi:10.15468/dl.v7fx5r): full monthly build in 11 s; all 9,243 species named; page data and district map written; both pages work on it with no errors. Pages now show a plain message if data fails to load.
- Owner approved a real snapshot in R2 and production deploys. All-India run `2026-10` started on Actions: ledger download `0030725-260928105237408` submitted 13:21 UTC; species history follows when it finishes.
- Decision: for BSI and ZSI we rely on the web-policy clause that allows free reproduction with prominent acknowledgement. No permission request. Every page that uses their data credits them by name.
- Cloudflare Pages project `overlooked-india` created (GitHub `main`, output `site/`, R2 bound as `DATA`, rebuilds only for `site/` and `functions/`). Production deploys off until a real snapshot is published.
- Source limits documented in `docs/sources.md` (GBIF, COL, Kew, IPNI, Index Fungorum, MycoBank, ZooBank, Plazi, BSI, iNaturalist, IUCN, bharatlas, Cloudflare, GitHub, data.gov.in).
- Pipeline changed to match: GBIF downloads run one after another and a 429 waits for the next check; User-Agent carries the repository URL; crons moved off the hour (02:17 and :47).
- BSI survey: no technical block. Plant Discoveries 2007 to 2025 online (2025 out since 30 June 2026); new edition about 1 July. Indian Virtual Herbarium: HTML only, no coordinates, about 26,100 types and 160,000 India records; new type specimens found by barcode prefix in about 20 requests. Web policy allows free reproduction with prominent credit, but a second clause asks for written permission: ask BSI to confirm.
- Pages Function for `/data/*` written and tested on wrangler with local R2: GET, HEAD, Range (206), ETag (304), `cache/` blocked, POST refused. Links now use `/ledger` (Pages redirects `.html`).
- Pages project: Cloudflare's GitHub app on `urbanmorph` covers selected repositories only, and `overlooked` is not one. Adding it needs an organisation owner.
- BSI: the earlier blanket exclusion was a misread instruction. BSI is now synced like every other source. A survey of BSI data and terms is running.
- Rate limits of all sources: research running; results go to `docs/sources.md`.
- Query C (species history and names) written. Queries B and D dropped. Kerala test download for query C running at GBIF.
- Unsurveyed groups: a group with no record in an area since the chosen year is set apart, not counted as quiet. Test data: districts with quiet species fell from 641 to 576.
- Site text rewritten to about 70% of ASD-STE100.
- Found: GBIF SQL downloads key species by Catalogue of Life ID (for example `5VKF2`). Pipeline and links changed to match.
- Kerala test on GitHub Actions passed (35 s): download, boundaries, build, checks, artifact, commit.
- Overview and ledger pages built for speed: no database or map library in the browser. Overview: 8 requests, 135 KB. Lighthouse mobile: 100 for accessibility, best practices and SEO.
- Kerala ledger (doi:10.15468/dl.6mfzfh): 8.85 million records, 9,243 species, 35,502 species x district rows.
- Grid test: coordinates rounded to 3 decimals beat a 1.7 km grid (0.2% against 1.6% of records in the wrong district).
- Overlap check: nothing found does modules 1 to 3 for India. Notes in `supporting-docs/overlap-check.md`.
- Repository, R2 bucket, secrets, plan and design canvas set up.
