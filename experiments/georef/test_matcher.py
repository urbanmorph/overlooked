"""Tests for the place-name matcher. Run: .venv/bin/python -m pytest experiments/georef -q"""

import pytest
from matcher import (
    Entry,
    Gazetteer,
    haversine_km,
    load_splits,
    match,
    normalise,
    phrases,
    sound_key,
    strip_generic,
)

# A small gazetteer: (kind, name, state_lgd, dist_lgd, lat, lon, radius_km)
ROWS = [
    ("state", "Kerala", 32, None, 10.4, 76.4, 150),
    ("state", "Karnataka", 29, None, 14.7, 76.2, 250),
    ("state", "Tamil Nadu", 33, None, 11.0, 78.5, 250),
    ("district", "Idukki", 32, 556, 9.9, 77.0, 30),
    ("district", "Shivamogga", 29, 557, 14.0, 75.3, 50),
    ("district", "Ernakulam", 32, 558, 10.0, 76.4, 30),
    ("district", "Aurangabad", 27, 401, 19.9, 75.3, 50),
    ("district", "Aurangabad", 10, 402, 24.7, 84.4, 40),
    ("district", "Coimbatore", 33, 560, 11.0, 76.9, 40),
    ("subdistrict", "Devikulam", 32, 556, 10.1, 77.1, 15),
    ("village", "Kumily", 32, 556, 9.6, 77.17, 3),
    ("village", "Rampur", 9, 100, 26.0, 80.0, 2),
    ("village", "Rampur", 10, 200, 25.0, 85.0, 2),
    ("village", "Rampur", 23, 300, 23.0, 78.0, 2),
    ("pa", "Periyar Wildlife Sanctuary Tiger Reserve", 32, 556, 9.5, 77.2, 20),
    ("alias", "Shimoga", 29, 557, 14.0, 75.3, 50),
    ("alias", "Cochin", 32, 558, 10.0, 76.4, 30),
]


@pytest.fixture(scope="module")
def gaz():
    return Gazetteer([Entry(*r) for r in ROWS])


def rec(**kw):
    return kw


# --- normalise and sound keys ---

def test_normalise_case_accents_punctuation():
    assert normalise("  Kumíly,  IDUKKI-Dist. ") == "kumily idukki dist"
    assert normalise("Jammu & Kashmir") == "jammu and kashmir"


@pytest.mark.parametrize("a, b", [
    ("Kumily", "Kumilly"),            # doubled letters
    ("Mahabaleshwar", "Mahabaleswar"),  # sh/s
    ("Thrissur", "Trissur"),          # th/t
    ("Wayanad", "Vayanad"),           # w/v
    ("Ooty", "Uty"),                  # oo/u
    ("Neelgiri", "Nilgiri"),          # ee/i
    ("Kaas", "Kas"),                  # aa/a
])
def test_sound_key_folds_spelling_variants(a, b):
    assert sound_key(a) == sound_key(b)


def test_sound_key_keeps_different_names_apart():
    assert sound_key("Idukki") != sound_key("Ernakulam")


@pytest.mark.parametrize("text, core", [
    ("Shimoga District", "shimoga"),
    ("Shimoga dist", "shimoga"),
    ("Shimoga Distt.", "shimoga"),
    ("Devikulam Taluk", "devikulam"),
    ("Periyar WLS", "periyar"),
    ("Periyar Tiger Reserve", "periyar"),
    ("Nelliampathy Hills", "nelliampathy"),
    ("near Kumily", "kumily"),
    ("Nr. Kumily", "kumily"),
    ("Silent Valley NP", "silent valley"),
])
def test_strip_generic(text, core):
    assert strip_generic(normalise(text)) == core


def test_phrases_split_fields_and_mark_patterns():
    got = phrases("Kumily, 5 km from Thekkady; Idukki Dist.")
    texts = {p.text: p.hint for p in got}
    assert texts["kumily"] is None
    assert texts["idukki"] == "district"
    assert any(p.text == "thekkady" for p in got)


def test_phrases_pattern_hints():
    hints = {p.text: p.hint for p in phrases("Devikulam Taluk, Periyar WLS")}
    assert hints["devikulam"] == "subdistrict"
    assert hints["periyar"] == "pa"


# --- matching ---

def test_district_name_gives_district(gaz):
    r = match(rec(locality="Idukki"), gaz)
    assert r.dist_lgd == 556 and r.state_lgd == 32


