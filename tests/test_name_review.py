"""Names to check (pipeline/name_review.py): species on the India list that no Indian checklist lists, reached by an
older name the Catalogue of Life places under them, with a related species on a checklist. They may hold another
species' records. The strong sign first, then the species whose IUCN range map leaves out India (the owner's
go-ahead, 1 November 2026, as for population trends), then most states with a record.
Not candidates: a species another India list has (State of India's Birds), a species whose older name is the name a
checklist uses (the same species, the genus moved), a subspecies of a listed species, and a species split from a
listed one (an older name is a subspecies of it). The public file has animals,
and plants and fungi only with the strong sign: an older name that a checklist uses for another species (a different
epithet). Without it they are mostly cultivated (the tomato) or have no Indian checklist."""

from pipeline import name_review as nr

ROWS = [("4Q34B", "Pteropus vampyrus", ["GBIF", "IUCN"], ["9", "32"], "Mammals: bats"),
        ("7WP9Q", "Pteropus medius", ["ZSI", "GBIF"], ["32"], "Mammals: bats"),
        ("X1", "Lonely onlyus", ["GBIF"], ["32"], "Other"),                     # no congener on a checklist
        ("X2", "Pteropus listed", ["BSI"], [], "Mammals: bats"),
        ("X3", "Pteropus alter", ["GBIF"], ["9", "32", "4"], "Mammals: bats"),
        ("B1", "Ardeola grayii", ["GBIF"], ["9"], "Birds"),                     # on State of India's Birds
        ("B2", "Ardeola bacchus", ["ZSI"], ["9"], "Birds"),
        ("C1", "Castalius ananda", ["GBIF"], ["9"], "Insects: butterflies"),   # ZSI lists it as Tarucus ananda
        ("C2", "Castalius rosimon", ["ZSI"], ["9"], "Insects: butterflies"),
        ("S1", "Pteropus medius minor", ["GBIF"], ["9"], "Mammals: bats"),     # a subspecies of a listed species
        ("K1", "Corvus culminatus", ["GBIF"], ["9"], "Birds"),                 # split from a listed species
        ("K2", "Corvus macrorhynchos", ["ZSI"], ["9"], "Birds"),
        ("P3", "Setaria parviflora", ["GBIF"], ["9", "4"], "Plants: grasses & sedges"),  # a checklist's other species
        ("P4", "Setaria viridis", ["BSI"], ["9"], "Plants: grasses & sedges"),
        ("P1", "Solanum lycopersicum", ["GBIF"], ["9"], "Plants: other flowering plants & conifers"),
        ("P2", "Solanum nigrum", ["BSI"], ["9"], "Plants: other flowering plants & conifers")]
CACHE = {"Pteropus giganteus": {"key": "4Q34B", "synonym": True}, "Lonely oldus": {"key": "X1", "synonym": True},
         "Pteropus medius": {"key": "7WP9Q", "synonym": False}, "Pteropus olda": {"key": "X3", "synonym": True},
         "Pteropus oldb": {"key": "X3", "synonym": True}, "Ardea grayii": {"key": "B1", "synonym": True},
         "Tarucus ananda": {"key": "C1", "synonym": True}, "Pteropus minor": {"key": "S1", "synonym": True},
         "Lycopersicon esculentum": {"key": "P1", "synonym": True},
         "Corvus macrorhynchos culminatus": {"key": "K1", "synonym": True},
         "Cenchrus polystachios": {"key": "P3", "synonym": True}}
CHECKLIST_NAMES = {"Pteropus medius", "Pteropus listed", "Ardeola bacchus", "Tarucus ananda", "Castalius rosimon",
                   "Solanum nigrum", "Corvus macrorhynchos", "Cenchrus polystachios"}


def test_candidates_leave_out_names_another_list_or_a_checklist_already_has():
    got = nr.candidates(ROWS, CACHE, checklist_names=CHECKLIST_NAMES, on_lists={"B1"})
    assert [r["name"] for r in got] == ["Setaria parviflora", "Pteropus alter", "Pteropus vampyrus", "Solanum lycopersicum"]
    assert [r["name"] for r in got if r["strong"]] == ["Setaria parviflora"]   # an older name is a checklist's other species


def test_the_public_rows_are_animals_and_strong_plants_with_old_names_and_relatives_most_states_first():
    assert nr.public_rows(ROWS, CACHE, CHECKLIST_NAMES, {"B1"}) == [
        ["P3", "Setaria parviflora", 2, ["Cenchrus polystachios"], ["Setaria viridis"], False],
        ["X3", "Pteropus alter", 3, ["Pteropus olda", "Pteropus oldb"], ["Pteropus listed", "Pteropus medius"], False],
        ["4Q34B", "Pteropus vampyrus", 2, ["Pteropus giganteus"], ["Pteropus listed", "Pteropus medius"], False]]


def test_a_species_whose_iucn_range_leaves_out_india_comes_before_more_states_and_is_marked():
    rows = nr.public_rows(ROWS, CACHE, CHECKLIST_NAMES, {"B1"}, {"Pteropus vampyrus": False, "Pteropus alter": True})
    assert [(r[1], r[5]) for r in rows] == [("Setaria parviflora", False), ("Pteropus vampyrus", True),
                                            ("Pteropus alter", False)]


def test_the_review_file_is_written_with_its_count(tmp_path):
    import json
    nr.review_file(ROWS, CACHE, tmp_path, CHECKLIST_NAMES, {"B1"}, {"Pteropus vampyrus": False})
    doc = json.loads((tmp_path / "review" / "names.json").read_text())
    assert doc["n"] == 3 and doc["rows"][1][1] == "Pteropus vampyrus" and doc["rows"][1][5] is True
