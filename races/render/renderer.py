"""Main rendering loop. Flag-racing layout for YouTube Shorts safe zones."""

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.patches import FancyBboxPatch
import imageio.plugins.ffmpeg as _ffmpeg_plugin

from ..util import format_value, display_name

from .theme import Theme, assign_colors
from .layout import (
    Columns, DEFAULT_COLUMNS, VerticalLayout, DEFAULT_VERTICAL,
    track_position, smoothstep,
)

plt.rcParams['animation.ffmpeg_path'] = _ffmpeg_plugin.get_exe()
sys.stdout.reconfigure(encoding='utf-8')


FIG_W_IN, FIG_H_IN = 10.8, 19.2
DPI = 100
FIG_W_PX = FIG_W_IN * DPI
FIG_H_PX = FIG_H_IN * DPI

AX_MARGIN = 0.02

SAFE_RIGHT = 0.86
SAFE_BOTTOM = 0.08   # just enough clearance for the source-credit line


def _interpolate_and_rank(df: pd.DataFrame, steps_per_year: int,
                           smooth_win_a: int, smooth_win_b: int):
    new_index = np.linspace(df.index.min(), df.index.max(),
                            (len(df) - 1) * steps_per_year + 1)
    scores = df.reindex(new_index).interpolate(method='linear')
    smoothed = scores.rolling(window=smooth_win_a, center=True, min_periods=1).mean()
    ranks = smoothed.rank(axis=1, method='first', ascending=True).astype(float)
    ranks = ranks.rolling(window=smooth_win_b, center=True, min_periods=1).mean()
    return scores, ranks


def _draw_background(ax, theme: Theme):
    bg = theme.background
    if isinstance(bg, tuple) and bg[0] == 'gradient':
        _, c_top, c_bottom = bg
        top_rgb = np.array(_hex_to_rgb(c_top))
        bot_rgb = np.array(_hex_to_rgb(c_bottom))
        grad = np.linspace(0, 1, 256).reshape(-1, 1)
        img = bot_rgb[None, None, :] * (1 - grad[:, :, None]) + top_rgb[None, None, :] * grad[:, :, None]
        img = np.flipud(img)
        ax.imshow(img, extent=[0, 1, 0, 1], aspect='auto', zorder=-10,
                  origin='upper', interpolation='bilinear')
    elif isinstance(bg, tuple) and bg[0] == 'radial':
        # ('radial', c_center, c_edge) — lighter center fading to dark edges.
        _, c_center, c_edge = bg
        center_rgb = np.array(_hex_to_rgb(c_center))
        edge_rgb = np.array(_hex_to_rgb(c_edge))
        h, w = 540, 960  # 16:9 sampling; bilinear handles upscale
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        # Normalized offset from center in [-1, 1], aspect-aware so the falloff is an ellipse matching the frame.
        nx = (xx - (w - 1) / 2) / ((w - 1) / 2)
        ny = (yy - (h - 1) / 2) / ((h - 1) / 2)
        dist = np.sqrt(nx * nx + ny * ny)
        # Smooth falloff: lighter (t=0) in center, dark (t=1) past the corners.
        t = np.clip(dist / 1.25, 0.0, 1.0)
        t = t * t * (3 - 2 * t)  # smoothstep
        img = center_rgb[None, None, :] * (1 - t[:, :, None]) + edge_rgb[None, None, :] * t[:, :, None]
        ax.imshow(img, extent=[0, 1, 0, 1], aspect='auto', zorder=-10,
                  origin='upper', interpolation='bilinear')
    else:
        ax.set_facecolor(bg)


