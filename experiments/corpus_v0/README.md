# Corpus v0: expert-confirmed Indian photos, and shortlists tested on the real queue

Date: 20 October 2026. Plan: `docs/plan.md`, section 1d (module 6), step 2 and the first part of step 3. Everything ran on an Apple M2 Pro. **Rule kept:** a model only makes a shortlist. Nothing was posted to iNaturalist or any site; all API use was read-only.

**Sovereignty.** Corpus v0 (photos, features, tables) is in `data/corpus_v0/` (gitignored), on this machine only. Nothing was uploaded to R2, Hugging Face or anywhere else. This folder holds only code and summary results.

## Headline

**Update, queue check (20 October 2026):** the groups for the experimental shortlist page are decided by the gate in "Queue check" below (rules fixed before the run, enlarged T1 of 2,545 rows): 12 Quick to confirm, 7 Genus first, 5 not enough data. A frozen sample of 8,044 queue observations (SHA-256 `c395de2a…3398`) will be re-checked at 30, 60 and 90 days. The verdicts in "Results on T1" were made with earlier, looser rules on the first T1 and are kept only as a record.

On **T1** (1,635 research-grade observations from observers that the corpus never saw, that waited 30 days or more for research grade), the best method is **zero-shot BioCLIP 2.5-filled plus a classifier trained on corpus v0** (combined). Overall:

| method | right species first | in top 5 | names for 90% | 90% set: coverage / median / 90th pct | 95% set: coverage / median / 90th pct | right genus first |
|---|---|---|---|---|---|---|
| zero-shot (BioCLIP 2.5-filled) | 75.9% | 95.4% | 3 | 92.9% / 2 / 7 | 97.4% / 4 / 56 | 91.7% |
| classifier on corpus v0 | 83.9% | 94.4% | 2 | 92.6% / 1 / 333 | 95.6% / 108 / 854 | 91.6% |
| **combined** | **86.7%** | **96.7%** | **2** | **92.6% / 1 / 5** | **97.0% / 3 / 84** | **93.5%** |

- Training on corpus v0 adds about 11 points at species level over zero-shot (75.9% to 86.7%). The gain is largest for bats (44.3% to 92.0%), molluscs, true bugs, beetles and fungi.
- **These T1 numbers are optimistic** (see Limits). Two checks show how much:
  - Zero-shot is right first for 81.1% of observations that reached research grade by 2024, but for 71.0% of those that reached it in 2025 or later. The older photos are probably in BioCLIP's training set. The combined method is the same in both (86.5% and 86.8%).
  - **On the real queue (T3)**, the observer's own species name is in the combined 90% set for 71.9% of 3,190 waiting observations (median set 2 names), not 90%. The observer's name is not a true answer, so this is a lower bound mixed with observer errors, but the queue is clearly harder than T1.
- **T2** (queue rows from the pilot that reached research grade in the 5 days since): only 19. The best method had the right species first for 18 (94.7%), and it was in the 90% set for all 19 (median 1 name). Too few to rely on.

## What was built

1. **Source.** One GBIF download (Darwin Core Archive with multimedia) of the iNaturalist Research-grade Observations dataset, country IN: key `0036259-260928105237408`, 1,705,774 records, 941 MB zip, 2,674,717 still images (100% of photo URLs map to the open-data bucket). The key is stored in `data/corpus_v0/download.json`, so the request is never sent twice.
2. **Names.** Groups from each record's classification with the model check's `GROUP_SQL`. Species matched to that group's candidate list. The list is the model check's bioclip-2.5-filled rule (Indian GBIF species that the filled label set can name): 33,669 species. Exact match first (GBIF species, then the iNaturalist name). Then synonyms through GBIF backbone matches: accepted name of the iNaturalist name, and candidates whose accepted name is the record's species (21,007 names matched through the GBIF API, cached). **No record needed a synonym:** the candidate names and the archive both use the GBIF backbone. 62,381 records are outside the 24 groups; 90,878 are not a candidate and were dropped (counted below).
3. **Observer split.** A stable hash of `recordedBy` (SHA-256 with a fixed salt): 20% of observers are test-only. 28,272 observers, 5,572 of them test. Matched records with a first photo: 1,202,356 train, 311,283 test. The 4,806 observations of the fnf pilot (its answer key and its queue) are in neither.
4. **T1 "waited".** 300 random test-observer observations per group (fewer where a group has fewer). Each one's identification history came from the iNaturalist API (30 requests of 200 ids). The research-grade date is the first time 2 or more identifications of the species are more than 2/3 of the identifications that count (iNaturalist's community-taxon rule; each user's latest identification; hidden ones excluded). The observation is kept if that date is 30 days or more after it was created, and it is still research grade at the same species.
5. **Corpus v0.** Train observers only, first photo only, at most 15 observations per species. Picks are spread out: every observer's first photo before anyone's second, and an observer's photos cycle through states. All candidate species with any train photo are included.
6. **Photos and features.** "Medium" photos from the `inaturalist-open-data` bucket (8 at a time), and BioCLIP 2.5 (ViT-H/14) image features from the model check's `embed.build`, in `.npz` shards of 2,000. Estimate before the run: 122,452 photos at 94.4 s per 1,000, so 3.2 h (under 8 h, so the cap stayed at 15).
7. **Evaluation** (`evaluate.py`), per group, over that group's candidates:
   - Zero-shot: BioCLIP 2.5 with the filled label vectors (model check `zeroshot.Scorer`).
   - Classifier: logistic regression on standardised features (full-batch L-BFGS, weight decay 1e-4, 1e-3 or 1e-2), or nearest neighbour (best cosine per species), chosen on validation. It can only name species with corpus photos.
   - Combined: w × zero-shot + (1 − w) × classifier, both temperature-calibrated, w ∈ {0.25, 0.5, 0.75}.
   - Validation: 15% of the train observers (a second stable hash), so it is also split by observer. Every choice (classifier, weight decay, temperatures, w, and the "best" method per group) is made on validation, never on T1.
   - Metrics: the model check's `scoring.shortlist_table`. Fixed list length k90/k95 is chosen on T1 itself. Split-conformal sets are calibrated per group on half of T1 split **by observer**, 20 repeats.
8. **Queue** (`queue_fetch.py`): the pilot's 12,000 needs-ID rows (`fnf/out/id_pilot_sample.csv`, read only), fetched again today (60 requests). The pilot's downloaded photos were reused. T2 and T3 use the fixed k90 and the conformal thresholds from all of T1 in the group.

## Counts

Names (records per group; "not a candidate" = dropped):

| group | exact | not a candidate | records | pct_kept |
|---|---|---|---|---|
| Algae & diatoms | 243 | 55 | 298 | 81.5 |
| Amphibians | 18005 | 1108 | 19113 | 94.2 |
| Bats | 2625 | 48 | 2673 | 98.2 |
| Bees, wasps & ants | 41076 | 2381 | 43457 | 94.5 |
| Beetles | 23787 | 5641 | 29428 | 80.8 |
| Birds | 532211 | 27924 | 560135 | 95.0 |
| Butterflies | 305827 | 23447 | 329274 | 92.9 |
| Dragonflies | 108588 | 309 | 108897 | 99.7 |
| Ferns | 1722 | 228 | 1950 | 88.3 |
| Fish | 413 | 62 | 475 | 86.9 |
| Flies | 6642 | 1232 | 7874 | 84.4 |
| Flowering plants (dicots) | 222700 | 5673 | 228373 | 97.5 |
| Fungi | 2501 | 423 | 2924 | 85.5 |
| Grasses & sedges | 4879 | 17 | 4896 | 99.7 |
| Large mammals | 42626 | 2506 | 45132 | 94.4 |
| Lichens | 37 | 1 | 38 | 97.4 |
| Molluscs | 14256 | 650 | 14906 | 95.6 |
| Mosses & liverworts | 131 | 3 | 134 | 97.8 |
| Moths | 108206 | 8852 | 117058 | 92.4 |
| Orchids | 4728 | 213 | 4941 | 95.7 |
| Reptiles | 50129 | 1035 | 51164 | 98.0 |
| Rodents & shrews | 10899 | 19 | 10918 | 99.8 |
| Spiders & kin | 38209 | 2316 | 40525 | 94.3 |
| True bugs | 12075 | 6735 | 18810 | 64.2 |
| All | 1552515 | 90878 | 1643393 | 94.5 |

Corpus v0 per group. `train_species` = candidate species with any train-observer photo; `species_with_cap` = species at the cap of 15:

| group | candidates | train_species | corpus_species | corpus_obs | corpus_photos | corpus_observers | species_with_cap | test_obs | t1_sample | pct_species_covered |
|---|---|---|---|---|---|---|---|---|---|---|
| Algae & diatoms | 213 | 15 | 15 | 51 | 51 | 20 | 1 | 2 | 2 | 7.0 |
| Amphibians | 271 | 208 | 208 | 1750 | 1750 | 520 | 81 | 3349 | 300 | 76.8 |
| Bats | 123 | 54 | 54 | 273 | 273 | 148 | 9 | 548 | 300 | 43.9 |
| Bees, wasps & ants | 1011 | 456 | 456 | 3238 | 3238 | 813 | 139 | 9018 | 300 | 45.1 |
| Beetles | 1269 | 854 | 854 | 5157 | 5157 | 1190 | 183 | 4841 | 300 | 67.3 |
| Birds | 1476 | 1168 | 1168 | 14821 | 14821 | 1418 | 868 | 113723 | 300 | 79.1 |
| Butterflies | 1002 | 779 | 779 | 8498 | 8498 | 1227 | 454 | 59785 | 300 | 77.7 |
| Dragonflies | 367 | 315 | 315 | 3299 | 3299 | 747 | 175 | 24154 | 300 | 85.8 |
| Ferns | 625 | 108 | 108 | 526 | 526 | 265 | 14 | 246 | 246 | 17.3 |
| Fish | 2642 | 50 | 50 | 273 | 273 | 99 | 5 | 45 | 45 | 1.9 |
| Flies | 623 | 281 | 281 | 1570 | 1570 | 523 | 57 | 1225 | 300 | 45.1 |
| Flowering plants (dicots) | 9147 | 4444 | 4444 | 30856 | 30856 | 3515 | 1241 | 42437 | 300 | 48.6 |
| Fungi | 2268 | 333 | 333 | 1186 | 1186 | 552 | 24 | 427 | 300 | 14.7 |
| Grasses & sedges | 1128 | 339 | 339 | 1844 | 1844 | 451 | 60 | 628 | 300 | 30.1 |
| Large mammals | 127 | 104 | 104 | 1243 | 1243 | 613 | 73 | 8271 | 300 | 81.9 |
| Lichens | 750 | 2 | 2 | 2 | 2 | 2 | 0 | 1 | 1 | 0.3 |
| Molluscs | 2680 | 609 | 609 | 3441 | 3441 | 677 | 121 | 2335 | 300 | 22.7 |
| Mosses & liverworts | 1122 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0.1 |
| Moths | 3862 | 3317 | 3317 | 24570 | 24570 | 1733 | 930 | 18163 | 300 | 85.9 |
| Orchids | 736 | 320 | 320 | 2005 | 2005 | 504 | 63 | 806 | 300 | 43.5 |
| Reptiles | 564 | 461 | 461 | 4302 | 4302 | 1321 | 199 | 8804 | 300 | 81.7 |
| Rodents & shrews | 107 | 58 | 58 | 559 | 559 | 312 | 31 | 2042 | 300 | 54.2 |
| Spiders & kin | 618 | 417 | 417 | 3252 | 3252 | 913 | 138 | 8046 | 300 | 67.5 |
| True bugs | 938 | 639 | 639 | 3740 | 3740 | 929 | 128 | 2386 | 300 | 68.1 |
| All | 33669 | 15332 | 15332 | 116457 | 116457 | 6925 | 4994 | 311283 | 5995 | 45.5 |

Corpus v0: **15,332 of 33,669 candidate species (45.5%), 116,457 observations, 116,457 photos (one per observation), 6,925 observers.** Licences: CC BY-NC 90,159; CC BY 19,082; CC0 2,456; CC BY-NC-SA 2,146; CC BY-NC-ND 1,871; CC BY-ND 441; CC BY-SA 302.

T1 "waited" (`qualify` = research grade 30 days or more after creation; `changed_or_gone` = no longer research grade, or the species changed since the GBIF copy):

| group | sampled | qualify | rg_within_30d | changed_or_gone | no_rg_date | median_waited_days | median_identifiers | observers | species |
|---|---|---|---|---|---|---|---|---|---|
| Algae & diatoms | 2 | 0 | 2 | 0 | 0 |  |  |  |  |
| Amphibians | 300 | 85 | 215 | 0 | 0 | 216.0 | 1.0 | 57.0 | 33.0 |
| Bats | 300 | 176 | 124 | 0 | 0 | 649.0 | 2.0 | 94.0 | 20.0 |
| Bees, wasps & ants | 300 | 45 | 255 | 0 | 0 | 168.0 | 2.0 | 32.0 | 35.0 |
| Beetles | 300 | 90 | 209 | 1 | 0 | 324.0 | 2.0 | 57.0 | 63.0 |
| Birds | 300 | 29 | 271 | 0 | 0 | 192.0 | 1.0 | 17.0 | 27.0 |
| Butterflies | 300 | 38 | 262 | 0 | 0 | 157.0 | 2.0 | 29.0 | 30.0 |
| Dragonflies | 300 | 20 | 275 | 5 | 0 | 230.0 | 2.5 | 16.0 | 17.0 |
| Ferns | 246 | 85 | 161 | 0 | 0 | 193.0 | 1.0 | 44.0 | 35.0 |
| Fish | 45 | 5 | 40 | 0 | 0 | 139.0 | 2.0 | 5.0 | 5.0 |
| Flies | 300 | 148 | 152 | 0 | 0 | 296.0 | 1.0 | 77.0 | 56.0 |
| Flowering plants (dicots) | 300 | 94 | 205 | 1 | 0 | 211.0 | 1.0 | 64.0 | 83.0 |
| Fungi | 300 | 115 | 185 | 0 | 0 | 155.0 | 1.0 | 75.0 | 58.0 |
| Grasses & sedges | 300 | 129 | 171 | 0 | 0 | 270.0 | 1.0 | 66.0 | 50.0 |
| Large mammals | 300 | 40 | 260 | 0 | 0 | 111.0 | 2.0 | 36.0 | 16.0 |
| Lichens | 1 | 0 | 1 | 0 | 0 |  |  |  |  |
| Molluscs | 300 | 85 | 215 | 0 | 0 | 206.0 | 2.0 | 60.0 | 40.0 |
| Mosses & liverworts | 1 | 1 | 0 | 0 | 0 | 698.0 | 2.0 | 1.0 | 1.0 |
| Moths | 300 | 100 | 199 | 1 | 0 | 387.0 | 1.0 | 56.0 | 80.0 |
| Orchids | 300 | 50 | 250 | 0 | 0 | 158.0 | 1.0 | 23.0 | 32.0 |
| Reptiles | 300 | 38 | 262 | 0 | 0 | 173.0 | 2.0 | 33.0 | 30.0 |
| Rodents & shrews | 300 | 52 | 248 | 0 | 0 | 147.0 | 1.0 | 44.0 | 15.0 |
| Spiders & kin | 300 | 95 | 205 | 0 | 0 | 530.0 | 1.0 | 61.0 | 41.0 |
| True bugs | 300 | 121 | 179 | 0 | 0 | 268.0 | 1.0 | 68.0 | 69.0 |
| All | 5995 | 1641 | 4346 | 8 | 0 | 273.0 | 1.0 | 499.0 | 836.0 |

**Too few in T1** (not padded): algae and diatoms 0, lichens 0, mosses and liverworts 1, fish 5. These four groups are left out of the T1 metrics (a group needs 20 rows). Dragonflies (20), birds (29), butterflies (38) and reptiles (38) are tested, but their results are provisional. 72% of the sample reached research grade within 30 days, so the waiting part of the queue is a minority.

## Results on T1

These tables are from the first T1 (1,635 rows). The enlarged T1 of the queue check is in "Queue check: results" below.

### Verdict per group

Method chosen per group on validation. The rules were fixed before reading the results: **Quick to confirm** if species k90 ≤ 3, 90% set median ≤ 2 and 95% set median ≤ 5. Otherwise **genus only** if genus k90 ≤ 3 and genus 95% set median ≤ 3. Otherwise **expert only**. "T3 name in 90% set" is the queue check (not used in the verdict).

