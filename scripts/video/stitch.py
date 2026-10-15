"""
Stitch a Playwright run into a highlight reel with title cards.

Usage:
    python3 scripts/video/stitch.py video-output/run_<timestamp>
    python3 scripts/video/stitch.py video-output/run_<timestamp> --title-seconds 2.0

Outputs (inside the run directory):
    highlight.mp4   final 1080p reel with a title card before each section
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

WIDTH = 1920
HEIGHT = 1080
FPS = 30
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def pick_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    raise RuntimeError("No suitable TTF font found; edit FONT_CANDIDATES.")


def run(cmd: list[str]) -> None:
    print("$", " ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)


def build_title_card(out_path: Path, title: str, font: str, seconds: float) -> None:
    safe_title = title.replace(":", r"\:").replace("'", r"\'")
    filter_expr = (
        f"color=c=0x0B1220:s={WIDTH}x{HEIGHT}:d={seconds}:r={FPS},"
        f"drawtext=fontfile={font}:text='Hawanama':"
        f"fontsize=56:fontcolor=0x7DD3FC:x=(w-text_w)/2:y=(h/2)-80,"
        f"drawtext=fontfile={font}:text='{safe_title}':"
        f"fontsize=88:fontcolor=white:x=(w-text_w)/2:y=(h/2)+10,"
        f"format=yuv420p"
    )
    run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", filter_expr,
        "-t", str(seconds),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-r", str(FPS),
        str(out_path),
    ])


def image_to_clip(image: Path, out_path: Path, seconds: float) -> None:
    run([
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-t", str(seconds),
        "-i", str(image),
        "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x0B1220,format=yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        str(out_path),
    ])


def normalize_clip(src: Path, dst: Path) -> None:
    run([
        "ffmpeg", "-y",
        "-i", str(src),
        "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
               f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x0B1220,fps={FPS},format=yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-an",
        str(dst),
    ])


def concat(clips: list[Path], out_path: Path) -> None:
    with TemporaryDirectory() as tmp:
        list_file = Path(tmp) / "list.txt"
        list_file.write_text("\n".join(f"file '{c.resolve()}'" for c in clips))
        run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(out_path),
        ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path, help="video-output/run_<timestamp>")
    parser.add_argument("--title-seconds", type=float, default=1.6)
    parser.add_argument("--image-seconds", type=float, default=2.5,
                        help="fallback stills duration if raw video is missing")
    args = parser.parse_args()

    run_dir: Path = args.run_dir
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text())
    font = pick_font()

    work = run_dir / "_stitch"
    work.mkdir(exist_ok=True)

    clips: list[Path] = []

    raw_video = run_dir / manifest.get("raw_video", "raw.webm")
    if raw_video.exists():
        normalized_raw = work / "raw.mp4"
        normalize_clip(raw_video, normalized_raw)

        intro = work / "title_intro.mp4"
        build_title_card(intro, "Air Quality Platform", font, 3.0)
        clips.append(intro)
        clips.append(normalized_raw)
    else:
        for i, section in enumerate(manifest["sections"]):
            title_clip = work / f"title_{i:02d}.mp4"
            build_title_card(title_clip, section["title"], font, args.title_seconds)
            clips.append(title_clip)

            image_clip = work / f"image_{i:02d}.mp4"
            image_to_clip(run_dir / section["screenshot"], image_clip, args.image_seconds)
            clips.append(image_clip)

    final = run_dir / "highlight.mp4"
    concat(clips, final)
    print(f"\nWrote {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
