-- Query U: records not named to species (genus, family or higher), by group, rank and point.
-- Module 5: where public records wait for a species name. Coordinates rounded to 3 decimals, as in query A.
-- {region_filter} is empty for the national run, or an extra AND clause for a test region.
SELECT
  kingdom,
  phylum,
  class,
  "order",
  family,
  taxonrank,
  ROUND(decimallatitude, 3) AS lat,
  ROUND(decimallongitude, 3) AS lon,
  MIN("year") AS first_year,
  MAX("year") AS last_year,
  COUNT(*) AS n_records
FROM occurrence
WHERE countrycode = 'IN'
  AND hascoordinate = TRUE
  AND hasgeospatialissues = FALSE
  AND occurrencestatus = 'PRESENT'
  AND specieskey IS NULL
  AND taxonkey IS NOT NULL
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND (coordinateuncertaintyinmeters IS NULL OR coordinateuncertaintyinmeters <= 25000)
  AND datasetkey NOT IN ({excluded})
  {region_filter}
GROUP BY kingdom, phylum, class, "order", family, taxonrank, ROUND(decimallatitude, 3), ROUND(decimallongitude, 3)
