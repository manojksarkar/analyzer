"""Joins the rendered graphics, the recording slates, the captions and the scratch voice-over into one
timing cut, out/animatic.mp4. Replace each slate with its screen recording in your editor.

    python build_animatic.py        (after: node render.js, make_vo.ps1)
Needs ffmpeg on PATH or in the FFMPEG environment variable.
"""
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

# (clip, voice-over key or None, [(caption number, seconds into the clip)])
TIMELINE = [
    ("scenes/s01_problem.mp4", "s01", []),
    ("scenes/s02_title.mp4", "s02", []),
    ("slates/s03.mp4", "s03", [(1, 1.0)]),
    ("slates/s04.mp4", "s04", [(2, 1.0)]),
    ("scenes/s04_pipeline.mp4", None, []),
    ("slates/s05.mp4", "s05", [(3, 1.0)]),
    ("slates/s06.mp4", "s06", [(4, 1.0)]),
    ("slates/s07.mp4", "s07", [(5, 1.0), (6, 15.0)]),
    ("slates/s08.mp4", "s08", [(7, 1.0)]),
    ("slates/s09.mp4", "s09", [(8, 1.0)]),
    ("scenes/s09b_effort.mp4", None, []),
    ("scenes/s10_endcard.mp4", "s10", []),
]


def duration(path: Path) -> float:
    r = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True)
    hh, mm, ss = r.stderr.split("Duration: ")[1].split(",")[0].split(":")
    return int(hh) * 3600 + int(mm) * 60 + float(ss)


def main() -> None:
    inputs, filters, t = [], [], 0.0
    video_labels, overlays, voices = [], [], []
    for clip, vo, caps in TIMELINE:
        path = OUT / clip
        inputs += ["-i", str(path)]
        video_labels.append(f"[{len(inputs) // 2 - 1}:v]")
        start = t
        for n, at in caps:
            inputs += ["-i", str(OUT / "captions" / f"{n:02d}.mov")]
            overlays.append((len(inputs) // 2 - 1, start + at))
        if vo:
            inputs += ["-i", str(OUT / "vo" / f"{vo}.wav")]
            voices.append((len(inputs) // 2 - 1, start + 0.3))
        t += duration(path)

    filters.append("".join(video_labels) + f"concat=n={len(video_labels)}:v=1:a=0,fps=30,format=yuv420p[base]")
    last = "base"
    for i, (idx, at) in enumerate(overlays):
        filters.append(f"[{idx}:v]setpts=PTS-STARTPTS+{at}/TB[c{i}]")
        filters.append(f"[{last}][c{i}]overlay=0:0:eof_action=pass[v{i}]")
        last = f"v{i}"
    for i, (idx, at) in enumerate(voices):
        ms = int(at * 1000)
        filters.append(f"[{idx}:a]aresample=48000,adelay={ms}|{ms}[a{i}]")
    filters.append("".join(f"[a{i}]" for i in range(len(voices)))
                   + f"amix=inputs={len(voices)}:normalize=0,apad[aout]")

    cmd = [FFMPEG, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
           "-map", f"[{last}]", "-map", "[aout]", "-t", f"{t:.2f}",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", str(OUT / "animatic.mp4")]
    subprocess.run(cmd, check=True)
    print(f"out/animatic.mp4  {t:.1f} s")


if __name__ == "__main__":
    main()
