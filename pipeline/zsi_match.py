"""Check every name extracted from the ZSI checklists against the Catalogue of Life.

Moved from fnf (scripts/18_zsi_name_match.py) on 1 Nov 2026, with a fourth step, ocr_letters, for names whose genus
OCR damaged in its first letters ("Lxobrychus sinensis").

The reference is the Catalogue of Life eXtended Release of 2026-09-25 (COL26.9 XR, ColDP export,
one download of 144 MB, matched locally: no per-name API calls). The base release was tried first;
it lacks species in some groups (no species under the mantis-shrimp genus Squilla), so the
extended release, which adds names from further sources, is used. GBIF's own backbone file was the first choice,
but its server failed at the same byte on every attempt (15 October 2026). The Catalogue of Life
is the source GBIF's next backbone is built from. Family and kingdom come from walking each
name's parent links.

Matching, in order (each row records which step matched it, nothing is silently changed):
  exact          canonical name (subgenus dropped) found among animals and protists.
                 Homonyms: prefer the record whose family equals the checklist's family,
                 then accepted over synonym over doubtful.
  fuzzy_epithet  genus found; epithet within edit distance 1 (2 for epithets of 8+ letters)
                 of a name in that genus. Catches OCR misreadings ("rn" for "m", "l" for "i").
                 A distance-2 match whose difference is not a Latin gender ending (-us/-a/-um
                 or -is/-e) can be a different real species (Corbicula assamensis vs
                 siamensis): it is kept as a suggestion, flagged needs_review, not applied.
  fuzzy_genus    genus not found; a genus with the same first two letters within edit distance 1,
                 and the epithet found in it exactly. Catches OCR damage in the genus.
  ocr_letters    the whole name equal to one name after folding the letters OCR confuses (pipeline.zsi_parse
                 fold: i l I 1 |, rn m, vv w), when exactly one name fits.
  none           no match. Kept, flagged for review: new species, recent combinations,
                 or OCR junk.
After matching, rows whose matched name repeats within one checklist are merged (OCR variants of
one species), keeping the first page.

Source and credit:
    Bánki, O. et al. (2026). Catalogue of Life eXtended Release (COL26.9 XR, 2026-09-25).
    Catalogue of Life, Amsterdam, Netherlands. https://doi.org/10.48580/dgz9s (CC BY 4.0)
    Zoological Survey of India. Fauna of India Checklist. https://zsi.gov.in

Input:  data/fnf/zsi/zsi_checklist.csv (pipeline/zsi_parse.py), data/fnf/col_xr_2026-09-25/col_xr_2026-09-25_coldp.zip
Output: data/fnf/zsi/zsi_checklist_matched.csv (the master list's ZSI input), zsi_checklist_match_qc.csv
        data/fnf/col_xr_2026-09-25/animals.parquet (cached subset)
Usage:  .venv/bin/python -m pipeline.zsi_match
"""

import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
COL = ROOT / "data" / "fnf" / "col_xr_2026-09-25" / "col_xr_2026-09-25_coldp.zip"
IN = ROOT / "data" / "fnf" / "zsi" / "zsi_checklist.csv"
OUT = ROOT / "data" / "fnf" / "zsi" / "zsi_checklist_matched.csv"
QC = ROOT / "data" / "fnf" / "zsi" / "zsi_checklist_match_qc.csv"
# pipeline.zsi_parse fold, in SQL
FOLD = "replace(replace(regexp_replace(lower({}), '[il1|]', 'i', 'g'), 'rn', 'm'), 'vv', 'w')"
KINGDOMS = ("Animalia", "Protozoa", "Chromista")  # ZSI covers protists too
STATUS_ORDER = """CASE b.status WHEN 'accepted' THEN 0 WHEN 'provisionally accepted' THEN 1
                  WHEN 'synonym' THEN 2 WHEN 'ambiguous synonym' THEN 3 ELSE 4 END"""