def test_old_name_alias(gaz):
    assert match(rec(locality="Shimoga"), gaz).dist_lgd == 557
    assert match(rec(locality="Cochin backwaters"), gaz).dist_lgd == 558


def test_village_gives_district_and_point(gaz):
    r = match(rec(locality="Kumily"), gaz)
    assert r.dist_lgd == 556
    assert (r.lat, r.lon) == (9.6, 77.17)
    assert r.radius_km >= 3


def test_spelling_variant_village(gaz):
    assert match(rec(locality="Kumilly"), gaz).dist_lgd == 556


def test_ambiguous_name_gets_no_district_but_records_candidates(gaz):
    r = match(rec(locality="Rampur"), gaz)
    assert r.dist_lgd is None
    assert set(r.candidates) == {100, 200, 300}
    assert r.state_lgd is None


def test_state_text_narrows_ambiguous_name(gaz):
    r = match(rec(locality="Rampur", stateprovince="Bihar"), gaz, state_names={"bihar": 10})
    assert r.dist_lgd == 200 and r.state_lgd == 10


def test_ambiguous_district_name_narrowed_by_state(gaz):
    assert match(rec(county="Aurangabad"), gaz).dist_lgd is None
    r = match(rec(county="Aurangabad", stateprovince="Bihar"), gaz, state_names={"bihar": 10})
    assert r.dist_lgd == 402


def test_another_field_narrows(gaz):
    # Village Kumily is in Idukki; the district field agrees.
    r = match(rec(locality="Kumily", county="Idukki"), gaz)
    assert r.dist_lgd == 556 and r.confidence == "high"


def test_conflicting_state_text_drops_match(gaz):
    # Kumily is in Kerala; the record says Karnataka: no district, state from the text.
    r = match(rec(locality="Kumily", stateprovince="Karnataka"), gaz, state_names={"karnataka": 29})
    assert r.dist_lgd is None and r.state_lgd == 29


def test_state_only(gaz):
    r = match(rec(locality="Western Ghats", stateprovince="Kerala"), gaz, state_names={"kerala": 32})
    assert r.dist_lgd is None and r.state_lgd == 32


def test_state_name_in_locality_counts_as_state_text(gaz):
    r = match(rec(locality="Rampur, Bihar"), gaz, state_names={"bihar": 10})
    assert r.dist_lgd == 200


def test_protected_area(gaz):
    r = match(rec(locality="Periyar Tiger Reserve"), gaz)
    assert r.dist_lgd == 556 and r.kind == "pa"


def test_most_specific_point_wins(gaz):
    r = match(rec(locality="Kumily, Devikulam taluk, Idukki district"), gaz)
    assert r.kind == "village" and r.dist_lgd == 556


def test_nothing(gaz):
    r = match(rec(locality="no locality data"), gaz)
    assert r.dist_lgd is None and r.state_lgd is None and r.kind is None


def test_common_word_is_not_a_place(gaz):
    # "road", "forest", "river" alone never match, even if a village has that name.
    g = Gazetteer([Entry("village", "Forest", 9, 100, 26.0, 80.0, 2)])
    assert match(rec(locality="forest"), g).dist_lgd is None


def test_confidence_levels(gaz):
    assert match(rec(county="Idukki"), gaz).confidence == "high"
    assert match(rec(locality="Kumily", stateprovince="Kerala"), gaz,
                 state_names={"kerala": 32}).confidence == "medium"
    assert match(rec(locality="Kumily"), gaz).confidence == "low"


def test_haversine():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.2)


def test_state_with_suffix_in_free_text(gaz):
    # "Andaman Islands" in a locality names the state, as query L reads stateprovince.
    r = match(rec(locality="Andaman Islands"), gaz, state_names={"andamanandnicobar": 35, "andaman": 35})
    assert r.state_lgd == 35


# --- rules added after the first run (dev half of the test sample) ---

STATES = {"jammuandkashmir": 1, "ladakh": 37, "kerala": 32, "andamanandnicobarislands": 35, "andamanandnicobar": 35,
          "punjab": 3, "himachalpradesh": 2}


