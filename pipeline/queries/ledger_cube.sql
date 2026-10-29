-- Query A: ledger cube. One row per species x point, coordinates rounded to 3 decimals (about 110 m).
-- Rounding moved 0.2% of records to another district in the grid test (scripts/grid_test.py),
-- against 1.6% for a 1.7 km grid.
-- n_trait: records with a trait (the Raunkiæran gap): a life stage, a sex, or flowers or fruits (iNaturalist annotations
-- reach GBIF as lifeStage, sex and reproductiveCondition); "Unknown", "Indeterminate" and "no flowers or fruits" do not count.
-- {region_filter} is empty for the national run, or an extra AND clause for a test region.
SELECT
  specieskey,
  ROUND(decimallatitude, 3) AS lat,
  ROUND(decimallongitude, 3) AS lon,
  MIN("year") AS first_year,
  MAX("year") AS last_year,
  COUNT(*) AS n_records,
  MAX(CASE WHEN datasetkey = '{dna_dataset}' THEN NULL ELSE "year" END) AS last_year_not_dna,
  SUM(CASE WHEN (lifestage.concept IS NOT NULL AND lifestage.concept <> 'Unknown')
             OR (sex.concept IS NOT NULL AND sex.concept <> 'Indeterminate')
             OR (reproductivecondition IS NOT NULL AND reproductivecondition <> ''
                 AND reproductivecondition <> 'no flowers or fruits')
           THEN 1 ELSE 0 END) AS n_trait
FROM occurrence
WHERE countrycode = 'IN'
  AND hascoordinate = TRUE
  AND hasgeospatialissues = FALSE
  AND occurrencestatus = 'PRESENT'
  AND specieskey IS NOT NULL
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND (coordinateuncertaintyinmeters IS NULL OR coordinateuncertaintyinmeters <= 25000)
  AND datasetkey NOT IN ({excluded})
  {region_filter}
GROUP BY specieskey, ROUND(decimallatitude, 3), ROUND(decimallongitude, 3)
