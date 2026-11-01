"""Names to check (pipeline/name_review.py): species on the India list that no Indian checklist lists, reached by an
older name the Catalogue of Life places under them, with a related species on a checklist. They may hold another
species' records. The public file has no IUCN range data (IUCN terms): its order is by states with a record."""

from pipeline import name_review as nr

ROWS = [("4Q34B", "Pteropus vampyrus", ["GBIF", "IUCN"], ["9", "32"]),
        ("7WP9Q", "Pteropus medius", ["ZSI", "GBIF"], ["32"]),
        ("X1", "Lonely onlyus", ["GBIF"], ["32"]),                     # no congener on a checklist
        ("X2", "Pteropus listed", ["BSI"], []),
        ("X3", "Pteropus alter", ["GBIF"], ["9", "32", "4"])]
CACHE = {"Pteropus giganteus": {"key": "4Q34B", "synonym": True}, "Lonely oldus": {"key": "X1", "synonym": True},
         "Pteropus medius": {"key": "7WP9Q", "synonym": False}, "Pteropus olda": {"key": "X3", "synonym": True},
         "Pteropus oldb": {"key": "X3", "synonym": True}}


def test_the_public_rows_name_the_old_names_and_the_relatives_on_checklists_most_states_first():
    assert nr.public_rows(ROWS, CACHE) == [
        ["X3", "Pteropus alter", 3, ["Pteropus olda", "Pteropus oldb"], ["Pteropus listed", "Pteropus medius"]],
        ["4Q34B", "Pteropus vampyrus", 2, ["Pteropus giganteus"], ["Pteropus listed", "Pteropus medius"]]]


def test_the_review_file_is_written_with_its_count(tmp_path):
    import json
    nr.review_file(ROWS, CACHE, tmp_path)
    doc = json.loads((tmp_path / "review" / "names.json").read_text())
    assert doc["n"] == 2 and doc["rows"][1][1] == "Pteropus vampyrus"