def backbone(con, pq=COL.parent / "animals.parquet"):
    if not pq.exists():
        tsv = COL.parent / "NameUsage.tsv"
        if not tsv.exists():
            zipfile.ZipFile(COL).extract("NameUsage.tsv", COL.parent)
        con.execute(f"""
            CREATE TEMP TABLE t AS
            SELECT "col:ID" AS id, "col:parentID" AS parent, "col:status" AS status, "col:rank" AS rank,
                   "col:scientificName" AS sci, "col:authorship" AS authorship
            FROM read_csv('{tsv}', delim='\t', header=true, quote='', escape='', all_varchar=true)""")
        # family and kingdom: walk down from each kingdom; synonyms hang off their accepted name
        con.execute("""
            CREATE TEMP TABLE tree AS
            WITH RECURSIVE w(id, kingdom, family) AS (
              SELECT id, sci, NULL::VARCHAR FROM t WHERE rank = 'kingdom'
              UNION ALL
              SELECT c.id, w.kingdom, CASE WHEN c.rank = 'family' THEN c.sci ELSE w.family END
              FROM t c JOIN w ON c.parent = w.id
            ) SELECT * FROM w""")
        con.execute(f"""
            COPY (
              SELECT t.id, t.status, t.rank, tree.kingdom, tree.family, t.authorship,
                     regexp_replace(t.sci, ' \\([^)]*\\)', '') AS canonical_name,
                     split_part(regexp_replace(t.sci, ' \\([^)]*\\)', ''), ' ', 1) AS genus,
                     split_part(regexp_replace(t.sci, ' \\([^)]*\\)', ''), ' ', 2) AS epithet,
                     split_part(regexp_replace(t.sci, ' \\([^)]*\\)', ''), ' ', 3) AS infra,
                     CASE WHEN t.status LIKE '%synonym' OR t.status = 'misapplied' THEN t.parent ELSE t.id END AS accepted_id
              FROM t JOIN tree USING (id)
              WHERE tree.kingdom IN {KINGDOMS}
                AND t.rank IN ('species', 'subspecies', 'variety', 'form')
            ) TO '{pq}' (FORMAT parquet)""")
        con.execute("DROP TABLE t; DROP TABLE tree")
    con.execute(f"CREATE TEMP TABLE bb AS SELECT * FROM '{pq}'")
    con.execute("""CREATE TEMP TABLE bb_acc AS
                   SELECT b.*, a.canonical_name AS accepted_name FROM bb b LEFT JOIN bb a ON a.id = b.accepted_id""")


