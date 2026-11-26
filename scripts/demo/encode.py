"""Scene cuts from the recorded videos -> demo.mp4 (H.264) and demo.gif."""

import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

SP = Path(sys.argv[1])
DEST = Path(sys.argv[2])
OUT = SP / "rec_out"
FF = imageio_ffmpeg.get_ffmpeg_exe()
meta = json.loads((OUT / "scenes.json").read_text())
videos = meta["videos"]
scenes = meta["scenes"]
DEST.mkdir(parents=True, exist_ok=True)


def marker_ends(path: str) -> list[float]:
    """Times (s) at which each magenta marker frame run ends."""
    gen = imageio_ffmpeg.read_frames(path, output_params=["-vf", "scale=16:10"])
    meta = gen.__next__()
    fps = meta["fps"]
    ends, inside = [], False
    for i, fr in enumerate(gen):
        px = [fr[k : k + 3] for k in range(0, len(fr), 3)]
        mag = sum(1 for r, g, b in px if r > 200 and g < 80 and b > 200) > len(px) * 0.8
        if inside and not mag:
            ends.append(i / fps)
        inside = mag
    return ends


starts: dict[str, list[float]] = {k: marker_ends(v) for k, v in videos.items()}
print({k: [round(t, 2) for t in v] for k, v in starts.items()})
seen: dict[str, int] = {}
for sc in scenes:
    n = seen.get(sc["video"], 0)
    seen[sc["video"]] = n + 1
    sc["cut_at"] = starts[sc["video"]][n] + 0.06  # skip the frame the marker fades from

FADE = 0.18
mp4, gif = DEST / "demo.mp4", DEST / "demo.gif"
cuts = []
for i, sc in enumerate(scenes):
    d = sc["end"] - sc["start"]
    cut = OUT / f"cut{i}.mp4"
    subprocess.run(
        [
            FF,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{sc['cut_at']:.3f}",
            "-t",
            f"{d:.3f}",
            "-i",
            videos[sc["video"]],
            "-vf",
            f"fps=30,format=yuv420p,fade=t=in:st=0:d={FADE},fade=t=out:st={d - FADE:.3f}:d={FADE}",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            str(cut),
        ],
        check=True,
    )
    cuts.append(cut)
lst = OUT / "cuts.txt"
lst.write_text("\n".join(f"file '{c.as_posix()}'" for c in cuts))
subprocess.run(
    [
        FF,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(lst),
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(mp4),
    ],
    check=True,
)
pal = OUT / "palette.png"
subprocess.run(
    [
        FF,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(mp4),
        "-vf",
        "fps=15,scale=960:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff",
        str(pal),
    ],
    check=True,
)
subprocess.run(
    [
        FF,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(mp4),
        "-i",
        str(pal),
        "-lavfi",
        "fps=15,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
        str(gif),
    ],
    check=True,
)
print(f"{sum(s['end'] - s['start'] for s in scenes):.1f}s")
for f in (mp4, gif):
    print(f.name, round(f.stat().st_size / 1e6, 2), "MB")
