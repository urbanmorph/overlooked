-- Georeferencing test sample: one row per record, text fields and coordinates.
-- sample = 'fix': query L records (no coordinates, flagged, or uncertain by more than 25 km), same filters as
--   pipeline/queries/unlocated_cube.sql, one record in 8 (gbifid % 8).
-- sample = 'test': records with good coordinates (uncertainty <= 1 km, no geospatial issues) and locality text;
--   every record that is not a human observation, one human observation in 20 (they are 90% of such records).
SELECT
  gbifid,
  datasetkey,
  basisofrecord,
  CASE WHEN hascoordinate = TRUE AND hasgeospatialissues = FALSE AND coordinateuncertaintyinmeters <= 1000
       THEN 'test' ELSE 'fix' END AS sample,
  CASE WHEN hascoordinate = FALSE THEN 'none' WHEN hasgeospatialissues = TRUE THEN 'issue'
       WHEN coordinateuncertaintyinmeters > 25000 THEN 'coarse' ELSE 'good' END AS problem,
  decimallatitude,
  decimallongitude,
  coordinateuncertaintyinmeters,
  locality,
  verbatimlocality,
  municipality,
  county,
  stateprovince,
  highergeography,
  island,
  islandgroup,
  waterbody,
  eventremarks,
  "year"
FROM occurrence
WHERE countrycode = 'IN'
  AND occurrencestatus = 'PRESENT'
  AND taxonkey IS NOT NULL
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND datasetkey NOT IN ({excluded})
  AND (
    ((hascoordinate = FALSE OR hasgeospatialissues = TRUE OR coordinateuncertaintyinmeters > 25000)
     AND NOT GBIF_STRINGARRAYCONTAINS(issue, 'COUNTRY_COORDINATE_MISMATCH', FALSE)
     AND (hascoordinate = TRUE OR datasetkey NOT IN ({sequence_datasets}))
     AND gbifid % 8 = 0)
    OR
    (hascoordinate = TRUE AND hasgeospatialissues = FALSE AND coordinateuncertaintyinmeters <= 1000
     AND (locality IS NOT NULL OR verbatimlocality IS NOT NULL)
     AND (basisofrecord <> 'HUMAN_OBSERVATION' OR gbifid % 20 = 0))
  )
