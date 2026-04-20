"""Claude API call that produces a single, continuous commentator script.

The model returns one flowing paragraph (no cue timing) designed to be read
straight through over the video duration.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import anthropic
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "anthropic SDK required for narration. `pip install anthropic`."
    ) from exc


SYSTEM_PROMPT = """You're writing voiceover for a 45-second vertical YouTube \
Shorts bar-chart race. One take, straight through, hype and casual — like \
you're on the couch reacting with a friend, not anchoring the 6 o'clock \
news.

# Voice & persona — LOUD, INFORMAL, EXCITED
- You are NOT a professional announcer. You're a hype friend who can't \
believe what you're seeing. Casual, loud, a little chaotic.
- Use informal language. Contractions, slang, casual fillers. "gonna", \
"massive", "insane", "huh?", "get this", "no way", "ridiculous", "watch \
this", "here we go", "hold up". ALL CAPS occasional words for emphasis.
- Absolutely NOT allowed: "expenditure", "fiscal", "geopolitical", \
"catalyst", "paramount", "unprecedented", "demonstrate", "surge", \
"trajectory". Drop every suit-and-tie word. If a 10-year-old wouldn't \
use it, you don't use it.
- Short punchy sentences. Fragments are fine. Exclamation marks are great.
- BAD (too formal): "The United States has dominated global military \
expenditure since 1960."
- GOOD (hype friend): "Check this out — America's been running this thing \
since the sixties. Like, the WHOLE thing."

# Tense & foreshadowing — FUTURE, NEVER SPOIL
- Write as if the events are ABOUT TO HAPPEN on screen. Build anticipation.
- Use future/expectation phrases: "watch what happens", "wait for it", \
"any second now", "keep your eye on", "here comes", "just wait", "you're \
about to see", "coming up".
- NEVER spoil the final numbers or final ranking in the first half. No \
"the USA ends up at 890 billion." No "64 straight years." Those are \
payoffs for later in the script.
- The first sentence is a HOOK and a QUESTION. Pull the viewer in, get \
them curious, get them guessing.

# Opening — QUESTION, not a summary
- Start with ONE engaging question in ≤10 words. Examples:
  - "Which country do you think spends the most on their military?"
  - "Guess how much the US spends compared to everyone else."
  - "Watch what happens when you line up 60 years of military budgets."
- Do NOT reveal the answer in the opening. Tease it, then make the viewer \
watch.

# Structure — ONE LINEAR STORY, 3 BEATS
- Three (max four) beats. ONE coherent story. NOT a list of facts. NOT a \
year-by-year rundown.
- Beat 1 (hook): the opening question + setup. "Watch this race start…"
- Beat 2 (the turn): the single biggest moment mid-video. Foreshadow it \
before it hits — "ok but something crazy is about to happen around the \
90s" — then let it land when it's on screen. Add a plain-language \
real-world "why" in one sentence if you're confident (e.g. "the Soviet \
Union's about to fall apart").
- Beat 3 (the payoff): the ending reveal. This is where you drop the final \
numbers and the "wow" stat. Save it for here.
- Each beat flows into the next. Connected sentences, not bullet points.

# Country flavor (use sparingly)
When a specific country is the subject of a sentence (big mover, rank-1 \
swap, or the ending reveal), you MAY sprinkle in ONE stereotype-flavored \
word or phrase. Playful, not mocking. Max one per country per script. \
If it feels forced, skip it. Word choice only — no fake accents.
- USA: "absolute unit", "cranks it up", "goes full send"
- UK: "mate", "absolutely mental", "proper"
- Russia / USSR: "comrade", "flexes hard"
- France: "oh là là", "casually"
- Germany: "engineered", "ruthlessly efficient"
- China: "quietly... then — BAM"
- Japan: "precise", "locked in"
- Saudi Arabia: "oil money says hi"
- India: "shows up big"

# Real-world 'why'
Add ONE short plain-language real-world reason for the big turn if you're \
confident ("the Soviet Union's collapsing", "9/11 just went down", "oil \
crashed"). If not confident, "around then, stuff was going sideways". \
NEVER dwell on casualties, conflicts, specific politicians.

