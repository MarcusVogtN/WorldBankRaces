"""LLM-scripted sports-commentator narration for the race video.

Pipeline (invoked by `run.py --generate-narration` / `--mux-narration`):
    1. stats.build_stat_pack      curated menu of interesting numbers
    2. timeline.build_timeline    frame-keyed event spine (movers + crossovers)
    3. script.generate_script     Claude tool-use call → cues + suggested_trim
    4. voice.synthesize           ElevenLabs TTS → cache/narration.wav
    5. mux.mux_audio              ffmpeg mux onto rendered mp4
"""
