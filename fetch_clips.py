#!/usr/bin/env python3
"""
fetch_clips.py — resolve Pexels stock clips for each scene of a render job.

Reads a job JSON whose scenes carry a search `query` (plus duration/text) but no
`clip` yet, queries the Pexels video API for one LANDSCAPE clip per scene, and
writes a completed job JSON with each scene's `clip` filled in (a direct https
video-file URL that render.py downloads).

Used ONLY by the long-form (anthology) pipeline. The daily Shorts pipeline
resolves clips in Make and never calls this script, so this file cannot affect
the live Shorts flow.

Env:
  PEXELS_API         Pexels API key (required)
  CLIP_ORIENTATION   'landscape' (default) or 'portrait'
  VIDEO_W / VIDEO_H  target dims used only to score which file to pick
                     (default 1920x1080 — matches the long-video workflow)

Usage:
  python3 fetch_clips.py job.in.json job.json
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PEXELS_KEY = os.environ.get("PEXELS_API", "").strip()
ORIENT = os.environ.get("CLIP_ORIENTATION", "landscape").strip().lower()
TARGET_W = int(os.environ.get("VIDEO_W", "1920"))
TARGET_H = int(os.environ.get("VIDEO_H", "1080"))

# generic queries tried when a scene's own query returns nothing
GENERIC_FALLBACKS = [
    "ancient ruins", "dark ocean waves", "misty forest",
    "old stone wall", "storm clouds", "night sky stars",
]


def pexels_search(query, per_page=15):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({
        "query": query,
        "orientation": ORIENT,
        "per_page": per_page,
        "size": "medium",
    })
    req = urllib.request.Request(url, headers={
        "Authorization": PEXELS_KEY,
        "User-Agent": "tsc-render/1.0",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def pick_file(video):
    """Choose the best single video-file link from a Pexels video object."""
    files = [f for f in video.get("video_files", []) if f.get("link")]
    if not files:
        return None
    want_land = ORIENT != "portrait"
    oriented = [
        f for f in files
        if ((f.get("width") or 0) >= (f.get("height") or 0)) == want_land
    ]
    pool = oriented or files

    def score(f):
        w = f.get("width") or 0
        # prefer >= target width, then closest to target
        return (w < TARGET_W, abs(w - TARGET_W))

    pool.sort(key=score)
    return pool[0]["link"]


def resolve(query, used):
    """Return one clip URL for a query, preferring one not already used."""
    try:
        data = pexels_search(query)
    except Exception as e:  # network / auth / rate limit — treat as no result
        print(f"[clips] search error for '{query}': {e}", file=sys.stderr)
        return None
    vids = data.get("videos", []) or []
    for v in vids:  # first pass: skip clips already used
        link = pick_file(v)
        if link and link not in used:
            return link
    for v in vids:  # second pass: allow reuse rather than fail
        link = pick_file(v)
        if link:
            return link
    return None


def main():
    if not PEXELS_KEY:
        sys.exit("[clips] PEXELS_API env var is not set")

    src = sys.argv[1] if len(sys.argv) > 1 else "job.in.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "job.json"
    job = json.loads(Path(src).read_text(encoding="utf-8"))
    scenes = job.get("scenes") or []
    if not scenes:
        sys.exit("[clips] job has no scenes")

    used = set()
    for i, sc in enumerate(scenes):
        if sc.get("clip"):                     # already resolved upstream — keep
            used.add(sc["clip"])
            print(f"[clips] scene {i}: pre-set, kept")
            continue
        q = (sc.get("query") or sc.get("keywords") or "").strip()
        link = resolve(q, used) if q else None
        if not link:
            for g in GENERIC_FALLBACKS:
                link = resolve(g, used)
                if link:
                    print(f"[clips] scene {i}: '{q}' empty -> fallback '{g}'")
                    break
        if link:
            sc["clip"] = link
            used.add(link)
            print(f"[clips] scene {i}: ok ({q or 'n/a'})")
        else:
            print(f"[clips] scene {i}: UNRESOLVED", file=sys.stderr)

    # backfill any still-missing scene from what we did fetch (cycle through pool)
    missing = [sc for sc in scenes if not sc.get("clip")]
    if missing:
        pool = [sc["clip"] for sc in scenes if sc.get("clip")]
        if not pool:
            sys.exit("[clips] no clips resolved at all — aborting "
                     "(check PEXELS_API / network)")
        for j, sc in enumerate(missing):
            sc["clip"] = pool[j % len(pool)]
            print(f"[clips] backfilled scene from pool")

    Path(dst).write_text(json.dumps(job, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    resolved = sum(1 for sc in scenes if sc.get("clip"))
    print(f"[clips] wrote {dst} ({resolved}/{len(scenes)} scenes have a clip, "
          f"{len(used)} unique)")


if __name__ == "__main__":
    main()