# Length — HIT THE WORD BUDGET
- Target word count comes in the user payload. Hit it ±10%.
- The word count is tuned so the LAST WORD lands right before the end of \
the video. Short means dead air; long means cut off mid-sentence.
- Count your words before emitting.

# Output
Call the `emit_script` tool exactly once with `script_text` and \
`suggested_trim`. Do not output prose outside the tool call.
"""


SCRIPT_TOOL = {
    "name": "emit_script",
    "description": "Emit the continuous commentator script and an optional trim suggestion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "suggested_trim": {
                "type": ["object", "null"],
                "description": "Null if the full timeframe is fine, otherwise a trim suggestion.",
                "properties": {
                    "start_year": {"type": "integer"},
                    "reason": {"type": "string"},
                    "boringness": {"type": "number"},
                },
                "required": ["start_year", "reason"],
            },
            "script_text": {
                "type": "string",
                "description": "Single continuous commentator script, read straight through over the whole video. One paragraph. Starts with a question. Builds in the future tense. Pays off at the end.",
            },
        },
        "required": ["script_text"],
    },
}


def generate_script(*,
                    stat_pack: dict,
                    timeline: dict,
                    narration_cfg: dict,
                    out_path: Path) -> dict[str, Any]:
    """Call Claude, validate length, write cache/narration.json."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Export it or add it to `.env`."
        )

    client = anthropic.Anthropic(api_key=api_key)
    model = narration_cfg.get("model", "claude-opus-4-7")
    wps = float(narration_cfg.get("words_per_second", 2.7))
    coverage = float(narration_cfg.get("max_speech_coverage", 0.6))
    tone = narration_cfg.get("tone", "hype friend, casual, loud")
    duration = float(timeline["video_duration_seconds"])
    # Pace speech to end before any hold on the final frame.
    speech_window = float(timeline.get("animation_seconds", duration))
    target_words = int(speech_window * wps * coverage)

    user_payload = {
        "tone": tone,
        "words_per_second": wps,
        "video_duration_seconds": duration,
        "speech_window_seconds": speech_window,
        "target_word_count": target_words,
        "year_to_seconds_map": timeline["year_to_seconds"],
        "events": timeline["events"],
        "stat_pack": stat_pack,
    }

    system = [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        tools=[SCRIPT_TOOL],
        tool_choice={"type": "tool", "name": "emit_script"},
        messages=[{
            "role": "user",
            "content": [{
                "type": "text",
                "text": (
                    f"Write ~{target_words} words (±10%) for a "
                    f"{duration:.1f}-second video. Open with a QUESTION. "
                    "Write in the future tense — tease what's coming, do NOT "
                    "reveal the final numbers until the last beat. Three "
                    "beats, one linear story. Hype friend voice, not news "
                    "anchor. Count your words before emitting.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False)
                ),
            }],
        }],
    )

    script_doc: dict[str, Any] | None = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_script":
            script_doc = block.input  # type: ignore[assignment]
            break
    if script_doc is None:
        raise RuntimeError("Model did not call `emit_script`. Response: "
                           + repr(response.content))

    script_text: str = script_doc["script_text"].strip()
    word_count = len(script_text.split())
    est_seconds = word_count / wps
    print(f"[narration] script: {word_count} words, ~{est_seconds:.1f}s of speech "
          f"(target {target_words} words / {duration:.1f}s video)")
    if est_seconds > duration * 1.1:
        print(f"[narration] warn: script may overrun video by "
              f"{est_seconds - duration:.1f}s")

    script_doc["script_text"] = script_text
    script_doc.setdefault("meta", {})
    script_doc["meta"].update({
        "generated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "model": model,
        "video_duration_seconds": duration,
        "words_per_second": wps,
        "target_word_count": target_words,
        "actual_word_count": word_count,
        "estimated_seconds": round(est_seconds, 2),
        "tone": tone,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read_input_tokens": getattr(
                response.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens": getattr(
                response.usage, "cache_creation_input_tokens", 0),
        },
    })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(script_doc, f, ensure_ascii=False, indent=2)
    print(f"→ wrote {out_path}")
    return script_doc
