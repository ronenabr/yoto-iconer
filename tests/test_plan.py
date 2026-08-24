from yoto_iconer import plan


def test_single_track_chapter_collapses_to_one_slot(card):
    slots = list(plan.iter_slots(card))
    ids = [s[0] for s in slots]
    assert "01" in ids and "01.01" not in ids


def test_collapsed_slot_is_marked_as_both(card):
    both = {s[0]: s[3] for s in plan.iter_slots(card)}
    assert both["01"] is True
    assert both["02"] is False


def test_multi_track_chapter_yields_chapter_and_tracks(card):
    ids = [s[0] for s in plan.iter_slots(card)]
    assert ids == ["01", "02", "02.01", "02.02"]


def test_only_missing_skips_slots_that_have_icons(card):
    ids = [s[0] for s in plan.iter_slots(card, only_missing=True)]
    assert ids == ["01", "02.01"]


def test_build_produces_short_ids_and_a_shared_icon_pool(seeded, card):
    built = plan.build(seeded, card, limit=4, live=False)
    assert built["cardId"] == "CARD1"
    assert all(sid.startswith("i") for sid in built["icons"])
    # every candidate reference resolves inside the pool
    for row in built["tracks"]:
        for sid in row["c"]:
            assert sid in built["icons"]


def test_icon_pool_is_deduplicated(seeded, card):
    built = plan.build(seeded, card, limit=4, live=False)
    refs = [sid for row in built["tracks"] for sid in row["c"]]
    assert len(built["icons"]) < len(refs)


def test_build_picks_sensible_candidates(seeded, card):
    built = plan.build(seeded, card, limit=4, live=False)
    rows = {r["t"]: r for r in built["tracks"]}
    top = rows["02.01"]["c"][0]
    assert "School bus" in built["icons"][top]


def test_keys_map_resolves_short_ids_to_catalog_keys(seeded, card):
    built = plan.build(seeded, card, limit=4, live=False)
    for sid, key in built["keys"].items():
        assert sid in built["icons"]
        assert key.split(":")[0] in ("official", "community", "user")


def test_current_icon_is_named_when_known(seeded, card):
    built = plan.build(seeded, card, limit=4, live=False)
    rows = {r["t"]: r for r in built["tracks"]}
    assert rows["02.02"]["now"] == "Music notes"
    assert "now" not in rows["01"]


def test_render_text_lists_every_slot(seeded, card):
    built = plan.build(seeded, card, limit=4, live=False)
    text = plan.render_text(built)
    for row in built["tracks"]:
        assert row["t"] in text


def _hebrew_card():
    return {
        "cardId": "HEB",
        "title": "Songs",
        "content": {"chapters": [
            {"key": "aaa", "title": "אדון שוקו.mp3", "display": {"icon16x16": None},
             "tracks": [{"key": "01", "title": "אדון שוקו.mp3", "trackUrl": "yoto:#x",
                         "duration": 60, "format": "mp3", "type": "audio",
                         "overlayLabel": "1"}]},
            {"key": "bbb", "title": "clock.mp3", "display": {"icon16x16": None},
             "tracks": [{"key": "01", "title": "clock.mp3", "trackUrl": "yoto:#y",
                         "duration": 60, "format": "mp3", "type": "audio",
                         "overlayLabel": "2"}]},
        ]},
    }


def test_non_latin_title_is_flagged_instead_of_searched(seeded):
    built = plan.build(seeded, _hebrew_card(), limit=4, live=False)
    rows = {r["t"]: r for r in built["tracks"]}
    assert rows["aaa"]["needs"] == "q"
    assert rows["aaa"]["c"] == []


def test_latin_title_is_searched_normally(seeded):
    built = plan.build(seeded, _hebrew_card(), limit=4, live=False)
    rows = {r["t"]: r for r in built["tracks"]}
    assert "needs" not in rows["bbb"]


def test_supplied_query_unlocks_a_non_latin_title(seeded):
    built = plan.build(
        seeded, _hebrew_card(), limit=4, live=False, queries={"aaa": "school bus"}
    )
    rows = {r["t"]: r for r in built["tracks"]}
    assert "needs" not in rows["aaa"]
    assert rows["aaa"]["q"] == "school bus"
    assert built["icons"][rows["aaa"]["c"][0]].endswith("School bus|bus school vehicle")


def test_supplied_query_overrides_a_latin_title_too(seeded):
    built = plan.build(
        seeded, _hebrew_card(), limit=4, live=False, queries={"bbb": "dinosaur"}
    )
    rows = {r["t"]: r for r in built["tracks"]}
    assert "Dinosaur" in built["icons"][rows["bbb"]["c"][0]]


def test_blank_supplied_query_still_flags_the_slot(seeded):
    built = plan.build(seeded, _hebrew_card(), limit=4, live=False, queries={"aaa": "  "})
    rows = {r["t"]: r for r in built["tracks"]}
    assert rows["aaa"]["needs"] == "q"


def test_render_text_calls_out_slots_needing_a_query(seeded):
    built = plan.build(seeded, _hebrew_card(), limit=4, live=False)
    assert "needs an English query" in plan.render_text(built)
