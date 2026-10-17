-- Query L: India records with no coordinates, by taxon, the state text as published, dataset and kind of record.
-- These records cannot be placed in a district. They are placed in a state when the text names one (unlocated.py).
-- species and the classification depend on specieskey, so they add no rows; genus and taxonrank matter only
-- for records not named to species. No year column: only the first and latest year.
-- {stateprovince_filter} is empty for the national run, or a state name for a test region (records with no
-- coordinates have no GADM level1name, so the usual region filter would select nothing).
SELECT
  specieskey,
  species,
  genus,
  taxonrank,
  kingdom,
  phylum,
  class,
  "order",
  family,
  stateprovince,
  datasetkey,
  basisofrecord,
  MIN("year") AS first_year,
  MAX("year") AS last_year,
  COUNT(*) AS n_records
FROM occurrence
WHERE countrycode = 'IN'
  AND hascoordinate = FALSE
  AND occurrencestatus = 'PRESENT'
  AND taxonkey IS NOT NULL
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND datasetkey NOT IN ({excluded_unlocated})
  {stateprovince_filter}
GROUP BY specieskey, species, genus, taxonrank, kingdom, phylum, class, "order", family, stateprovince, datasetkey, basisofrecord
