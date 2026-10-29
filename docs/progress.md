# Progress

Newest first. Updated as work happens.

## 29 October 2026

- The Hutchinsonian gap and the 2 km grid: query A also counts records placed to 1 km or better (n_precise; validated with GBIF). The ledger build writes species_places.parquet per species: places (110 m points) with such a record, and occupied 2 km cells of an equal-area sinusoidal grid centred on 80 E (area of occupancy, IUCN's grid size; computed from the cube's points, no extra GBIF query). The master list counts species with exact records at 10 or more places (a common minimum to relate a species to climate maps); species pages show the area of occupancy. Both fill from the GBIF run of 2 November, with the traits. All seven gaps now have a measure.
- The Prestonian gap, for birds: State of India's Birds 2023 (MIT; pipeline/soib.py fetches its main table from GitHub each master run and keeps a copy in R2 cache/soib/). A trend is known when the long-term or current trend is rising, stable or falling (338 and 359 species of 942 assessed). Other groups stay not measured (IUCN). Research the same night: no BSI or other national checklist for fungi, mosses, liverworts or algae has open terms; the best, the 2024 lichen checklist (Sinha, Nayaka and Mishra 2025, 3,236 taxa, free PDF), is CC BY-NC 4.0, so it waits for a decision.
- The Raunkiæran gap, from the weekly GBIF request: query A now counts records with a trait (n_trait: a life stage, a sex, or flowers or fruits; "Unknown", "Indeterminate" and "no flowers or fruits" do not count), checked with GBIF's validate endpoint. The ledger carries it; the master list counts species with such a record placed in India, per group (summary traits, history measure traits; null for older ledgers). It fills from the run of 2 November. Facet counts for India: about 6 lakh records with a life stage, 2.8 lakh with a sex; iNaturalist flowering and fruiting annotations reach GBIF as reproductiveCondition.
- Home page: one list of groups. The group cards beside the map carry each group's Wallacean bar (open record and recent views), so the second list under the bar is gone. The BSI states were measured and not put on the maps: the books give a state for 2,741 species-state pairs (1,685 species, 281 of them with no open record), too few to show per state without suggesting the rest are absent.
- The shortlist is ranked by gaps: an observation comes first when its first (most likely) name, if right, gives the first open record of the species in the observation's state, or a record of a threatened (IUCN CR, EN, VU) or endemic species, from the published master list. Then the longest waiting. Of 13,522 rows on the current run: 1,878 a first in a state, 46 threatened, 165 endemic; no candidate is without an open record in India. Genus-first rows (amphibians, birds and others) have no reason yet. Each card says why it is near the top. experiments/corpus_v0/live.py rank <run> <new run> writes a ranked copy as a new run (published runs are immutable in R2), and prune ranks too; latest.json names the master list build. Also fixed: one beetle row had NaN for its place, which browsers refuse, so the live Beetles shortlist did not load since 27 October.
- The Eltonian gap, from GloBI's weekly snapshot (pipeline/globi.py; globi.yml weekly, only the 5 MB species table in R2 cache/globi/, the 2.7 GB snapshot downloaded only when its ETag changes): 48,606 species of the India list (30%) have an interaction recorded anywhere, 12,328 (7.5%) one recorded in India. Beetles: 5% anywhere, 0.4% in India. A locality counts as India only with the word India (not Indiana). Species pages show the number of partner species and link to GloBI; we publish only counts.
- IUCN: the Red List API extractor (pipeline/iucn_api.py) runs for internal analysis only; IUCN's terms (v3.1) free the categories but need a written waiver for any other Red List data on the site, even counts. From IUCN's own CC BY copy on GBIF the list now also keeps the year and DOI of each assessment. A home-page card counts, per group: assessed by IUCN (17,192, 10%); not assessed with open records in 5+ states (8,481); assessed before 2016 (4,166); Data Deficient with newer records (342); threatened with no recent record (1,544 of 2,442); endemic and not assessed (6,911). Species pages show the year of the assessment and link its DOI. The Prestonian gap waits for IUCN's permission (or State of India's Birds for birds).
- Safari kept an old module in memory across today's deploys and the home page stayed on "Loading..." (a mixed module set fails to load before it can show an error); quitting Safari cleared it. Fixes: scripts/pages.py stamps ?v=<hash of the contents and of the imported modules> on every script and stylesheet reference and every import, so a deploy changes the addresses; /assets/* is then cached for a year (_headers). The pages start their first data request in the head (window.early, reused by getJSON) instead of a preload link, which WebKit fetched twice. Checked in WebKit and Chromium: one request per file, no errors.
- Records to fix moved to its own page (/fix), with a state and a group to choose, kept in the address; in the main menu on every page; the home page links to it under the Wallacean bar. One list of group families (assets/cats.js) for both pages.
- Code review: one shared group-sum helper (common.js sumGroups) for the bar and the seven gaps; the three per-group summary counts in one query; place and group names from one helper each; dead CSS from removed pages deleted (17 rules); eslint finds no unused or undefined names.
- The seven gaps (shortfalls, Hortal et al. 2015) frame the home page: Linnean (species on the list described in the last 10 years), Wallacean (the bar), Prestonian, Darwinian (species with a DNA sequence or sample from India on GBIF), Raunkiæran, Hutchinsonian, Eltonian; a gap with no open data yet says where its data would come from. The bar is the Wallacean detail: all four parts are degrees of where-a-species-lives knowledge (an earlier version wrongly called "only in checklists" Linnean). summary.json and history.json add described_recent and dna per group. Method page: the standard definitions, the citation, and two later additions (Racovitzan, Haeckelian).
- Home page, redrawn the same day (dataviz review): "How far does our knowledge go?" counts each documented species once, at the furthest step we know about it, in one 100% bar: only in checklists and papers 67,425 (41%), open record but no place 27,088 (16%), placed but not recent 39,900 (24%), recorded in the last 10 years 29,867 (18%). Each part is a gap. One hue, light to dark (an ordinal ramp, validated). The same bar for each group family, sorted by the recent share: birds mostly recent, insects mostly checklists only, mosses mostly placed but old. The legend carries every number; a part with a map view sets it; the 9,261 names not on the list sit beside the bar. In a state the bar starts at the open record.
- Home page (first version, replaced): an evidence funnel replaces the weekly tiles and the view buttons. Linnean gap: documented in India (1,64,280), and beside it the names not on the list yet (9,182). Wallacean gap: with an open record (96,855, 59%), placed in a state (69,767, 42%), recorded in a state in the last 10 years (29,867, 18%). Eltonian gap: not measured yet. The line above each step names the gap; a step sets the map and the group cards (new view: recorded in the last 10 years); the change since the last list shows on each step. The species list has a Latest record column.
- Master list: each species and species x state keeps the latest year of a record with a place (`last_year`); summary.json adds per group "in a state", "recent" (since `recent_from`, 10 years before the list) and `unlisted`; history.json adds the three measures (older lists: null where they had no such count, kept by name). check_numbers checks the new totals.
- Coverage study, step 1 (`experiments/coverage_v0/`): the Linnean and Wallacean columns by group from the list and the snapshot.

