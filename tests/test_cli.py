import json

import pytest

from yoto_iconer import api, catalog, cli


def test_parser_exposes_the_documented_commands():
    parser = cli.build_parser()
    for argv in (["cards"], ["status"], ["search", "dino"], ["plan", "C1"],
                 ["apply", "-d", "d.json"], ["show", "C1"], ["catalog", "sync"]):
        assert parser.parse_args(argv).func is not None


def test_apply_requires_decisions():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["apply", "C1"])


def test_setup_stores_the_client_id(capsys):
    assert cli.main(["setup", "--client-id", "  CID123 "]) == 0
    from yoto_iconer import config
    assert config.client_id() == "CID123"


def test_setup_without_args_prints_the_instructions(capsys):
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "user:content:manage" in out and "127.0.0.1:8787/callback" in out


def test_login_without_a_client_id_fails_with_guidance(capsys):
    assert cli.main(["login"]) == 2
    assert "PUBLIC" in capsys.readouterr().err


def test_search_command_prints_hits(seeded, monkeypatch, capsys):
    monkeypatch.setattr(catalog, "connect", lambda path=None: seeded)
    assert cli.main(["search", "wheels on the bus"]) == 0
    assert "School bus" in capsys.readouterr().out


def test_plan_command_writes_a_file(seeded, card, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(catalog, "connect", lambda path=None: seeded)
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "get_card", lambda tok, cid: card)
    out = tmp_path / "plan.json"
    assert cli.main(["plan", "CARD1", "-o", str(out), "--no-live"]) == 0
    built = json.loads(out.read_text())
    assert built["cardId"] == "CARD1" and built["tracks"]


def test_apply_command_dry_run_reports_changes(seeded, card, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(catalog, "connect", lambda path=None: seeded)
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "get_card", lambda tok, cid: card)
    monkeypatch.setattr(api, "update_card", lambda tok, c: pytest.fail("posted"))
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps(
        {"cardId": "CARD1", "assignments": [{"t": "02.01", "icon": "official:MEDIA_BUS"}]}
    ))
    assert cli.main(["apply", "-d", str(decisions), "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_errors_exit_with_code_two(capsys):
    assert cli.main(["cards"]) == 2
    assert "error:" in capsys.readouterr().err


def _hebrew_card():
    return {
        "cardId": "HEB", "title": "Songs",
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


def test_titles_command_emits_slot_to_title(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "get_card", lambda tok, cid: _hebrew_card())
    assert cli.main(["titles", "HEB"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["titles"] == {"aaa": "אדון שוקו.mp3", "bbb": "clock.mp3"}


def test_titles_needs_query_filters_to_non_latin(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "get_card", lambda tok, cid: _hebrew_card())
    assert cli.main(["titles", "HEB", "--needs-query"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert list(payload["titles"]) == ["aaa"]


def test_titles_output_is_readable_unicode(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "get_card", lambda tok, cid: _hebrew_card())
    out = tmp_path / "t.json"
    assert cli.main(["titles", "HEB", "-o", str(out)]) == 0
    assert "אדון" in out.read_text()


def test_plan_accepts_a_queries_file(seeded, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(catalog, "connect", lambda path=None: seeded)
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "get_card", lambda tok, cid: _hebrew_card())
    qfile = tmp_path / "q.json"
    qfile.write_text(json.dumps({"titles": {"aaa": "school bus"}}, ensure_ascii=False))
    out = tmp_path / "plan.json"
    assert cli.main(["plan", "HEB", "--queries", str(qfile), "-o", str(out), "--no-live"]) == 0
    rows = {r["t"]: r for r in json.loads(out.read_text())["tracks"]}
    assert rows["aaa"]["q"] == "school bus" and rows["aaa"]["c"]


def test_cards_omits_counts_when_the_summary_has_no_chapters(monkeypatch, capsys):
    # /content/mine returns summaries whose `content` holds config, not chapters.
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "list_cards", lambda tok: [
        {"cardId": "A1", "title": "Songs 1", "content": {"config": {}}},
    ])
    assert cli.main(["cards"]) == 0
    out = capsys.readouterr().out
    assert "A1  Songs 1" in out and "0 ch" not in out


def test_cards_shows_counts_when_chapters_are_present(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_token", lambda: "tok")
    monkeypatch.setattr(api, "list_cards", lambda tok: [
        {"cardId": "A1", "title": "S", "content": {"chapters": [
            {"key": "01", "tracks": [{"key": "01"}, {"key": "02"}]}]}},
    ])
    assert cli.main(["cards"]) == 0
    assert "(1 ch / 2 tr)" in capsys.readouterr().out
