-- Query Y (module 3): India records since the first year of the new-species window (gbif.NEW_SPECIES_FROM), by species, year and kind of record.
-- Used to see whether a species described from India was recorded after its description.
-- sequence_only: a record from a dataset in excluded_unlocated.csv (INSDC Sequences) with no coordinates. The master
-- list does not count these as observations (dates are often submission dates), so the match does not either.
SELECT
  specieskey,
  "year",
  basisofrecord,
  (hascoordinate = FALSE AND datasetkey IN ({sequence_datasets})) AS sequence_only,
  COUNT(*) AS n_records
FROM occurrence
WHERE countrycode = 'IN'
  AND occurrencestatus = 'PRESENT'
  AND specieskey IS NOT NULL
  AND "year" >= {first_year}
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND datasetkey NOT IN ({excluded})
  {region_filter}
GROUP BY specieskey, "year", basisofrecord, (hascoordinate = FALSE AND datasetkey IN ({sequence_datasets}))
