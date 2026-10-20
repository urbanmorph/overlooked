"""Tests for the place-name matcher. Run: .venv/bin/python -m pytest experiments/georef -q"""

import pytest
from matcher import Entry, Gazetteer, haversine_km, match, normalise, phrases, sound_key, strip_generic

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
