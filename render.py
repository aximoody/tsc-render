#!/usr/bin/env python3
"""
TheSecretCodex render engine — Creatomate replacement.

Takes a job JSON and produces a 1080x1920 (9:16) vertical MP4:
  - N scenes, each a Pexels stock clip scaled/cropped to fill, trimmed to duration
  - styled burned-in captions (per scene) via libass
  - background music (looped/trimmed to length, ducked under voiceover)
  - optional voiceover audio track (ElevenLabs) as the primary audio

Job JSON shape (see job.example.json):
{
  "title": "The Roman Dodecahedron",
  "scenes": [
    {"text": "For 300 years...", "clip": "<local path or http url>", "duration": 12},
    ...
  ],
  "music": "<local path or http url>",         # optional
  "voiceover": "<local path or http url>",      # optional (whole-video track)
  "font": "DejaVu Serif"                        # optional, family name
}

Everything works with local paths OR http(s) urls (downloaded first).
Network-dependent bits (Pexels, ElevenLabs, music) only need to work on the
GitHub Actions runner; the FFmpeg logic itself is fully testable offline.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path

W = int(os.environ.get("VIDEO_W", "1080"))
H = int(os.environ.get("VIDEO_H", "1920"))
FPS = 30

# ---------- helpers ----------

def run(cmd):
    """Run a command, raise with stderr tail on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-25:])
        raise RuntimeError(f"cmd failed ({p.returncode}):\n{' '.join(cmd)}\n---\n{tail}")
    return p


def fetch(src, dst):
    """Copy a local file or download a url to dst."""
    if str(src).startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": "tsc-render/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
            f.write(r.read())
    else:
        # local
        data = Path(src).read_bytes()
        Path(dst).write_bytes(data)
    return dst


def ass_time(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


import re as _re

def clean_caption(text):
    """Strip stray model artifacts before captioning/voicing:
    [music]/[sound]/(...) style cue tags, backslashes, and doubled spaces."""
    if not text:
        return " "
    t = _re.sub(r"\[[^\]]*\]", " ", str(text))   # remove [music], [pause], etc.
    t = t.replace("\\", " ")                        # kill stray backslashes
    t = _re.sub(r"\s+", " ", t).strip()             # collapse whitespace
    return t or " "


def wrap(text, width=26):
    return "\n".join(textwrap.wrap(text, width=width)) or " "


# ---------- steps ----------

def render_scene(src_clip, duration, out_path):
    """Scale+crop a source clip to fill 1080x1920, trim/loop to duration, strip audio."""
    # cover-fit: scale so both dims >= target, then crop center. Loop short clips.
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1,fps={FPS}"
    )
    run([
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", src_clip,   # loop in case clip < duration
        "-t", f"{duration}",
        "-an",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        out_path,
    ])
    return out_path


def build_ass(scenes, font, out_path):
    """Build a styled ASS subtitle file, one caption block per scene, timed sequentially."""
    # Gilded Cipher vibe: warm gold text, heavy outline + soft shadow, lower third.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},74,&H00E8D28C,&H000000FF,&H00202020,&H90000000,1,0,0,0,100,100,1,0,1,5,3,2,90,90,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    t = 0.0
    for sc in scenes:
        dur = float(sc["duration"])
        start, end = t, t + dur
        # tiny fade in/out per caption
        text = "{\\fad(250,250)}" + ass_escape(wrap(clean_caption(sc["text"])))
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{text}")
        t = end
    Path(out_path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path, t  # t == total duration


def concat_scenes(scene_paths, out_path):
    lst = out_path + ".txt"
    Path(lst).write_text("".join(f"file '{os.path.abspath(p)}'\n" for p in scene_paths))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", out_path])
    return out_path


def build_audio(total_dur, music, voiceover, out_path):
    """
    Produce the final audio track of length total_dur.
      - voiceover present: voiceover full volume + music ducked to ~18%
      - music only: music at ~35%
      - neither: silent track
    """
    if not music and not voiceover:
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"anullsrc=r=44100:cl=stereo", "-t", f"{total_dur}",
             "-c:a", "aac", "-b:a", "160k", out_path])
        return out_path

    inputs, filters, labels = [], [], []
    idx = 0
    if voiceover:
        inputs += ["-i", voiceover]
        filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                       f"apad,atrim=0:{total_dur}[vo]")
        labels.append("[vo]")
        idx += 1
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        vol = "0.18" if voiceover else "0.35"
        filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                       f"volume={vol},atrim=0:{total_dur},afade=t=out:st={max(total_dur-1.5,0)}:d=1.5[mus]")
        labels.append("[mus]")
        idx += 1

    if len(labels) == 2:
        filters.append(f"{labels[0]}{labels[1]}amix=inputs=2:duration=first:dropout_transition=0[aout]")
    else:
        filters.append(f"{labels[0]}anull[aout]")

    run(["ffmpeg", "-y", *inputs,
         "-filter_complex", ";".join(filters),
         "-map", "[aout]", "-t", f"{total_dur}",
         "-c:a", "aac", "-b:a", "160k", out_path])
    return out_path


def mux(video, ass, audio, out_path):
    ass_esc = ass.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    run([
        "ffmpeg", "-y",
        "-i", video, "-i", audio,
        "-vf", (
            f"subtitles='{ass_esc}',"
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            "text=SUBSCRIBE:fontcolor=white:fontsize=46:"
            "box=1:boxcolor=0xCC0000@0.9:boxborderw=20:"
            "x=(w-text_w)/2:y=80"
        ),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        "-shortest",
        out_path,
    ])
    return out_path


# ---------- main ----------

def main():
    job_path = sys.argv[1] if len(sys.argv) > 1 else "job.json"
    out_final = sys.argv[2] if len(sys.argv) > 2 else "out.mp4"
    job = json.loads(Path(job_path).read_text())

    font = job.get("font", "DejaVu Serif")
    scenes = job["scenes"]

    work = tempfile.mkdtemp(prefix="tscrender_")
    print(f"[render] work dir: {work}")

    # 1. fetch + render each scene
    scene_vids = []
    for i, sc in enumerate(scenes):
        raw = fetch(sc["clip"], os.path.join(work, f"src{i}.mp4"))
        vid = render_scene(raw, float(sc["duration"]), os.path.join(work, f"scene{i}.mp4"))
        scene_vids.append(vid)
        print(f"[render] scene {i} ok ({sc['duration']}s)")

    # 2. captions
    ass, total = build_ass(scenes, font, os.path.join(work, "caps.ass"))
    print(f"[render] captions built, total {total:.1f}s")

    # 3. concat video
    concat = concat_scenes(scene_vids, os.path.join(work, "concat.mp4"))

    # 4. audio
    music = fetch(job["music"], os.path.join(work, "music.mp3")) if job.get("music") else None
    vo = fetch(job["voiceover"], os.path.join(work, "vo.mp3")) if job.get("voiceover") else None
    audio = build_audio(total, music, vo, os.path.join(work, "audio.m4a"))
    print(f"[render] audio built (voiceover={'yes' if vo else 'no'}, music={'yes' if music else 'no'})")

    # 5. mux + burn captions
    mux(concat, ass, audio, out_final)
    print(f"[render] DONE -> {out_final}")


if __name__ == "__main__":
    main()
