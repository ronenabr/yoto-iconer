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