def _hex_to_rgb(hx: str) -> tuple:
    hx = hx.lstrip('#')
    return tuple(int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _rounded_rect(ax, x, y, w, h, *, radius_px, fig_w_px, facecolor, alpha,
                  edgecolor='none', zorder=1):
    r = radius_px / fig_w_px
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={r}",
        linewidth=0, edgecolor=edgecolor,
        facecolor=facecolor, alpha=alpha, zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * float(np.clip(t, 0.0, 1.0))


def _round_image_corners(img: np.ndarray, radius_frac: float = 0.12) -> np.ndarray:
    """Apply rounded-corner alpha mask to RGBA image. radius_frac is fraction of short side."""
    if img.ndim != 3 or img.shape[2] != 4:
        return img
    h, w = img.shape[:2]
    r = max(1, int(round(min(h, w) * radius_frac)))
    mask = np.ones((h, w), dtype=np.float32)

    # Build corner masks using distance-to-corner-center
    yy, xx = np.ogrid[:h, :w]
    # Top-left
    corners = [
        (r, r, yy < r, xx < r),
        (r, w - 1 - r, yy < r, xx > w - 1 - r),
        (h - 1 - r, r, yy > h - 1 - r, xx < r),
        (h - 1 - r, w - 1 - r, yy > h - 1 - r, xx > w - 1 - r),
    ]
    for cy, cx, my, mx in corners:
        region = my & mx
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        # Smooth 1-pixel edge
        a = np.clip(r + 0.5 - dist, 0.0, 1.0)
        mask = np.where(region, np.minimum(mask, a), mask)

    out = img.copy()
    out[..., 3] = (out[..., 3].astype(np.float32) * mask).astype(np.uint8)
    return out


def _draw_title_year_trend(ax, theme: Theme, title: str, year_int: int,
                            t_ease: float, *,
                            trend_series: Optional[np.ndarray],
                            trend_pos: Optional[float],
                            trend_label: str,
                            start_year: Optional[int] = None,
                            end_year: Optional[int] = None,
                            t_title: float = 1.0,
                            t_draw: float = 1.0,
                            total_value: Optional[float] = None,
                            value_format: str = ''):
    """Title card + (label-card | year-card) row + wide borderless trend line."""
    if ' (' in title:
        main = title.split(' (', 1)[0]
    else:
        main = title

    alpha = t_ease

    # Back-ease-out bounce for the title: overshoots above 1.0 then settles.
    tt = float(np.clip(t_title, 0.0, 1.0))
    c1 = 1.70158
    c3 = c1 + 1.0
    title_scale = 1.0 + c3 * (tt - 1) ** 3 + c1 * (tt - 1) ** 2
    # Start slightly shrunk so the pop reads clearly.
    title_scale = 0.35 + title_scale * 0.65

    title_cx = 0.5
    title_cy = 0.935

    ax.text(title_cx, title_cy, main.upper(),
            transform=ax.transAxes, ha='center', va='center',
            color=theme.text_primary, fontsize=44 * title_scale, fontweight='bold',
            alpha=alpha, fontfamily=theme.font_family, zorder=3)

    # Header row above the trend line: label card (left) + year card (right).
    if trend_series is None:
        # Fallback: keep a centered year card if there's no trend line.
        year_card_w = 0.28
        year_card_h = 0.065
        year_card_x = 0.5 - year_card_w / 2
        year_card_y = 0.810
        if theme.title_card:
            _rounded_rect(
                ax, year_card_x, year_card_y, year_card_w, year_card_h,
                radius_px=24, fig_w_px=FIG_W_PX,
                facecolor=theme.title_card_color,
                alpha=theme.title_card_opacity * alpha, zorder=2,
            )
        ax.text(0.5, year_card_y + year_card_h / 2, str(year_int),
                transform=ax.transAxes, ha='center', va='center',
                color=theme.text_primary, fontsize=52, fontweight='bold',
                alpha=alpha, fontfamily=theme.font_family, zorder=3)
        return

    header_y = 0.850
    header_h = 0.042

    # Trend label (no card) — "TREND:" prefix in secondary color, label in primary.
    label_x = 0.070
    label_y = header_y + header_h / 2
    prefix = 'TREND: '
    ax.text(label_x, label_y, prefix,
            transform=ax.transAxes, ha='left', va='center',
            color=theme.text_secondary, fontsize=16, fontweight='black',
            alpha=alpha * 0.9, fontfamily=theme.font_family, zorder=3)
    ax.text(label_x + 0.095, label_y, trend_label.upper(),
            transform=ax.transAxes, ha='left', va='center',
            color=theme.text_primary, fontsize=21, fontweight='black',
            alpha=alpha, fontfamily=theme.font_family, zorder=3)

    # Live total on the right side of the header row.
    if total_value is not None and np.isfinite(total_value):
        ax.text(0.930, label_y, format_value(float(total_value), value_format).upper(),
                transform=ax.transAxes, ha='right', va='center',
                color=theme.text_primary, fontsize=26, fontweight='black',
                alpha=alpha, fontfamily=theme.font_family, zorder=3)

    # Trend line — wide, no background card. Sits closer to the flag race;
    # the TREND header above stays in place.
    plot_x0 = 0.070
    plot_x1 = 0.930
    plot_y0 = 0.755
    plot_y1 = 0.815

    ys = trend_series.astype(float)
    ymin = float(np.nanmin(ys)) if np.isfinite(np.nanmin(ys)) else 0.0
    ymax = float(np.nanmax(ys)) if np.isfinite(np.nanmax(ys)) else 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    n = len(ys)
    xs_frac = np.linspace(0.0, 1.0, n)
    line_x = plot_x0 + xs_frac * (plot_x1 - plot_x0)
    line_y = plot_y0 + (ys - ymin) / (ymax - ymin) * (plot_y1 - plot_y0)

    td = float(np.clip(t_draw, 0.0, 1.0))
    # Ease-out cubic for a smooth "draw-in" sweep from left to right.
    td_eased = 1.0 - (1.0 - td) ** 3
    draw_end = max(2, int(round(td_eased * n)))

    # Vertical back-ease-out bounce around the baseline — same curve as the title.
    _pop = 1.0 + c3 * (tt - 1) ** 3 + c1 * (tt - 1) ** 2
    trend_pop = 0.35 + _pop * 0.65
    line_y_pop = plot_y0 + (line_y - plot_y0) * trend_pop
    ax.plot(line_x[:draw_end], line_y_pop[:draw_end],
            color=theme.text_primary, linewidth=1.6,
            alpha=alpha * 0.75, zorder=3, solid_capstyle='round')

    # Current-position indicator
    if trend_pos is not None:
        tp = float(np.clip(trend_pos, 0.0, 1.0))
        idx = int(round(tp * (n - 1)))
        dot_x = line_x[idx]
        dot_y = line_y_pop[idx]
        guide_top = plot_y0 + (plot_y1 - plot_y0) * trend_pop
        # Vertical guide
        ax.plot([dot_x, dot_x], [plot_y0, guide_top],
                color=theme.text_primary, linewidth=1.0,
                alpha=alpha * 0.35, zorder=3)
        ax.plot([dot_x], [dot_y], marker='o', markersize=7,
                color=theme.text_primary, markeredgewidth=0,
                alpha=alpha, zorder=4)

        # Current year follows the indicator, sitting just above the trend plot.
        edge_pad = 0.05
        if dot_x - plot_x0 < edge_pad:
            year_ha = 'left'
        elif plot_x1 - dot_x < edge_pad:
            year_ha = 'right'
        else:
            year_ha = 'center'
        ax.text(dot_x, guide_top + 0.008, str(year_int),
                transform=ax.transAxes, ha=year_ha, va='bottom',
                color=theme.text_primary, fontsize=24, fontweight='bold',
                alpha=alpha, fontfamily=theme.font_family, zorder=4)

    if start_year is not None:
        ax.text(plot_x0, plot_y0 - 0.012, str(start_year),
                transform=ax.transAxes, ha='left', va='top',
                color=theme.text_secondary, fontsize=17, fontweight='bold',
                alpha=alpha * 0.85, fontfamily=theme.font_family, zorder=3)
    if end_year is not None:
        ax.text(plot_x1, plot_y0 - 0.012, str(end_year),
                transform=ax.transAxes, ha='right', va='top',
                color=theme.text_secondary, fontsize=17, fontweight='bold',
                alpha=alpha * 0.85, fontfamily=theme.font_family, zorder=3)


def _weighted_row_position(display_rank_target: float,
                            all_ranks: np.ndarray,
                            all_weights: np.ndarray,
                            *,
                            race_top: float,
                            race_height: float,
                            total_weight_norm: float) -> tuple:
    """y_center and slot height for a country, using smoothstep-blended
    cumulative weight of all other countries above it by fractional rank."""
    # Fraction of each other country that sits above this one.
    # Input to smoothstep: (dr_target - dr_other) + 0.5, clamped to [0,1].
    # = 1 when other is clearly above; 0 when below; 0.5 when tied.
    u = np.clip((display_rank_target - all_ranks) + 0.5, 0.0, 1.0)
    fracs = u * u * (3 - 2 * u)  # smoothstep
    # Exclude self (where dr_other == dr_target exactly — they contribute 0.5,
    # we want 0). Simplest: the self term's fraction is 0.5 * its own weight,
    # which we subtract out.
    cum_above = float(np.sum(fracs * all_weights))
    return cum_above


def render(data: pd.DataFrame,
           *,
           load_icon,
           title: str,
           value_format: str,
           source_credit: str,
           theme: Theme,
           output_path: Path,
           render_cfg: dict,
           columns: Columns = DEFAULT_COLUMNS,
           preview_timeframe: Optional[tuple] = None) -> None:

    n_on_screen = render_cfg.get('top_n_on_screen', 10)
    steps_per_year = render_cfg.get('steps_per_year', 60)
    fps = render_cfg.get('fps', 30)
    bitrate = render_cfg.get('bitrate', 8000)
    smooth_a = render_cfg.get('rank_smooth_window_a', 25)
    smooth_b = render_cfg.get('rank_smooth_window_b', 35)
    row_min_weight = render_cfg.get('row_min_weight', 0.35)
    show_total_trend = render_cfg.get('show_total_trend', True)
    trend_label = render_cfg.get('trend_label', 'Total — all countries')
    flag_corner_radius_frac = render_cfg.get('flag_corner_radius_frac', 0.14)
    row_gap = render_cfg.get('row_gap', 0.008)

    race_top = render_cfg.get('race_top', 0.72 if show_total_trend else 0.78)
    race_bottom = render_cfg.get('race_bottom', 0.11)

    vertical = VerticalLayout(
        race_top=race_top,
        race_bottom=race_bottom,
        n_on_screen=n_on_screen,
    )
    race_height = vertical.race_height

    print('Preparing frames...')
    scores_df, ranks_df = _interpolate_and_rank(data, steps_per_year, smooth_a, smooth_b)
    country_colors = assign_colors(data.columns, theme.accent_palette)

    total_countries = len(data.columns)

    # Precompute total-trend series (sum across countries per frame).
    if show_total_trend:
        trend_series = scores_df.fillna(0).sum(axis=1).to_numpy()
    else:
        trend_series = None

    # Per-country normalized history for in-row sparklines.
    country_hist: dict = {}
    for c in scores_df.columns:
        vals = scores_df[c].fillna(0).to_numpy(dtype=float)
        vmax = float(np.nanmax(vals)) if len(vals) else 0.0
        country_hist[c] = vals / vmax if vmax > 0 else vals
    spark_x0 = columns.name_box_left + 0.010
    spark_x1 = columns.name_box_right - 0.010
    spark_xs_full = np.linspace(spark_x0, spark_x1, len(scores_df))

    # Flag cache with rounded corners applied.
    flag_cache: dict = {}

    def get_flag(country):
        if country in flag_cache:
            return flag_cache[country]
        icon = load_icon(country)
        if icon is not None and flag_corner_radius_frac > 0:
            icon = _round_image_corners(icon, flag_corner_radius_frac)
        flag_cache[country] = icon
        return icon

    fig = plt.figure(figsize=(FIG_W_IN, FIG_H_IN), dpi=DPI)
    fig.patch.set_facecolor('#000000')
    ax = fig.add_axes([AX_MARGIN, 0.0, 1.0 - 2 * AX_MARGIN, 1.0])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    state = {
        'frame': 0,
        'prev_int_rank': {},
        'flash_start': {},
        'flash_color': {},
    }

    start_year = int(float(data.index.min()))
    end_year = int(float(data.index.max()))

    n_frames_total = len(scores_df)

    def update(frame_idx):
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        _draw_background(ax, theme)

        scores = scores_df.iloc[frame_idx]
        ranks = ranks_df.iloc[frame_idx]
        year_int = int(float(scores_df.index[frame_idx]))

        max_val = float(scores.max())
        if not np.isfinite(max_val) or max_val <= 0:
            return

        state['frame'] += 1
        t_ease = smoothstep(min(1.0, state['frame'] / 50))
        t_title = min(1.0, state['frame'] / 18)
        t_draw = min(1.0, state['frame'] / 55)

        # Same back-ease-out bounce used for the title, applied to each race row.
        _tt = float(np.clip(t_title, 0.0, 1.0))
        _c1 = 1.70158
        _c3 = _c1 + 1.0
        _bounce = 1.0 + _c3 * (_tt - 1) ** 3 + _c1 * (_tt - 1) ** 2
        race_intro_scale = 0.35 + _bounce * 0.65

        trend_pos = (frame_idx / max(1, n_frames_total - 1)) if show_total_trend else None
        current_total = float(trend_series[frame_idx]) if trend_series is not None else None
        _draw_title_year_trend(ax, theme, title, year_int, t_ease,
                                trend_series=trend_series,
                                trend_pos=trend_pos,
                                trend_label=trend_label,
                                start_year=start_year,
                                end_year=end_year,
                                t_title=t_title,
                                t_draw=t_draw,
                                total_value=current_total,
                                value_format=value_format)

        ax.text(0.04, SAFE_BOTTOM - 0.02, source_credit.upper(),
                transform=ax.transAxes, ha='left', va='bottom',
                color=theme.text_secondary, fontsize=10,
                alpha=0.5, fontfamily=theme.font_family, zorder=3)

        # ── Visible countries by smoothed fractional display rank ───────────
        display_ranks_all = {c: total_countries - r + 1
                             for c, r in zip(ranks.index, ranks.values)}
        # Keep countries within entry-fade band (dr <= n_on_screen + 1).
        visible = [c for c, dr in display_ranks_all.items()
                   if dr <= n_on_screen + 1.0]
        if not visible:
            return

        # Per-country weight (value/max, floored).
        def weight_of(c):
            v = float(scores[c])
            if not np.isfinite(v) or v <= 0:
                return row_min_weight
            return max(row_min_weight, v / max_val)

        weights = {c: weight_of(c) for c in visible}

        # Normalization: always sum weights of the top-n_on_screen countries by
        # smoothed rank. Using a 0.5-threshold could briefly include 9 or 11
        # countries during rank transitions, which rescales every row.
        top_n = sorted(weights.items(),
                       key=lambda kv: display_ranks_all[kv[0]])[:n_on_screen]
        w_norm = sum(w for _, w in top_n) or 1.0

        # Equal inter-row gaps: distribute card heights proportional to weight
        # over (race_height - n_on_screen * row_gap); gap itself is constant.
        avail_for_cards = max(race_height - n_on_screen * row_gap, race_height * 0.5)
        card_scale = avail_for_cards / w_norm
        max_card_h_render = max(weights.values()) * card_scale

        visible_ranks = np.array([display_ranks_all[c] for c in visible])
        visible_weights = np.array([weights[c] for c in visible])
        # Per-country total vertical footprint (card + one gap) used for y-placement.
        visible_footprint = visible_weights * card_scale + row_gap

        for country in visible:
            dr = display_ranks_all[country]
            weight = weights[country]
            value = float(scores[country])

            # Smoothstep-blended vertical footprint above this country.
            u = np.clip((dr - visible_ranks) + 0.5, 0.0, 1.0)
            fracs = u * u * (3 - 2 * u)
            y_center = race_top - float(np.sum(fracs * visible_footprint))

            card_h_i = weight * card_scale * race_intro_scale
            slot_h = card_h_i + row_gap

            entry_alpha = float(np.clip((n_on_screen + 0.5) - dr, 0.0, 1.0))
            int_rank = int(round(dr))
            s = card_h_i / max_card_h_render if max_card_h_render > 0 else 1.0

            # Rank-change flash
            if theme.rank_flash and entry_alpha >= 0.95:
                prev_r = state['prev_int_rank'].get(country)
                if prev_r is not None and prev_r != int_rank:
                    state['flash_start'][country] = state['frame']
                    state['flash_color'][country] = (
                        '#22c55e' if int_rank < prev_r else '#ef4444'
                    )
                state['prev_int_rank'][country] = int_rank
            flash_alpha = 0.0
            if theme.rank_flash and country in state['flash_start']:
                dt = state['frame'] - state['flash_start'][country]
                flash_alpha = max(0.0, 1.0 - dt / 20.0)

            color = country_colors.get(country, theme.accent_palette[0])
            flash_color = state['flash_color'].get(country, color)

            # Glass name box
            card_h = card_h_i
            card_y = y_center - card_h / 2
            name_box_x = columns.name_box_left
            name_box_w = columns.name_box_right - columns.name_box_left
            if theme.row_card:
                _rounded_rect(
                    ax, name_box_x, card_y, name_box_w, card_h,
                    radius_px=theme.row_card_corner_radius_px,
                    fig_w_px=FIG_W_PX,
                    facecolor=theme.row_card_color,
                    alpha=theme.row_card_opacity * entry_alpha, zorder=2,
                )
            if flash_alpha > 0:
                _rounded_rect(
                    ax, name_box_x, card_y, name_box_w, card_h,
                    radius_px=theme.row_card_corner_radius_px,
                    fig_w_px=FIG_W_PX,
                    facecolor=flash_color,
                    alpha=0.28 * flash_alpha * entry_alpha, zorder=2.5,
                )

            # In-row sparkline: this country's own history up to now, drawn
            # in the bottom band of the name card so it sits under the text.
            if card_h >= 0.022 and frame_idx >= 2:
                hist = country_hist[country][:frame_idx + 1]
                xs_hist = spark_xs_full[:frame_idx + 1]
                spark_bot = card_y + card_h * 0.08
                spark_top = card_y + card_h * 0.44
                ys_hist = spark_bot + hist * (spark_top - spark_bot)
                ax.plot(xs_hist, ys_hist,
                        color=theme.text_primary, linewidth=1.4,
                        alpha=0.55 * entry_alpha, zorder=2.6,
                        solid_capstyle='round')

            rank_fs = _lerp(14, 28, s)
            ax.text(columns.rank_x, y_center, str(int_rank),
                    ha='right', va='center',
                    color=theme.text_primary,
                    fontsize=rank_fs, fontweight='bold',
                    alpha=_lerp(0.55, 0.95, s) * entry_alpha,
                    fontfamily=theme.font_family, zorder=4)

            name_fs = _lerp(13, 21, s)
            label = display_name(country).upper()
            ax.text(columns.name_left, y_center, label,
                    ha='left', va='center',
                    color=theme.text_primary,
                    fontsize=name_fs, fontweight='bold',
                    alpha=_lerp(0.9, 1.0, s) * entry_alpha,
                    fontfamily=theme.font_family, zorder=5)

            # Flag
            icon = get_flag(country)
            flag_h = card_h_i * 0.96
            if icon is not None:
                ih, iw = icon.shape[0], icon.shape[1]
                draw_h = flag_h
                draw_w = draw_h * (iw / ih) * (FIG_H_PX / FIG_W_PX)

                fx = track_position(
                    value, max_val,
                    columns.track_left, columns.track_right,
                    draw_w,
                )
                fy = y_center - draw_h / 2

                if flash_alpha > 0:
                    _rounded_rect(
                        ax, fx - 0.01, fy - 0.005,
                        draw_w + 0.02, draw_h + 0.01,
                        radius_px=12, fig_w_px=FIG_W_PX,
                        facecolor=flash_color,
                        alpha=0.35 * flash_alpha * entry_alpha, zorder=4.5,
                    )

                img = icon
                if entry_alpha < 1.0:
                    img = img.copy()
                    img[..., 3] = (img[..., 3] * entry_alpha).astype(np.uint8)
                ax.imshow(img, extent=[fx, fx + draw_w, fy, fy + draw_h],
                          origin='upper', aspect='auto', zorder=5,
                          clip_on=False)

                value_fs = _lerp(14, 24, s)
                value_str = format_value(value, value_format).upper()
                gap = 0.012
                trailing_x = fx - gap
                approx_text_w = len(value_str) * (value_fs * 0.68 / FIG_W_PX)
                trailing_left = trailing_x - approx_text_w
                min_allowed_left = columns.track_left + 0.025

                if trailing_left >= min_allowed_left:
                    ax.text(trailing_x, y_center, value_str,
                            ha='right', va='center',
                            color=theme.text_primary,
                            fontsize=value_fs, fontweight='bold',
                            alpha=entry_alpha,
                            fontfamily=theme.font_family, zorder=5)
                else:
                    ax.text(fx + draw_w + gap, y_center, value_str,
                            ha='left', va='center',
                            color=theme.text_primary,
                            fontsize=value_fs, fontweight='bold',
                            alpha=entry_alpha,
                            fontfamily=theme.font_family, zorder=5)

    if preview_timeframe:
        y0, y1 = preview_timeframe
        idx = scores_df.index
        frames = [i for i, y in enumerate(idx) if y0 <= y <= y1]
        print(f"Preview mode: {len(frames)} frames ({y0}-{y1}) → {output_path}")
    else:
        frames = list(range(len(scores_df)))
        print(f"Rendering {len(frames)} frames → {output_path}")

    ani = animation.FuncAnimation(fig, update, frames=frames, interval=1000 / fps)
    writer = animation.FFMpegWriter(fps=fps, bitrate=bitrate)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ani.save(str(output_path), writer=writer)
    plt.close(fig)
    print(f"Done → {output_path}")


def validate_layout(columns: Columns = DEFAULT_COLUMNS) -> dict:
    assert columns.name_box_left < columns.name_box_right, "name box has non-positive width"
    assert columns.name_box_right < columns.track_left, (
        f"name_box_right {columns.name_box_right} overlaps track_left {columns.track_left}"
    )
    assert columns.track_right <= SAFE_RIGHT + 1e-9, (
        f"track_right {columns.track_right} exceeds Shorts safe zone {SAFE_RIGHT}"
    )
    bounds = {
        'name_box': (columns.name_box_left, columns.name_box_right),
        'gutter':   (columns.name_box_right, columns.track_left),
        'track':    (columns.track_left, columns.track_right),
    }
    return {k: (round(l * FIG_W_PX, 1), round(r * FIG_W_PX, 1))
            for k, (l, r) in bounds.items()}