| group | method | T1 n | species k90 | 90% set median | 95% set median | genus k90 | genus 95% set median | T3 name in 90% set | verdict |
|---|---|---|---|---|---|---|---|---|---|
| Amphibians | combined | 85 | 2 | 2 | 4 | 1 | 1 | 61.6 | Quick to confirm |
| Bats | classifier | 176 | 1 | 1 | 54 | 1 | 1 | 41.4 | genus only |
| Bees, wasps & ants | combined | 45 | 2 | 1 | 1011 | 1 | 331 | 71.3 | expert only |
| Beetles | combined | 90 | 2 | 2 | 3 | 1 | 2 | 76.1 | Quick to confirm |
| Birds | combined | 29 | 2 | 2 | 1476 | 2 | 511 | 57.5 | expert only (provisional: few test rows) |
| Butterflies | combined | 38 | 2 | 2 | 7 | 1 | 2 | 91.1 | genus only (provisional: few test rows) |
| Dragonflies | combined | 20 | 3 | 2 | 367 | 1 | 139 | 69.5 | expert only (provisional: few test rows) |
| Ferns | combined | 85 | 2 | 2 | 4 | 1 | 1 | 80.5 | Quick to confirm |
| Flies | combined | 148 | 2 | 1 | 2 | 1 | 1 | 60.3 | Quick to confirm |
| Flowering plants (dicots) | combined | 94 | 2 | 2 | 18 | 1 | 2 | 70.0 | genus only |
| Fungi | combined | 115 | 2 | 1 | 2 | 1 | 1 | 64.2 | Quick to confirm |
| Grasses & sedges | combined | 129 | 3 | 1 | 3 | 2 | 1 | 75.2 | Quick to confirm |
| Large mammals | classifier | 40 | 3 | 2 | 2 | 1 | 1 | 73.5 | Quick to confirm |
| Molluscs | combined | 85 | 1 | 1 | 1 | 1 | 1 | 66.2 | Quick to confirm |
| Moths | combined | 100 | 2 | 1 | 8 | 1 | 2 | 68.8 | genus only |
| Orchids | combined | 50 | 2 | 2 | 3 | 1 | 1 | 52.5 | Quick to confirm |
| Reptiles | combined | 38 | 2 | 11 | 30 | 2 | 5 | 98.3 | expert only (provisional: few test rows) |
| Rodents & shrews | combined | 52 | 2 | 2 | 2 | 1 | 1 | 77.4 | Quick to confirm |
| Spiders & kin | combined | 95 | 1 | 1 | 2 | 1 | 1 | 67.0 | Quick to confirm |
| True bugs | combined | 121 | 1 | 1 | 2 | 1 | 1 | 69.6 | Quick to confirm |

How to read the verdicts:
- "Quick to confirm" here means "on T1". T3 shows the observer's name in the 90% set for only 41.4% (bats) to 98.3% (reptiles) of queue rows. Before a group goes on the queue page, check its shortlists on fresh queue data (step 3 of the plan: time identifiers).
- The 95% set often fails because of the small T1 calibration halves, not only because the model is weak. With about 20 rows in a half, one hard photo pushes the 95% threshold to the whole candidate list (bees 1,011, birds 1,476, dragonflies 367). More T1 rows per group would settle this.
- Reptiles are weak: 68.4% top-1 and a median 90% set of 11 names. Bats, bees, birds, butterflies, dragonflies, dicots and moths pass at 90% and fail only on the 95% set median.
- Fish, mosses, lichens and algae: **not tested** (too few T1 rows). The corpus barely covers them: 50, 1, 2 and 15 species.

### Best method per group

| group | method | n | r@1 | r@5 | genus r@1 | k90 | conf90_median | conf95_median |
|---|---|---|---|---|---|---|---|---|
| Bats | classifier | 176 | 92.0 | 96.6 | 94.3 | 1 | 1 | 54 |
| Large mammals | classifier | 40 | 80.0 | 92.5 | 92.5 | 3 | 2 | 2 |
| Amphibians | combined | 85 | 81.2 | 96.5 | 91.8 | 2 | 2 | 4 |
| Bees, wasps & ants | combined | 45 | 86.7 | 95.6 | 93.3 | 2 | 1 | 1011 |
| Beetles | combined | 90 | 85.6 | 96.7 | 91.1 | 2 | 2 | 3 |
| Birds | combined | 29 | 72.4 | 96.6 | 82.8 | 2 | 2 | 1476 |
| Butterflies | combined | 38 | 84.2 | 100.0 | 92.1 | 2 | 2 | 7 |
| Dragonflies | combined | 20 | 85.0 | 100.0 | 95.0 | 3 | 2 | 367 |
| Ferns | combined | 85 | 84.7 | 95.3 | 92.9 | 2 | 2 | 4 |
| Flies | combined | 148 | 87.8 | 98.6 | 94.6 | 2 | 1 | 2 |
| Flowering plants (dicots) | combined | 94 | 89.4 | 93.6 | 92.6 | 2 | 2 | 18 |
| Fungi | combined | 115 | 85.2 | 94.8 | 93.9 | 2 | 1 | 2 |
| Grasses & sedges | combined | 129 | 82.2 | 91.5 | 88.4 | 3 | 1 | 3 |
| Molluscs | combined | 85 | 92.9 | 97.6 | 95.3 | 1 | 1 | 1 |
| Moths | combined | 100 | 88.0 | 95.0 | 95.0 | 2 | 1 | 8 |
| Orchids | combined | 50 | 88.0 | 100.0 | 98.0 | 2 | 2 | 3 |
| Reptiles | combined | 38 | 68.4 | 94.7 | 86.8 | 2 | 11 | 30 |
| Rodents & shrews | combined | 52 | 80.8 | 100.0 | 96.2 | 2 | 2 | 2 |
| Spiders & kin | combined | 95 | 90.5 | 98.9 | 94.7 | 1 | 1 | 2 |
| True bugs | combined | 121 | 90.1 | 99.2 | 94.2 | 1 | 1 | 2 |

### All methods, per group

`n` = T1 rows, `median_candidates` = candidates per photo, `r@k` = right species in the top k, `k90`/`k95` = fixed list length for 90%/95% (chosen on T1), `conf..` = conformal sets (coverage %, median size, 90th percentile size), `genus r@1/3`.

| group | n | median_candidates | r@1 | r@3 | r@5 | r@10 | r@20 | k90 | k95 | conf90_cov | conf90_median | conf90_p90 | conf95_cov | conf95_median | conf95_p90 | genus r@1 | genus r@3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Amphibians | 85 | 271 | 81.2 | 92.9 | 96.5 | 97.6 | 98.8 | 2 | 4 | 92.8 | 2 | 5 | 97.1 | 4 | 15 | 91.8 | 98.8 |
| Bats | 176 | 123 | 93.8 | 97.7 | 97.7 | 98.9 | 98.9 | 1 | 2 | 91.8 | 1 | 2 | 96.4 | 2 | 4 | 96.0 | 100.0 |
| Bees, wasps & ants | 45 | 1011 | 86.7 | 95.6 | 95.6 | 97.8 | 97.8 | 2 | 3 | 88.5 | 1 | 16 | 94.0 | 1011 | 1011 | 93.3 | 97.8 |
| Beetles | 90 | 1269 | 85.6 | 95.6 | 96.7 | 98.9 | 100.0 | 2 | 3 | 94.4 | 2 | 4 | 99.2 | 3 | 8 | 91.1 | 96.7 |
| Birds | 29 | 1476 | 72.4 | 96.6 | 96.6 | 96.6 | 96.6 | 2 | 2 | 95.4 | 2 | 30 | 100.0 | 1476 | 1476 | 82.8 | 96.6 |
| Butterflies | 38 | 1002 | 84.2 | 97.4 | 100.0 | 100.0 | 100.0 | 2 | 3 | 94.7 | 2 | 5 | 96.8 | 7 | 1002 | 92.1 | 100.0 |
| Dragonflies | 20 | 367 | 85.0 | 90.0 | 100.0 | 100.0 | 100.0 | 3 | 4 | 92.5 | 2 | 367 | 100.0 | 367 | 367 | 95.0 | 100.0 |
| Ferns | 85 | 625 | 84.7 | 95.3 | 95.3 | 96.5 | 96.5 | 2 | 3 | 93.1 | 2 | 7 | 97.8 | 4 | 12 | 92.9 | 95.3 |
| Flies | 148 | 623 | 87.8 | 96.6 | 98.6 | 99.3 | 99.3 | 2 | 2 | 92.9 | 1 | 2 | 98.0 | 2 | 4 | 94.6 | 98.0 |
| Flowering plants (dicots) | 94 | 9147 | 89.4 | 92.6 | 93.6 | 94.7 | 94.7 | 2 | 21 | 94.2 | 2 | 15 | 97.9 | 18 | 369 | 92.6 | 95.7 |
| Fungi | 115 | 2268 | 85.2 | 93.0 | 94.8 | 98.3 | 100.0 | 2 | 6 | 90.7 | 1 | 3 | 96.9 | 2 | 9 | 93.9 | 97.4 |
| Grasses & sedges | 129 | 1128 | 82.2 | 90.7 | 91.5 | 94.6 | 95.3 | 3 | 13 | 90.0 | 1 | 5 | 94.9 | 3 | 21 | 88.4 | 94.6 |
| Large mammals | 40 | 127 | 82.5 | 95.0 | 97.5 | 100.0 | 100.0 | 3 | 3 | 92.9 | 2 | 6 | 93.9 | 2 | 9 | 97.5 | 100.0 |
| Molluscs | 85 | 2680 | 92.9 | 96.5 | 97.6 | 100.0 | 100.0 | 1 | 3 | 93.8 | 1 | 2 | 97.5 | 1 | 5 | 95.3 | 98.8 |
| Moths | 100 | 3862 | 88.0 | 95.0 | 95.0 | 95.0 | 97.0 | 2 | 2 | 91.2 | 1 | 2 | 96.2 | 8 | 48 | 95.0 | 97.0 |
| Orchids | 50 | 736 | 88.0 | 98.0 | 100.0 | 100.0 | 100.0 | 2 | 3 | 94.2 | 2 | 4 | 96.2 | 3 | 736 | 98.0 | 100.0 |
| Reptiles | 38 | 564 | 68.4 | 94.7 | 94.7 | 94.7 | 94.7 | 2 | 102 | 94.0 | 11 | 39 | 95.3 | 30 | 564 | 86.8 | 94.7 |
| Rodents & shrews | 52 | 107 | 80.8 | 100.0 | 100.0 | 100.0 | 100.0 | 2 | 3 | 96.5 | 2 | 5 | 97.1 | 2 | 5 | 96.2 | 100.0 |
| Spiders & kin | 95 | 618 | 90.5 | 97.9 | 98.9 | 100.0 | 100.0 | 1 | 2 | 95.5 | 1 | 2 | 98.2 | 2 | 4 | 94.7 | 98.9 |
| True bugs | 121 | 938 | 90.1 | 98.3 | 99.2 | 99.2 | 99.2 | 1 | 2 | 94.0 | 1 | 2 | 97.6 | 2 | 5 | 94.2 | 98.3 |
| All | 1635 | 938 | 86.7 | 95.5 | 96.7 | 98.0 | 98.4 | 2 | 3 | 92.6 | 1 | 5 | 97.0 | 3 | 84 | 93.5 | 97.8 |

