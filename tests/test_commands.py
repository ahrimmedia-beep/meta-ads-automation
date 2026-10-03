import re
from argparse import Namespace

import pytest

from meta_ads.commands import cents, cmd_budget, cmd_create_campaign, cmd_delete, cmd_status, dry, usd
from meta_ads.graph import API, GraphClient
from tests.fakes import TOKEN, FakeHTTP


def client(*responses):
    http = FakeHTTP(*responses)
    return GraphClient(TOKEN, opener=http), http


def campaign_args(**overrides):
    values = {"account": "act_1", "name": "Test campaign", "objective": "OUTCOME_LEADS",
              "special": None, "countries": None, "dry_run": False}
    values.update(overrides)
    return Namespace(**values)


def test_money_is_sent_in_cents_and_shown_in_dollars():
    assert cents("6") == 600
    assert cents("6.5") == 650
    assert cents(0.01) == 1
    assert usd(650) == "$6.50"
    assert usd("1999") == "$19.99"
    assert usd(0) == "$0.00"
    assert usd(None) == ""
    assert usd("") == ""


def test_dry_marks_the_request_validate_only():
    assert dry(Namespace(dry_run=True), {"name": "x"}) == {"name": "x", "execution_options": ["validate_only"]}
    assert dry(Namespace(dry_run=False), {"name": "x"}) == {"name": "x"}
    assert dry(Namespace(), {"name": "x"}) == {"name": "x"}


def test_campaign_is_always_created_paused(capsys):
    api, http = client({"id": "777"})
    assert cmd_create_campaign(api, campaign_args()) == "777"
    sent = http.requests[0]
    assert (sent.method, sent.url) == ("POST", f"{API}/act_1/campaigns")
    assert sent.form["status"] == "PAUSED"
    assert sent.form["objective"] == "OUTCOME_LEADS"
    assert sent.form["special_ad_categories"] == "[]"
    assert "execution_options" not in sent.form
    assert "campaign: 777 (paused)" in capsys.readouterr().out


def test_dry_run_asks_meta_to_validate_and_create_nothing(capsys):
    api, http = client({"success": True})
    assert cmd_create_campaign(api, campaign_args(dry_run=True)) is None
    form = http.requests[0].form
    assert form["execution_options"] == '["validate_only"]'
    assert form["status"] == "PAUSED"
    assert "campaign NOT created (--dry-run)" in capsys.readouterr().out


def test_special_category_needs_countries_before_any_request():
    api, http = client()
    with pytest.raises(SystemExit, match="--countries is required with --special"):
        cmd_create_campaign(api, campaign_args(special="HOUSING"))
    assert http.requests == []


def test_special_category_is_sent_with_its_countries():
    api, http = client({"id": "778"})
    cmd_create_campaign(api, campaign_args(special="HOUSING", countries="DE,FR"))
    form = http.requests[0].form
    assert form["special_ad_categories"] == '["HOUSING"]'
    assert form["special_ad_category_country"] == '["DE", "FR"]'


def test_turning_ads_on_without_confirm_sends_nothing():
    api, http = client()
    with pytest.raises(SystemExit, match="Run again with --confirm only after the account owner says yes"):
        cmd_status(api, Namespace(status="ACTIVE", ids=["11", "12"], confirm=False))
    assert http.requests == []


def test_turning_ads_on_with_confirm_updates_every_id(capsys):
    api, http = client({"success": True}, {"success": True})
    cmd_status(api, Namespace(status="ACTIVE", ids=["11", "12"], confirm=True))
    assert [(s.method, s.url, s.form["status"]) for s in http.requests] == [
        ("POST", f"{API}/11", "ACTIVE"), ("POST", f"{API}/12", "ACTIVE")]
    assert "12 → ACTIVE" in capsys.readouterr().out


def test_pausing_needs_no_confirm():
    api, http = client({"success": True})
    cmd_status(api, Namespace(status="PAUSED", ids=["11"], confirm=False))
    assert http.requests[0].form["status"] == "PAUSED"


def test_delete_without_confirm_sends_nothing():
    api, http = client()
    with pytest.raises(SystemExit, match="cannot be undone"):
        cmd_delete(api, Namespace(ids=["11"], confirm=False))
    assert http.requests == []


def test_delete_with_confirm():
    api, http = client({"success": True}, {"success": True})
    cmd_delete(api, Namespace(ids=["11", "12"], confirm=True))
    assert [(s.method, s.url) for s in http.requests] == [("DELETE", f"{API}/11"), ("DELETE", f"{API}/12")]


def test_small_budget_change_is_applied_and_read_back(capsys):
    api, http = client({"name": "Set A", "daily_budget": "1000"}, {"success": True}, {"daily_budget": "1200"})
    cmd_budget(api, Namespace(id="55", usd="12", force=False))
    assert [s.method for s in http.requests] == ["GET", "POST", "GET"]
    assert http.requests[1].form["daily_budget"] == "1200"
    out = capsys.readouterr().out
    assert "Set A: $10.00 → $12.00 (+20%)" in out
    assert "applied and verified: $12.00" in out


@pytest.mark.parametrize("new_usd", ["12.50", "7.50"])
def test_budget_change_over_20_percent_needs_force(new_usd):
    api, http = client({"name": "Set A", "daily_budget": "1000"})
    with pytest.raises(SystemExit, match="--force"):
        cmd_budget(api, Namespace(id="55", usd=new_usd, force=False))
    assert [s.method for s in http.requests] == ["GET"]


def test_force_allows_a_big_change():
    api, http = client({"daily_budget": "1000"}, {"success": True}, {"daily_budget": "5000"})
    cmd_budget(api, Namespace(id="55", usd="50", force=True))
    assert http.requests[1].form["daily_budget"] == "5000"


def test_first_budget_has_no_change_limit(capsys):
    api, _ = client({"name": "New set"}, {"success": True}, {"daily_budget": "5000"})
    cmd_budget(api, Namespace(id="55", usd="50", force=False))
    assert "New set: $0.00 → $50.00" in capsys.readouterr().out


def test_budget_that_did_not_stick_is_reported():
    api, _ = client({"daily_budget": "1000"}, {"success": True}, {"daily_budget": "1000"})
    with pytest.raises(SystemExit, match=re.escape("Meta shows $10.00 instead of $11.00")):
        cmd_budget(api, Namespace(id="55", usd="11", force=False))
