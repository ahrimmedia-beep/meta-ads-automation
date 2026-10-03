import pytest

from meta_ads.reels import API, ReelsPublisher, main
from tests.fakes import TOKEN, FakeHTTP, HTTPFailure

COVER = {"data": [{"url": "https://cdn.example/cover.jpg"}]}


def publisher(*responses):
    http = FakeHTTP(*responses)
    pauses = []
    ig = ReelsPublisher(TOKEN, "ig_7", "act_1", opener=http, sleep=pauses.append)
    return ig, http, pauses


def test_prepare_creates_a_container_uploads_and_waits(tmp_path, capsys):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"0123456789")
    ig, http, pauses = publisher(
        COVER,
        {"id": "c1", "uri": "https://rupload.example/ig-api-upload/c1"},
        {"success": True},
        {"status_code": "IN_PROGRESS"},
        {"status_code": "IN_PROGRESS"},
        {"status_code": "FINISHED"},
    )
    assert ig.prepare(str(video), "hash1", "Caption") == "c1"

    cover, create, upload, *polls = http.requests
    assert (cover.method, cover.url) == ("GET", f"{API}/act_1/adimages")
    assert cover.query["hashes"] == '["hash1"]'
    assert (create.method, create.url) == ("POST", f"{API}/ig_7/media")
    assert create.form == {"media_type": "REELS", "upload_type": "resumable", "caption": "Caption",
                           "cover_url": "https://cdn.example/cover.jpg", "share_to_feed": "true",
                           "access_token": TOKEN}
    assert upload.req.full_url == "https://rupload.example/ig-api-upload/c1"
    assert upload.req.data == b"0123456789"
    assert upload.req.get_header("Authorization") == f"OAuth {TOKEN}"
    assert upload.req.get_header("File_size") == "10"
    assert upload.req.get_header("Offset") == "0"
    assert upload.timeout == 900
    assert [p.url for p in polls] == [f"{API}/c1"] * 3
    assert pauses == [10, 10]
    assert "container: c1, status FINISHED, not published" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["ERROR", "EXPIRED"])
def test_polling_stops_on_a_final_state(state):
    ig, http, pauses = publisher({"status_code": "IN_PROGRESS"}, {"status_code": state})
    assert ig.wait_until_done("c1") == state
    assert len(http.requests) == 2
    assert pauses == [10]


def test_polling_gives_up_after_the_attempt_limit():
    ig, http, pauses = publisher(*[{"status_code": "IN_PROGRESS"}] * 3)
    assert ig.wait_until_done("c1", attempts=3, interval=5) == "IN_PROGRESS"
    assert len(http.requests) == 3
    assert pauses == [5, 5, 5]


def test_prepare_from_ad_video_lets_instagram_fetch_the_file():
    ig, http, _ = publisher(
        {"source": "https://video.example/v9.mp4"},
        COVER,
        {"id": "c2"},
        {"status_code": "FINISHED"},
    )
    assert ig.prepare_from_ad_video("v9", "hash1", "Caption") == "c2"
    source, _, create, _ = http.requests
    assert (source.url, source.query["fields"]) == (f"{API}/v9", "source")
    assert create.form["video_url"] == "https://video.example/v9.mp4"
    assert "upload_type" not in create.form


def test_publish_is_a_separate_step(capsys):
    ig, http, _ = publisher(
        {"id": "m1"},
        {"permalink": "https://ig.example/reel/abc/", "timestamp": "2026-01-15T10:00:00+0000"},
    )
    assert ig.publish("c1") == "https://ig.example/reel/abc/"
    publish, media = http.requests
    assert (publish.method, publish.url, publish.form["creation_id"]) == ("POST", f"{API}/ig_7/media_publish", "c1")
    assert (media.url, media.query["fields"]) == (f"{API}/m1", "permalink,timestamp")
    assert "published: https://ig.example/reel/abc/" in capsys.readouterr().out


def test_api_errors_exit_with_the_token_masked():
    ig, _, _ = publisher(HTTPFailure(400, {"error": {"message": f"Invalid token {TOKEN}"}}))
    with pytest.raises(SystemExit) as e:
        ig.status("c1")
    assert str(e.value).startswith("❌ 400: ")
    assert TOKEN not in str(e.value)
    assert "Invalid token ***" in str(e.value)


def test_token_is_masked_before_a_long_error_is_cut():
    ig, _, _ = publisher(HTTPFailure(500, b"x" * 495 + TOKEN.encode() + b"y" * 100))
    with pytest.raises(SystemExit) as e:
        ig.status("c1")
    assert "TEST" not in str(e.value)


def test_upload_errors_exit_with_the_token_masked(tmp_path):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"0")
    ig, _, _ = publisher(HTTPFailure(401, f"bad OAuth {TOKEN}".encode()))
    with pytest.raises(SystemExit) as e:
        ig.upload("https://rupload.example/ig-api-upload/c1", str(video))
    assert str(e.value) == "❌ upload 401: bad OAuth ***"


def test_command_line_reads_the_caption_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"META_ACCESS_TOKEN={TOKEN}\nMETA_INSTAGRAM_ID=ig_7\nMETA_AD_ACCOUNT_ID=act_1\n")
    caption = tmp_path / "caption.txt"
    caption.write_text("  First line\nSecond line\n\n", encoding="utf-8")
    http = FakeHTTP({"source": "https://video.example/v9.mp4"}, COVER, {"id": "c2"}, {"status_code": "FINISHED"})
    main(["--env", str(env), "prepare-url", "v9", "hash1", str(caption)], opener=http, sleep=lambda s: None)
    assert http.requests[2].form["caption"] == "First line\nSecond line"


def test_command_line_needs_the_instagram_id(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"META_ACCESS_TOKEN={TOKEN}\nMETA_AD_ACCOUNT_ID=act_1\n")
    with pytest.raises(SystemExit) as e:
        main(["--env", str(env), "status", "c1"], opener=FakeHTTP())
    assert str(e.value) == ".env: missing META_INSTAGRAM_ID"
