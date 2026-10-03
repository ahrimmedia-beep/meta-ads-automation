import pytest

from meta_ads.cli import build_parser, main
from meta_ads.commands import cmd_create_campaign, cmd_status
from meta_ads.config import load_env
from meta_ads.graph import API
from tests.fakes import TOKEN, FakeHTTP, HTTPFailure


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(f'# test credentials\n\nMETA_ACCESS_TOKEN="{TOKEN}"\nMETA_AD_ACCOUNT_ID=act_1\n')
    return str(path)


def test_load_env_skips_comments_and_strips_quotes(env_file):
    assert load_env(env_file) == {"META_ACCESS_TOKEN": TOKEN, "META_AD_ACCOUNT_ID": "act_1"}


def test_load_env_names_the_missing_keys(tmp_path):
    path = tmp_path / ".env"
    path.write_text("META_ACCESS_TOKEN=x\nMETA_AD_ACCOUNT_ID=\n")
    with pytest.raises(SystemExit) as e:
        load_env(str(path))
    assert str(e.value) == ".env: missing META_AD_ACCOUNT_ID"


def test_create_campaign_defaults():
    a = build_parser().parse_args(["create-campaign", "--name", "Test"])
    assert a.fn is cmd_create_campaign
    assert a.objective == "OUTCOME_TRAFFIC"
    assert a.dry_run is False
    assert a.special is None


@pytest.mark.parametrize("argv", [
    ["create-campaign"],
    ["create-campaign", "--name", "Test", "--objective", "OUTCOME_UNKNOWN"],
    ["status", "RUNNING", "11"],
    ["status", "ACTIVE"],
    ["budget", "55"],
])
def test_invalid_arguments_are_rejected(argv):
    with pytest.raises(SystemExit) as e:
        build_parser().parse_args(argv)
    assert e.value.code == 2


def test_status_takes_many_ids():
    a = build_parser().parse_args(["status", "ACTIVE", "11", "12", "--confirm"])
    assert (a.fn, a.status, a.ids, a.confirm) == (cmd_status, "ACTIVE", ["11", "12"], True)


def test_dry_run_from_the_command_line(env_file, capsys):
    http = FakeHTTP({"success": True})
    main(["--env", env_file, "create-campaign", "--name", "Test", "--dry-run"], opener=http)
    sent = http.requests[0]
    assert sent.url == f"{API}/act_1/campaigns"
    assert sent.form["status"] == "PAUSED"
    assert sent.form["execution_options"] == '["validate_only"]'
    assert sent.form["access_token"] == TOKEN
    assert TOKEN not in capsys.readouterr().out


def test_activation_is_refused_before_any_request(env_file):
    http = FakeHTTP()
    with pytest.raises(SystemExit):
        main(["--env", env_file, "status", "ACTIVE", "11"], opener=http)
    assert http.requests == []


def test_meta_errors_end_the_command_with_one_line(env_file):
    http = FakeHTTP(HTTPFailure(400, {"error": {"message": "Invalid OAuth access token.", "code": 190}}))
    with pytest.raises(SystemExit) as e:
        main(["--env", env_file, "status", "PAUSED", "11"], opener=http)
    assert str(e.value) == "❌ Meta: Invalid OAuth access token. (code 190, subcode None)"
