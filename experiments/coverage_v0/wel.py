"""Coverage study: for each species of the India list, which kinds of knowledge exist, grouped by the gaps they
measure (the shortfalls of Hortal et al. 2015). Linnean: is the species described and named. Wallacean: do we know
where it lives (a listing for India is the coarsest step of it). Eltonian (later): do we know how it interacts. Each column nests in the one before where the funnel needs it: in_state needs an open
record, recent needs a record placed in a state.

Inputs: master.parquet (the list), and the GBIF snapshot's ledger.parquet (species x district, years) and
unlocated.parquet (records that cannot go in a district; state_lgd when the state is known).
"""

# Column -> the gap it measures. Order: the order of the funnel and of the matrix.
COLUMNS = {
    "accepted_name": "Linnean",   # matches the Catalogue of Life (no "name not matched" label)
    "checklist": "Wallacean",     # listed for India by a checklist or paper source, not only by a record
    "open_record": "Wallacean",   # a GBIF record or an iNaturalist research-grade observation
    "in_state": "Wallacean",      # an open record placed in a state
    "in_district": "Wallacean",   # a GBIF record placed in a district
    "recent": "Wallacean",        # a record placed in a state, in recent_from or later
}
LISTING_SOURCES = ["ZSI", "BSI", "WCVP", "Plazi"]


def flags(con, master, ledger, unlocated, recent_from):
    """One row per species: name, a boolean per COLUMNS key, then the group."""
    return con.sql(f"""
        WITH placed AS (
            SELECT species_key, max(last_year) AS last_year FROM (
                SELECT species_key, last_year FROM '{ledger}'
                UNION ALL SELECT species_key, last_year FROM '{unlocated}' WHERE state_lgd IS NOT NULL)
            GROUP BY 1),
        district AS (SELECT DISTINCT species_key FROM '{ledger}' WHERE district_lgd IS NOT NULL)
        SELECT m.name,
               NOT list_contains(m.labels, 'nm') AS accepted_name,
               list_has_any(m.sources, {LISTING_SOURCES}) AS checklist,
               m.observed AS open_record,
               m.observed AND len(m.states_observed) > 0 AS in_state,
               d.species_key IS NOT NULL AS in_district,
               m.observed AND len(m.states_observed) > 0 AND coalesce(p.last_year >= {int(recent_from)}, false) AS recent,
               m."group"
        FROM '{master}' m
        LEFT JOIN placed p ON p.species_key = m.key
        LEFT JOIN district d ON d.species_key = m.key""")


def by_group(con, rel):
    """{group: {"species": n, column: n with it, ...}} from flags() joined back to the groups."""
    return {g: dict(zip(["species", *COLUMNS], counts)) for g, *counts in rel.aggregate(
        '"group", count(*), ' + ", ".join(f"count(*) FILTER (WHERE {c})" for c in COLUMNS), '"group"').fetchall()}