def test_state_name_is_not_read_as_places():
    # "Jammu and Kashmir" must not vote for Jammu district.
    g = Gazetteer([Entry("district", "Jammu", 1, 5, 32.7, 74.9, 30), Entry("pa", "Hemis", 37, 9, 33.9, 77.5, 40)])
    r = match(rec(locality="Hemis NP", stateprovince="Jammu and Kashmir"), g, state_names=STATES)
    assert r.dist_lgd == 9


def test_old_state_covers_its_later_split():
    # Before 2019 Jammu and Kashmir included Ladakh; before 1966 Punjab included Kangra.
    g = Gazetteer([Entry("district", "Kangra", 2, 18, 32.1, 76.3, 30)])
    assert match(rec(locality="Kangra", stateprovince="Punjab"), g, state_names=STATES).dist_lgd == 18


def test_longer_name_wins_over_the_name_inside_it():
    g = Gazetteer([Entry("district", "Kolkata", 19, 315, 22.5, 88.3, 10),
                   Entry("alias", "Botanic Garden Calcutta", 19, 313, 22.56, 88.29, 10),
                   Entry("alias", "Calcutta", 19, 315, 22.5, 88.3, 10)])
    assert match(rec(locality="Botanic Garden, Calcutta"), g).dist_lgd == 315  # two pieces: not one name
    assert match(rec(locality="Botanic Garden Calcutta"), g).dist_lgd == 313


def test_distance_offset_lowers_confidence(gaz):
    r = match(rec(locality="60 km SW of Idukki"), gaz)
    assert r.dist_lgd == 556 and r.confidence == "low"
    assert match(rec(locality="2 km from Idukki"), gaz).confidence == "high"


def test_district_name_beats_villages_of_the_same_name():
    g = Gazetteer([Entry("district", "Indore", 23, 410, 22.7, 75.8, 30),
                   Entry("village", "Indore", 27, 480, 19.0, 74.0, 2),
                   Entry("village", "Indore", 8, 100, 26.0, 74.0, 2)])
    assert match(rec(locality="Indore"), g).dist_lgd == 410


def test_subdistrict_beats_villages_of_the_same_name():
    g = Gazetteer([Entry("subdistrict", "Bhaderwah", 1, 4, 32.9, 75.7, 15),
                   Entry("village", "Bhaderwah", 9, 100, 26.0, 80.0, 2)])
    assert match(rec(locality="Bhaderwah"), g).dist_lgd == 4


def test_later_state_is_more_specific_than_the_old_one():
    # "Kashmir, Ladakh": the state is Ladakh.
    g = Gazetteer([])
    r = match(rec(stateprovince="Kashmir", county="Ladakh"), g, state_names={"kashmir": 1, "ladakh": 37})
    assert r.state_lgd == 37


def test_state_with_postcode_is_not_read_as_places():
    g = Gazetteer([Entry("alias", "Nicobar", 35, 603, 8.0, 93.5, 50), Entry("village", "Kalatang", 35, 602, 11.7, 92.7, 2)])
    r = match(rec(locality="Kalatang, Andaman and Nicobar Islands 744107, India"), g,
              state_names={"andamanandnicobarislands": 35, "andamanandnicobar": 35})
    assert r.dist_lgd == 602 and r.state_lgd == 35


def test_short_state_name_alone():
    assert match(rec(locality="Goa", verbatimlocality="Goa, India"), Gazetteer([]), state_names={"goa": 30}).state_lgd == 30


# --- district splits: an old district name means the district and the districts carved from it ---

# (parent, child, year): Jaipur gave Dudu (2023); Hyderabad gave Ranga Reddy (1978), which gave Medchal (2016).
SPLITS = [(102, 769, 2023), (507, 518, 1978), (518, 700, 2016), (560, 580, None)]


@pytest.fixture(scope="module")
def split_gaz():
    rows = [Entry("district", "Jaipur", 8, 102, 26.9, 75.8, 40), Entry("district", "Dudu", 8, 769, 26.6, 75.3, 30),
            Entry("alias", "Jeypore", 8, 102, 26.9, 75.8, 40), Entry("village", "Sambhar", 8, 102, 26.9, 75.2, 3),
            Entry("district", "Hyderabad", 36, 507, 17.4, 78.5, 15),
            Entry("district", "Ranga Reddy", 36, 518, 17.2, 78.2, 40),
            Entry("district", "Medchal Malkajgiri", 36, 700, 17.6, 78.5, 25),
            Entry("district", "Coimbatore", 33, 560, 11.0, 76.9, 40), Entry("district", "Tiruppur", 33, 580, 11.1, 77.3, 40),
            Entry("district", "Idukki", 32, 556, 9.9, 77.0, 30)]
    return Gazetteer(rows, splits=SPLITS)