## 28 October 2026

- One folder per master-list build (`layers/master/<week>/<build>/`, named by build time, never changed after). Files first (16 at once, each retried, `r2.UploadFailed` names any that fail), then the week's `current.json`, then `latest.json`: a publish never shows a mix of two builds. Builds of the week older than the one before are deleted. Earlier lists are read from R2 through their pointer, never from a local copy. Publishing the master list: 15.5 minutes to about 70 seconds.
- Retention of the master list in R2 (`master.prune`, after each publish): this week, the current build and the one before; a past week, only its last build (the one its `current.json` names); files from before builds go where the week has a pointer (October has none and keeps its files). GBIF snapshots are kept. About 45 MB of master list per week.

- Open records, the standard of biodiversity data: a species has an open record when a GBIF record or an iNaturalist research-grade observation gives it for India. An iNaturalist "needs ID" observation is not one: it waits for a name. Observed and identified became one measure, "With an open record" (they were 13 species apart once needs ID was set apart). A species named only in needs-ID observations is not on the list (status 2) but keeps its page and its place in the waiting lists. Effect on the 26 October list: documented 1,73,567 to 1,64,306 (9,261 off the list), with an open record 96,879 (was observed 1,07,554, identified 96,866); 1,414 stay with no open record (a checklist lists them). Home views: Open record, Waiting, IUCN; five weekly tiles. Lists from before are read with the same rule for the change log and the history (`master.previous_list`, `previous_summary`).

