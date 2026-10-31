"""scripts/override_candidates.py: species that may hold another species' India records under an old name."""

from scripts import override_candidates as oc


def test_a_species_no_checklist_lists_reached_by_a_synonym_with_a_congener_on_a_checklist():
    rows = [("4Q34B", "Pteropus vampyrus", ["GBIF", "IUCN"], ["9", "32"]),
            ("7WP9Q", "Pteropus medius", ["ZSI", "GBIF"], ["32"]),
            ("X1", "Lonely onlyus", ["GBIF"], ["32"]),                     # no congener on a checklist
            ("X2", "Pteropus listed", ["BSI"], [])]
    cache = {"Pteropus giganteus": {"key": "4Q34B", "synonym": True, "accepted_name": "Pteropus vampyrus"},
             "Lonely oldus": {"key": "X1", "synonym": True},
             "Pteropus medius": {"key": "7WP9Q", "synonym": False}}
    got = oc.candidates(rows, cache, {"Pteropus vampyrus": False})
    assert got == [{"key": "4Q34B", "name": "Pteropus vampyrus", "sources": "GBIF; IUCN", "states": 2, "iucn_india": False,
                    "synonyms": "Pteropus giganteus", "congeners_on_checklists": "Pteropus listed; Pteropus medius"}]
