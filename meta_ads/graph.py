"""Small Graph API client on the standard library.

The HTTP call is injected (``opener``), so the client can be tested without a network.
The access token is added to every request here and never printed.
"""
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://graph.facebook.com/v26.0"


class MetaError(Exception):
    """An error returned by the Graph API, as one readable line."""


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    for key, path in files.items():
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; '
                f'filename="{os.path.basename(path)}"\r\nContent-Type: {mime}\r\n\r\n')
        parts.append(head.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class GraphClient:
    def __init__(self, token, api=API, opener=urllib.request.urlopen, timeout=600):
        self.token = token
        self.api = api
        self.opener = opener
        self.timeout = timeout

    def request(self, req):
        try:
            with self.opener(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = json.load(e).get("error", {})
            except Exception:
                raise MetaError(f"HTTP {e.code}") from None
            msg = err.get("error_user_msg") or err.get("message", "unknown error")
            title = err.get("error_user_title")
            text = f"{title + ': ' if title else ''}{msg} (code {err.get('code')}, subcode {err.get('error_subcode')})"
            raise MetaError(text.replace(self.token, "***")) from None  # Meta can quote a bad token back

    def call(self, method, path, params=None, files=None):
        params = dict(params or {})
        params["access_token"] = self.token
        for key, value in list(params.items()):
            if isinstance(value, (dict, list, bool)):
                params[key] = json.dumps(value)
        url = f"{self.api}/{path.lstrip('/')}"
        if method == "GET":
            params.setdefault("locale", "en_US")  # names and statuses in English, whatever the account language
            return self.request(urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}"))
        if files:
            body, ctype = multipart(params, files)
            return self.request(urllib.request.Request(url, data=body, method=method,
                                                       headers={"Content-Type": ctype}))
        return self.request(urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                                   method=method))

    def get_all(self, path, params):
        """GET every page of a list: Meta returns a ready ``paging.next`` URL for the next page."""
        rows, res = [], self.call("GET", path, params)
        while True:
            rows += res.get("data", [])
            nxt = res.get("paging", {}).get("next")
            if not nxt:
                return rows
            res = self.request(urllib.request.Request(nxt))
