#!/usr/bin/env python3
"""
Turn the repository_dispatch client_payload (from Make) into a job.json.

Make sends, in client_payload:
{
  "title": "The Roman Dodecahedron",
  "caption": "...instagram caption...",       # passed through to the callback
  "hashtags": "#history #mystery ...",         # passed through to the callback
  "scenes": [
    {"text": "...", "clip": "https://.../pexels.mp4", "duration": 12},
    ...
  ]
}

Music is chosen at random from ./music/*.mp3 (committed royalty-free tracks).
Durations here are provisional; if ElevenLabs runs, tts.py overwrites them to
match the narration length.
"""
import json
import os
import random
import re
from pathlib import Path


def clean_text(t):
    """Remove stray model cue tags like [music] and backslashes from scene text."""
    if not t:
        return t
    t = re.sub(r"\[[^\]]*\]", " ", str(t))
    t = t.replace("\\", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


payload = json.loads(os.environ.get("PAYLOAD", "{}"))

scenes = payload.get("scenes", [])
if not scenes:
    raise SystemExit("[build_job] payload has no scenes")

# fallback duration if Make didn't send one
for sc in scenes:
    sc.setdefault("duration", 12)
    sc["text"] = clean_text(sc.get("text", ""))

music_dir = Path("music")
tracks = sorted(music_dir.glob("*.mp3")) if music_dir.exists() else []
music = str(random.choice(tracks)) if tracks else None

job = {
    "title": payload.get("title", "Untitled"),
    "font": payload.get("font", "DejaVu Serif"),
    "scenes": scenes,
    "music": music,
}
Path("job.json").write_text(json.dumps(job, indent=2))
print(f"[build_job] {len(scenes)} scenes, music={music}")
