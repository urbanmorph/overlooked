"""Compact (columnar) format of layers/newspecies/<month>/new_species.json."""

import json

from pipeline.layer_newspecies import FORMAT_VERSION, PAGE_FIELDS, compact, expand

BSI = "https://bsi.gov.in/page/en/national-wild-life-action-plan"
PLAZI = "https://tb.plazi.org/GgServer/summary/"


def row(name, **kw):
    base = {"name": name, "year": 2020, "sources": ["Plazi"], "journal": "Zootaxa", "state": "Kerala",
            "link": PLAZI + name.replace(" ", ""), "group": "Fungi", "bsi_group": "", "key": None,
            "matched_by": "not found", "status": "none", "latest_after": None, "records_after": 0,
            "papers_after": 0, "any_record": False}
    return {**base, **kw}


ROWS = [
    row("Aa bb"),
    row("Cc dd", year=2015, sources=["BSI Plant Discoveries"], journal="", state="", link=BSI, bsi_group="FUNGI",
        key="92BX", matched_by="exact name", status="recorded", latest_after=2024, records_after=3, any_record=True),
    row("Ee ff", sources=["Plazi", "BSI Plant Discoveries"], link=BSI, group="Lichens", status="later_papers",
        papers_after=2, any_record=True),
    row("Gg hh", link="https://example.org/x", journal="Phytotaxa", key="T373", matched_by="synonym"),
]


def test_round_trip_keeps_page_fields():
    doc = compact(ROWS)
    assert expand(doc) == [{k: r[k] for k in PAGE_FIELDS} for r in ROWS]


def test_compact_shape():
    doc = compact(ROWS)
    assert doc["version"] == FORMAT_VERSION == 2
    assert doc["n"] == len(ROWS)
    assert all(len(col) == len(ROWS) for col in doc["columns"].values())
    # Repeated strings are stored once, in lookup tables.
    assert doc["lookups"]["group"] == ["Fungi", "Lichens"]
    assert doc["lookups"]["sources"] == [["Plazi"], ["BSI Plant Discoveries"], ["Plazi", "BSI Plant Discoveries"]]
    assert BSI in doc["lookups"]["link"] and PLAZI in doc["lookups"]["link"]
    # Fields the page does not use are not written.
    assert not {"bsi_group", "records_after", "papers_after"} & set(doc["columns"])


def test_expand_reads_old_format():
    old = {"species": ROWS}
    assert expand(old) == ROWS


def test_compact_is_smaller():
    rows = [row(f"Genus{i} species{i}", link=PLAZI + f"{i:032X}") for i in range(500)]
    rows += [row(f"Plant{i} name{i}", link=BSI, sources=["BSI Plant Discoveries"], journal="") for i in range(500)]
    old = len(json.dumps({"species": rows}, separators=(",", ":")))
    new = len(json.dumps(compact(rows), separators=(",", ":")))
    assert new < old / 3
