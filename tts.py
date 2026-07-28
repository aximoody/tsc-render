#!/usr/bin/env python3
"""
ElevenLabs voiceover step (runs on the GitHub Actions runner, before render.py).

Reads job.json, and for each scene:
  - synthesizes the scene text to speech via ElevenLabs
  - measures the resulting clip length
  - sets scene["duration"] = speech length + tail padding
Then concatenates all scene voiceovers (with the same padding gaps) into one
vo.mp3, and writes it back into job["voiceover"] and the updated durations.

If ELEVENLABS_API_KEY is missing/empty, this is a no-op: the job keeps its
existing durations and no voiceover is added (music-only render). That lets the
whole pipeline run TODAY, and voiceover switches on the moment the key exists.

Env:
  ELEVENLABS_API_KEY   required to actually synthesize
  ELEVENLABS_VOICE_ID  optional (defaults to a calm narrator voice)
  ELEVENLABS_MODEL     optional (default eleven_multilingual_v2)
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PAD = 0.6  # seconds of silence after each scene's speech

DEFAULT_VOICE = "onwK4e9ZLuTAKqWW03F9"      # "Daniel" - deep, calm narrator
DEFAULT_MODEL = "eleven_multilingual_v2"


def ffprobe_dur(path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True)
    return float(p.stdout.strip())


def tts_scene(text, out_mp3, key, voice, model):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    with urllib.request.urlopen(req, timeout=120) as r, open(out_mp3, "wb") as f:
        f.write(r.read())



def pick_voice(key):
    """Return a voice_id: env override, else first voice available on the account."""
    env = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if env:
        return env
    req = urllib.request.Request("https://api.elevenlabs.io/v1/voices",
                                 headers={"xi-api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode())
    voices = data.get("voices", [])
    if not voices:
        raise RuntimeError("No voices available on this ElevenLabs account")
    vid = voices[0]["voice_id"]
    print(f"[tts] auto-selected voice: {voices[0].get('name')} ({vid})")
    return vid


def main():
    job_path = sys.argv[1] if len(sys.argv) > 1 else "job.json"
    job = json.loads(Path(job_path).read_text())

    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("[tts] no ELEVENLABS_API_KEY -> skipping voiceover (music-only render)")
        return

    voice = pick_voice(key)
    model = os.environ.get("ELEVENLABS_MODEL", DEFAULT_MODEL)

    work = Path("vo_parts"); work.mkdir(exist_ok=True)
    parts = []
    for i, sc in enumerate(job["scenes"]):
        mp3 = str(work / f"vo{i}.mp3")
        tts_scene(sc["text"], mp3, key, voice, model)
        dur = ffprobe_dur(mp3)
        sc["duration"] = round(dur + PAD, 2)      # scene lasts exactly as long as its narration
        parts.append((mp3, dur))
        print(f"[tts] scene {i}: {dur:.2f}s speech -> scene {sc['duration']}s")

    # concat with trailing padding so audio boundaries match scene boundaries
    concat_list = work / "list.txt"
    silence = str(work / "sil.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"anullsrc=r=44100:cl=stereo", "-t", str(PAD),
                    "-c:a", "libmp3lame", silence],
                   capture_output=True, check=True)
    with open(concat_list, "w") as f:
        for mp3, _ in parts:
            f.write(f"file '{os.path.abspath(mp3)}'\n")
            f.write(f"file '{os.path.abspath(silence)}'\n")
    vo_final = "vo.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_list), "-c:a", "libmp3lame", vo_final],
                   capture_output=True, check=True)

    job["voiceover"] = vo_final
    Path(job_path).write_text(json.dumps(job, indent=2))
    print(f"[tts] wrote {vo_final}, updated durations in {job_path}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
ElevenLabs voiceover step (runs on the GitHub Actions runner, before render.py).

Reads job.json, and for each scene:
  - synthesizes the scene text to speech via ElevenLabs
  - measures the resulting clip length
  - sets scene["duration"] = speech length + tail padding
Then concatenates all scene voiceovers (with the same padding gaps) into one
vo.mp3, and writes it back into job["voiceover"] and the updated durations.

If ELEVENLABS_API_KEY is missing/empty, this is a no-op: the job keeps its
existing durations and no voiceover is added (music-only render). That lets the
whole pipeline run TODAY, and voiceover switches on the moment the key exists.

Env:
  ELEVENLABS_API_KEY   required to actually synthesize
  ELEVENLABS_VOICE_ID  optional (defaults to a calm narrator voice)
  ELEVENLABS_MODEL     optional (default eleven_multilingual_v2)
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

PAD = 0.6  # seconds of silence after each scene's speech

DEFAULT_VOICE = "onwK4e9ZLuTAKqWW03F9"      # "Daniel" - deep, calm narrator
DEFAULT_MODEL = "eleven_multilingual_v2"


def ffprobe_dur(path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True)
    return float(p.stdout.strip())


def tts_scene(text, out_mp3, key, voice, model):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    with urllib.request.urlopen(req, timeout=120) as r, open(out_mp3, "wb") as f:
        f.write(r.read())


def main():
    job_path = sys.argv[1] if len(sys.argv) > 1 else "job.json"
    job = json.loads(Path(job_path).read_text())

    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        print("[tts] no ELEVENLABS_API_KEY -> skipping voiceover (music-only render)")
        return

    voice = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE)
    model = os.environ.get("ELEVENLABS_MODEL", DEFAULT_MODEL)

    work = Path("vo_parts"); work.mkdir(exist_ok=True)
    parts = []
    for i, sc in enumerate(job["scenes"]):
        mp3 = str(work / f"vo{i}.mp3")
        tts_scene(sc["text"], mp3, key, voice, model)
        dur = ffprobe_dur(mp3)
        sc["duration"] = round(dur + PAD, 2)      # scene lasts exactly as long as its narration
        parts.append((mp3, dur))
        print(f"[tts] scene {i}: {dur:.2f}s speech -> scene {sc['duration']}s")

    # concat with trailing padding so audio boundaries match scene boundaries
    concat_list = work / "list.txt"
    silence = str(work / "sil.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"anullsrc=r=44100:cl=stereo", "-t", str(PAD),
                    "-c:a", "libmp3lame", silence],
                   capture_output=True, check=True)
    with open(concat_list, "w") as f:
        for mp3, _ in parts:
            f.write(f"file '{os.path.abspath(mp3)}'\n")
            f.write(f"file '{os.path.abspath(silence)}'\n")
    vo_final = "vo.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_list), "-c:a", "libmp3lame", vo_final],
                   capture_output=True, check=True)

    job["voiceover"] = vo_final
    Path(job_path).write_text(json.dumps(job, indent=2))
    print(f"[tts] wrote {vo_final}, updated durations in {job_path}")


if __name__ == "__main__":
    main()
