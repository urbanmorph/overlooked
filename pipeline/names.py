"""Species names, classification and history from a query C download (species_history.sql).

Creates tables:
  species         species_key, name, kingdom, phylum, class, "order", family, genus
  species_decade  species_key, decade, basis, n_records
"""


def load_history(con, tsv):
    con.sql(f"""
        CREATE OR REPLACE TABLE history AS
        SELECT * FROM read_csv('{tsv}', delim = '\t', header = true, quote = '',
            columns = {{'specieskey': 'VARCHAR', 'kingdom': 'VARCHAR', 'phylum': 'VARCHAR', 'class': 'VARCHAR',
                        'order': 'VARCHAR', 'family': 'VARCHAR', 'genus': 'VARCHAR', 'species': 'VARCHAR',
                        'decade': 'INTEGER', 'basisofrecord': 'VARCHAR', 'n_records': 'BIGINT'}})
    """)
    # A species key should carry one classification; if GBIF ever returns two, keep the commonest.
    con.sql("""
        CREATE OR REPLACE TABLE species AS
        SELECT specieskey AS species_key, species AS name, kingdom, phylum, class, "order", family, genus
        FROM (SELECT *, row_number() OVER (PARTITION BY specieskey ORDER BY n DESC) AS rk
              FROM (SELECT specieskey, species, kingdom, phylum, class, "order", family, genus, sum(n_records) AS n
                    FROM history GROUP BY ALL))
        WHERE rk = 1
    """)
    con.sql("""
        CREATE OR REPLACE TABLE species_decade AS
        SELECT specieskey AS species_key, decade, basisofrecord AS basis, sum(n_records) AS n_records
        FROM history GROUP BY ALL ORDER BY species_key, decade, basis
    """)
