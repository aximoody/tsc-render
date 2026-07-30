#!/usr/bin/env python3
"""
TikTok upload step (runs on GitHub Actions after render).
Sends the rendered mp4 to the operator's TikTok account as a DRAFT
(inbox upload, sandbox/audit-free). The operator taps "post" in the app.

Flow:
  1. refresh_token -> access_token   (POST /v2/oauth/token/)
  2. init upload (FILE_UPLOAD)       (POST /v2/post/publish/inbox/video/init/)
  3. PUT the mp4 bytes to upload_url
  -> video appears in TikTok inbox as a draft.

Env (GitHub secrets):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN
  VIDEO_PATH   local path to out.mp4 (default out.mp4)
If any TIKTOK_* secret is empty -> no-op (skip), so the pipeline still runs.
"""
import json, os, urllib.parse, urllib.request

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INIT_URL  = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"


def post_form(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get_access_token(ck, cs, rt):
    j = post_form(TOKEN_URL, {
        "client_key": ck, "client_secret": cs,
        "grant_type": "refresh_token", "refresh_token": rt,
    })
    if "access_token" not in j:
        raise RuntimeError("token refresh failed: " + json.dumps(j))
    # TikTok may rotate the refresh token; surface the new one in case it changed
    print("::notice::TikTok refresh_token (update secret if changed): "
          + j.get("refresh_token", "(none)"))
    return j["access_token"]


def init_and_upload(access_token, video_path):
    size = os.path.getsize(video_path)
    payload = json.dumps({
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        }
    }).encode()
    req = urllib.request.Request(INIT_URL, data=payload, method="POST", headers={
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json; charset=UTF-8",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.loads(r.read().decode())
    data = j.get("data", {})
    upload_url = data.get("upload_url")
    if not upload_url:
        raise RuntimeError("init failed: " + json.dumps(j))
    with open(video_path, "rb") as f:
        blob = f.read()
    put = urllib.request.Request(upload_url, data=blob, method="PUT", headers={
        "Content-Type": "video/mp4",
        "Content-Length": str(size),
        "Content-Range": f"bytes 0-{size-1}/{size}",
    })
    with urllib.request.urlopen(put, timeout=300) as r:
        status = r.status
    print(f"[tiktok] upload status={status}, publish_id={data.get('publish_id')}")
    return data.get("publish_id")


def main():
    ck = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    cs = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    rt = os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()
    vp = os.environ.get("VIDEO_PATH", "out.mp4").strip()
    if not (ck and cs and rt):
        print("[tiktok] missing TIKTOK_* secrets -> skipping TikTok upload")
        return
    if not os.path.exists(vp):
        print(f"[tiktok] video not found at {vp} -> skipping")
        return
    at = get_access_token(ck, cs, rt)
    init_and_upload(at, vp)
    print("[tiktok] done -> video sent to TikTok inbox as draft")


if __name__ == "__main__":
    main()