def test_parent_district_name_gives_parent_and_children(split_gaz):
    r = match(rec(locality="Jaipur"), split_gaz)
    assert r.dist_lgd == 102 and r.districts == [102, 769]


def test_alias_of_parent_gives_the_set_too(split_gaz):
    assert match(rec(locality="Jeypore"), split_gaz).districts == [102, 769]


def test_record_made_after_the_split_keeps_the_parent_only(split_gaz):
    assert match(rec(locality="Jaipur", year=2024), split_gaz).districts == [102]
    assert match(rec(locality="Jaipur", year=2023), split_gaz).districts == [102, 769]


def test_splits_follow_children_of_children_made_after_the_record(split_gaz):
    assert match(rec(locality="Hyderabad"), split_gaz).districts == [507, 518, 700]
    assert match(rec(locality="Hyderabad", year="1970"), split_gaz).districts == [507, 518, 700]
    assert match(rec(locality="Hyderabad", year=1990), split_gaz).districts == [507]


def test_split_with_unknown_year_always_applies(split_gaz):
    assert match(rec(county="Coimbatore", year=2020), split_gaz).districts == [560, 580]


def test_village_in_parent_keeps_one_district(split_gaz):
    # A village names a place inside today's district: no set.
    assert match(rec(locality="Sambhar"), split_gaz).districts == [102]


def test_no_split_gives_one_district_and_no_answer_gives_none(split_gaz):
    assert match(rec(locality="Idukki"), split_gaz).districts == [556]
    assert match(rec(locality="no locality data"), split_gaz).districts == []


def test_set_radius_covers_the_children(split_gaz):
    r = match(rec(locality="Jaipur"), split_gaz)
    assert r.radius_km >= haversine_km(26.9, 75.8, 26.6, 75.3) + 30
    assert (r.lat, r.lon) == (26.9, 75.8)


def test_split_cycle_does_not_loop():
    g = Gazetteer([Entry("district", "Mehrauli", 7, 83, 28.5, 77.2, 10), Entry("district", "Saket", 7, 670, 28.55, 77.27, 8)],
                  splits=[(83, 670, 2012), (670, 83, None)])
    assert match(rec(locality="Mehrauli"), g).districts == [83, 670]


def test_load_splits(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("parent,parent_lgd,parent_state_lgd,child,child_lgd,child_state_lgd,year,source\n"
                 "Jaipur,102,8,Dudu,769,8,2023,https://example.org\nCoimbatore,560,33,Tiruppur,580,33,,https://x\n")
    assert load_splits(f) == [(102, 769, 2023), (560, 580, None)]


def test_load_splits_old_district_without_lgd_code(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("parent,parent_lgd,parent_state_lgd,child,child_lgd,child_state_lgd,year,source\n"
                 "Khasi Hills,,17,East Khasi Hills,272,17,1976,https://x\n")
    assert load_splits(f) == [(("Khasi Hills", 17), 272, 1976)]


# An old district that LGD no longer has: its name gives all its successors.
OLD = [(("Khasi Hills", 17), 272, 1976), (("Khasi Hills", 17), 279, 1976), (272, 274, 1992)]


@pytest.fixture(scope="module")
def old_gaz():
    rows = [Entry("district", "East Khasi Hills", 17, 272, 25.5, 91.9, 30),
            Entry("district", "West Khasi Hills", 17, 279, 25.5, 91.3, 35),
            Entry("district", "Ri Bhoi", 17, 274, 25.8, 92.0, 30), Entry("alias", "Shillong", 17, 272, 25.57, 91.88, 30)]
    return Gazetteer(rows, splits=OLD)


def test_old_district_name_gives_its_successors(old_gaz):
    r = match(rec(locality="Khasi Hills"), old_gaz)
    assert r.dist_lgd == 272 and r.districts == [272, 279, 274] and r.state_lgd == 17
    assert match(rec(locality="Khasi Hills", year=2000), old_gaz).districts == [272, 279]


def test_old_district_name_with_a_present_place_gives_that_place(old_gaz):
    assert match(rec(locality="Shillong", county="Khasi Hills", year=2000), old_gaz).districts == [272]
