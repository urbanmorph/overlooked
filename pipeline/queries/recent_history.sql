-- Query Y (module 3): India records since 2015, by species, year and kind of record.
-- Used to see whether a species described from India was recorded after its description.
SELECT
  specieskey,
  "year",
  basisofrecord,
  COUNT(*) AS n_records
FROM occurrence
WHERE countrycode = 'IN'
  AND occurrencestatus = 'PRESENT'
  AND specieskey IS NOT NULL
  AND "year" >= 2015
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND datasetkey NOT IN ({excluded})
  {region_filter}
GROUP BY specieskey, "year", basisofrecord