| group | n | median_candidates | r@1 | r@3 | r@5 | r@10 | r@20 | k90 | k95 | conf90_cov | conf90_median | conf90_p90 | conf95_cov | conf95_median | conf95_p90 | genus r@1 | genus r@3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Amphibians | 85 | 271 | 71.8 | 90.6 | 96.5 | 98.8 | 98.8 | 3 | 4 | 92.1 | 2 | 5 | 97.5 | 6 | 22 | 90.6 | 98.8 |
| Bats | 176 | 123 | 44.3 | 90.9 | 96.0 | 97.2 | 99.4 | 3 | 4 | 91.8 | 3 | 5 | 95.7 | 3 | 7 | 96.6 | 100.0 |
| Bees, wasps & ants | 45 | 1011 | 77.8 | 93.3 | 93.3 | 95.6 | 97.8 | 2 | 6 | 90.9 | 2 | 14 | 94.9 | 1011 | 1011 | 93.3 | 97.8 |
| Beetles | 90 | 1269 | 71.1 | 90.0 | 94.4 | 98.9 | 98.9 | 3 | 6 | 94.4 | 2 | 5 | 98.9 | 8 | 24 | 86.7 | 97.8 |
| Birds | 29 | 1476 | 82.8 | 93.1 | 93.1 | 93.1 | 96.6 | 2 | 13 | 96.1 | 4 | 36 | 100.0 | 1476 | 1476 | 89.7 | 93.1 |
| Butterflies | 38 | 1002 | 89.5 | 97.4 | 100.0 | 100.0 | 100.0 | 2 | 3 | 96.3 | 1 | 3 | 97.6 | 4 | 1002 | 94.7 | 100.0 |
| Dragonflies | 20 | 367 | 80.0 | 95.0 | 100.0 | 100.0 | 100.0 | 3 | 3 | 94.5 | 2 | 367 | 100.0 | 367 | 367 | 95.0 | 100.0 |
| Ferns | 85 | 625 | 82.4 | 94.1 | 94.1 | 95.3 | 96.5 | 2 | 6 | 93.6 | 2 | 7 | 97.5 | 5 | 21 | 90.6 | 95.3 |
| Flies | 148 | 623 | 80.4 | 92.6 | 97.3 | 98.6 | 99.3 | 2 | 4 | 94.1 | 1 | 3 | 97.8 | 2 | 7 | 92.6 | 98.6 |
| Flowering plants (dicots) | 94 | 9147 | 85.1 | 91.5 | 91.5 | 92.6 | 95.7 | 2 | 14 | 94.4 | 3 | 34 | 97.9 | 13 | 164 | 91.5 | 94.7 |
| Fungi | 115 | 2268 | 76.5 | 93.0 | 95.7 | 98.3 | 100.0 | 3 | 5 | 91.5 | 2 | 4 | 95.9 | 3 | 12 | 90.4 | 97.4 |
| Grasses & sedges | 129 | 1128 | 82.9 | 88.4 | 90.7 | 94.6 | 98.4 | 5 | 12 | 89.6 | 1 | 7 | 95.5 | 3 | 19 | 86.8 | 95.3 |
| Large mammals | 40 | 127 | 77.5 | 97.5 | 97.5 | 100.0 | 100.0 | 3 | 3 | 93.9 | 2 | 6 | 94.4 | 2 | 7 | 97.5 | 100.0 |
| Molluscs | 85 | 2680 | 77.6 | 85.9 | 94.1 | 98.8 | 100.0 | 5 | 6 | 91.6 | 2 | 6 | 97.4 | 3 | 15 | 90.6 | 97.6 |
| Moths | 100 | 3862 | 82.0 | 92.0 | 95.0 | 96.0 | 97.0 | 3 | 4 | 91.6 | 2 | 7 | 96.3 | 7 | 36 | 92.0 | 96.0 |
| Orchids | 50 | 736 | 78.0 | 94.0 | 96.0 | 98.0 | 100.0 | 2 | 4 | 94.2 | 3 | 7 | 97.8 | 7 | 736 | 98.0 | 100.0 |
| Reptiles | 38 | 564 | 60.5 | 94.7 | 94.7 | 94.7 | 94.7 | 2 | 49 | 93.7 | 8 | 22 | 95.0 | 21 | 564 | 84.2 | 94.7 |
| Rodents & shrews | 52 | 107 | 80.8 | 94.2 | 98.1 | 100.0 | 100.0 | 2 | 4 | 95.5 | 2 | 4 | 95.7 | 2 | 5 | 96.2 | 100.0 |
| Spiders & kin | 95 | 618 | 87.4 | 96.8 | 97.9 | 98.9 | 100.0 | 2 | 2 | 93.9 | 1 | 3 | 96.9 | 2 | 9 | 93.7 | 98.9 |
| True bugs | 121 | 938 | 81.8 | 95.9 | 97.5 | 99.2 | 99.2 | 2 | 3 | 93.1 | 1 | 2 | 97.4 | 3 | 14 | 88.4 | 96.7 |
| All | 1635 | 938 | 75.9 | 92.4 | 95.4 | 97.4 | 98.7 | 3 | 5 | 92.9 | 2 | 7 | 97.4 | 4 | 56 | 91.7 | 97.6 |

