"""Cross-checks of the numbers the site shows (scripts/check_numbers.py)."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_numbers", Path(__file__).resolve().parent.parent / "scripts" / "check_numbers.py")
cn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cn)

from pipeline import master

CATS = master.IUCN_CATS


def summary(period, rows, waiting, totals=None):
    """rows: per group (documented, with an open record, {IUCN category: count})."""
    india = [[d, o, [c.get(k, 0) for k in CATS], 0] for d, o, c in rows]
    t = totals or dict(zip(("documented", "observed"), [sum(r[n] for r in rows) for n in range(2)]))
    return {"period": period, "groups": [f"G{i}" for i in range(len(rows))], "india": india, "totals": t,
            "waiting": {"india": waiting, "genus": {"india": [[1, 10]] * len(rows)}, "coarse": {"india": {"Plantae": 5}}}}


S1 = summary("2026-10", [(10, 6, {"VU": 2}), (5, 2, {})], [[3, 30, 0], [1, 7, 0]])
S2 = summary("2026-10-26", [(11, 7, {"VU": 3}), (5, 2, {"EN": 1})], [[2, 25, 0], [1, 7, 0]])


def test_a_summary_whose_totals_are_the_sum_of_its_groups_passes():
    assert cn.check_summary(S2) == []
    assert cn.check_summary({**S2, "totals": {"documented": 99, "observed": 9}}) == [
        "summary 2026-10-26: totals documented is 99, its groups add up to 16"]


def test_history_matches_the_summaries_of_its_lists():
    h = master.next_history({"summary": S1}, S2)
    assert cn.check_history(h, {"2026-10": S1, "2026-10-26": S2}) == []
    bad = master.next_history({"summary": S1}, {**S2, "india": S1["india"]})
    assert cn.check_history(bad, {"2026-10": S1, "2026-10-26": S2})[0].startswith("history 2026-10-26: documented is 15")
    # A list from before open records: its history entry is read from its master.parquet, not its summary.
    old = {**S1, "totals": {"documented": 15, "observed": 8, "identified": 5}}
    assert cn.check_history(h, {"2026-10": old, "2026-10-26": S2}) == []
    assert cn.check_summary(old) == []


def test_changes_agree_with_the_pointer_the_history_and_their_own_rows():
    h = master.next_history({"summary": S1}, S2)
    ch = {"from": "2026-10", "to": "2026-10-26", "counts": {"dropped": 1, "iucn": 0}, "rows": [["dropped", "K", "A b", 0, [], []]],
          "waiting": {"before": 37, "now": 32}}
    ptr = {"period": "2026-10-26", "previous": "2026-10"}
    assert cn.check_changes(ch, ptr, h) == []
    assert cn.check_changes({**ch, "counts": {"dropped": 2}, "waiting": {"before": 37, "now": 30}}, ptr, h) == [
        "changes: dropped counted 2, rows 1", "changes: waiting now 30, history 32"]


def test_shortlist_counts_agree_with_the_rows_in_the_files():
    latest = {"rows": 3, "groups": [{"key": "a", "rows": 2}, {"key": "b", "rows": 1}]}
    assert cn.check_shortlist(latest, {"a": 2, "b": 1}) == []
    assert cn.check_shortlist(latest, {"a": 2, "b": 0}) == ["shortlist b: latest.json says 1 rows, the files hold 0"]


def test_the_waiting_queue_in_lakh_is_the_sum_of_every_rank():
    assert cn.waiting_all(S2) == 32 + 20 + 5
    assert cn.check_lakh("about 29 lakh", 28_74_567) == []
    assert cn.check_lakh("about 29 lakh", 35_00_000) == ["text says about 29 lakh, the data says 35.0 lakh"]


def test_the_method_table_matches_the_gate_results():
    html = "<tr><td>Birds</td><td>Genus first</td><td>107</td><td>75.7%</td><td>93.1%</td></tr>"
    gate = [{"group": "Birds", "verdict": "Genus first", "n": "107", "top1": "75.7", "sp_cov": "92.8", "g_cov": "93.1"}]
    assert cn.check_method_table(html, gate) == []
    assert cn.check_method_table(html.replace("75.7%", "76.0%"), gate) == ["method table Birds: first name right 76.0, gate.csv 75.7"]


def test_a_week_is_read_from_the_build_its_pointer_names():
    files = {"layers/master/2026-11-02/current.json": {"base": "layers/master/2026-11-02/20261102T010000Z/"}}
    get = files.get
    assert cn.week_base(get, "2026-11-02") == "layers/master/2026-11-02/20261102T010000Z/"
    assert cn.week_base(get, "2026-10-26") == "layers/master/2026-10-26/"     # a list from before builds


def test_the_funnel_totals_are_the_sum_of_their_groups():
    s = {"period": "2026-11-02", "groups": ["G0", "G1"], "unlisted": [2, 1], "dna": [4, 0],
         "india": [[10, 6, [0] * len(CATS), 1, 5, 3], [5, 2, [0] * len(CATS), 0, 2, 1]],
         "totals": {"documented": 15, "observed": 8, "in_state": 7, "recent": 4, "unlisted": 3, "dna": 4}}
    assert cn.check_summary(s) == []
    assert cn.check_summary({**s, "totals": {**s["totals"], "recent": 5, "unlisted": 9}}) == [
        "summary 2026-11-02: totals recent is 5, its groups add up to 4",
        "summary 2026-11-02: totals unlisted is 9, its groups add up to 3"]


def test_the_red_list_totals_are_the_sum_of_their_groups():
    s = {"period": "2026-11-02", "groups": ["G0", "G1"], "india": [[1, 0, [0] * len(CATS), 0], [1, 0, [0] * len(CATS), 0]],
         "redlist": {"assessed": [3, 1], "out_of_date": [2, 0]},
         "totals": {"documented": 2, "observed": 0, "redlist": {"assessed": 4, "out_of_date": 3}}}
    assert cn.check_summary(s) == ["summary 2026-11-02: totals redlist out_of_date is 3, its groups add up to 2"]
