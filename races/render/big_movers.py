"""Big-mover event extraction and curation for the spotlight callout.

Two-step workflow:
    1. `python run.py --extract-movers` writes `cache/big_movers.json` with
       every candidate event (runs where a non-top-N country's windowed
       |Δvalue| exceeds the dataset-wide percentile threshold).
    2. A human or LLM reviews the JSON, flips `keep: true/false` per event,
       optionally overrides `label_override` or tweaks `start_year`/`end_year`.
    3. `python run.py` with `render.spotlight.curated_file` pointing at the
       JSON renders using only kept events.

This module is data-only (no matplotlib). The rank/interpolation helper
`interpolate_and_rank` lives here so both the renderer and the extractor
share exactly the same signal pipeline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..util import display_name, format_value


# ── Shared signal pipeline ────────────────────────────────────────────────

def interpolate_and_rank(df: pd.DataFrame, steps_per_year: int,
                         smooth_win_a: int, smooth_win_b: int):
    """Interpolate yearly values to sub-frames and compute smoothed ranks.

    Returns (scores, ranks). `scores` are the per-sub-frame values; `ranks`
    are fractional (rolling-mean-smoothed) ranks ascending so that larger
    values → larger rank numbers.
    """
    new_index = np.linspace(df.index.min(), df.index.max(),
                            (len(df) - 1) * steps_per_year + 1)
    scores = df.reindex(new_index).interpolate(method='linear')
    smoothed = scores.rolling(window=smooth_win_a, center=True, min_periods=1).mean()
    ranks = smoothed.rank(axis=1, method='first', ascending=True).astype(float)
    ranks = ranks.rolling(window=smooth_win_b, center=True, min_periods=1).mean()
    return scores, ranks


# ── Event model ───────────────────────────────────────────────────────────

@dataclass
class Event:
    id: str
    country: str
    display_name: str
    start_year: float
    peak_year: float
    end_year: float
    delta: float
    delta_pct: float
    value_before: float
    value_at_peak: float
    rank_before: int
    rank_at_peak: int
    direction: str                 # "up" | "down"
    description_hint: str
    keep: Optional[bool] = None    # LLM flips to true/false during review
    label_override: Optional[str] = None
    note: str = ''


def _slug(country: str, year: float) -> str:
    base = re.sub(r'[^a-z0-9]+', '_', country.lower()).strip('_')
    return f"{base}_{int(round(year))}"


def _rank_to_display(rank_val: float, total_countries: int) -> int:
    """Convert ascending-rank float (larger → higher value) to display rank (1 = top)."""
    if not np.isfinite(rank_val):
        return total_countries
    return int(round(total_countries - rank_val + 1))


# ── Event detection ───────────────────────────────────────────────────────

def compute_events(scores_df: pd.DataFrame,
                   ranks_df: pd.DataFrame,
                   *,
                   rate_window_frames: int,
                   threshold: float,
                   n_on_screen: int,
                   steps_per_year: int,
                   merge_gap_years: float = 2.0,
                   max_events: int = 50) -> list[Event]:
    """Extract discrete big-mover events from the rate-of-change signal."""
    total_countries = len(scores_df.columns)
    signed = scores_df.diff(periods=rate_window_frames)
    deltas = signed.abs()
    index = scores_df.index.to_numpy()

    merge_gap_frames = max(1, int(round(merge_gap_years * steps_per_year)))

    events: list[Event] = []

    for country in scores_df.columns:
        col = deltas[country].to_numpy()
        mask = np.isfinite(col) & (col > threshold)
        if not mask.any():
            continue

        # Find contiguous True runs in `mask`.
        runs: list[tuple[int, int]] = []
        in_run = False
        start = 0
        for i, m in enumerate(mask):
            if m and not in_run:
                in_run = True
                start = i
            elif not m and in_run:
                in_run = False
                runs.append((start, i - 1))
        if in_run:
            runs.append((start, len(mask) - 1))

        # Merge runs separated by less than merge_gap_frames.
        merged: list[tuple[int, int]] = []
        for s, e in runs:
            if merged and s - merged[-1][1] <= merge_gap_frames:
                merged[-1] = (merged[-1][0], e)
            else:
                merged.append((s, e))

        for s, e in merged:
            segment = col[s:e + 1]
            peak_off = int(np.argmax(segment))
            peak_frame = s + peak_off

            rank_at_peak_f = ranks_df[country].iloc[peak_frame]
            rank_at_peak_display = _rank_to_display(rank_at_peak_f, total_countries)
            # Skip events whose peak is already on-screen (top-N).
            if rank_at_peak_display <= n_on_screen:
                continue

            rank_before_f = ranks_df[country].iloc[s]
            rank_before_display = _rank_to_display(rank_before_f, total_countries)

            peak_delta = float(col[peak_frame])
            signed_peak = float(signed[country].iloc[peak_frame])
            direction = 'up' if signed_peak >= 0 else 'down'

            value_at_peak = float(scores_df[country].iloc[peak_frame])
            # "Value before" is the value rate_window_frames before the peak.
            before_idx = max(0, peak_frame - rate_window_frames)
            value_before = float(scores_df[country].iloc[before_idx])
            if not np.isfinite(value_before) or value_before <= 0:
                delta_pct = float('inf') if np.isfinite(peak_delta) and peak_delta > 0 else 0.0
            else:
                delta_pct = peak_delta / value_before

            start_year = float(index[s])
            peak_year = float(index[peak_frame])
            end_year = float(index[e])

            events.append(Event(
                id=_slug(country, peak_year),
                country=country,
                display_name=display_name(country),
                start_year=round(start_year, 2),
                peak_year=round(peak_year, 2),
                end_year=round(end_year, 2),
                delta=peak_delta,
                delta_pct=round(delta_pct, 3) if np.isfinite(delta_pct) else None,  # type: ignore
                value_before=value_before if np.isfinite(value_before) else 0.0,
                value_at_peak=value_at_peak,
                rank_before=rank_before_display,
                rank_at_peak=rank_at_peak_display,
                direction=direction,
                description_hint='',  # filled below
            ))

    # Rank by peak delta and cap.
    events.sort(key=lambda ev: ev.delta, reverse=True)
    events = events[:max_events]

    # Now that we know the overall ranking, populate hints (includes
    # "largest move in the dataset" / "top 5 move" flags).
    dataset_max = events[0].delta if events else 0.0
    top5_threshold = events[4].delta if len(events) >= 5 else (events[-1].delta if events else 0.0)
    for rank_idx, ev in enumerate(events, start=1):
        ev.description_hint = describe_event(ev, rank_idx=rank_idx,
                                             dataset_max=dataset_max,
                                             top5_threshold=top5_threshold)

    # Stable order by peak_year for review readability.
    events.sort(key=lambda ev: ev.peak_year)
    return events


def describe_event(event: Event, *, rank_idx: int,
                   dataset_max: float, top5_threshold: float) -> str:
    parts: list[str] = []

    span_years = max(0.1, event.peak_year - event.start_year)
    span_txt = f"{span_years:.0f}y" if span_years >= 1 else f"{span_years:.1f}y"

    # Growth magnitude
    if event.delta_pct is not None and np.isfinite(event.delta_pct) and event.delta_pct >= 1.0:
        mult = 1.0 + event.delta_pct
        parts.append(f"value {mult:.1f}×'d in {span_txt}")
    elif event.delta_pct is not None and np.isfinite(event.delta_pct) and event.delta_pct >= 0.5:
        pct = event.delta_pct * 100
        verb = 'grew' if event.direction == 'up' else 'fell'
        parts.append(f"{verb} {pct:.0f}% in {span_txt}")
    else:
        verb = 'grew' if event.direction == 'up' else 'fell'
        parts.append(f"{verb} by {format_value(event.delta, 'currency')} in {span_txt}")

    # Rank motion (display ranks; lower number = higher on chart)
    if event.rank_before != event.rank_at_peak:
        direction_word = 'climbed' if event.rank_at_peak < event.rank_before else 'dropped'
        parts.append(f"{direction_word} from #{event.rank_before} → #{event.rank_at_peak}")
    else:
        parts.append(f"held at #{event.rank_at_peak}")

    # Dataset-relative magnitude flag
    if rank_idx == 1 and event.delta >= dataset_max * 0.999:
        parts.append('largest move in the dataset')
    elif rank_idx <= 5 and event.delta >= top5_threshold * 0.999:
        parts.append(f'top-{rank_idx} move in the dataset')

    return '; '.join(parts)


# ── JSON I/O ──────────────────────────────────────────────────────────────

def extract_and_write(*,
                      data: pd.DataFrame,
                      render_cfg: dict,
                      value_format: str,
                      source_indicator: str,
                      out_path: Path) -> Path:
    """Run the extractor and write cache/big_movers.json. Returns the path."""
    steps_per_year = int(render_cfg.get('steps_per_year', 60))
    smooth_a = int(render_cfg.get('rank_smooth_window_a', 25))
    smooth_b = int(render_cfg.get('rank_smooth_window_b', 35))
    n_on_screen = int(render_cfg.get('top_n_on_screen', 10))

    spotlight_cfg = render_cfg.get('spotlight', {}) or {}
    rate_window_years = float(spotlight_cfg.get('rate_window_years', 3))
    rate_window_frames = max(1, int(rate_window_years * steps_per_year))
    percentile = float(spotlight_cfg.get('event_threshold_percentile',
                                         spotlight_cfg.get('percentile', 98.0)))
    merge_gap_years = float(spotlight_cfg.get('event_merge_gap_years', 2.0))
    max_events = int(spotlight_cfg.get('max_events', 50))

    scores_df, ranks_df = interpolate_and_rank(data, steps_per_year, smooth_a, smooth_b)
    deltas = scores_df.diff(periods=rate_window_frames).abs()

    flat = deltas.to_numpy().ravel()
    flat = flat[np.isfinite(flat) & (flat > 0)]
    threshold = float(np.percentile(flat, percentile)) if flat.size else 0.0

    events = compute_events(
        scores_df, ranks_df,
        rate_window_frames=rate_window_frames,
        threshold=threshold,
        n_on_screen=n_on_screen,
        steps_per_year=steps_per_year,
        merge_gap_years=merge_gap_years,
        max_events=max_events,
    )

    payload = {
        'dataset_indicator': source_indicator,
        'value_format': value_format,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'threshold_used': threshold,
        'percentile': percentile,
        'rate_window_years': rate_window_years,
        'merge_gap_years': merge_gap_years,
        'n_on_screen': n_on_screen,
        'schema_hint': (
            "Review each event and set `keep` to true or false. Optional: "
            "override `label_override` (banner text) or trim `start_year`/"
            "`end_year`. Free-form `note` is preserved on re-runs."
        ),
        'events': [asdict(ev) for ev in events],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # Summary
    print(f"Extracted {len(events)} events · threshold |Δ|≥{threshold:,.0f} "
          f"(p{percentile}) · window={rate_window_years}y")
    for ev in sorted(events, key=lambda e: -e.delta)[:5]:
        print(f"  Δ={ev.delta:>12,.0f}  {int(round(ev.peak_year))}  "
              f"{ev.display_name:<22}  {ev.description_hint}")
    print(f"→ wrote {out_path}")
    return out_path


@dataclass
class CuratedEvent:
    country: str
    start_year: float
    end_year: float
    peak_year: float
    label_override: Optional[str]
    subtext: str = ''


def load_curated(path: Path) -> list[CuratedEvent]:
    """Load kept events from a curated JSON. Returns [] on missing/invalid."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[spotlight] Could not read curated file {path}: {exc}. "
              "Falling back to auto-selection.")
        return []

    kept: list[CuratedEvent] = []
    for ev in payload.get('events', []):
        if not ev.get('keep'):
            continue
        try:
            subtext = ev.get('subtext_override')
            if not subtext:
                delta_pct = ev.get('delta_pct')
                direction = ev.get('direction') or ''
                years = max(1, int(round(float(ev['end_year']) - float(ev['start_year']))))
                if delta_pct is not None and direction in ('up', 'down'):
                    arrow = 'UP' if direction == 'up' else 'DOWN'
                    subtext = f"{arrow} {abs(float(delta_pct)):.0f}% IN {years}Y"
                else:
                    subtext = ''
            kept.append(CuratedEvent(
                country=ev['country'],
                start_year=float(ev['start_year']),
                end_year=float(ev['end_year']),
                peak_year=float(ev.get('peak_year', ev['start_year'])),
                label_override=ev.get('label_override') or None,
                subtext=subtext,
            ))
        except (KeyError, TypeError, ValueError):
            continue

    kept.sort(key=lambda e: e.start_year)
    return kept