| group | n | median_candidates | r@1 | r@3 | r@5 | r@10 | r@20 | k90 | k95 | conf90_cov | conf90_median | conf90_p90 | conf95_cov | conf95_median | conf95_p90 | genus r@1 | genus r@3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Amphibians | 85 | 208 | 80.0 | 90.6 | 90.6 | 94.1 | 100.0 | 3 | 11 | 94.8 | 4 | 17 | 98.7 | 6 | 23 | 90.6 | 96.5 |
| Bats | 176 | 54 | 92.0 | 95.5 | 96.6 | 96.6 | 96.6 | 1 | 2 | 90.9 | 1 | 2 | 96.0 | 54 | 54 | 94.3 | 98.3 |
| Bees, wasps & ants | 45 | 456 | 84.4 | 93.3 | 95.6 | 95.6 | 95.6 | 3 | 5 | 90.5 | 2 | 456 | 94.0 | 456 | 456 | 93.3 | 97.8 |
| Beetles | 90 | 854 | 78.9 | 91.1 | 91.1 | 94.4 | 94.4 | 3 | not reached | 92.5 | 3 | 854 | not reached | not reached | not reached | 86.7 | 93.3 |
| Birds | 29 | 1168 | 72.4 | 93.1 | 93.1 | 96.6 | 96.6 | 3 | 7 | 95.4 | 2 | 26 | 100.0 | 1168 | 1168 | 79.3 | 96.6 |
| Butterflies | 38 | 779 | 76.3 | 89.5 | 89.5 | 92.1 | 94.7 | 6 | 25 | 94.5 | 4 | 25 | 97.1 | 59 | 779 | 94.7 | 97.4 |
| Dragonflies | 20 | 315 | 80.0 | 90.0 | 100.0 | 100.0 | 100.0 | 3 | 5 | 93.5 | 2 | 315 | 100.0 | 315 | 315 | 95.0 | 100.0 |
| Ferns | 85 | 108 | 82.4 | 90.6 | 92.9 | 94.1 | 94.1 | 3 | 42 | 93.8 | 5 | 108 | 94.9 | 108 | 108 | 90.6 | 92.9 |
| Flies | 148 | 281 | 85.1 | 95.3 | 95.3 | 95.9 | 95.9 | 2 | 3 | 92.2 | 1 | 2 | 96.2 | 281 | 281 | 93.9 | 97.3 |
| Flowering plants (dicots) | 94 | 4444 | 84.0 | 91.5 | 93.6 | 95.7 | 95.7 | 3 | 10 | 92.9 | 1 | 12 | 96.1 | 4444 | 4444 | 88.3 | 94.7 |
| Fungi | 115 | 333 | 80.0 | 88.7 | 90.4 | 91.3 | 91.3 | 5 | not reached | 91.7 | 333 | 333 | not reached | not reached | not reached | 87.0 | 92.2 |
| Grasses & sedges | 129 | 339 | 80.6 | 89.9 | 91.5 | 93.0 | 93.0 | 4 | not reached | 88.9 | 2 | 339 | not reached | not reached | not reached | 86.0 | 94.6 |
| Large mammals | 40 | 104 | 80.0 | 90.0 | 92.5 | 95.0 | 100.0 | 3 | 6 | 92.4 | 2 | 11 | 93.7 | 2 | 12 | 92.5 | 97.5 |
| Molluscs | 85 | 609 | 89.4 | 94.1 | 97.6 | 98.8 | 98.8 | 2 | 4 | 94.1 | 1 | 4 | 99.3 | 609 | 609 | 94.1 | 97.6 |
| Moths | 100 | 3317 | 86.0 | 94.0 | 96.0 | 96.0 | 97.0 | 2 | 4 | 91.0 | 1 | 2 | 95.9 | 24 | 3317 | 95.0 | 97.0 |
| Orchids | 50 | 320 | 82.0 | 94.0 | 96.0 | 96.0 | 96.0 | 2 | 4 | 93.8 | 320 | 320 | 94.2 | 320 | 320 | 96.0 | 100.0 |
| Reptiles | 38 | 461 | 73.7 | 92.1 | 92.1 | 94.7 | 94.7 | 3 | 352 | 94.0 | 22 | 83 | 95.6 | 58 | 461 | 89.5 | 94.7 |
| Rodents & shrews | 52 | 58 | 73.1 | 94.2 | 100.0 | 100.0 | 100.0 | 2 | 4 | 97.7 | 5 | 27 | 98.3 | 6 | 27 | 92.3 | 98.1 |
| Spiders & kin | 95 | 417 | 88.4 | 96.8 | 97.9 | 98.9 | 100.0 | 2 | 3 | 95.1 | 1 | 3 | 97.8 | 2 | 16 | 95.8 | 97.9 |
| True bugs | 121 | 639 | 90.9 | 95.9 | 95.9 | 96.7 | 96.7 | 1 | 3 | 93.5 | 1 | 2 | 97.8 | 639 | 639 | 94.2 | 98.3 |
| All | 1635 | 339 | 83.9 | 92.9 | 94.4 | 95.6 | 96.2 | 2 | 7 | 92.6 | 1 | 333 | 95.6 | 108 | 854 | 91.6 | 96.4 |

### Species with no corpus photo

50 of 1,635 T1 rows (3.1%) are species with no corpus photo. The classifier cannot name them (0%). The combined list still has the right species first for 22.0% of them, in the top 5 for 60.0% and in the top 20 for 76.0%. Zero-shot alone does better on them (36.0% / 72.0% / 90.0%), because the classifier pulls probability towards seen species. Per group and method: `results/t1_unseen.csv`.

### Check for training overlap

| research grade | n | zero-shot r@1 | zero-shot r@5 | classifier r@1 | classifier r@5 | combined r@1 | combined r@5 |
|---|---|---|---|---|---|---|---|
| 2025 or later | 841 | 71.0 | 94.3 | 84.1 | 94.2 | 86.8 | 96.3 |
| by 2024 | 794 | 81.1 | 96.6 | 83.6 | 94.6 | 86.5 | 97.1 |

