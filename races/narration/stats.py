"""Precomputed statistic pack for the narration LLM.

The LLM picks from a curated menu of numbers rather than hallucinating. Each
entry carries enough context (year, countries, values) to be dropped into a
cue verbatim after a plain-language rewrite.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..util import display_name, format_value


def _yearly_from_scores(scores_df: pd.DataFrame, steps_per_year: int) -> pd.DataFrame:
    """Downsample scores_df (sub-frame) to one row per integer year."""
    idx = scores_df.index.to_numpy()
    years = np.round(idx).astype(int)
    # Keep the first sub-frame per integer year.
    first_mask = np.concatenate([[True], np.diff(years) != 0])
    yearly = scores_df.iloc[first_mask].copy()
    yearly.index = years[first_mask]
    return yearly


def _display_ranks(yearly: pd.DataFrame) -> pd.DataFrame:
    """Display rank (1 = largest). NaN where value is NaN."""
    return yearly.rank(axis=1, method='min', ascending=False)


def build_stat_pack(scores_df: pd.DataFrame,
                    ranks_df: pd.DataFrame,
                    *,
                    steps_per_year: int,
                    value_format: str,
                    video_title: str,
                    n_on_screen: int = 10) -> dict[str, Any]:
    yearly = _yearly_from_scores(scores_df, steps_per_year)
    ranks = _display_ranks(yearly)
    years = yearly.index.to_numpy()
    countries = list(yearly.columns)

    total_per_year = yearly.fillna(0).sum(axis=1)

    # ── Top-1 share per decade ──────────────────────────────────────────
    top_share_per_decade: list[dict[str, Any]] = []
    for decade in range(int(years.min()) // 10 * 10, int(years.max()) + 1, 10):
        mask = (years >= decade) & (years < decade + 10)
        if not mask.any():
            continue
        sub = yearly.iloc[mask]
        sub_total = sub.fillna(0).sum(axis=1)
        top1_values = sub.max(axis=1)
        top1_names = sub.idxmax(axis=1)
        share = float((top1_values / sub_total.replace(0, np.nan)).mean())
        dominant = top1_names.mode().iloc[0] if not top1_names.empty else None
        top_share_per_decade.append({
            'decade': int(decade),
            'dominant_country': display_name(dominant) if dominant else None,
            'avg_top1_share': round(share, 3),
            'avg_top1_share_pct_str': f"{share * 100:.0f}%",
        })

    # ── Total growth start → end ────────────────────────────────────────
    total_start = float(total_per_year.iloc[0]) if len(total_per_year) else 0.0
    total_end = float(total_per_year.iloc[-1]) if len(total_per_year) else 0.0
    total_growth = {
        'year_start': int(years[0]),
        'year_end': int(years[-1]),
        'value_start': total_start,
        'value_end': total_end,
        'value_start_str': format_value(total_start, value_format),
        'value_end_str': format_value(total_end, value_format),
        'multiplier': round(total_end / total_start, 2) if total_start > 0 else None,
    }

    # ── Longest reign at rank 1 ─────────────────────────────────────────
    top1_names = yearly.idxmax(axis=1)
    longest_reign = {'country': None, 'years': 0, 'start': None, 'end': None}
    if len(top1_names):
        cur_country = top1_names.iloc[0]
        cur_start = int(years[0])
        run = 1
        for i in range(1, len(top1_names)):
            if top1_names.iloc[i] == cur_country:
                run += 1
            else:
                if run > longest_reign['years']:
                    longest_reign = {
                        'country': display_name(cur_country),
                        'years': run,
                        'start': cur_start,
                        'end': int(years[i - 1]),
                    }
                cur_country = top1_names.iloc[i]
                cur_start = int(years[i])
                run = 1
        if run > longest_reign['years']:
            longest_reign = {
                'country': display_name(cur_country),
                'years': run,
                'start': cur_start,
                'end': int(years[-1]),
            }

    # ── Rank-1 crossovers ───────────────────────────────────────────────
    crossovers: list[dict[str, Any]] = []
    for i in range(1, len(top1_names)):
        a, b = top1_names.iloc[i - 1], top1_names.iloc[i]
        if a != b and pd.notna(a) and pd.notna(b):
            crossovers.append({
                'year': int(years[i]),
                'from': display_name(a),
                'to': display_name(b),
            })

    # ── Top-N entries and exits ─────────────────────────────────────────
    in_top = (ranks <= n_on_screen).fillna(False)
    entries_exits: list[dict[str, Any]] = []
    for country in countries:
        col = in_top[country].to_numpy()
        for i in range(1, len(col)):
            if col[i] and not col[i - 1]:
                entries_exits.append({
                    'country': display_name(country),
                    'year': int(years[i]),
                    'kind': 'entered_top_n',
                    'value_str': format_value(float(yearly[country].iloc[i]), value_format),
                })
            elif not col[i] and col[i - 1]:
                entries_exits.append({
                    'country': display_name(country),
                    'year': int(years[i]),
                    'kind': 'exited_top_n',
                    'value_str': format_value(float(yearly[country].iloc[i - 1]), value_format),
                })

    # ── Largest single-year jumps (top 20 by |Δ|) ───────────────────────
    diffs = yearly.diff()
    stacked = diffs.stack().dropna()
    stacked = stacked.reindex(stacked.abs().sort_values(ascending=False).index)
    largest_single_year_jumps: list[dict[str, Any]] = []
    for (year_val, country), delta in stacked.head(20).items():
        v_now = float(yearly.loc[year_val, country])
        v_prev = float(yearly.loc[year_val - 1, country]) if (year_val - 1) in yearly.index else None
        largest_single_year_jumps.append({
            'country': display_name(country),
            'year': int(year_val),
            'delta': float(delta),
            'delta_str': format_value(abs(float(delta)), value_format),
            'direction': 'up' if delta > 0 else 'down',
            'value_after_str': format_value(v_now, value_format),
            'value_before_str': format_value(v_prev, value_format) if v_prev is not None else None,
        })

    # ── Most volatile country ever in top-10 ────────────────────────────
    ever_top10 = [c for c in countries if (ranks[c] <= 10).any()]
    volatility = {}
    for c in ever_top10:
        vals = yearly[c].dropna()
        if len(vals) < 5 or vals.mean() <= 0:
            continue
        volatility[c] = float(vals.std() / vals.mean())
    if volatility:
        vc = max(volatility, key=volatility.get)  # type: ignore
        most_volatile_top10 = {
            'country': display_name(vc),
            'coefficient_of_variation': round(volatility[vc], 2),
        }
    else:
        most_volatile_top10 = None

    # ── Flat windows (≥4y where total changes <5%) ──────────────────────
    flat_windows: list[dict[str, Any]] = []
    win = 4
    totals = total_per_year.to_numpy()
    i = 0
    while i < len(totals) - win:
        seg = totals[i:i + win + 1]
        if seg.min() > 0 and (seg.max() - seg.min()) / seg.min() < 0.05:
            j = i + win
            while j + 1 < len(totals) and totals[j + 1] > 0 and \
                    (max(totals[i], totals[j + 1]) - min(totals[i], totals[j + 1])) / totals[i] < 0.05:
                j += 1
            flat_windows.append({'year_start': int(years[i]), 'year_end': int(years[j])})
            i = j + 1
        else:
            i += 1

    # ── Early boring score (first 5y of the dataset) ────────────────────
    early_n = min(5, len(years))
    if early_n >= 2:
        early_total = total_per_year.iloc[:early_n]
        early_var = float(early_total.std() / early_total.mean()) if early_total.mean() > 0 else 0.0
        early_ranks = ranks.iloc[:early_n].ffill().bfill()
        early_rank_changes = 0
        top_n_set_prev = None
        for yr in early_ranks.index:
            top_n_set = set(early_ranks.columns[early_ranks.loc[yr] <= n_on_screen])
            if top_n_set_prev is not None and top_n_set != top_n_set_prev:
                early_rank_changes += 1
            top_n_set_prev = top_n_set
        # Score: 0 = exciting, 1 = flat as a pancake.
        score = max(0.0, 1.0 - (early_var * 10 + early_rank_changes * 0.25))
        early_boring = {
            'score': round(min(1.0, score), 2),
            'years_considered': int(early_n),
            'variance_of_total': round(early_var, 4),
            'top_n_membership_changes': int(early_rank_changes),
            'first_interesting_year_guess': _first_interesting_year(total_per_year, ranks, n_on_screen),
        }
    else:
        early_boring = None

    return {
        'video_title': video_title,
        'years': [int(years[0]), int(years[-1])],
        'value_format': value_format,
        'top_share_per_decade': top_share_per_decade,
        'total_growth': total_growth,
        'longest_reign_at_1': longest_reign,
        'crossovers_at_1': crossovers,
        'entries_exits': entries_exits,
        'largest_single_year_jumps': largest_single_year_jumps,
        'most_volatile_top10': most_volatile_top10,
        'flat_windows': flat_windows,
        'early_boring': early_boring,
    }


def _first_interesting_year(total_per_year: pd.Series,
                            ranks: pd.DataFrame,
                            n_on_screen: int) -> int | None:
    """Earliest year where either total jumps >20% YoY or top-N membership shifts."""
    years = total_per_year.index.to_numpy()
    totals = total_per_year.to_numpy()
    prev_top_n: set[str] | None = None
    for i, yr in enumerate(years):
        top_n_set = set(ranks.columns[ranks.loc[yr] <= n_on_screen])
        jumped = i > 0 and totals[i - 1] > 0 and abs(totals[i] - totals[i - 1]) / totals[i - 1] > 0.2
        shifted = prev_top_n is not None and top_n_set != prev_top_n
        if jumped or shifted:
            return int(yr)
        prev_top_n = top_n_set
    return None