def match(src=IN, out=OUT, qc=QC, pq=COL.parent / "animals.parquet"):
    con = duckdb.connect()
    backbone(con, pq)
    con.execute(f"""
        CREATE TEMP TABLE z AS
        SELECT row_number() OVER () AS rid, *,
               regexp_replace(name, ' \\([^)]*\\)', '') AS canon,
               split_part(regexp_replace(name, ' \\([^)]*\\)', ''), ' ', 1) AS g,
               split_part(regexp_replace(name, ' \\([^)]*\\)', ''), ' ', 2) AS e,
               split_part(regexp_replace(name, ' \\([^)]*\\)', ''), ' ', 3) AS i
        FROM read_csv('{src}', all_varchar=true)""")
    rank_pref = f"CASE WHEN b.family = z.family THEN 0 ELSE 1 END, {STATUS_ORDER}, b.id"   # b.id: the same choice on every run

    # 1 exact
    con.execute(f"""
        CREATE TEMP TABLE m1 AS
        SELECT z.rid, 'exact' AS match_type, b.id AS col_id, b.canonical_name AS matched_name,
               b.status, b.accepted_id, b.accepted_name, b.family AS col_family, 0 AS dist
        FROM z JOIN bb_acc b ON b.canonical_name = z.canon
        QUALIFY row_number() OVER (PARTITION BY z.rid ORDER BY {rank_pref}) = 1""")

    # 2 fuzzy epithet within a known genus
    con.execute(f"""
        CREATE TEMP TABLE m2 AS
        SELECT z.rid, 'fuzzy_epithet' AS match_type, b.id, b.canonical_name, b.status, b.accepted_id,
               b.accepted_name, b.family, levenshtein(z.e, b.epithet) AS dist
        FROM z JOIN bb_acc b ON b.genus = z.g
        WHERE z.rid NOT IN (SELECT rid FROM m1)
          AND b.infra = '' AND z.i = ''
          AND levenshtein(z.e, b.epithet) <= CASE WHEN length(z.e) >= 8 THEN 2 ELSE 1 END
        QUALIFY row_number() OVER (PARTITION BY z.rid ORDER BY dist, {rank_pref}) = 1""")

    # 3 fuzzy genus (same first two letters), exact epithet
    con.execute(f"""
        CREATE TEMP TABLE m3 AS
        SELECT z.rid, 'fuzzy_genus' AS match_type, b.id, b.canonical_name, b.status, b.accepted_id,
               b.accepted_name, b.family, levenshtein(z.g, b.genus) AS dist
        FROM z JOIN bb_acc b ON b.epithet = z.e AND left(b.genus, 2) = left(z.g, 2)
        WHERE z.rid NOT IN (SELECT rid FROM m1) AND z.rid NOT IN (SELECT rid FROM m2)
          AND z.g NOT IN (SELECT DISTINCT genus FROM bb)
          AND b.infra = '' AND z.i = ''
          AND levenshtein(z.g, b.genus) <= 1
        QUALIFY row_number() OVER (PARTITION BY z.rid ORDER BY dist, {rank_pref}) = 1""")

    # 4 the whole name after folding OCR look-alikes, when one name fits
    con.execute(f"""
        CREATE TEMP TABLE m4 AS
        SELECT z.rid, 'ocr_letters' AS match_type, b.id, b.canonical_name, b.status, b.accepted_id,
               b.accepted_name, b.family, 0 AS dist
        FROM z JOIN bb_acc b ON {FOLD.format('b.canonical_name')} = {FOLD.format('z.canon')}
        WHERE z.rid NOT IN (SELECT rid FROM m1 UNION ALL SELECT rid FROM m2 UNION ALL SELECT rid FROM m3)
        QUALIFY count(DISTINCT b.accepted_id) OVER (PARTITION BY z.rid) = 1
            AND row_number() OVER (PARTITION BY z.rid ORDER BY {rank_pref}) = 1""")

    con.execute("""
        CREATE TEMP TABLE m AS
        SELECT z.* EXCLUDE (canon, g, e, i),
               coalesce(x.match_type, 'none') AS match_type, x.col_id, x.matched_name, x.status AS col_status,
               x.accepted_id AS col_accepted_id, x.accepted_name AS col_accepted_name,
               x.col_family, x.dist AS edit_distance,
               coalesce(x.match_type = 'fuzzy_epithet' AND x.dist = 2
                 AND regexp_replace(split_part(z.canon, ' ', 2), '(us|um|a|is|e)$', '')
                     <> regexp_replace(split_part(x.matched_name, ' ', 2), '(us|um|a|is|e)$', ''), false) AS needs_review
        FROM z LEFT JOIN (SELECT * FROM m1 UNION ALL SELECT * FROM m2 UNION ALL SELECT * FROM m3 UNION ALL SELECT * FROM m4) x USING (rid)""")
    # merge OCR variants of one species within a checklist
    con.execute(f"""
        COPY (
          SELECT * EXCLUDE (rid) FROM m
          QUALIFY match_type = 'none' OR needs_review
               OR row_number() OVER (PARTITION BY checklist, matched_name ORDER BY page::INT, rid) = 1
          ORDER BY rid
        ) TO '{out}' (HEADER, DELIMITER ',')""")
    con.execute(f"""
        COPY (
          SELECT checklist, count(*) AS rows_in,
                 count(*) FILTER (match_type = 'exact') AS exact,
                 count(*) FILTER (match_type LIKE 'fuzzy%') AS fuzzy,
                 count(*) FILTER (match_type = 'none') AS no_match,
                 count(DISTINCT matched_name) FILTER (rank = 'species') + count(*) FILTER (match_type = 'none' AND rank = 'species') AS species_after_merge
          FROM m GROUP BY checklist ORDER BY checklist
        ) TO '{qc}' (HEADER, DELIMITER ',')""")
    print(con.execute("""SELECT match_type, count(*) n FROM m GROUP BY 1 ORDER BY 2 DESC""").fetchall())
    (n,), = con.execute(f"SELECT count(*) FROM '{out}'").fetchall()
    print(n, "rows after merging OCR variants")


if __name__ == "__main__":
    match()
