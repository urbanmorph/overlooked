-- Query V (module 3): India records since the first year of the new-species window (gbif.NEW_SPECIES_FROM) that GBIF could not match to a species,
-- by the name as published, year and kind of record. New species often appear here first,
-- because GBIF's taxonomy has not caught up with the description.
SELECT
  v_scientificname,
  "year",
  basisofrecord,
  COUNT(*) AS n_records
FROM occurrence
WHERE countrycode = 'IN'
  AND occurrencestatus = 'PRESENT'
  AND specieskey IS NULL
  AND "year" >= {first_year}
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND datasetkey NOT IN ({excluded})
  {region_filter}
GROUP BY v_scientificname, "year", basisofrecord
