-- Query L: India records that cannot be placed in a district, by taxon, the state text as published, dataset, kind of
-- record and problem: no coordinates ('none'), coordinates GBIF flags ('issue'), or uncertain by more than 25 km
-- ('coarse'); query A takes the rest. They are placed in a state when the text names one (unlocated.py).
-- Left out: coordinates that GBIF finds outside India (the record may not be from India), and records from
-- excluded_unlocated.csv (INSDC Sequences) with no coordinates; with coordinates they count, as in query A.
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
  CASE WHEN hascoordinate = FALSE THEN 'none' WHEN hasgeospatialissues = TRUE THEN 'issue' ELSE 'coarse' END AS problem,
  MIN("year") AS first_year,
  MAX("year") AS last_year,
  COUNT(*) AS n_records
FROM occurrence
WHERE countrycode = 'IN'
  AND (hascoordinate = FALSE OR hasgeospatialissues = TRUE OR coordinateuncertaintyinmeters > 25000)
  AND NOT GBIF_STRINGARRAYCONTAINS(issue, 'COUNTRY_COORDINATE_MISMATCH', FALSE)
  AND occurrencestatus = 'PRESENT'
  AND taxonkey IS NOT NULL
  AND basisofrecord <> 'FOSSIL_SPECIMEN' AND basisofrecord <> 'LIVING_SPECIMEN'
  AND datasetkey NOT IN ({excluded})
  AND (hascoordinate = TRUE OR datasetkey NOT IN ({sequence_datasets}))
  {stateprovince_filter}
GROUP BY specieskey, species, genus, taxonrank, kingdom, phylum, class, "order", family, stateprovince, datasetkey, basisofrecord, CASE WHEN hascoordinate = FALSE THEN 'none' WHEN hasgeospatialissues = TRUE THEN 'issue' ELSE 'coarse' END
