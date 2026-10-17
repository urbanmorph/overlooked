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


def merge_duplicates(con):
    """The Catalogue of Life can give one species two keys with the same name and classification.
    Keep the key with the most records and fold the others into it, so a species is not shown as
    not recorded under one key while its recent records sit under the other. A homonym (same name,
    other classification) stays separate.
    Creates table key_map (species_key -> canonical) for load_cube; returns the number of names merged."""
    con.sql("""
        CREATE OR REPLACE TABLE key_map AS
        WITH n AS (SELECT species_key, sum(n_records) AS n FROM species_decade GROUP BY 1),
        ranked AS (
            SELECT s.species_key, s.name,
                   first_value(s.species_key) OVER w AS canonical, count(*) OVER (PARTITION BY s.name, s.kingdom, s.phylum,
                       s.class, s."order", s.family, s.genus) AS keys
            FROM species s JOIN n USING (species_key)
            WINDOW w AS (PARTITION BY s.name, s.kingdom, s.phylum, s.class, s."order", s.family, s.genus
                         ORDER BY n.n DESC, s.species_key))
        SELECT species_key, canonical, name FROM ranked WHERE keys > 1 AND species_key <> canonical
    """)
    con.sql("DELETE FROM species WHERE species_key IN (SELECT species_key FROM key_map)")
    con.sql("""
        CREATE OR REPLACE TABLE species_decade AS
        SELECT coalesce(m.canonical, d.species_key) AS species_key, d.decade, d.basis, sum(d.n_records) AS n_records
        FROM species_decade d LEFT JOIN key_map m USING (species_key)
        GROUP BY ALL ORDER BY species_key, decade, basis
    """)
    return con.sql("SELECT count(DISTINCT name) FROM key_map").fetchone()[0]