## 27 October 2026

- Weekly, not monthly: GBIF snapshot each Monday (`request.yml`, `build.yml` Monday to Thursday); iNaturalist, new-species and master list layers keyed by week (`util.period`, the Monday in UTC). The master list compares with the list `latest.json` names (`master.previous_period`), so the first weekly list (`2026-10-26`) compares with October. Site text says "week"; `periodName` shows "week of 26 October 2026".
- README rewritten for the current site (master list, Changes, Shortlists) and how the parts connect; the old ledger, backlog and new-species pages and `candidates.json` are gone from it.
- Shortlists, first week: 19 page views, 1 link followed to iNaturalist. Re-check at 7 days: 318 of 13,842 shown (2.3%) got a confirmed name; the species was on the list for 95% of Quick to confirm rows, the genus for 97% of Genus first rows. Not yet an effect of the page.
- Wrong-country records: VectorBase (US mosquitoes coded India, 30 species), Indian_sediments (metagenome names), two South African museums and state text naming other countries put about 356 non-Indian species in the master list. 17,364 species rest only on GBIF records with no exact place (mostly old museum specimens).
- Fixed: VectorBase, Indian_sediments and four Slovenian cave datasets added to `excluded_datasets.csv`; state text naming a place outside India (`pipeline/ref/foreign_places.csv`: Nepal, Sind, Ceylon, Burma, Japanese prefectures, Indiana, ...) dropped in `unlocated.py` and, for snapshots built before, in the master list. Effect on the October list: 214 species leave (1,74,157 to 1,73,943); observed share 62.11% to 62.06%. KwaZulu-Natal and IZIKO museum records name Indian states and stay. New label `lgo`, "Only GBIF records with no exact location" (about 17,150 species), so a reader can set apart species that rest on one source and no map point. Old Indian names (Madras, Bombay, Mysore) still go to no state: a later fix.

## Status (19 October 2026)

| Area | State |
|---|---|
| Repository, licence, secrets | Done. Public repo `urbanmorph/overlooked` (MIT). Actions secrets: GBIF and bucket-scoped R2 keys only. |
| Cloudflare | **Live: https://overlooked-india.pages.dev** since 16 October 2026. R2 bucket `overlooked-data` holds snapshot `2026-10`. |
| Plan | `docs/plan.md`, approved 16 October 2026, updated as decisions change. |
| Master list (the site model) | **Live.** 1,74,155 species documented from India (ZSI, BSI, Kew WCVP, GBIF, iNaturalist, Plazi, IUCN Red List; names from the Catalogue of Life); 1,08,173 observed, 97,586 identified, IUCN status per species. Rebuilt daily (`master.yml`), skipped when no input changed. |
| Explore (front page) | **Live.** Map by state, groups, search, filters (year described, source, status, IUCN, label), species list with labels. Wait for a name (iNaturalist) in the Identified view. Records to fix for data publishers (11,48,847 GBIF records that cannot go in a district, records not named to species). |
| Species page | **Live.** Sources, status, IUCN, states, GBIF records by decade and district, and a Next step block with links to act (add a record, identify, correct records on GBIF, check the name, IUCN, state forest department). |
| Change feed | Built and live; shows its first changes after the 1 November run. |
| Layers | iNaturalist (daily), new species since 2007 (daily, ZSI and BSI Discoveries), described years (COL, WCVP), BSI national checklists. |
| Monthly run (GitHub Actions) | **On** (`PIPELINE_ENABLED`). Downloads requested on the 1st at 02:17 UTC; build every 6 hours on days 1 to 10 until the snapshot is out. |
| Source limits | Documented in `docs/sources.md`. Pipeline follows them (GBIF downloads one at a time, crons off the hour). |