BioCLIP 2.5 was trained on TreeOfLife-200M, which is built from GBIF images, iNaturalist research-grade photos among them. The cut-off date of that snapshot was not checked. A T1 photo that was research grade by 2024 may have been in that training set. Zero-shot drops 10.1 points on the 2025-or-later photos; the trained classifier and the combination do not. So the zero-shot T1 figures (and the model check's) are partly inflated by training overlap, and the gain from the corpus is larger than T1 shows on new photos (71.0% to 86.8%).

## Results on the queue

### T2: pilot queue rows that are research grade now

| group | method | n | top1 | top5 | in k90 list | median k90 | in 90% set | median 90% set | in 95% set | median 95% set |
|---|---|---|---|---|---|---|---|---|---|---|
| Bats | classifier | 1 | 100.0 | 100.0 | 100.0 | 1.0 | 100.0 | 1.0 | 100.0 | 1.0 |
| Bees, wasps & ants | combined | 4 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 6.5 |
| Beetles | combined | 1 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 4.0 |
| Birds | combined | 1 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 2.0 |
| Dragonflies | combined | 5 | 80.0 | 100.0 | 100.0 | 3.0 | 100.0 | 2.0 | 100.0 | 2.0 |
| Ferns | combined | 1 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 2.0 |
| Flowering plants (dicots) | combined | 3 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 3.0 |
| Orchids | combined | 1 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 2.0 |
| Reptiles | combined | 1 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 5.0 |
| Rodents & shrews | combined | 1 | 100.0 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 2.0 |
| All | best per group | 19 | 94.7 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 2.0 |
| All | classifier | 19 | 94.7 | 100.0 | 94.7 | 3.0 | 100.0 | 1.0 | 100.0 | 108.0 |
| All | combined | 19 | 94.7 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 2.0 |
| All | zero-shot | 19 | 94.7 | 100.0 | 100.0 | 2.0 | 100.0 | 1.0 | 100.0 | 3.0 |

Of the 12,000 needs-ID rows the pilot sampled on 15 October, 20 are research grade today. 19 are at a species that is a candidate. 1 observation is no longer returned by the API. This is a true test, but far too small to rely on.

### T3: the observer's own species name on the queue

3,552 queue rows have an observer's species identification that is a candidate. 3,190 are in groups tested on T1. "In 90% set" uses the T1-calibrated threshold of that group.

| group | method | n | top1 | top5 | in k90 list | median k90 | in 90% set | median 90% set | in 95% set | median 95% set |
|---|---|---|---|---|---|---|---|---|---|---|
| Amphibians | combined | 159 | 44.7 | 74.8 | 62.3 | 2.0 | 61.6 | 2.0 | 76.7 | 4.0 |
| Bats | classifier | 87 | 47.1 | 80.5 | 47.1 | 1.0 | 41.4 | 1.0 | 78.2 | 4.0 |
| Bees, wasps & ants | combined | 94 | 60.6 | 88.3 | 75.5 | 2.0 | 71.3 | 1.0 | 97.9 | 14.0 |
| Beetles | combined | 67 | 68.7 | 88.1 | 77.6 | 2.0 | 76.1 | 1.0 | 85.1 | 3.0 |
| Birds | combined | 266 | 50.8 | 76.7 | 63.9 | 2.0 | 57.5 | 1.0 | 86.5 | 10.0 |
| Butterflies | combined | 247 | 62.3 | 93.1 | 80.2 | 2.0 | 91.1 | 3.0 | 92.3 | 3.0 |
| Dragonflies | combined | 187 | 51.3 | 80.7 | 68.4 | 3.0 | 69.5 | 2.0 | 69.5 | 2.0 |
| Ferns | combined | 164 | 57.3 | 89.0 | 78.7 | 2.0 | 80.5 | 2.0 | 93.3 | 5.0 |
| Flies | combined | 68 | 60.3 | 88.2 | 75.0 | 2.0 | 60.3 | 1.0 | 79.4 | 2.0 |
| Flowering plants (dicots) | combined | 260 | 61.2 | 80.4 | 73.5 | 2.0 | 70.0 | 1.0 | 90.4 | 13.0 |
| Fungi | combined | 120 | 46.7 | 73.3 | 63.3 | 2.0 | 64.2 | 2.0 | 75.0 | 4.0 |
| Grasses & sedges | combined | 234 | 48.7 | 78.6 | 70.9 | 3.0 | 75.2 | 3.0 | 85.9 | 8.0 |
| Large mammals | classifier | 268 | 35.8 | 63.8 | 55.2 | 3.0 | 73.5 | 8.0 | 74.3 | 9.0 |
| Molluscs | combined | 77 | 48.1 | 85.7 | 48.1 | 1.0 | 66.2 | 1.0 | 85.7 | 3.0 |
| Moths | combined | 112 | 64.3 | 85.7 | 76.8 | 2.0 | 68.8 | 1.0 | 87.5 | 5.0 |
| Orchids | combined | 139 | 34.5 | 69.8 | 52.5 | 2.0 | 52.5 | 2.0 | 69.1 | 4.0 |
| Reptiles | combined | 229 | 58.5 | 85.6 | 75.1 | 2.0 | 98.3 | 16.0 | 99.1 | 32.0 |
| Rodents & shrews | combined | 252 | 50.8 | 87.7 | 79.0 | 2.0 | 77.4 | 2.0 | 92.9 | 4.0 |
| Spiders & kin | combined | 91 | 68.1 | 83.5 | 68.1 | 1.0 | 67.0 | 1.0 | 81.3 | 3.0 |
| True bugs | combined | 69 | 69.6 | 91.3 | 69.6 | 1.0 | 69.6 | 1.0 | 85.5 | 2.0 |
| All | best per group | 3190 | 52.9 | 81.2 | 68.9 | 2.0 | 71.9 | 2.0 | 85.0 | 5.0 |
| All | classifier | 3190 | 50.1 | 77.5 | 69.7 | 3.0 | 74.6 | 3.0 | 88.1 | 19.0 |
| All | combined | 3190 | 53.3 | 82.0 | 69.6 | 2.0 | 70.9 | 2.0 | 85.7 | 5.0 |
| All | zero-shot | 3190 | 51.2 | 79.9 | 69.6 | 2.0 | 74.3 | 3.0 | 84.6 | 6.0 |

The observer's name is not the truth. Observers are often wrong, and wrong names wait longer, so these figures mix model misses with observer errors. Still, the gap to T1 (71.9% against 92.6% at the 90% target) says shortlists must be checked on the queue before they are shown.

## Queue check (rules fixed 20 October 2026)

These rules decide which groups go on the experimental shortlist page. They were written here before the enlarged
T1 or the frozen sample was drawn, and are not changed after seeing results.

- **Enough data.** A group needs at least 100 T1 rows (research grade reached 30 days or more after creation;
  observers not in the corpus or its validation, that is test observers only). Fewer: "not enough data", no verdict.
- **Quick to confirm** (on the page, species shortlist): species 90% conformal set coverage at least 88% (calibrated
  on observer-split halves of T1, 20 repeats, as before) **and** median 90% set at most 2 names **and** top-1 at
  least 80%.
- Else **Genus first** (on the page, genus shortlist): genus 90% coverage at least 88% and genus median at most 2.
- Else **For an expert** (not on the page).
- The 95% set is reported but not used in the gate (it needs far more calibration rows).
- **Training-overlap check.** Coverage is also reported for T1 rows that reached research grade in 2025 or later. If
  that subgroup has at least 40 rows and its coverage is below 85%, the group drops one level (Quick to confirm to
  Genus first, Genus first to For an expert). The coverage checked is that of the level the group is on (species
  for Quick to confirm, genus for Genus first).
- Method per group: the one chosen on corpus validation (not re-chosen on T1).

## Queue check: results (run 20 October 2026, after the rules above)

**Part A: enlarged T1.** Every group below 100 qualifying rows got more test-observer observations, in the same
shuffled order as the first sample (so the first 300 are unchanged), until it reached 100 or ran out (cap 4,000
sampled; `grow_t1.py`, 32 more iNaturalist requests). T1 is now 2,545 rows from 12,366 sampled. The method per group
and every validation choice (classifier, weight decay, temperatures, weight) are identical to the first run (checked
against the saved `choice.csv`); nothing was chosen on T1. The tables in "Results on T1" above are the first T1
(1,635 rows, commit 5c78420); `results/*.csv` now hold the enlarged run.

| group | sampled | qualify | rg_within_30d | changed_or_gone | no_rg_date | median_waited_days | median_identifiers | observers | species |
|---|---|---|---|---|---|---|---|---|---|
| Algae & diatoms | 2 | 0 | 2 | 0 | 0 |  |  |  |  |
| Amphibians | 500 | 154 | 346 | 0 | 0 | 242.0 | 1.0 | 94.0 | 40.0 |
| Bats | 300 | 176 | 124 | 0 | 0 | 649.0 | 2.0 | 94.0 | 20.0 |
| Bees, wasps & ants | 740 | 119 | 621 | 0 | 0 | 168.0 | 2.0 | 65.0 | 73.0 |
| Beetles | 500 | 148 | 351 | 1 | 0 | 322.0 | 2.0 | 83.0 | 85.0 |
| Birds | 1182 | 107 | 1075 | 0 | 0 | 156.0 | 1.0 | 49.0 | 93.0 |
| Butterflies | 1088 | 115 | 969 | 4 | 0 | 246.0 | 2.0 | 64.0 | 71.0 |
| Dragonflies | 1740 | 108 | 1604 | 28 | 0 | 146.0 | 2.0 | 65.0 | 53.0 |
| Ferns | 246 | 85 | 161 | 0 | 0 | 193.0 | 1.0 | 44.0 | 35.0 |
| Fish | 45 | 5 | 40 | 0 | 0 | 139.0 | 2.0 | 5.0 | 5.0 |
| Flies | 300 | 148 | 152 | 0 | 0 | 296.0 | 1.0 | 77.0 | 56.0 |
| Flowering plants (dicots) | 500 | 156 | 342 | 2 | 0 | 181.0 | 1.0 | 95.0 | 125.0 |
| Fungi | 300 | 115 | 185 | 0 | 0 | 155.0 | 1.0 | 75.0 | 58.0 |
| Grasses & sedges | 300 | 129 | 171 | 0 | 0 | 270.0 | 1.0 | 66.0 | 50.0 |
| Large mammals | 840 | 104 | 736 | 0 | 0 | 139.0 | 1.0 | 74.0 | 28.0 |
| Lichens | 1 | 0 | 1 | 0 | 0 |  |  |  |  |
| Molluscs | 500 | 144 | 356 | 0 | 0 | 206.0 | 2.0 | 91.0 | 63.0 |
| Mosses & liverworts | 1 | 1 | 0 | 0 | 0 | 698.0 | 2.0 | 1.0 | 1.0 |
| Moths | 300 | 100 | 199 | 1 | 0 | 387.0 | 1.0 | 56.0 | 80.0 |
| Orchids | 660 | 109 | 551 | 0 | 0 | 179.0 | 1.0 | 42.0 | 61.0 |
| Reptiles | 888 | 126 | 762 | 0 | 0 | 228.0 | 2.0 | 82.0 | 63.0 |
| Rodents & shrews | 633 | 126 | 507 | 0 | 0 | 152.0 | 1.0 | 92.0 | 23.0 |
| Spiders & kin | 500 | 149 | 351 | 0 | 0 | 518.0 | 2.0 | 87.0 | 52.0 |
| True bugs | 300 | 121 | 179 | 0 | 0 | 268.0 | 1.0 | 68.0 | 69.0 |
| All | 12366 | 2545 | 9785 | 36 | 0 | 242.0 | 1.0 | 680.0 | 1204.0 |

Not enough data: ferns 85 (the test pool has only 246 observations), fish 5, mosses and liverworts 1, lichens 0,
algae 0. Overall on the enlarged T1 (2,539 rows tested; fish and mosses are below the 20-row minimum), combined:
right species first 84.4%, top 5 96.5%, 90% set coverage 92.0% with median 1 name, 95% set coverage 96.8% with
median 3; zero-shot alone 75.5% first.

**Gate verdicts** (method chosen on validation; coverage in %, sets calibrated on observer-split halves of T1, 20
repeats; "2025+" = rows that reached research grade in 2025 or later):

| group | method | T1 n | verdict | top-1 | species 90% cov | species 90% median | genus 90% cov | genus 90% median | 2025+ n | 2025+ species cov | 2025+ genus cov | species 95% cov | species 95% median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Amphibians | combined | 154 | Genus first | 77.9 | 91.8 | 2 | 92.7 | 1 | 79 | 96.8 | 94.5 | 97.3 | 3 |
| Birds | combined | 107 | Genus first | 75.7 | 92.8 | 2 | 93.1 | 1 | 61 | 89.5 | 89.2 | 97.9 | 4 |
| Butterflies | combined | 115 | Genus first | 76.5 | 93.4 | 2 | 94.3 | 1 | 58 | 97.2 | 96.7 | 98.0 | 3 |
| Grasses & sedges | combined | 129 | Genus first | 82.2 | 90.0 | 1 | 91.1 | 1 | 50 | 81.3 | 86.6 | 94.9 | 3 |
| Large mammals | classifier | 104 | Genus first | 74.0 | 93.3 | 3 | 92.3 | 1 | 63 | 90.6 | 89.1 | 98.1 | 6 |
| Reptiles | combined | 126 | Genus first | 73.0 | 91.5 | 2 | 90.9 | 1 | 41 | 92.3 | 90.2 | 97.3 | 6 |
| Rodents & shrews | combined | 126 | Genus first | 73.8 | 93.3 | 2 | 92.7 | 1 | 86 | 93.0 | 92.4 | 96.9 | 3 |
| Bats | classifier | 176 | Quick to confirm | 92.0 | 90.9 | 1 | 91.1 | 1 | 146 | 96.6 | 96.4 | 96.0 | 54 |
| Bees, wasps & ants | combined | 119 | Quick to confirm | 85.7 | 88.2 | 1 | 89.7 | 1 | 45 | 85.3 | 84.9 | 97.7 | 6 |
| Beetles | combined | 148 | Quick to confirm | 89.2 | 92.1 | 1 | 92.9 | 1 | 67 | 91.2 | 92.0 | 97.2 | 2 |
| Dragonflies | combined | 108 | Quick to confirm | 88.0 | 93.4 | 1 | 94.1 | 1 | 43 | 94.2 | 93.2 | 96.9 | 2 |
| Flies | combined | 148 | Quick to confirm | 87.8 | 92.9 | 1 | 91.5 | 1 | 84 | 90.6 | 90.5 | 98.0 | 2 |
| Flowering plants (dicots) | combined | 156 | Quick to confirm | 88.5 | 92.5 | 1 | 92.1 | 1 | 84 | 91.3 | 91.2 | 96.6 | 5 |
| Fungi | combined | 115 | Quick to confirm | 85.2 | 90.7 | 1 | 92.8 | 1 | 49 | 94.2 | 93.0 | 96.9 | 2 |
| Molluscs | combined | 144 | Quick to confirm | 89.6 | 91.8 | 1 | 93.0 | 1 | 76 | 92.5 | 90.2 | 96.9 | 2 |
| Moths | combined | 100 | Quick to confirm | 88.0 | 91.2 | 1 | 91.6 | 1 | 51 | 87.6 | 85.2 | 96.2 | 8 |
| Orchids | combined | 109 | Quick to confirm | 80.7 | 91.6 | 2 | 94.2 | 1 | 36 | 86.0 | 97.8 | 97.3 | 5 |
| Spiders & kin | combined | 149 | Quick to confirm | 90.6 | 91.3 | 1 | 92.1 | 1 | 71 | 92.7 | 92.1 | 96.6 | 1 |
| True bugs | combined | 121 | Quick to confirm | 90.1 | 94.0 | 1 | 92.7 | 1 | 60 | 93.9 | 92.4 | 97.6 | 2 |
| Algae & diatoms | zero-shot | 0 | not enough data |  |  |  |  |  |  |  |  |  |  |
| Ferns | combined | 85 | not enough data | 84.7 | 93.1 | 2 | 93.4 | 1 | 35 | 89.5 | 92.7 | 97.8 | 4 |
| Fish | classifier | 0 | not enough data |  |  |  |  |  |  |  |  |  |  |
| Lichens | combined | 0 | not enough data |  |  |  |  |  |  |  |  |  |  |
| Mosses & liverworts | zero-shot | 0 | not enough data |  |  |  |  |  |  |  |  |  |  |

- **Quick to confirm (12):** bats, bees wasps and ants, beetles, dragonflies, flies, flowering plants (dicots),
  fungi, molluscs, moths, orchids, spiders and kin, true bugs.
- **Genus first (7):** amphibians, birds, butterflies, large mammals, reptiles and rodents and shrews (top-1 under
  80%), and grasses and sedges (passed the species rules, but its 2025+ species coverage is 81.3% on 50 rows, under
  85%, so it drops one level).
- **For an expert:** none.
- **Not enough data (5):** algae, ferns, fish, lichens, mosses and liverworts.
- **2025+ check:** only grasses and sedges drops. Close to the line: bees, wasps and ants 85.3% (45 rows), moths
  87.6% (51), orchids 86.0% (36, under 40 so not judged).
- The gate's figures equal the observer-split conformal figures in `results/t1_metrics.csv` exactly (checked).

**Part B: frozen prospective test.** `queue_sample.py` drew the India needs-ID queue on 20 October 2026:
observations created in the last 120 days, named to a candidate species or a genus with candidates, open-licence
first photo, not the pilot's rows; random pages, up to 400 per group (bats 61, algae 45, lichens 141, orchids 201,
large mammals 220, mosses 250 and rodents 326 have fewer in the window). 8,044 observations: 4,986 named to species,
3,058 to genus. Each got its shortlist from the best method per group, calibrated with `pipeline/shortlist.py` on all
of that group's T1 rows (target 90%; calibration version `ce7c9b55be8e`), and a band from the
group's verdict: Quick to confirm (species set of 1 to 3 names), Genus first (a genus set), else For an expert.

