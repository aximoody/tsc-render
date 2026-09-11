#!/usr/bin/env python3
"""
Voiceover step (runs on the GitHub Actions runner, before render.py).

Uses Microsoft Edge neural TTS via the `edge-tts` package: free, no API key,
no monthly character quota, and it works from GitHub Actions runners (unlike the
ElevenLabs free tier, which caps at ~10k chars/month and blocks datacenter IPs).

For each scene it synthesizes the scene text to speech, measures the resulting
clip length, and sets scene["duration"] = speech length + tail padding. Then it
concatenates all scene voiceovers (with the same padding gaps) into one vo.mp3
and writes it back into job["voiceover"] plus the updated durations, which is
exactly the contract render.py already expects.

If no scene has any text, voiceover is skipped (music-only render) so the
pipeline never hard-fails on the audio step.

Env:
  TTS_VOICE  optional (default en-US-ChristopherNeural, a warm male narrator)
  TTS_RATE   optional edge-tts speaking rate, e.g. "-5%" (default "+0%")
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

def ensure_edge_tts():
    """Install edge-tts on the runner if it isn't present (keeps render.yml untouched)."""
    try:
        import edge_tts  # noqa: F401
    except Exception:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "edge-tts"], check=True)

PAD = 0.2  # seconds of silence after each scene's speech
DEFAULT_VOICE = "en-US-ChristopherNeural"  # warm, deep narrator (fits the brand)
DEFAULT_RATE = "+0%"


def ffprobe_dur(path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", path],
        capture_output=True, text=True)
    return float(p.stdout.strip())


def silence(out_mp3, seconds):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", str(seconds), "-c:a", "libmp3lame", out_mp3],
        capture_output=True, check=True)


def tts_scene(text, out_mp3, voice, rate):
    """Synthesize one scene to out_mp3 with edge-tts; retry once on a hiccup."""
    last = None
    for attempt in range(2):
        try:
            subprocess.run(
                ["edge-tts", "--voice", voice, "--rate", rate,
                 "--text", text, "--write-media", out_mp3],
                check=True, capture_output=True, text=True)
            if Path(out_mp3).exists() and Path(out_mp3).stat().st_size > 0:
                return
            last = RuntimeError("edge-tts produced an empty file")
        except subprocess.CalledProcessError as e:
            last = RuntimeError(f"edge-tts failed: {e.stderr or e}")
        time.sleep(2)
    raise last


def main():
    job_path = sys.argv[1] if len(sys.argv) > 1 else "job.json"
    ensure_edge_tts()
    job = json.loads(Path(job_path).read_text())

    voice = os.environ.get("TTS_VOICE", "").strip() or DEFAULT_VOICE
    rate = os.environ.get("TTS_RATE", "").strip() or DEFAULT_RATE

    scenes = job.get("scenes", [])
    if not any((sc.get("text") or "").strip() for sc in scenes):
        print("[tts] no scene text -> skipping voiceover (music-only render)")
        return

    print(f"[tts] voice={voice} rate={rate}")
    work = Path("vo_parts"); work.mkdir(exist_ok=True)
    parts = []
    for i, sc in enumerate(scenes):
        text = (sc.get("text") or "").strip()
        mp3 = str(work / f"vo{i}.mp3")
        if not text:
            silence(mp3, 0.8)  # keep scene indexing aligned
        else:
            tts_scene(text, mp3, voice, rate)
        dur = ffprobe_dur(mp3)
        sc["duration"] = round(dur + PAD, 2)  # scene lasts as long as its narration
        parts.append(mp3)
        print(f"[tts] scene {i}: {dur:.2f}s speech -> scene {sc['duration']}s")

    # trailing padding so audio boundaries line up with scene boundaries
    sil = str(work / "sil.mp3")
    silence(sil, PAD)
    concat_list = work / "list.txt"
    with open(concat_list, "w") as f:
        for mp3 in parts:
            f.write(f"file '{os.path.abspath(mp3)}'\n")
            f.write(f"file '{os.path.abspath(sil)}'\n")

    vo_final = "vo.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:a", "libmp3lame", vo_final],
        capture_output=True, check=True)

    job["voiceover"] = vo_final
    Path(job_path).write_text(json.dumps(job, indent=2))
    print(f"[tts] wrote {vo_final}, updated durations in {job_path}")


if __name__ == "__main__":
    main()
