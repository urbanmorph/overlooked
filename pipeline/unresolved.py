"""Records not named to species (query U), placed in districts. Module 5.

Creates table unresolved: district_lgd, state_lgd, grp, genus, taxonrank, n_records, n_records_since_1980,
first_year, last_year. genus is NULL above genus rank, and for downloads made before query U kept it.
n_records_since_1980 counts records at points (about 110 m) whose latest record is 1980 or later.
"""

from pipeline.groups import GROUP_SQL
from pipeline.places import place_points
from pipeline.util import value

TYPES = {"kingdom": "VARCHAR", "phylum": "VARCHAR", "class": "VARCHAR", "order": "VARCHAR", "family": "VARCHAR",
         "genus": "VARCHAR", "taxonrank": "VARCHAR", "lat": "DOUBLE", "lon": "DOUBLE",
         "first_year": "INTEGER", "last_year": "INTEGER", "n_records": "BIGINT"}


def read_tsv(con, table, tsv, types):
    """Load a GBIF SQL download, typed by column name. Columns missing from an older download are NULL."""
    with open(tsv, encoding="utf-8") as f:
        header = f.readline().rstrip("\r\n").split("\t")
    columns = ", ".join(f"'{c}': '{types[c]}'" for c in header)
    missing = "".join(f", NULL::{t} AS \"{c}\"" for c, t in types.items() if c not in header)
    con.sql(f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT *{missing} FROM read_csv('{tsv}', delim = '\t', header = true, quote = '', columns = {{{columns}}})
    """)


def build(con, tsv, districts_path):
    read_tsv(con, "ucube", tsv, TYPES)
    # place_points replaces table point_district; the ledger is already built by now.
    place_points(con, "ucube", districts_path)
    con.sql(f"""
        CREATE OR REPLACE TABLE unresolved AS
        SELECT p.dist_lgd AS district_lgd, p.state_lgd, {GROUP_SQL} AS grp, u.genus, lower(u.taxonrank) AS taxonrank,
               sum(u.n_records) AS n_records,
               coalesce(sum(u.n_records) FILTER (WHERE u.last_year >= 1980), 0) AS n_records_since_1980,
               min(u.first_year) AS first_year, max(u.last_year) AS last_year
        FROM ucube u JOIN point_district p USING (lat, lon)
        WHERE p.dist_lgd IS NOT NULL
        GROUP BY ALL
        ORDER BY state_lgd, district_lgd, grp, taxonrank, genus
    """)
    return value(con, "SELECT sum(n_records) FROM unresolved") or 0
