import json

import pytest

from yoto_iconer import api, apply, catalog, yotoicons


def test_resolve_key_accepts_yoto_ref():
    assert apply.resolve_key("yoto:#ABC", None) == "yoto:#ABC"


def test_resolve_key_accepts_yotoicons_ref():
    assert apply.resolve_key("yotoicons:1346", None) == "community:1346"


def test_resolve_key_accepts_catalog_key():
    assert apply.resolve_key("official:MEDIA_BUS", None) == "official:MEDIA_BUS"


def test_resolve_key_resolves_short_id_via_plan():
    plan = {"keys": {"i3": "community:1346"}}
    assert apply.resolve_key("i3", plan) == "community:1346"


def test_resolve_key_rejects_unknown_short_id():
    with pytest.raises(apply.ApplyError):
        apply.resolve_key("i9", {"keys": {}})


def test_media_id_for_official_needs_no_upload(seeded):
    media_id, uploaded = apply.media_id_for(seeded, "official:MEDIA_BUS", "tok")
    assert media_id == "MEDIA_BUS" and uploaded is False


def test_media_id_for_community_uploads_once(seeded, monkeypatch):
    calls = []
    monkeypatch.setattr(yotoicons, "download_png", lambda ref: b"PNGDATA")
    monkeypatch.setattr(
        api, "upload_icon", lambda tok, data, name: calls.append(name) or "NEWMEDIA"
    )
    first, uploaded = apply.media_id_for(seeded, "community:1346", "tok")
    second, again = apply.media_id_for(seeded, "community:1346", "tok")
    assert (first, uploaded) == ("NEWMEDIA", True)
    assert (second, again) == ("NEWMEDIA", False)
    assert len(calls) == 1


def test_identical_png_is_not_uploaded_twice(seeded, monkeypatch):
    calls = []
    monkeypatch.setattr(yotoicons, "download_png", lambda ref: b"SAMEBYTES")
    monkeypatch.setattr(
        api, "upload_icon", lambda tok, data, name: calls.append(name) or "M1"
    )
    apply.media_id_for(seeded, "community:1346", "tok")
    apply.media_id_for(seeded, "community:99", "tok")
    assert len(calls) == 1


def test_media_id_for_dry_run_does_not_upload(seeded, monkeypatch):
    monkeypatch.setattr(yotoicons, "download_png", lambda ref: pytest.fail("downloaded"))
    media_id, uploaded = apply.media_id_for(seeded, "community:1346", "tok", dry_run=True)
    assert uploaded is True and media_id.startswith("<upload")


def test_patch_card_sets_track_icon(card):
    apply.patch_card(card, {"02.02": "NEW"})
    track = card["content"]["chapters"][1]["tracks"][1]
    assert track["display"]["icon16x16"] == "yoto:#NEW"


def test_patch_card_collapsed_chapter_stamps_its_only_track(card):
    changes = apply.patch_card(card, {"01": "NEW"})
    chapter = card["content"]["chapters"][0]
    assert chapter["display"]["icon16x16"] == "yoto:#NEW"
    assert chapter["tracks"][0]["display"]["icon16x16"] == "yoto:#NEW"
    assert {c["level"] for c in changes} == {"chapter", "track"}


def test_patch_card_multitrack_chapter_leaves_tracks_alone(card):
    apply.patch_card(card, {"02": "NEW"})
    chapter = card["content"]["chapters"][1]
    assert chapter["display"]["icon16x16"] == "yoto:#NEW"
    assert chapter["tracks"][0].get("display") is None


def test_patch_card_preserves_unknown_fields(card):
    before = json.dumps(card["metadata"])
    apply.patch_card(card, {"02.01": "NEW"})
    assert json.dumps(card["metadata"]) == before
    assert card["content"]["chapters"][0]["customField"] == "must survive"
    track = card["content"]["chapters"][1]["tracks"][0]
    assert track["trackUrl"] == "yoto:#d" and track["duration"] == 90


def test_patch_card_reports_old_values(card):
    changes = apply.patch_card(card, {"02.02": "NEW"})
    assert changes[0]["old"] == "yoto:#MEDIA_MUSIC"


def test_patch_card_rejects_unknown_slot(card):
    with pytest.raises(apply.ApplyError, match="09.09"):
        apply.patch_card(card, {"09.09": "NEW"})


def test_run_dry_run_writes_nothing(seeded, card, monkeypatch):
    monkeypatch.setattr(api, "update_card", lambda tok, c: pytest.fail("posted"))
    decisions = {"cardId": "CARD1", "assignments": [{"t": "02.01", "icon": "official:MEDIA_BUS"}]}
    result = apply.run(seeded, "tok", decisions, None, dry_run=True, card=card)
    assert result["dryRun"] and result["changes"] and "backup" not in result


def test_run_posts_the_patched_card(seeded, card, monkeypatch):
    posted = {}
    monkeypatch.setattr(api, "update_card", lambda tok, c: posted.update(c))
    decisions = {"cardId": "CARD1", "assignments": [{"t": "02.01", "icon": "official:MEDIA_BUS"}]}
    result = apply.run(seeded, "tok", decisions, None, card=card)
    assert result["applied"] is True
    track = posted["content"]["chapters"][1]["tracks"][0]
    assert track["display"]["icon16x16"] == "yoto:#MEDIA_BUS"


def test_run_backs_up_the_original_before_writing(seeded, card, monkeypatch):
    monkeypatch.setattr(api, "update_card", lambda tok, c: None)
    decisions = {"cardId": "CARD1", "assignments": [{"t": "02.01", "icon": "official:MEDIA_BUS"}]}
    result = apply.run(seeded, "tok", decisions, None, card=card)
    saved = json.loads(open(result["backup"]).read())
    assert saved["content"]["chapters"][1]["tracks"][0].get("display") is None


def test_run_survives_one_bad_icon(seeded, card, monkeypatch):
    monkeypatch.setattr(api, "update_card", lambda tok, c: None)
    decisions = {
        "cardId": "CARD1",
        "assignments": [
            {"t": "02.01", "icon": "official:MEDIA_BUS"},
            {"t": "02.02", "icon": "i404"},
        ],
    }
    result = apply.run(seeded, "tok", decisions, None, card=card)
    assert len(result["problems"]) == 1
    assert any(c["slot"] == "02.01" for c in result["changes"])


def test_run_needs_a_card_id(seeded, card):
    with pytest.raises(apply.ApplyError):
        apply.run(seeded, "tok", {"assignments": []}, None, card=card)
