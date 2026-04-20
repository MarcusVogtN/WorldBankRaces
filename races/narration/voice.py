"""Single-shot ElevenLabs TTS + background-music mixing via ffmpeg.

One call per script (keyed by sha256 of text + voice_id + model_id so edits
re-synthesize). Output is a single `cache/narration.wav` that already has
the background music ducked underneath the voice.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

try:
    from elevenlabs.client import ElevenLabs
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "elevenlabs SDK required for narration. `pip install elevenlabs`."
    ) from exc

import imageio.plugins.ffmpeg as _ffmpeg_plugin
_FFMPEG_EXE = _ffmpeg_plugin.get_exe()


def _script_hash(text: str, voice_id: str, model_id: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    h.update(b"|")
    h.update(voice_id.encode("utf-8"))
    h.update(b"|")
    h.update(model_id.encode("utf-8"))
    return h.hexdigest()[:16]


def synthesize(*,
               script_doc: dict,
               narration_cfg: dict,
               video_duration_seconds: float,
               clips_dir: Path,
               out_wav_path: Path,
               repo_root: Path) -> Path:
    """Synthesize one continuous voice track, then mix with background music."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set. Export it or add it to `.env`."
        )

    tts_cfg = narration_cfg.get("tts", {})
    voice_id = tts_cfg.get("voice_id")
    if not voice_id:
        raise RuntimeError("render.narration.tts.voice_id is required.")
    model_id = tts_cfg.get("model_id", "eleven_turbo_v2_5")
    stability = float(tts_cfg.get("stability", 0.45))
    style = float(tts_cfg.get("style", 0.75))
    similarity = float(tts_cfg.get("similarity_boost", 0.75))
    speed = float(tts_cfg.get("speed", 1.0))

    script_text = script_doc["script_text"]
    clips_dir.mkdir(parents=True, exist_ok=True)
    key = _script_hash(script_text, voice_id, model_id)
    voice_mp3 = clips_dir / f"{key}.mp3"

    if not voice_mp3.exists():
        print(f"[narration] synthesizing {len(script_text)} chars via ElevenLabs…")
        client = ElevenLabs(api_key=api_key)
        stream = client.text_to_speech.convert(
            voice_id=voice_id,
            model_id=model_id,
            text=script_text,
            voice_settings={
                "stability": stability,
                "style": style,
                "similarity_boost": similarity,
                "use_speaker_boost": True,
                "speed": speed,
            },
        )
        with open(voice_mp3, "wb") as f:
            for chunk in stream:
                if chunk:
                    f.write(chunk)
    else:
        print(f"[narration] voice track cached: {voice_mp3.name}")

    _mix_with_music(
        voice_mp3=voice_mp3,
        music_cfg=narration_cfg.get("background_music", {}) or {},
        repo_root=repo_root,
        out_wav_path=out_wav_path,
        duration_s=float(video_duration_seconds),
    )

    # Write a small manifest for debugging.
    manifest_path = out_wav_path.with_suffix(".manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "voice_id": voice_id,
            "model_id": model_id,
            "voice_mp3": voice_mp3.name,
            "duration_seconds": float(video_duration_seconds),
            "script_text": script_text,
        }, f, ensure_ascii=False, indent=2)
    return out_wav_path


def _mix_with_music(*, voice_mp3: Path, music_cfg: dict, repo_root: Path,
                    out_wav_path: Path, duration_s: float) -> None:
    """ffmpeg mix: voice on top + (optional) looping, ducked background music."""
    out_wav_path.parent.mkdir(parents=True, exist_ok=True)
    sr = 44100

    music_path: Path | None = None
    music_rel = music_cfg.get("path")
    if music_rel:
        candidate = (repo_root / music_rel).resolve()
        if candidate.exists():
            music_path = candidate
        else:
            print(f"[narration] warn: background_music.path {candidate} not found, "
                  "rendering voice-only")

    voice_volume = float(music_cfg.get("voice_volume_db", 0.0))
    music_volume = float(music_cfg.get("music_volume_db", -18.0))
    fade_in_s = float(music_cfg.get("fade_in_seconds", 0.5))
    fade_out_s = float(music_cfg.get("fade_out_seconds", 1.5))

    if music_path is None:
        # Voice only — pad with silence to video duration.
        cmd = [
            _FFMPEG_EXE, "-y",
            "-f", "lavfi", "-t", f"{duration_s:.3f}",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={sr}",
            "-i", str(voice_mp3),
            "-filter_complex",
            f"[1:a]aresample={sr},aformat=channel_layouts=stereo,"
            f"volume={voice_volume}dB[v];"
            f"[0:a][v]amix=inputs=2:normalize=0:duration=first[mix]",
            "-map", "[mix]",
            "-ac", "2", "-ar", str(sr),
            "-t", f"{duration_s:.3f}",
            str(out_wav_path),
        ]
    else:
        fade_out_start = max(0.0, duration_s - fade_out_s)
        filter_graph = (
            # Voice: resample, apply user volume.
            f"[1:a]aresample={sr},aformat=channel_layouts=stereo,"
            f"volume={voice_volume}dB[voice];"
            # Music: loop to cover full duration, trim, fade in/out, duck.
            f"[2:a]aresample={sr},aformat=channel_layouts=stereo,"
            f"aloop=loop=-1:size=2147483647,atrim=0:{duration_s:.3f},"
            f"afade=t=in:st=0:d={fade_in_s},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_s},"
            f"volume={music_volume}dB[music];"
            # Mix voice + music, using silent base to lock duration.
            f"[0:a][voice][music]amix=inputs=3:normalize=0:duration=first[mix]"
        )
        cmd = [
            _FFMPEG_EXE, "-y",
            "-f", "lavfi", "-t", f"{duration_s:.3f}",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={sr}",
            "-i", str(voice_mp3),
            "-i", str(music_path),
            "-filter_complex", filter_graph,
            "-map", "[mix]",
            "-ac", "2", "-ar", str(sr),
            "-t", f"{duration_s:.3f}",
            str(out_wav_path),
        ]
        print(f"[narration] mixing with music: {music_path.name} "
              f"(voice {voice_volume:+.0f} dB, music {music_volume:+.0f} dB)")

    subprocess.run(cmd, check=True)
    print(f"→ wrote {out_wav_path}  ({duration_s:.1f}s)")
