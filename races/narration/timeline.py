"""Frame-keyed event spine for the narration LLM.

Merges curated big-mover events, rank-1 crossovers, and top-N entries into a
single chronological list with `time_seconds` (when the event lands on
screen) so the LLM can schedule cues around them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..util import display_name


def _year_to_seconds(year_float: float, year_start: float, steps_per_year: int,
                     fps: int) -> float:
    frame = (year_float - year_start) * steps_per_year
    return float(frame / fps)


def build_timeline(scores_df: pd.DataFrame,
                   ranks_df: pd.DataFrame,
                   *,
                   steps_per_year: int,
                   fps: int,
                   n_on_screen: int,
                   curated_movers_path: Path | None,
                   preview_timeframe: tuple | None = None,
                   end_hold_seconds: float = 0.0) -> dict[str, Any]:
    # Clip to preview_timeframe if set, so timings match the rendered video.
    idx = scores_df.index.to_numpy()
    if preview_timeframe:
        y0, y1 = preview_timeframe
        mask = (idx >= y0) & (idx <= y1)
        scores_df = scores_df.iloc[mask]
        ranks_df = ranks_df.iloc[mask]
        idx = scores_df.index.to_numpy()

    year_start = float(idx[0])
    year_end = float(idx[-1])
    n_frames = len(scores_df)
    animation_seconds = n_frames / fps
    video_duration_seconds = animation_seconds + float(end_hold_seconds)

    total_countries = len(scores_df.columns)
    # Display rank: 1 = largest. `ranks_df` is ascending (larger value = larger).
    display_ranks = total_countries - ranks_df + 1

    # ── Rank-1 crossovers (sub-frame granularity, downsampled to yearly) ─
    yearly_idx = np.arange(int(np.ceil(year_start)), int(np.floor(year_end)) + 1)
    top1_by_year: dict[int, str] = {}
    for yr in yearly_idx:
        row_mask = np.isclose(np.round(idx), yr)
        if not row_mask.any():
            continue
        row_i = int(np.where(row_mask)[0][0])
        vals = scores_df.iloc[row_i]
        if vals.notna().any():
            top1_by_year[int(yr)] = vals.idxmax()

    events: list[dict[str, Any]] = []

    prev_top1 = None
    prev_year = None
    for yr, country in sorted(top1_by_year.items()):
        if prev_top1 is not None and country != prev_top1:
            events.append({
                'kind': 'rank1_crossover',
                'year': int(yr),
                'time_seconds': round(
                    _year_to_seconds(yr, year_start, steps_per_year, fps), 2),
                'subject': display_name(country),
                'from': display_name(prev_top1),
                'hint': f"{display_name(country)} takes #1 from {display_name(prev_top1)}",
            })
        prev_top1 = country
        prev_year = yr

    # ── Curated big-mover events (or fallback to none if file missing) ──
    if curated_movers_path and curated_movers_path.exists():
        try:
            payload = json.loads(curated_movers_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            payload = {}
        for ev in payload.get('events', []):
            if not ev.get('keep'):
                continue
            start_year = float(ev.get('start_year', year_start))
            if not (year_start <= start_year <= year_end):
                continue
            events.append({
                'kind': 'big_mover',
                'year': float(start_year),
                'time_seconds': round(
                    _year_to_seconds(start_year, year_start, steps_per_year, fps), 2),
                'subject': ev.get('display_name') or display_name(ev['country']),
                'direction': ev.get('direction'),
                'delta_str': None,
                'hint': ev.get('description_hint', ''),
                'anchor_id': ev.get('id'),
                'peak_year': ev.get('peak_year'),
                'end_year': ev.get('end_year'),
                'rank_before': ev.get('rank_before'),
                'rank_at_peak': ev.get('rank_at_peak'),
            })

    events.sort(key=lambda e: e['time_seconds'])

    # year_to_seconds_map at each integer year for the LLM
    year_to_seconds = {
        int(yr): round(_year_to_seconds(int(yr), year_start, steps_per_year, fps), 2)
        for yr in yearly_idx
    }

    return {
        'year_start': year_start,
        'year_end': year_end,
        'fps': fps,
        'steps_per_year': steps_per_year,
        'n_frames': n_frames,
        'video_duration_seconds': round(video_duration_seconds, 2),
        'animation_seconds': round(animation_seconds, 2),
        'end_hold_seconds': float(end_hold_seconds),
        'year_to_seconds': year_to_seconds,
        'events': events,
    }