- File: `data/corpus_v0/frozen_2026-10-20.parquet` (local only, never uploaded).
- **SHA-256: `c395de2a16730e31338b02953f371fe8435cd20d606cb99724d0661d2e523398`** (also in `results/frozen.csv`). This checksum is the pre-registration: `recheck.py` refuses
  to score a file that does not match it, and `freeze.py` never writes it again.
- Bands: Quick to confirm 3,950, Genus first 2,455, For an expert 1,639 (of which 1,236 are in the five groups with
  not enough data). Per group:

| group | For an expert | Genus first | Quick to confirm | rows | group_verdict |
|---|---|---|---|---|---|
| Algae & diatoms | 45 | 0 | 0 | 45 | not enough data |
| Amphibians | 39 | 361 | 0 | 400 | Genus first |
| Bats | 11 | 3 | 47 | 61 | Quick to confirm |
| Bees, wasps & ants | 9 | 8 | 383 | 400 | Quick to confirm |
| Beetles | 16 | 5 | 379 | 400 | Quick to confirm |
| Birds | 32 | 368 | 0 | 400 | Genus first |
| Butterflies | 49 | 351 | 0 | 400 | Genus first |
| Dragonflies | 19 | 0 | 381 | 400 | Quick to confirm |
| Ferns | 400 | 0 | 0 | 400 | not enough data |
| Fish | 400 | 0 | 0 | 400 | not enough data |
| Flies | 40 | 10 | 350 | 400 | Quick to confirm |
| Flowering plants (dicots) | 7 | 5 | 388 | 400 | Quick to confirm |
| Fungi | 22 | 10 | 368 | 400 | Quick to confirm |
| Grasses & sedges | 16 | 384 | 0 | 400 | Genus first |
| Large mammals | 11 | 209 | 0 | 220 | Genus first |
| Lichens | 141 | 0 | 0 | 141 | not enough data |
| Molluscs | 5 | 1 | 394 | 400 | Quick to confirm |
| Mosses & liverworts | 250 | 0 | 0 | 250 | not enough data |
| Moths | 24 | 6 | 370 | 400 | Quick to confirm |
| Orchids | 2 | 1 | 198 | 201 | Quick to confirm |
| Reptiles | 2 | 398 | 0 | 400 | Genus first |
| Rodents & shrews | 28 | 298 | 0 | 326 | Genus first |
| Spiders & kin | 31 | 13 | 356 | 400 | Quick to confirm |
| True bugs | 40 | 24 | 336 | 400 | Quick to confirm |
| All | 1639 | 2455 | 3950 | 8044 |  |

**Re-check** (`recheck.py`): run at 30, 60 and 90 days (on or after 19 November 2026, 19 December 2026 and 18
January 2027):

```sh
data/model_check/.venv/bin/python -u experiments/corpus_v0/recheck.py   # newest frozen_*.parquet
```

