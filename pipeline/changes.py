"""Module 2: what changed since the previous snapshot.

Compares this month's ledger with the previous published one. Change types:
  recorded_again   a species x district pair was quiet (no record since 1980, in a group recorded there
                   since 1980) and now has a record from 1980 or later
  first_in_state   a species x state pair that was not in the previous snapshot
  now_quiet        a species whose latest record in India is now more than 30 years old, and was not before
  withdrawn        a species x district pair that was in the previous snapshot and is not now
                   (records deleted, moved or re-identified at the source)
Reason for a new record: "new record" if its year is the previous run's year or later, otherwise
"older record, newly published".

Species keys are Catalogue of Life IDs, which can change between releases. A previous key that is
missing now is matched again by its exact name before it counts as a change.
"""

QUIET_YEAR = 1980
QUIET_SPAN = 30


def build(con, prev_ledger, prev_species, prev_year, this_year):
    """Needs tables ledger, species (this month). prev_*: paths to last month's Parquet files.
    Creates table changes and returns counts by type."""
    con.sql(f"CREATE OR REPLACE TABLE p_ledger AS SELECT * FROM '{prev_ledger}'")
    con.sql(f"CREATE OR REPLACE TABLE p_species AS SELECT species_key, name FROM '{prev_species}'")
    # Map previous keys to current keys: same key, else the same exact name.
    con.sql("""
        CREATE OR REPLACE TABLE keymap AS
        SELECT p.species_key AS old_key,
               coalesce(same.species_key, byname.species_key) AS new_key
        FROM p_species p
        LEFT JOIN species same ON same.species_key = p.species_key
        LEFT JOIN (SELECT name, min(species_key) AS species_key FROM species GROUP BY name HAVING count(*) = 1) byname
               ON same.species_key IS NULL AND byname.name = p.name
    """)
    con.sql("""
        CREATE OR REPLACE TABLE prev AS
        SELECT coalesce(k.new_key, l.species_key) AS species_key, l.district_lgd, l.state_lgd,
               l.first_year, l.last_year, l.n_records
        FROM p_ledger l LEFT JOIN keymap k ON k.old_key = l.species_key
    """)
    # Effort in the previous snapshot: species of each group recorded in a district since 1980.
    con.sql(f"""
        CREATE OR REPLACE TABLE prev_effort AS
        SELECT p.district_lgd, s.grp, count(*) FILTER (WHERE p.last_year >= {QUIET_YEAR}) AS active
        FROM prev p JOIN sp s USING (species_key) GROUP BY ALL
    """)
    reason = f"CASE WHEN c.last_year >= {prev_year} THEN 'new record' ELSE 'older record, newly published' END"
    con.sql(f"""
        CREATE OR REPLACE TABLE changes AS
        -- Recorded again in a district
        SELECT 'recorded_again' AS change, c.species_key, c.district_lgd, c.state_lgd,
               p.last_year AS before_year, c.last_year AS now_year, {reason} AS reason
        FROM ledger c
        JOIN prev p USING (species_key, district_lgd)
        JOIN sp s USING (species_key)
        JOIN prev_effort e ON e.district_lgd = p.district_lgd AND e.grp = s.grp
        WHERE p.last_year < {QUIET_YEAR} AND e.active > 0 AND c.last_year >= {QUIET_YEAR}
        UNION ALL
        -- First record in a state
        SELECT 'first_in_state', c.species_key, NULL, c.state_lgd, NULL, max(c.last_year),
               CASE WHEN max(c.last_year) >= {prev_year} THEN 'new record' ELSE 'older record, newly published' END
        FROM ledger c
        WHERE NOT EXISTS (SELECT 1 FROM prev p WHERE p.species_key = c.species_key AND p.state_lgd = c.state_lgd)
          AND EXISTS (SELECT 1 FROM prev p WHERE p.species_key = c.species_key)
        GROUP BY c.species_key, c.state_lgd
        UNION ALL
        -- Now quiet in India: latest record passed {QUIET_SPAN} years
        SELECT 'now_quiet', c.species_key, NULL, NULL, p.last_year, c.last_year, 'time passed'
        FROM (SELECT species_key, max(last_year) AS last_year FROM ledger GROUP BY 1) c
        JOIN (SELECT species_key, max(last_year) AS last_year FROM prev GROUP BY 1) p USING (species_key)
        WHERE c.last_year < {this_year - QUIET_SPAN} AND p.last_year >= {prev_year - QUIET_SPAN}
        UNION ALL
        -- Withdrawn from a district
        SELECT 'withdrawn', p.species_key, p.district_lgd, p.state_lgd, p.last_year, NULL, 'records removed or moved at the source'
        FROM prev p
        WHERE NOT EXISTS (SELECT 1 FROM ledger c WHERE c.species_key = p.species_key AND c.district_lgd = p.district_lgd)
    """)
    return dict(con.sql("SELECT change, count(*) FROM changes GROUP BY 1").fetchall())
