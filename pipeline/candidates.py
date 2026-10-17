"""May be an overlooked species: records named only to genus, where a species of that genus has no
public record since 1980.

For each district and genus with records named only to genus (query U) at points recorded since 1980,
look for species of the same genus and group with no record in the district since 1980 (tier
"district"); if there are none, in the state (tier "state"). The unsurveyed rule of the ledger holds:
a species counts only if its group has a record in that area since 1980.

Creates table candidates: district_lgd, state_lgd, grp, genus, tier, n_records_unnamed,
n_species_not_recorded, examples, example_keys, last_year_unnamed.
"""

from pipeline.groups import GROUP_SQL

SINCE = 1980
EXAMPLES = 3


def not_recorded(area, rel):
    """Species of rel with no record in the area since SINCE, by area, group and genus, in groups recorded there since."""
    order = "ORDER BY last_year DESC, name"
    return f"""
        (SELECT x.{area}, x.grp, x.genus, count(*) AS n,
                list(x.name {order})[1:{EXAMPLES}] AS ex, list(x.species_key {order})[1:{EXAMPLES}] AS ex_keys
         FROM {rel} x
         JOIN (SELECT {area}, grp FROM {rel} GROUP BY ALL HAVING max(last_year) >= {SINCE}) USING ({area}, grp)
         WHERE x.last_year < {SINCE} AND x.genus IS NOT NULL
         GROUP BY ALL)"""


def build(con):
    """Needs tables ledger, species (with genus) and unresolved (with genus). Returns the number of rows,
    or None if query U came without genus (downloads made before it was added)."""
    cols = lambda t: [c[0] for c in con.sql(f"DESCRIBE {t}").fetchall()]
    if "genus" not in cols("unresolved") or "genus" not in cols("species"):
        return None
    con.sql(f"""
        CREATE OR REPLACE TABLE cand_d AS
        SELECT l.species_key, l.district_lgd, l.state_lgd, l.last_year, s.name, s.genus, {GROUP_SQL} AS grp
        FROM ledger l JOIN species s USING (species_key)
    """)
    con.sql("""
        CREATE OR REPLACE TABLE cand_s AS
        SELECT state_lgd, species_key, any_value(name) AS name, any_value(genus) AS genus, any_value(grp) AS grp,
               max(last_year) AS last_year
        FROM cand_d GROUP BY state_lgd, species_key
    """)
    con.sql(f"""
        CREATE OR REPLACE TABLE candidates AS
        WITH u AS (
            SELECT district_lgd, state_lgd, grp, genus, sum(n_records_since_1980) AS n, max(last_year) AS last_year
            FROM unresolved WHERE taxonrank = 'genus' AND genus IS NOT NULL AND n_records_since_1980 > 0
            GROUP BY ALL)
        SELECT u.district_lgd, u.state_lgd, u.grp, u.genus,
               CASE WHEN d.n IS NOT NULL THEN 'district' ELSE 'state' END AS tier,
               u.n AS n_records_unnamed, coalesce(d.n, s.n) AS n_species_not_recorded,
               coalesce(d.ex, s.ex) AS examples, coalesce(d.ex_keys, s.ex_keys) AS example_keys,
               u.last_year AS last_year_unnamed
        FROM u
        LEFT JOIN {not_recorded("district_lgd", "cand_d")} d USING (district_lgd, grp, genus)
        LEFT JOIN {not_recorded("state_lgd", "cand_s")} s USING (state_lgd, grp, genus)
        WHERE d.n IS NOT NULL OR s.n IS NOT NULL
        ORDER BY n_records_unnamed DESC, district_lgd, genus
    """)
    return con.sql("SELECT count(*) FROM candidates").fetchone()[0]