## Log

### 20 October 2026

- Georeferencing test for Records to fix (`experiments/georef/`), place names only (LGD state to village and
  protected areas from bharatlas, 244 old district names, spelling variants; no LLM). On 20,000 records with good
  coordinates hidden: right district 49.1%, wrong 9.5%, none 41.4% (83.8% right when it names one; hold-out half
  84.3%); right state 78.7%; median error 14.1 km. On the real records to fix (weighted to all 11,48,847): district
  37.9%, state or better 60.7% (today 30.9%). Most wrong answers are districts split after the record was made, or
  city against suburb. High or medium answers placed at a village, block, subdistrict or protected area: 92.4% right
  on the hold-out half, for 16% of records. A proposal is a suggestion for the publisher, never a fix.
- Georeferencing, district splits (`ref/district_splits.csv`, 515 rows, 1970 to 2023, one source per row, mostly
  Wikipedia and Statoids; LGD has no parent data). A district name now gives the district and the districts made
  from it after the record's year. Right 50.9% (was 49.1%), wrong 8.2% (was 9.5%), 86.1% right when it names
  one; but right with a single district fell to 39.1%, and 73% of the new sets were right with the parent alone.
  Records to fix: district 39.2%, state or better 61.5%. Splits explain 25% of the wrong answers, not most: the
  rest are city names (Mumbai, Hyderabad) and villages filed under their old district. Next: place villages in
  today's district by their point.
- Species health, first measure (plan section 6b): a state file per species in each snapshot and a list of
  changes against the previous one, with flags for changes in the sources. October is the baseline.
- Model check, corpus v0, shortlist module: see plan section 1d.
- BSI papers link to the PDF of their year, not BSI's listing page. The new-species layer checks each listed
  file with one HEAD request, keeps the larger PDF when a year has two, and keeps the answers in
  `cache/bsi/pdf_links.json`. A year is checked again only when its file leaves the listing.
- Mobile pass at 360 px. Pages loaded data into space that had no room kept for it, so the map moved down
  (layout shift 0.27 on the front page, 0.42 to 0.46 on species pages, 0.06 on Changes). Now main reaches
  below the screen and, on narrow screens, the status and group cards fill the screen while they load.
  Already fixed since the 18 October audit: self-hosted fonts, decade labels on phones, nav height (one
  row, 107 px), no file over 200 KB. Map on phones: usable; small states are easier to reach with search.

### 19 October 2026

- Records that cannot go in a district now count. Query L covers India records with no coordinates, coordinates
  uncertain by more than 25 km, or coordinates GBIF flags; it leaves out coordinates GBIF finds outside India and
  INSDC sequences with no coordinates. Backfilled for snapshot 2026-10 as new files only
  (`scripts/backfill_unlocated.py`, doi:10.15468/dl.tnbsse): 11,48,847 records (9,63,107 no coordinates, 1,64,308
  coarse, 21,432 flagged). The owner chose to count them as observed and documented. Master list rebuilt:
  1,74,155 documented (was 1,54,355), 1,08,172 observed (was 74,023), 97,586 identified; 34,126 species have the
  label "No exact location". Some of these records are not from India (for example American mosquitoes in a
  VectorBase dataset); the Records to fix table asks publishers to correct the country too.
- Records to fix on the front page, for data publishers: these records and the records not named to species, by
  state and group, the datasets that hold most of them and the species known only from them, with GBIF links.
  The species page links to the species' GBIF records from India, and to the ones with no coordinates when it has
  the label "No exact location".
- New species is no longer a category. Labels renamed: "No record since it was described" (only when the paper is
  the description), "No exact location". New label "Recorded under the name as published" (35 species). The
  new-species layer ignores INSDC sequences with no coordinates and matches names as published by whole words.
