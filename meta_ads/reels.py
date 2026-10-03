"""Instagram Reel through the Graph API.

`prepare` uploads a video into a media container and does not publish it.
`publish` publishes a prepared container as a separate step, so a person can check it first.

    python -m meta_ads.reels prepare <video.mp4> <cover_image_hash> <caption.txt>
    python -m meta_ads.reels prepare-url <ad_video_id> <cover_image_hash> <caption.txt>
    python -m meta_ads.reels publish <container_id>
    python -m meta_ads.reels status <container_id>

The HTTP call and the pause between status checks are injected, so the flow is tested without a network.
The token is read from .env and masked in error messages.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import load_env

API = "https://graph.facebook.com/v23.0"
FINAL_STATES = ("FINISHED", "ERROR", "EXPIRED")


class ReelsPublisher:
    def __init__(self, token, ig_user_id, ad_account_id, opener=urllib.request.urlopen, sleep=time.sleep,
                 api=API):
        self.token = token
        self.ig_user_id = ig_user_id
        self.ad_account_id = ad_account_id
        self.opener = opener
        self.sleep = sleep
        self.api = api

    def _mask(self, text):
        return text.replace(self.token, "***")

    def req(self, method, url, params=None):
        params = dict(params or {})
        params["access_token"] = self.token
        if method == "GET":
            r = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}")
        else:
            r = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), method=method)
        try:
            with self.opener(r, timeout=600) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            sys.exit(f"❌ {e.code}: {self._mask(e.read().decode())[:500]}")

    def cover_url(self, image_hash):
        """Public URL of an image already uploaded to the ad account, used as the Reel cover."""
        r = self.req("GET", f"{self.api}/{self.ad_account_id}/adimages",
                     {"hashes": json.dumps([image_hash]), "fields": "url"})
        return r["data"][0]["url"]

    def upload(self, uri, video_path):
        """Send the whole file in one request to the resumable upload URI of the container."""
        size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            body = f.read()
        r = urllib.request.Request(uri, data=body, method="POST", headers={
            "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size),
            "Content-Type": "application/octet-stream"})
        try:
            with self.opener(r, timeout=900) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            sys.exit(f"❌ upload {e.code}: {self._mask(e.read().decode())[:300]}")

    def wait_until_done(self, cid, attempts=60, interval=10):
        """Poll the container until Meta finishes processing the video. Returns the last status_code."""
        status = None
        for _ in range(attempts):
            s = self.req("GET", f"{self.api}/{cid}", {"fields": "status_code,status"})
            status = s.get("status_code")
            print(f"   status: {status}")
            if status in FINAL_STATES:
                break
            self.sleep(interval)
        return status

    def prepare(self, video_path, image_hash, caption):
        c = self.req("POST", f"{self.api}/{self.ig_user_id}/media", {
            "media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "cover_url": self.cover_url(image_hash), "share_to_feed": "true"})
        cid, uri = c["id"], c["uri"]
        print(f"uploaded: {self.upload(uri, video_path)}")
        status = self.wait_until_done(cid)
        print(f"container: {cid}, status {status}, not published")
        return cid

    def prepare_from_ad_video(self, ad_video_id, image_hash, caption):
        """Instagram fetches the video from the ad library by its source URL, no local upload."""
        src = self.req("GET", f"{self.api}/{ad_video_id}", {"fields": "source"})["source"]
        c = self.req("POST", f"{self.api}/{self.ig_user_id}/media", {
            "media_type": "REELS", "video_url": src, "caption": caption,
            "cover_url": self.cover_url(image_hash), "share_to_feed": "true"})
        cid = c["id"]
        status = self.wait_until_done(cid)
        print(f"container: {cid}, status {status}, not published")
        return cid

    def publish(self, cid):
        r = self.req("POST", f"{self.api}/{self.ig_user_id}/media_publish", {"creation_id": cid})
        m = self.req("GET", f"{self.api}/{r['id']}", {"fields": "permalink,timestamp"})
        print(f"✅ published: {m.get('permalink')} {m.get('timestamp')}")
        return m.get("permalink")

    def status(self, cid):
        return self.req("GET", f"{self.api}/{cid}", {"fields": "status_code,status"})


def build_parser():
    p = argparse.ArgumentParser(prog="meta_ads.reels", description="Instagram Reels through the Graph API")
    p.add_argument("--env", default=".env",
                   help="file with META_ACCESS_TOKEN, META_INSTAGRAM_ID and META_AD_ACCOUNT_ID")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare", help="upload a local video into a container, do not publish")
    s.add_argument("video")
    s.add_argument("cover_image_hash")
    s.add_argument("caption_file")
    s = sub.add_parser("prepare-url", help="container from a video already in the ad library, do not publish")
    s.add_argument("ad_video_id")
    s.add_argument("cover_image_hash")
    s.add_argument("caption_file")
    sub.add_parser("publish", help="publish a prepared container").add_argument("container_id")
    sub.add_parser("status", help="processing status of a container").add_argument("container_id")
    return p


def main(argv=None, opener=urllib.request.urlopen, sleep=time.sleep):
    a = build_parser().parse_args(argv)
    env = load_env(a.env, required=("META_ACCESS_TOKEN", "META_INSTAGRAM_ID", "META_AD_ACCOUNT_ID"))
    ig = ReelsPublisher(env["META_ACCESS_TOKEN"], env["META_INSTAGRAM_ID"], env["META_AD_ACCOUNT_ID"],
                        opener=opener, sleep=sleep)
    if a.cmd in ("prepare", "prepare-url"):
        with open(a.caption_file, encoding="utf-8") as f:
            caption = f.read().strip()
        if a.cmd == "prepare":
            return ig.prepare(a.video, a.cover_image_hash, caption)
        return ig.prepare_from_ad_video(a.ad_video_id, a.cover_image_hash, caption)
    if a.cmd == "publish":
        return ig.publish(a.container_id)
    print(ig.status(a.container_id))


if __name__ == "__main__":
    main()
