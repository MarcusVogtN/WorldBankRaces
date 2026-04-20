"""ffmpeg mux: combine the rendered MP4 with the narration WAV."""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio.plugins.ffmpeg as _ffmpeg_plugin


def mux_audio(video_path: Path, audio_path: Path, out_path: Path,
              *, audio_bitrate: str = "192k") -> Path:
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}. Render it first.")
    if not audio_path.exists():
        raise FileNotFoundError(
            f"Narration audio not found: {audio_path}. "
            "Run `python run.py --generate-narration` first."
        )

    ffmpeg = _ffmpeg_plugin.get_exe()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(out_path),
    ]
    print("Muxing: " + " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"→ wrote {out_path}")
    return out_path
