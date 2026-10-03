"""A fake HTTP layer: stands in for urllib.request.urlopen, so no test touches the network."""
import io
import json
import urllib.error
import urllib.parse

TOKEN = "TEST_TOKEN"


class HTTPFailure:
    """A queued response that makes the fake raise HTTPError with this status and body."""

    def __init__(self, code, body):
        self.code = code
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()


class Sent:
    """One recorded request, split into the parts the tests check."""

    def __init__(self, req, timeout):
        self.req = req
        self.timeout = timeout
        self.method = req.get_method()
        split = urllib.parse.urlsplit(req.full_url)
        self.url = f"{split.scheme}://{split.netloc}{split.path}"
        self.query = dict(urllib.parse.parse_qsl(split.query))
        is_form = req.data is not None and req.get_header("Content-type") is None
        self.form = dict(urllib.parse.parse_qsl(req.data.decode())) if is_form else {}


class FakeHTTP:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(Sent(req, timeout))
        if not self.responses:
            raise AssertionError(f"unexpected request: {req.get_method()} {req.full_url}")
        res = self.responses.pop(0)
        if isinstance(res, Exception):
            raise res
        if isinstance(res, HTTPFailure):
            raise urllib.error.HTTPError(req.full_url, res.code, "error", {}, io.BytesIO(res.body))
        return io.BytesIO(json.dumps(res).encode())
