"""Records not named to species (query U), placed in districts. Module 5.

Creates table unresolved: district_lgd, state_lgd, grp, taxonrank, n_records, first_year, last_year.
"""

from pipeline.groups import GROUP_SQL
from pipeline.places import place_points


def build(con, tsv, districts_path):
    con.sql(f"""
        CREATE OR REPLACE TABLE ucube AS
        SELECT * FROM read_csv('{tsv}', delim = '\t', header = true, quote = '',
            columns = {{'kingdom': 'VARCHAR', 'phylum': 'VARCHAR', 'class': 'VARCHAR', 'order': 'VARCHAR',
                        'family': 'VARCHAR', 'taxonrank': 'VARCHAR', 'lat': 'DOUBLE', 'lon': 'DOUBLE',
                        'first_year': 'INTEGER', 'last_year': 'INTEGER', 'n_records': 'BIGINT'}})
    """)
    # place_points replaces table point_district; the ledger is already built by now.
    place_points(con, "ucube", districts_path)
    con.sql(f"""
        CREATE OR REPLACE TABLE unresolved AS
        SELECT p.dist_lgd AS district_lgd, p.state_lgd, {GROUP_SQL} AS grp, lower(u.taxonrank) AS taxonrank,
               sum(u.n_records) AS n_records, min(u.first_year) AS first_year, max(u.last_year) AS last_year
        FROM ucube u JOIN point_district p USING (lat, lon)
        WHERE p.dist_lgd IS NOT NULL
        GROUP BY ALL
        ORDER BY state_lgd, district_lgd, grp, taxonrank
    """)
    return con.sql("SELECT sum(n_records) FROM unresolved").fetchone()[0] or 0