- Every species is tagged by the location problems of its GBIF records: no coordinates (65,385 species), coordinates
  uncertain by more than 25 km (12,514), coordinates GBIF marks as possibly wrong (975; such a record may not be
  from India). The species page has a "Next step" block: what a person can do and where (add a record, identify on
  iNaturalist, ask a specialist, correct records on GBIF with a link per problem, check the name, IUCN assessment,
  state forest department).
- Map fills its card again (its CSS had targeted the wrong class); search fixes; review: one helper fetches a GBIF
  download once.

### 18 October 2026

- Year described for every species, and the New species page folded into Explore. `pipeline/described.py`
  reduces the Catalogue of Life XR export (ChecklistBank, 144 MB, authorship) and Kew WCVP (88 MB, the
  basionym's year) to two parquet files in R2 `cache/described/`, downloaded again only for a new release.
  Order: the paper of a new species (a COL or ZSI year more than a year earlier wins: 85 Discoveries entries are
  older species listed as new), then COL, then the ZSI checklist authority, then WCVP for plants. 1,40,821 of
  1,54,355 species have a year (animals 92 to 100%, plants 84 to 96%; fungi 13%, lichens 17%, mosses 6%).
  Explore has a "Described" year range in Filters (`?described=2007-`); all filters now drive the map, cards and
  headline (counted in the browser from the group files; with no filter the counts equal summary.json exactly).
  `/new-species` redirects to `/?described=2007-`. Label "New species since 2007" replaced by "New species: no
  record after the description"; `ns.json` removed. 14,930 species on the list were described from 2007.
- Wait for a name: the master list now writes `w/<group>.json` and `summary.waiting` from the iNaturalist
  needs-ID species lists. 9,76,938 observations of 34,866 species wait for a name (named to species by the
  observer, not confirmed; fnf counted 9,74,192). For 12,654 of these species one confirmation gives the
  first identification in India. The Identified view lists them per group and state, most useful first
  (no identification here yet, threatened, endemic), each with a link to iNaturalist's Identify page.
- New species from 2007 (one constant, `gbif.NEW_SPECIES_FROM`): BSI Plant Discoveries 2007 to 2025 (2013 and 2014
  editions found and OCR'd; place words and host plants no longer read as species names, about 300 author-name
  headings replaced by the right names in 2015 to 2025), ZSI Animal Discoveries 2009 to 2024 (4,548 new animal
  species; 2007 and 2008 are not posted), Plazi from 2007. The New species page has a year range and shows
  identified and IUCN from the master list (`ns.json`). A state built for another window starts the month again.
- Retired the "last seen" model: the Last seen and Waiting for a name pages (redirected to the front page),
  the GBIF change feed (`changes.py`), the GBIF genus candidates (`candidates.py`), the quiet statistics and
  per-district ledger files in `site_data`, and the iNaturalist quiet check and backlog fetch (the daily
  iNaturalist budget now goes only to the species lists). The species page now reads the master list
  (`sp/<shard>.json`): status, IUCN, sources, labels, a map of where it is observed and identified, and
  observations that wait for a name, with GBIF records by decade and district below. Genus names now match
  by kingdom when both sides know it (a plant and an animal genus can share a name).
- Wait for a name, all three levels: the iNaturalist layer also fetches genera of observations named only to
  genus (8,55,929 observations, 13,957 genera) and counts of those named only above genus per iconic group
  (10,41,700), 694 requests. The master list ranks genera: not on the India list under any name the list knows
  (1,757 genera, 6,333 observations: possible new records for India), then genera with species never identified
  in India. Fixed in `layer_inat.run`: the species-lists document was overwritten by the quiet-species list
  before it was written (the run would have failed with a TypeError).
- Changes page rebuilt on the master list: each month is compared with the month before (`changes.json`):
  species identified for the first time in India or in a state, observed for the first time, added, or
  dropped (renamed or merged), with the sources that brought the change, and the waiting backlog before
  and now. October 2026 is the first list, so the first changes show after the November list.
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