It fetches the same 8,044 ids (41 requests), and reports per group, band and overall: the share that reached
research grade or changed taxon, and of those that reached research grade, the share whose final species was in the
shown shortlist, in the frozen 90% set, first, in the top 5, and whose genus was in the shown genera. Its answers are
cached per day, so a second run on the same day sends no requests and writes the same file
(`results/recheck_<drawn>_<date>.csv`, one row per run in `results/recheck_log.csv`).
Run once on the day of drawing, as a test: 9 of 8,044 had already reached research grade (0.1%); too few to read.

Run times (queue check): growing T1 3 min (32 requests); queue sample 6 min (85 requests); re-check 3 min (41 requests and 1 retry); photos for 8,948 new
rows 15 min; their features 11 min; evaluation 6.4 min; gate and freeze under 1 min. iNaturalist
requests on 20 October 2026 in all: 249. Disk: `data/corpus_v0/` is now 17 GB (photos 15 GB).

## Live shortlists for the experimental page (20 October 2026)

Contract: `docs/shortlist_data.md`. `live.py draw` took the current India needs-ID queue for the 19 groups that
passed the gate, with the same window and filters as the frozen sample (created in the last 120 days, named to a
candidate species or a genus with candidates, open-licence first photo), up to 1,000 per group. It excluded every
frozen id and the pilot's rows: 14,786 observations, 396 iNaturalist requests that day in all at that point.

- **Bats: none.** All 61 bats in the window are in the frozen test, which must never be shown. Large mammals (61),
  orchids (47) and rodents and shrews (92) are small for the same reason.
- `live.py build`: best method per group and the frozen calibration (`ce7c9b55be8e`). The model was refitted by
  `evaluate.py`; its T1 and frozen-sample probabilities are bit-identical to those calibrated (largest difference 0).
- Band from the group's verdict: quick (1 to 3 species) or genus (up to 5 genera). The 944 rows with no usable list
  ("For an expert") are not published: **13,842 rows** (8,908 quick, 4,934 genus).
- LGD state from the coordinates with `pipeline.places` and the pipeline's district file. It is null for the 747
  obscured rows. No coordinates are published.
- **Order** within a group: `pipeline.shortlist.priority(value({}), band)`. No value flags (first in state,
  threatened, endemic, listed only) are computed for queue rows, so this is quick before genus. Ties go oldest
  waiting first (created date), then id.
- Files: `data/shortlist/2026-10-20/latest.json` and `g/<key>.json`, compact JSON, 6.32 MB in all. Each group file
  is under 300 KB; groups over that are split into pages (`g/<key>.2.json`; the contract was updated). A second
  build is byte-identical.
- `shown.parquet` (local only) holds every published id with its full shortlist. Its SHA-256 is in `shown.sha256`.
  `recheck.py --shown 2026-10-20` scores it (70 requests); a test run on the day: 15 of 13,842 already research
  grade.
- `publish_live.py <run>` would copy the JSON files to R2 `layers/shortlist/`, latest.json last, never
  shown.parquet. **Not run**: the owner decides.

## Limits

- **Research grade is a proxy for "an expert confirmed it".** Research grade needs 2 agreeing identifiers (median identifiers other than the observer in T1: 1). Some of these identifiers are not experts, and research-grade names can be wrong.
- **Waited-set bias.** T1 keeps observations that waited 30 days or more (1,641 of 5,995 sampled). They are harder than quick ones, but they are still the ones that were solved in the end. The queue that is never solved is harder still (T3).
- **Training overlap** (above): zero-shot is inflated on photos from 2024 or earlier. The classifier is trained only on train observers, so it has no such leak on T1.
- **Same observer avoided**, not same site or same individual animal. Train and test observers are disjoint (hash of `recordedBy`). Two names for one person, or two people at one event, can still link train and test. The queue observers (T2/T3) were not matched to the split, so a queue observer's other photos can be in the corpus.
- **CC licences only.** GBIF's iNaturalist dataset has only CC0, CC BY and CC BY-NC (with SA/ND variants) records. All-rights-reserved photos are not in it, so species photographed mostly by such observers are under-represented.
- **Candidates are the model check's list** (Indian GBIF species that BioCLIP 2.5-filled can name). 5.5% of research-grade records in the 24 groups are species outside that list and were dropped. Those are misses that T1 does not count (true bugs 35.8%, beetles 19.2%, fungi 14.5% of records). The model check counted such photos as misses.
- **Small T1 groups.** 20 to 176 rows per group, often from few observers (dragonflies: 16). Per-group figures have wide margins; conformal sets at 95% need more calibration rows.
- **Validation is species-balanced and T1 is not.** The corpus caps species at 15, so validation top-1 is lower than T1 (for example 78.0% against 89.4% for dicots). T1 is dominated by common species.
- **Frozen sample and corpus observers.** 61.7% of the 8,044 frozen rows are by observers whose name or login is also a corpus observer (2,672 observers in the sample). The frozen test is prospective (truth from the future), not observer-disjoint. The verdicts come from T1, which is observer-disjoint.
- **Frozen truth will be biased** in the same way as T1: the observations that reach research grade within 90 days are the easier ones. The re-check reports the share that reached it, so this stays visible.
- **Not measured:** time saved for an identifier, other models (only BioCLIP 2.5), more than one photo per observation, a test of the corpus on the queue's genus- or family-level rows, and the 95% target with enough calibration data.

## Run times and disk

| step | time |
|---|---|
| GBIF download (prepare and fetch, 941 MB) | 46 min (12:12 to 12:58) |
| Name matching through the GBIF API (21,007 names) | about 1.5 h (many connection errors and retries) |
| iNaturalist API: T1 (30 requests) and queue (60 requests) | 2 min each |
| Photos (118,072 medium, 8 at a time) | 4 h 57 min, plus 2 min to retry 2,251 that failed in a network drop |
| BioCLIP 2.5 features (121,630 photos) | 3.75 h of image work in all; 82 to 85 s per 1,000 on mains power, much slower on battery |
| Evaluation (`evaluate.py`) | 6.7 min |

Disk: `data/corpus_v0/` is 16 GB (photos 14 GB, features 476 MB, GBIF zip 941 MB), within the 40 GB budget.

## Files and rerun

Code in this folder; data in `data/corpus_v0/` (gitignored, this machine only). Every extractor caches as it goes and continues where it stopped. A second run sends no new requests and writes the same files.

```sh
PY=data/model_check/.venv/bin/python     # the model check's overlay venv (plus boto3, for pipeline.health)
cd experiments/corpus_v0
$PY -u source.py          # GBIF download (key kept in download.json), records.parquet, photos.parquet
$PY -u candidates.py      # candidate lists (model check rule)
$PY -u build_sets.py      # names, groups, observer split, corpus.parquet, t1_sample.parquet [cap, default 15]
$PY -u waited.py          # T1: iNaturalist histories (cached in inat_t1.jsonl), t1.parquet
$PY -u queue_fetch.py     # pilot queue now (cached in inat_queue.jsonl), queue.parquet
$PY -u photos.py          # medium photos from the open-data bucket [--retry]
$PY -u embed_v0.py        # BioCLIP 2.5 features, shards in emb/
$PY -u evaluate.py        # T1, T2, T3 predictions and metrics
$PY report.py > results/report.md
# queue check (README "Queue check")
$PY -u grow_t1.py         # enlarge T1 to 100 qualifying rows per group (same cache as T1)
$PY -u queue_sample.py    # fresh needs-ID queue sample (state in queue_sample_state.json)
$PY -u photos.py && $PY -u embed_v0.py && $PY -u evaluate.py   # also scores/<group>.npz
$PY -u gate.py            # results/gate.csv
$PY -u freeze.py          # frozen_<date>.parquet, calibration_<date>.json, results/frozen.csv (never rewritten)
$PY -u recheck.py         # at 30, 60, 90 days
$PY -m pytest -q -p no:cacheprovider     # logic tests (41)
```

- Logic, with tests in `test_logic.py`: `logic.py` (photo URLs, observer split, capped sampling, research-grade date, name matching, k-NN scores, temperature, combination, conformal threshold, fixed k).
- Results: `results/` (`corpus_counts.csv`, `names.csv`, `t1_waited.csv`, `t1_metrics.csv`, `t1_unseen.csv`, `choice.csv`, `t1_best.csv`, `t2.csv`, `t3.csv`, `verdicts.csv`, `report.md`).
- Request limits kept: iNaturalist at least 1.1 s apart, a daily count capped at 8,500 (`inat_requests.json`), 200 ids per request, User-Agent from `pipeline.health.ua()`. GBIF credentials only through `pipeline.gbif.session()`.
