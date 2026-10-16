-- Query C: species history and names. One row per species x decade x basis of record, across India.
-- It also carries each species' classification, so no separate taxonomy query is needed.
-- Names and ranks follow GBIF's interpretation (Catalogue of Life taxonomy, keyed by COL ID).
-- {region_filter} is empty for the national run, or an extra AND clause for a test region.
SELECT
  specieskey,
  kingdom,
  phylum,
  class,
  "order",
  family,
  genus,
  species,
  FLOOR("year" / 10) * 10 AS decade,
  basisofrecord,
  COUNT(*) AS n_records
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
GROUP BY specieskey, kingdom, phylum, class, "order", family, genus, species, FLOOR("year" / 10) * 10, basisofrecord
