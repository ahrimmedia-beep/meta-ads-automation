import json
import urllib.error

import pytest

from meta_ads.graph import API, GraphClient, MetaError, multipart
from tests.fakes import TOKEN, FakeHTTP, HTTPFailure


def client(*responses):
    http = FakeHTTP(*responses)
    return GraphClient(TOKEN, opener=http), http


def test_get_puts_token_and_english_locale_in_the_query():
    api, http = client({"id": "act_1", "name": "Test account"})
    assert api.call("GET", "act_1", {"fields": "name"}) == {"id": "act_1", "name": "Test account"}
    sent = http.requests[0]
    assert sent.method == "GET"
    assert sent.url == f"{API}/act_1"
    assert sent.query == {"fields": "name", "access_token": TOKEN, "locale": "en_US"}
    assert sent.timeout == 600


def test_get_keeps_a_locale_set_by_the_caller():
    api, http = client({})
    api.call("GET", "act_1", {"locale": "de_DE"})
    assert http.requests[0].query["locale"] == "de_DE"


def test_post_sends_params_in_the_body_and_strips_the_leading_slash():
    api, http = client({"id": "7"})
    api.call("POST", "/act_1/campaigns", {"name": "Test"})
    sent = http.requests[0]
    assert sent.method == "POST"
    assert sent.url == f"{API}/act_1/campaigns"
    assert sent.query == {}
    assert sent.form == {"name": "Test", "access_token": TOKEN}


def test_dicts_lists_and_bools_are_sent_as_json():
    api, http = client({"id": "7"})
    api.call("POST", "act_1/adsets", {
        "special_ad_categories": [], "is_adset_budget_sharing_enabled": False,
        "targeting": {"geo_locations": {"countries": ["DE"]}}, "daily_budget": 600})
    form = http.requests[0].form
    assert form["special_ad_categories"] == "[]"
    assert form["is_adset_budget_sharing_enabled"] == "false"
    assert json.loads(form["targeting"]) == {"geo_locations": {"countries": ["DE"]}}
    assert form["daily_budget"] == "600"


def test_the_callers_params_are_not_changed():
    api, _ = client({})
    params = {"fields": "name", "filtering": [{"field": "x"}]}
    api.call("GET", "act_1", params)
    assert params == {"fields": "name", "filtering": [{"field": "x"}]}


def test_delete_uses_the_delete_method():
    api, http = client({"success": True})
    api.call("DELETE", "42")
    assert http.requests[0].method == "DELETE"
    assert http.requests[0].url == f"{API}/42"


def test_files_are_sent_as_multipart(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x01video")
    api, http = client({"id": "9"})
    api.call("POST", "act_1/advideos", {"name": "clip"}, files={"source": str(video)})
    req = http.requests[0].req
    assert req.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="name"\r\n\r\nclip\r\n' in req.data
    assert f'name="access_token"\r\n\r\n{TOKEN}\r\n'.encode() in req.data
    assert b'filename="clip.mp4"\r\nContent-Type: video/mp4\r\n\r\n\x00\x01video\r\n' in req.data


def test_multipart_falls_back_to_octet_stream_and_closes_the_body(tmp_path):
    blob = tmp_path / "data.unknownext"
    blob.write_bytes(b"x")
    body, ctype = multipart({}, {"file": str(blob)})
    boundary = ctype.split("boundary=")[1]
    assert b"Content-Type: application/octet-stream" in body
    assert body.endswith(f"--{boundary}--\r\n".encode())


def test_meta_error_becomes_one_readable_line():
    api, _ = client(HTTPFailure(400, {"error": {
        "message": "Invalid parameter", "error_user_title": "Budget too low",
        "error_user_msg": "The daily budget must be at least $1.00", "code": 100, "error_subcode": 1885272}}))
    with pytest.raises(MetaError) as e:
        api.call("POST", "act_1/adsets", {"daily_budget": 50})
    assert str(e.value) == "Budget too low: The daily budget must be at least $1.00 (code 100, subcode 1885272)"


def test_meta_error_without_user_text_uses_the_technical_message():
    api, _ = client(HTTPFailure(400, {"error": {"message": "(#100) Invalid parameter", "code": 100}}))
    with pytest.raises(MetaError, match=r"^\(#100\) Invalid parameter \(code 100, subcode None\)$"):
        api.call("GET", "act_1")


def test_error_body_that_is_not_json_gives_the_http_code():
    api, _ = client(HTTPFailure(502, b"<html>Bad Gateway</html>"))
    with pytest.raises(MetaError, match=r"^HTTP 502$"):
        api.call("GET", "act_1")


def test_a_token_quoted_back_by_meta_is_masked():
    api, _ = client(HTTPFailure(400, {"error": {"message": f"Malformed access token {TOKEN}", "code": 190}}))
    with pytest.raises(MetaError) as e:
        api.call("GET", "act_1")
    assert TOKEN not in str(e.value)
    assert str(e.value) == "Malformed access token *** (code 190, subcode None)"


def test_network_errors_are_not_hidden():
    api, _ = client(urllib.error.URLError("connection refused"))
    with pytest.raises(urllib.error.URLError):
        api.call("GET", "act_1")


def test_get_all_follows_paging_next():
    next_url = f"{API}/act_1/campaigns?after=abc&access_token={TOKEN}"
    api, http = client(
        {"data": [{"id": "1"}, {"id": "2"}], "paging": {"next": next_url}},
        {"data": [{"id": "3"}], "paging": {}},
    )
    assert api.get_all("act_1/campaigns", {"fields": "name"}) == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    assert len(http.requests) == 2
    assert http.requests[1].req.full_url == next_url
