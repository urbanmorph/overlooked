# Model check: which image species-ID models work for Indian biodiversity

Date: 20 October 2026. Scope: test every open image model we could run on the same Indian test photos, and record the access status of the models we could not run. Everything ran on an Apple M2 Pro (MPS, fp32).

**Headline (owner decision: the model only proposes a shortlist; a taxonomist approves).** The best open model is **BioCLIP 2.5** (MIT). To use it we had to fill gaps in its published label file (see "Faults found"). On 5,604 Research Grade photos in 24 groups:

- **Species shortlists.** The right species is in the top 5 for 86.5% of photos, the top 10 for 88.9% and the top 20 for 90.2%. A fixed list of 17 names reaches 90% overall. **95% is not reached at species level for any model.** The reason: for 8.4% of the photos, the right species is not in the candidate list at all (it is not in the GBIF India list, or not in the model's vocabulary).
- **Genus shortlists.** 3 genera reach 90% and 31 genera reach 95%.
- **Weak groups.** For true bugs, beetles, fungi, flies and algae, no zero-shot model reaches 90% at species level within its candidate list. For true bugs, even the top 20 holds the right species only 59.9% of the time.
- **Training on Indian photos (probe).** A simple classifier trained on Indian photos, on top of frozen BioCLIP 2.5 features, closes most of the gap for the common species: true bugs 94.9% top-1 against 55.9% for zero-shot over the same species. The right answer is in a list of 2 for 95% of photos. This covers only species with at least 3 answer-key photos (472 species), so it is an upper bound (see Limits).

## Method

The test reuses the fnf identification pilot (`/Users/sathya/Projects/biodiversity/fnf`, read only; see its `out/id_pilot_findings.md`):

- **Answer key.** The pilot's iNaturalist India Research Grade observations, named to species or below: 5,604 photos (one per observation), 24 groups, open licences, "medium" size (up to 500 px).
- **Candidates.** For each photo, the candidates are the species of its group that have an Indian GBIF record (44,637 species) **and** that the model can name. For BioCLIP this means its published text-embedding label set; for EVA02 it means its 10,000 iNat21 classes. This is the pilot's rule, so the results compare with it. Our BioCLIP 2 run reproduces the pilot exactly: 62.6% top-1 species, 78.4% genus, 80.6% top-5.
- **Exact vs synonym-aware match.** Exact match compares the predicted name with the iNaturalist name, cut to a binomial. The synonym-aware match ("syn") also accepts the name's accepted species in the GBIF backbone (GBIF `/v1/species/match`, 2,251 names, cached). It maps 113 names to a different accepted name (e.g. *Clanga hastata* to *Aquila hastata*). 104 names have no species-level match. Candidate names come from GBIF occurrences, so they are already backbone names.
- **Top-1 metrics.** Top-1 species, top-1 genus (species probabilities summed by genus) and top-5 species.
- **Shortlist metrics (headline).**
  - Recall at k = 1, 3, 5, 10, 20.
  - **Fixed k:** the smallest list length that holds the right answer for 90% or 95% of photos, chosen on all photos.
  - **Calibrated set (split conformal):**
    - The score is 1 − p(true).
    - The threshold is calibrated per group on a random half of the observations and tested on the other half. This is repeated 20 times.
    - We report coverage and the median and 90th-percentile set size on the test halves.
  - All of these are given at species level and at genus level.
  - "not reached" means the full candidate list holds the answer for less than the target share of photos.
  - Overall rows pool the groups. Their conformal coverage can fall below target because groups that cannot reach it are capped at their full list.
- **Probe (second protocol).**
  - Only species with at least 3 answer-key photos in a group: 3,460 photos, 472 species.
  - 5-fold cross-validation (StratifiedGroupKFold on observation id).
  - Two classifiers: 1-nearest-neighbour (cosine), and logistic regression on standardised frozen features (C = 1, not tuned).
  - The candidates are the species of the training folds (median 20 per group), so we also report **closed-set zero-shot** over exactly those species. This separates the gain from training from the gain from a smaller list.
- **Speed.** Seconds of image work (decode, preprocess, encode) per 1,000 photos, batch 32 (16 for the large models), 8 loader threads. The pilot's 57.6 s for BioCLIP 2 used a single-threaded loader. BioCLIP 2 rerun here takes 39.1 s, with features identical to the pilot's (cosine 1.0).

## Models: access, licence, size

Models we ran (all from the official HF org; total new download 11.21 GB):

| Model | Access | Licence (commercial use / redistribution) | Download | Notes |
|---|---|---|---|---|
| BioCLIP 2 `imageomics/bioclip-2` | open | MIT (yes / yes) | 1.71 GB weights (already cached by the pilot) + label file 2.66 GB (pilot copy) | ViT-L/14; TreeOfLife-200M (CC0); 867,455 label taxa |
| BioCLIP 2.5 `imageomics/bioclip-2.5-vith14` | open | MIT (yes / yes) | 3.94 GB weights + 3.26 GB label file (`TreeOfLife-200M/embeddings/txt_emb_bioclip-2.5-vith14.npy`) | ViT-H/14; created 2026-02-10; 794,878 label taxa |
| BioCLIP `imageomics/bioclip` | open | MIT (yes / yes) | 0.60 GB weights + 0.79 GB label file (`TreeOfLife-10M/embeddings/txt_emb_species.npy`) | ViT-B/16; TreeOfLife-10M |
| DINOv2-L `facebook/dinov2-large` | open | Apache-2.0 (yes / yes) | 1.22 GB | general backbone, probe only |
| EVA02-L iNat21 `timm/eva02_large_patch14_clip_336.merged2b_ft_inat21` | open | **CC BY-NC 4.0 (no commercial use)** | 1.26 GB | 10,000 iNat21 species; best of the timm iNat21 fine-tunes (92.05% top-1 on iNat21 val) |

Models we could not run or did not run, with access status from official sources (no sign-up, no keys):

| Model | Access | Licence / terms | Notes |
|---|---|---|---|
| DINOv3 `facebook/dinov3-*` | **gated (manual approval)** | custom "DINOv3 License" | Not run (would need accepting terms). |
| iNaturalist computer vision | **closed** | n/a | `api.inaturalist.org/v1/computervision/score_image` is not in the public v1 API spec; access is for approved partners via OAuth. The open `inaturalist/model-files` release (MIT) is a "small" model of about 500 taxa only. Terms and limits of the full API: not verified. |
| Pl@ntNet API | **key required** | Free: 500 identifications/day. Pro: €1,000/year (200,000 requests), then €0.005 to €0.002 per identification. Non-profit/education plan on request. | Has a flora `k-indian-subcontinent` (a search result says 7,485 species; the API project id was not verified without a key). No open global weights (only PlantCLEF 2024 Europe, CC BY 4.0). |
| Pathanga Suchaka (UAS-GKVK Bengaluru, IBIN/DBT funded) | **closed, offline** | "All rights reserved" | About 800 butterfly and 500 moth species. The domain no longer resolves; the last Wayback snapshot is 2022-11-15. No API or model download found. |
| Google SpeciesNet (`google/cameratrapai`) | open | Apache-2.0 (yes / yes) | Camera-trap mammals and birds. 2,498 labels (2,066 to species). Present: tiger, Asian elephant, chital, nilgai, sambar, sloth bear, dhole, Indian peafowl, leopard, gaur and others. Absent: blackbuck, Indian rhino. Not run: camera-trap model, outside this photo test. |
| BirdNET (audio) | open | code MIT; **models CC BY-NC-SA 4.0** (no commercial use without permission) | V2.4, 6,522 classes. |
| Perch 2.0 (audio, Google DeepMind) | open | Apache-2.0 | About 15,000 species (birds, frogs, insects, mammals). Kaggle `google/bird-vocalization-classifier`. Whether the download needs a Kaggle login: not verified. |

## Results: zero-shot (answer key, 5,604 photos)

"bioclip-2.5" uses the published label file as is; "bioclip-2.5-filled" adds the Indian candidates that file lacks (see "Faults found"). Same image features.

| model | s/1000 photos | Indian spp. in vocab | answer in candidates | top-1 sp. (exact / syn) | top-1 genus (syn) | top-5 sp. (syn) | top-1 if answer is a candidate | sp. r@10 | sp. r@20 | sp. k for 90% | genus k for 90% | genus k for 95% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bioclip-2 | 39.1 | 75.4% | 91.6% | 62.6 / 64.2 | 79.4 | 82.7 | 70.2 | 86.2 | 88.4 | 39 | 4 | 46 |
| bioclip-2.5 | 94.4 | 67.6% | 83.1% | 63.2 / 65.0 | 76.6 | 79.0 | 78.2 | 80.8 | 81.9 | not reached | not reached | not reached |
| bioclip-2.5-filled | 94.4 | 75.4% | 91.6% | 69.3 / 71.1 | 83.9 | 86.5 | 77.7 | 88.9 | 90.2 | 17 | 3 | 31 |
| bioclip | 9.9 | 48.7% | 83.0% | 42.4 / 43.3 | 61.2 | 64.6 | 51.8 | 70.2 | 74.7 | not reached | 30 | not reached |
| eva02-inat21 | 107.2 | 4.7% | 32.2% | 29.8 / 30.1 | 41.4 | 31.9 | 93.5 | 32.1 | 32.1 | not reached | not reached | not reached |

Species-level 95% is "not reached" for every model overall. Reasons:

- With the BioCLIP 2 vocabulary, the right species is missing from the candidates for 473 photos (8.4%).
- 256 of those are species in the GBIF India list that the model cannot name.
- 217 are species with no Indian GBIF record in that group, as of the pilot's GBIF download.
- The largest shares are in true bugs (97), beetles (49), flies (49) and fungi (38).

Calibrated sets, overall (each group calibrated on half its observations, tested on the other half):

| Model | Level | Coverage, target 90% | Median set | 90th pct. set | Coverage, target 95% | Median set | 90th pct. set |
|---|---|---|---|---|---|---|---|
| bioclip-2 | species | 87.8% | 14 | 1,266 | not reached | | |
| bioclip-2 | genus | 89.5% | 2 | 261 | 93.4% | 7 | 608 |
| bioclip-2.5-filled | species | 87.8% | 5 | 1,269 | not reached | | |
| bioclip-2.5-filled | genus | 89.6% | 1 | 261 | 93.4% | 2 | 609 |

Most photos get a short list, but about one photo in ten gets a list of hundreds of names. These are the uncertain photos; a taxonomist would get no help from the model on them.

### Per group, zero-shot: top-1 species (syn) / species in top 10 / list length for 90% of photos

| group | bioclip-2 | bioclip-2.5 | bioclip-2.5-filled | bioclip | eva02-inat21 |
|---|---|---|---|---|---|
| True bugs | 44.1 / 57.1 / not reached | 48.2 / 58.3 / not reached | 48.2 / 58.3 / not reached | 21.5 / 37.2 / not reached | 6.9 / 6.9 / not reached |
| Beetles | 54.0 / 75.6 / not reached | 59.6 / 77.2 / not reached | 59.6 / 77.2 / not reached | 39.6 / 65.6 / not reached | 18.8 / 22.4 / not reached |
| Fungi | 51.0 / 76.3 / not reached | 59.8 / 80.7 / not reached | 59.8 / 81.1 / not reached | 42.6 / 65.5 / not reached | 36.9 / 38.2 / not reached |
| Lichens (n=33) | 18.2 / 81.8 / 17 | 30.3 / 69.7 / 40 | 30.3 / 69.7 / 40 | 18.2 / 42.4 / not reached | 15.2 / 27.3 / not reached |
| Spiders & kin | 76.3 / 91.4 / 5 | 80.8 / 94.7 / 3 | 80.8 / 94.7 / 3 | 44.5 / 76.3 / not reached | 19.6 / 20.0 / not reached |
| Flies | 61.3 / 79.8 / not reached | 66.9 / 79.4 / not reached | 66.9 / 79.4 / not reached | 56.0 / 81.5 / not reached | 42.3 / 42.7 / not reached |
| Moths | 71.2 / 88.8 / 16 | 73.2 / 90.0 / 8 | 73.2 / 90.0 / 8 | 51.2 / 74.4 / not reached | 22.0 / 22.4 / not reached |
| Fish | 36.0 / 74.9 / 96 | 1.6 / 4.9 / not reached | 62.3 / 87.4 / 24 | 26.3 / 54.3 / 650 | 7.3 / 8.1 / not reached |
| Reptiles | 56.4 / 92.0 / 7 | 0.0 / 0.0 / not reached | 76.8 / 96.4 / 4 | 35.2 / 64.4 / not reached | 22.4 / 23.2 / not reached |
| Dragonflies | 85.2 / 98.4 / 2 | 91.2 / 98.4 / 1 | 91.2 / 98.4 / 1 | 71.6 / 95.2 / 4 | 71.6 / 74.0 / not reached |
| Bees, wasps & ants | 81.1 / 95.1 / 3 | 88.1 / 95.9 / 2 | 88.1 / 95.9 / 2 | 46.3 / 79.5 / 41 | 41.0 / 42.2 / not reached |
| Butterflies | 81.2 / 91.2 / 4 | 85.2 / 91.6 / 3 | 85.2 / 91.6 / 3 | 60.0 / 81.6 / 89 | 64.8 / 70.0 / not reached |
| Birds | 75.9 / 92.8 / 6 | 87.1 / 94.8 / 2 | 87.1 / 94.8 / 2 | 64.7 / 85.9 / 26 | 61.0 / 67.1 / not reached |
| Rodents & shrews | 78.0 / 99.6 / 2 | 82.4 / 99.6 / 2 | 82.4 / 99.6 / 2 | 54.0 / 92.8 / 7 | 42.0 / 49.6 / not reached |

At genus level, BioCLIP 2.5-filled reaches 90% with 1 to 3 genera for most groups, but not at all for true bugs (r@20 70.0%), beetles (87.2%) and flies (85.1%). It needs 15 genera for lichens and 21 for ferns. All groups, both levels, both BioCLIP 2 models: `results/shortlist_zeroshot.csv`.

## Results: probe (training on the answer key itself)

The probe uses species with at least 3 answer-key photos: 3,460 photos, 472 species, median 20 candidates per group. Validation is 5-fold, grouped by observation.

| features | 1-NN top-1 | LR top-1 | LR genus | LR top-5 | LR list length for 95% | LR calibrated 95%: coverage / median / 90th pct. set | zero-shot closed-set top-1 / top-5 | zero-shot open top-1 (same photos) |
|---|---|---|---|---|---|---|---|---|
| bioclip-2 | 90.2 | 90.9 | 95.0 | 99.2 | 2 | 96.7% / 1 / 3 | 86.2 / 92.6 | 70.0 |
| bioclip-2.5 | 92.1 | 92.9 | 96.4 | 99.4 | 2 | 96.8% / 1 / 2 | 87.7 / 92.7 | 75.5 |
| bioclip | 74.4 | 79.1 | 84.7 | 96.2 | 4 | 96.9% / 2 / 10 | 67.4 / 84.5 | 48.6 |
| dinov2-large | 68.3 | 73.5 | 80.1 | 93.3 | 7 | 96.9% / 3 / 17 | n/a | n/a |
| eva02-inat21 | 88.8 | 88.8 | 92.8 | 98.8 | 2 | 96.9% / 1 / 4 | 40.6 / 41.8 | 39.1 |

Per group, LR top-1 (closed-set zero-shot top-1 over the same species in brackets):

| group | bioclip-2 | bioclip-2.5 | bioclip | dinov2-large | eva02-inat21 |
|---|---|---|---|---|---|
| True bugs (n=118) | 93.2 (55.1) | 94.9 (55.9) | 81.4 (34.7) | 72.0 | 92.4 (11.9) |
| Beetles (n=123) | 96.7 (77.2) | 99.2 (80.5) | 84.6 (61.8) | 64.2 | 93.5 (36.6) |
| Fungi (n=144) | 95.1 (74.3) | 97.2 (77.1) | 91.7 (75.7) | 89.6 | 92.4 (50.0) |
| Lichens (n=11) | 90.9 (100.0) | 90.9 (100.0) | 81.8 (72.7) | 72.7 | 90.9 (63.6) |
| Spiders & kin (n=176) | 96.0 (96.6) | 98.9 (98.3) | 81.8 (72.2) | 73.9 | 92.6 (26.7) |
| Flies (n=166) | 97.6 (77.1) | 95.8 (76.5) | 88.0 (89.8) | 71.7 | 93.4 (59.6) |
| Moths (n=64) | 96.9 (100.0) | 96.9 (100.0) | 93.8 (89.1) | 70.3 | 96.9 (53.1) |
| Fish (n=79) | 89.9 (89.9) | 93.7 (91.1) | 68.4 (81.0) | 73.4 | 82.3 (8.9) |
| Reptiles (n=157) | 79.6 (89.8) | 85.4 (91.7) | 57.3 (58.6) | 75.8 | 80.3 (32.5) |
| Dragonflies (n=209) | 91.9 (94.7) | 95.2 (96.7) | 79.9 (86.6) | 47.4 | 92.3 (82.3) |
| Bees, wasps & ants (n=173) | 89.6 (96.5) | 94.2 (96.5) | 72.3 (75.1) | 50.9 | 89.6 (54.9) |
| Butterflies (n=154) | 87.7 (93.5) | 92.9 (96.8) | 73.4 (81.2) | 28.6 | 93.5 (84.4) |
| Birds (n=87) | 96.6 (98.9) | 98.9 (98.9) | 90.8 (90.8) | 90.8 | 97.7 (85.1) |
| Rodents & shrews (n=229) | 83.4 (86.5) | 83.0 (89.1) | 65.1 (65.5) | 75.5 | 83.4 (45.9) |

How to read this:

- **Weak groups gain the most from training.** On the same short candidate list, training lifts top-1 by 19 to 39 points for true bugs, beetles, fungi and flies.
- **Strong groups barely change.** Training adds little for birds, butterflies, dragonflies, bees, spiders and reptiles; zero-shot over a short list is as good or better there.
- **Shortlists come from both things together.** Most of the shortlist gain comes from the much shorter candidate list (20 species, not hundreds). Training gives the rest.

## Verdicts

| Model | Verdict | Why |
|---|---|---|
| **BioCLIP 2.5** | **Usable now for shortlists in strong groups; usable with a corpus for weak groups** | Best on every measure once its label gaps are filled. Species 90% within 1 to 8 names for dragonflies, bees, butterflies, birds, spiders, reptiles, rodents, orchids, dicots, moths and grasses. MIT. Slowest of the BioCLIP models (94.4 s per 1,000 photos), which is about 77 hours for 2.95 million photos on one laptop. Its published label file has a fault (below), so do not use the file as is. |
| **BioCLIP 2** | Usable now (second choice) | 6.7 points below 2.5-filled at top-1 overall. Same vocabulary coverage. 2.4 times faster (39.1 s per 1,000). MIT. Its label file has zero vectors that must be re-encoded (pilot finding). |
| BioCLIP (original) | Not usable | Knows 48.7% of Indian species. 43.3% top-1, 74.7% in top 20. It is fast (9.9 s per 1,000) but clearly worse at everything. |
| EVA02-L iNat21 (timm) | Not usable for India as is | It is right 93.5% of the time when the species is in its list, but its 10,000 iNat21 classes cover only 4.7% of Indian species (32.2% of answer-key photos). CC BY-NC 4.0 blocks commercial use. Its features probe well (88.8% LR), but no better than BioCLIP 2.5, which is MIT. |
| DINOv2-L | Not usable (BioCLIP is better as a backbone) | A general backbone with no names, so probe only: 73.5% LR top-1, against 92.9% for BioCLIP 2.5 features. Apache-2.0. |
| DINOv3 | Not tested (gated) | Needs accepting Meta's licence and manual approval. |
| iNaturalist CV | Not usable (closed) | No public API; only a 500-taxon small model is open. |
| Pl@ntNet API | Usable with a key (plants only) | 500 identifications/day free, paid beyond that. Has an Indian-subcontinent flora. Not measured here. |
| Pathanga Suchaka | Not usable | Offline since about 2022, no API, all rights reserved. |
| SpeciesNet | Out of scope (camera traps) | Apache-2.0, covers most large Indian mammals; not a general photo ID model. |
| BirdNET / Perch 2.0 | Audio, not tested | BirdNET models are non-commercial (CC BY-NC-SA 4.0); Perch 2.0 is Apache-2.0. |

## Faults found

1. **The BioCLIP 2.5 label file lacks reptiles and ray-finned fish.** `TreeOfLife-200M/embeddings/txt_emb_bioclip-2.5-vith14.json` has 794,878 taxa, against 867,455 for BioCLIP 2. Its chordates include only 7 Squamata, no Testudines or Crocodylia, and 24 Actinopterygii. For example, *Naja naja*, *Calotes versicolor*, *Labeo rohita* and *Danio rerio* are all absent. As published, reptiles score 0.0% and fish 1.6% top-1.
   - **Our fix ("filled").** We took the 3,495 Indian candidates that are missing from the file and encoded them with the BioCLIP 2.5 text encoder, using BioCLIP 2's taxonomy strings and the pilot's template.
   - **Check of the fix.** On 300 random taxa that are in the file, re-encoded and published vectors agree at cosine 0.854 to 0.983 (median 0.950).
   - **Result.** Filled, reptiles score 76.8% and fish 62.3%. The fault may be worth reporting to Imageomics (not done; it would be a public post).
2. **BioCLIP 2's zero vectors.** This is the pilot's finding: 670 of the Indian candidates had zero vectors and were re-encoded. BioCLIP 2.5 and BioCLIP have no zero vectors among the Indian candidates.

## Limits

- **Research Grade is a best case.** The pilot showed that the waiting queue is harder: 78.5% agreement against 95% on the answer key. None of these numbers were measured on the queue.
- **Fixed-k lengths are chosen on the same photos they are scored on.** The conformal sets are calibrated and tested on separate halves, so they are the fairer guide.
- **The probe is optimistic:**
  - It covers only species with at least 3 photos, which are the common ones.
  - It has a median of 20 candidates per group, and new or rare species are not in its classes.
  - It is trained and tested within one 250-photo sample per group.
  - Folds are by observation, but the sample has no observer field, so photos from the same observer or site can fall in both training and test folds. Near-duplicates are rare: 1.2% of test photos have a training photo above cosine 0.95 (DINOv2 features).
  - Treat it as "what an Indian corpus could add", not as a deployable accuracy.
- **Synonym matching covers only the answer key's names.** We did not map model vocabularies through GBIF, so the vocabulary coverage figures are exact-name lower bounds.
- **Small samples:** lichens have 33 answer-key photos (11 in the probe), and mosses have 129.
- **Not measured:**
  - Pl@ntNet, iNaturalist CV, DINOv3, SpeciesNet and the audio models.
  - The other timm iNat21 checkpoints (same 10,000 classes, so the same vocabulary gap).
  - GPU types other than the M2 Pro.

## Files and rerun

The scripts are in this folder. Large outputs and caches are in `data/model_check/` (gitignored). Every step is cached and resumes. A second run does no new downloads, no encoding and no GBIF calls; it rescores in a few minutes.

```sh
# one-time env: overlays the fnf ML venv (read only) and adds transformers, scikit-learn, pytest, ruff
python3.11 -m venv data/model_check/.venv
echo /Users/sathya/Projects/biodiversity/fnf/.venv-ml/lib/python3.11/site-packages \
  > data/model_check/.venv/lib/python3.11/site-packages/zz_fnf_ml.pth
data/model_check/.venv/bin/pip install "transformers<5" scikit-learn pytest ruff
cd experiments/model_check
PY=../../data/model_check/.venv/bin/python
$PY -u download.py                       # weights + label files from official HF repos (11.21 GB)
$PY -u embed.py bioclip-2 bioclip-2-rerun bioclip bioclip-2.5 dinov2-large eva02-inat21
$PY -u synonyms.py                       # GBIF matches, cached
$PY -u zeroshot.py                       # protocol 1 + shortlists
$PY -u probe.py                          # protocol 2 + shortlists
$PY tables.py                            # markdown tables used above
$PY -m pytest -q -p no:cacheprovider     # scoring tests
```

- `results/zeroshot_groups.csv`: top-1, genus, top-5, exact and syn, per model and group.
- `results/shortlist_zeroshot.csv`, `results/shortlist_probe.csv`: recall at k, fixed k, conformal sets, species and genus.
- `results/probe_groups.csv`, `results/vocab.csv`, `results/speed.csv`.
- `data/model_check/zeroshot_<model>.csv`, `probe_<model>.csv`: per-photo guesses (top-5 names, probabilities).
- `data/model_check/feats_<model>.npz`: image features (and EVA02 logits); `txt_reencoded_*.npz`: re-encoded label vectors; `gbif_match.json`: GBIF matches.
