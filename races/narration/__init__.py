"""LLM-scripted sports-commentator narration for the race video.

Pipeline (invoked by `run.py --generate-variants` →
`--auto-assemble` → `--generate-narration` / `--mux-narration`):
    1. stats.build_stat_pack      curated menu of interesting numbers
    2. timeline.build_timeline    frame-keyed event spine (movers + crossovers)
    3. script.generate_variants   Claude tool-use call → one option per beat
    4. assemble.write_narration_json   pick option 0 from each beat
    5. voice.synthesize           ElevenLabs TTS → cache/narration.wav
    6. mux.mux_audio              ffmpeg mux onto rendered mp4
"""
