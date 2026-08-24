from yoto_iconer import search


def test_tokenize_drops_stopwords_and_noise():
    assert search.tokenize("The Wheels on the Bus") == ["wheels", "bus"]


def test_tokenize_strips_featuring_brackets():
    assert search.tokenize("Dinosaur Stomp (feat. Barney) [Official Video]") == [
        "dinosaur",
        "stomp",
    ]


def test_tokenize_strips_leading_track_number():
    assert search.tokenize("03 - Rocket Ship") == ["rocket", "ship"]


def test_tokenize_expands_ampersand():
    assert search.tokenize("Bread & Butter") == ["bread", "butter"]


def test_query_for_falls_back_when_all_stopwords():
    assert search.query_for("The And Of") != ""


def test_search_ranks_the_obvious_match_first(seeded):
    hits = search.search(seeded, "The Wheels on the Bus", limit=3)
    assert hits[0]["key"] == "official:MEDIA_BUS"


def test_search_finds_community_icons(seeded):
    hits = search.search(seeded, "Big Red Dinosaur Stomp", limit=3)
    assert hits[0]["key"] == "community:1346"


def test_search_can_restrict_source(seeded):
    hits = search.search(seeded, "dinosaur", limit=5, sources=("official",))
    assert all(h["source"] == "official" for h in hits)


def test_search_returns_nothing_for_unknown_subject(seeded):
    assert search.search(seeded, "xyzzy", limit=5) == []


def test_live_terms_demotes_filler_words():
    assert search.live_terms("Twinkle Twinkle Little Star") == ["twinkle", "star"]


def test_live_terms_prefers_the_most_specific_token():
    assert search.live_terms("Dinosaur Stomp", count=1) == ["dinosaur"]


def test_has_lexical_hit_counts_tags_too():
    cands = [{"title": "Magic School Bus", "tags": "magic school bus dinosaurs"}]
    assert search.has_lexical_hit(cands, ["dinosaur", "stomp"]) is True
    assert search.has_lexical_hit(cands, ["giraffe"]) is False


def test_has_lexical_hit_matches_on_tags(seeded):
    cands = [{"title": "Anything", "tags": "rex dinosaur"}]
    assert search.has_lexical_hit(cands, ["dinosaur"]) is True


def test_stem_handles_plurals():
    assert search.stem("stars") == "star"
    assert search.stem("bunnies") == "bunny"
    assert search.stem("boxes") == "box"
    assert search.stem("bus") == "bus"
    assert search.stem("dress") == "dress"


def test_title_hit_ignores_a_tag_only_match():
    cand = {"title": "Magic School Bus", "tags": "magic school bus dinosaurs"}
    assert search.title_hit(cand, ["dinosaur", "stomp"]) is False


def test_title_hit_matches_across_plurals():
    assert search.title_hit({"title": "stars", "tags": ""}, ["star"]) is True


def test_plural_icon_name_still_ranks_for_a_singular_query(conn):
    from yoto_iconer import catalog

    catalog.upsert(conn, [
        {"key": "community:5", "source": "community", "ref": "5", "title": "Stars",
         "tags": "stars", "category": "", "author": "", "downloads": 10,
         "media_id": None, "img_url": None},
        {"key": "community:6", "source": "community", "ref": "6", "title": "Truck",
         "tags": "truck", "category": "", "author": "", "downloads": 900,
         "media_id": None, "img_url": None},
    ])
    assert search.search(conn, "Twinkle Twinkle Little Star", limit=3)[0]["key"] == "community:5"


def test_more_specific_title_beats_a_generic_one(seeded):
    # "Twinkle star" matches two words of the query; a bare "Stars" matches one.
    assert search.search(seeded, "Twinkle Twinkle Little Star", limit=3)[0]["key"] == "community:99"


def test_file_extension_is_not_a_search_term():
    assert search.tokenize("clock.mp3") == ["clock"]
    assert "mp3" not in search.tokenize("Row Row Row Your Boat.mp3")


def test_extension_stripping_leaves_nothing_for_a_hebrew_title():
    assert search.tokenize("אדון שוקו.mp3") == []


def test_is_latin_detects_english():
    assert search.is_latin("The Wheels on the Bus") is True


def test_is_latin_rejects_hebrew():
    assert search.is_latin("אדון שוקו.mp3") is False


def test_is_latin_rejects_a_mostly_hebrew_title_with_a_latin_artist():
    assert search.is_latin("אוהב את המשפחה שלי - בתאל צברי Batel Tzabari") is False


def test_is_latin_tolerates_accents():
    assert search.is_latin("Frère Jacques") is True
