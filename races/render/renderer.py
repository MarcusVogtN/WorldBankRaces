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
from .big_movers import interpolate_and_rank, load_curated

plt.rcParams['animation.ffmpeg_path'] = _ffmpeg_plugin.get_exe()
sys.stdout.reconfigure(encoding='utf-8')


FIG_W_IN, FIG_H_IN = 10.8, 19.2
DPI = 100
FIG_W_PX = FIG_W_IN * DPI
FIG_H_PX = FIG_H_IN * DPI

AX_MARGIN = 0.02

SAFE_RIGHT = 0.86
SAFE_BOTTOM = 0.08   # just enough clearance for the source-credit line


def _draw_background(ax, theme: Theme, *, frame_idx: int = 0, fps: int = 30,
                     tension: float = 0.0, anim_cfg: dict | None = None,
                     cache: dict | None = None):
    bg = theme.background
    if isinstance(bg, tuple) and bg[0] == 'lava':
        _draw_lava_background(ax, bg, frame_idx=frame_idx, fps=fps,
                              tension=tension, anim_cfg=anim_cfg or {},
                              cache=cache if cache is not None else {})
        return
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


def _draw_lava_background(ax, bg: tuple, *, frame_idx: int, fps: int,
                          tension: float, anim_cfg: dict, cache: dict):
    """Animated 'blurred lava lamp' background with tension-driven brightness.

    Canvas regens every `regen_every` frames for speed; blob motion is smooth
    because canvas regen cadence is unrelated to the visible smoothness of a
    heavily-blurred image.
    """
    _, c_center, c_edge, c_blob = bg
    blob_count = int(anim_cfg.get('blob_count', 4))
    base_period = float(anim_cfg.get('base_period_seconds', 18.0))
    pulse_gain = float(anim_cfg.get('pulse_gain', 0.45))
    regen_every = int(anim_cfg.get('regen_every_frames', 6))

    key = frame_idx // max(1, regen_every)
    if cache.get('key') == key and 'img' in cache:
        ax.imshow(cache['img'], extent=[0, 1, 0, 1], aspect='auto', zorder=-10,
                  origin='upper', interpolation='bilinear')
        return

    center_rgb = np.array(_hex_to_rgb(c_center))
    edge_rgb = np.array(_hex_to_rgb(c_edge))
    blob_rgb = np.array(_hex_to_rgb(c_blob))

    h, w = 135, 240  # coarse; bilinear upscale handles smoothing
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx - (w - 1) / 2) / ((w - 1) / 2)
    ny = (yy - (h - 1) / 2) / ((h - 1) / 2)
    dist = np.sqrt(nx * nx + ny * ny)
    t_radial = np.clip(dist / 1.25, 0.0, 1.0)
    t_radial = t_radial * t_radial * (3 - 2 * t_radial)
    base = center_rgb[None, None, :] * (1 - t_radial[:, :, None]) + \
        edge_rgb[None, None, :] * t_radial[:, :, None]

    t_sec = frame_idx / max(1, fps)
    blob_field = np.zeros((h, w), dtype=np.float32)
    for i in range(blob_count):
        period = base_period * (0.78 + 0.22 * i)
        phase_x = i * 1.37
        phase_y = i * 2.11
        # Drift center in axes-fraction space [-0.55, 0.55].
        cx = 0.5 + 0.55 * np.sin(2 * np.pi * t_sec / period + phase_x)
        cy = 0.5 + 0.55 * np.cos(2 * np.pi * t_sec / period * 0.81 + phase_y)
        px = (xx / (w - 1)) - cx
        py = (yy / (h - 1)) - cy
        r2 = px * px + py * py
        sigma2 = 0.12  # ~radius 0.35
        blob_field += np.exp(-r2 / sigma2)

    blob_field /= max(1.0, blob_count * 0.9)  # keep in [0, ~1]
    intensity = 0.55 + pulse_gain * float(np.clip(tension, 0.0, 1.0))
    blob_alpha = np.clip(blob_field * intensity, 0.0, 0.85)[:, :, None]
    img = base * (1 - blob_alpha) + blob_rgb[None, None, :] * blob_alpha
    img = np.clip(img, 0.0, 1.0)

    cache['key'] = key
    cache['img'] = img
    ax.imshow(img, extent=[0, 1, 0, 1], aspect='auto', zorder=-10,
              origin='upper', interpolation='bilinear')


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
    title_cy = 0.915

    ax.text(title_cx, title_cy, main.upper(),
            transform=ax.transAxes, ha='center', va='center',
            color=theme.text_primary, fontsize=44 * title_scale, fontweight='bold',
            alpha=1.0, fontfamily=theme.font_family, zorder=3)

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
    # Shares the same back-ease-out bounce as the main title (title_scale) so
    # these header elements pop in rather than appearing full-size.
    label_x = 0.070
    label_y = header_y + header_h / 2
    prefix = 'TREND: '
    # matplotlib warns on zero-size text; floor scale to a tiny positive value.
    header_scale = max(title_scale, 1e-3)
    ax.text(label_x, label_y, prefix,
            transform=ax.transAxes, ha='left', va='center',
            color=theme.text_secondary, fontsize=16 * header_scale, fontweight='black',
            alpha=0.9, fontfamily=theme.font_family, zorder=3)
    ax.text(label_x + 0.095, label_y, trend_label.upper(),
            transform=ax.transAxes, ha='left', va='center',
            color=theme.text_primary, fontsize=21 * header_scale, fontweight='black',
            alpha=1.0, fontfamily=theme.font_family, zorder=3)

    # Live total on the right side of the header row.
    if total_value is not None and np.isfinite(total_value):
        ax.text(0.930, label_y, format_value(float(total_value), value_format).upper(),
                transform=ax.transAxes, ha='right', va='center',
                color=theme.text_primary, fontsize=26 * header_scale, fontweight='black',
                alpha=1.0, fontfamily=theme.font_family, zorder=3)

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
            alpha=0.75, zorder=3, solid_capstyle='round')

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
                alpha=0.35, zorder=3)
        ax.plot([dot_x], [dot_y], marker='o', markersize=7,
                color=theme.text_primary, markeredgewidth=0,
                alpha=1.0, zorder=4)

        # Current year floats above the indicator, tracking dot_x smoothly.
        # Instead of flipping ha=left/center/right at the plot edges (which
        # snapped visibly), use ha='left' with a clamped x so the text
        # visually centers over dot_x but slides to stay inside [plot_x0, plot_x1].
        year_str = str(year_int)
        year_fs = 24
        year_text_w = len(year_str) * year_fs * 0.68 / FIG_W_PX
        year_x = dot_x - year_text_w / 2
        year_x = max(plot_x0, min(plot_x1 - year_text_w, year_x))
        ax.text(year_x, guide_top + 0.008, year_str,
                transform=ax.transAxes, ha='left', va='bottom',
                color=theme.text_primary, fontsize=year_fs, fontweight='bold',
                alpha=1.0, fontfamily=theme.font_family, zorder=4)

    if start_year is not None:
        ax.text(plot_x0, plot_y0 - 0.012, str(start_year),
                transform=ax.transAxes, ha='left', va='top',
                color=theme.text_secondary, fontsize=17, fontweight='bold',
                alpha=0.85, fontfamily=theme.font_family, zorder=3)
    if end_year is not None:
        ax.text(plot_x1, plot_y0 - 0.012, str(end_year),
                transform=ax.transAxes, ha='right', va='top',
                color=theme.text_secondary, fontsize=17, fontweight='bold',
                alpha=0.85, fontfamily=theme.font_family, zorder=3)


# Spotlight card geometry (axes fractions). Spans rows 7-10's y band on the
# right side; flags of rows 7-10 cluster near track_left (smaller values), so
# the card has real estate to the right without colliding. Kept inside
# SAFE_RIGHT so social-button overlays stay clear.
SPOTLIGHT_X = 0.575
SPOTLIGHT_Y = 0.115
SPOTLIGHT_W = 0.245
SPOTLIGHT_H = 0.140


def _draw_spotlight(ax, theme: Theme, *, country: str, display_name_str: str,
                    rank_int: int, value: float, icon, alpha: float,
                    label_text: str, subtext: str, value_format: str):
    """Vertical stack: banner, name, [subtext], centered flag, value. Rank pinned top-right."""
    if alpha <= 0.0:
        return
    x, y, w, h = SPOTLIGHT_X, SPOTLIGHT_Y, SPOTLIGHT_W, SPOTLIGHT_H

    # Glass card
    if theme.row_card:
        _rounded_rect(
            ax, x, y, w, h,
            radius_px=theme.row_card_corner_radius_px,
            fig_w_px=FIG_W_PX,
            facecolor=theme.row_card_color,
            alpha=theme.row_card_opacity * alpha, zorder=4,
        )

    pad = 0.010
    cx = x + w / 2

    # Banner (top)
    banner_h = 0.020
    banner_y = y + h - banner_h - pad * 0.2
    ax.text(cx, banner_y + banner_h / 2, label_text,
            transform=ax.transAxes, ha='center', va='center',
            color=theme.text_secondary, fontsize=9, fontweight='black',
            alpha=0.9 * alpha, fontfamily=theme.font_family, zorder=5)

    # Rank pinned to top-right of card.
    ax.text(x + w - pad, banner_y + banner_h / 2, f'#{rank_int}',
            transform=ax.transAxes, ha='right', va='center',
            color=theme.text_primary, fontsize=12, fontweight='black',
            alpha=alpha, fontfamily=theme.font_family, zorder=5)

    # Name (centered, directly under banner).
    name_label = display_name_str.upper()
    if len(name_label) > 16:
        name_label = name_label[:15] + '…'
    name_y = banner_y - 0.006
    ax.text(cx, name_y, name_label,
            transform=ax.transAxes, ha='center', va='top',
            color=theme.text_primary, fontsize=13, fontweight='black',
            alpha=alpha, fontfamily=theme.font_family, zorder=5)

    # Subtext (optional, under name).
    has_subtext = bool(subtext)
    subtext_y = name_y - 0.018
    if has_subtext:
        ax.text(cx, subtext_y, subtext.upper(),
                transform=ax.transAxes, ha='center', va='top',
                color=theme.text_secondary, fontsize=9, fontweight='bold',
                alpha=0.9 * alpha, fontfamily=theme.font_family, zorder=5)

    # Value (bottom, centered).
    value_y = y + pad * 0.4 + 0.002
    ax.text(cx, value_y, format_value(value, value_format).upper(),
            transform=ax.transAxes, ha='center', va='bottom',
            color=theme.text_primary, fontsize=15, fontweight='black',
            alpha=alpha, fontfamily=theme.font_family, zorder=5)

    # Flag centered between name/subtext and value.
    flag_top = (subtext_y - 0.008) if has_subtext else (name_y - 0.010)
    flag_bot = value_y + 0.005
    flag_box_h = max(0.02, flag_top - flag_bot)
    flag_cy = (flag_top + flag_bot) / 2
    flag_cx = cx
    if icon is not None and flag_box_h > 0:
        ih, iw = icon.shape[0], icon.shape[1]
        # Fit within both a max width and the available height.
        max_flag_w = w - 2 * pad - 0.020
        draw_h = flag_box_h
        draw_w = draw_h * (iw / ih) * (FIG_H_PX / FIG_W_PX)
        if draw_w > max_flag_w:
            draw_w = max_flag_w
            draw_h = draw_w * (ih / iw) * (FIG_W_PX / FIG_H_PX)
        draw_h *= 0.70
        draw_w *= 0.70
        fx = flag_cx - draw_w / 2
        fy = flag_cy - draw_h / 2
        img = icon
        if alpha < 1.0:
            img = img.copy()
            img[..., 3] = (img[..., 3] * alpha).astype(np.uint8)
        ax.imshow(img, extent=[fx, fx + draw_w, fy, fy + draw_h],
                  origin='upper', aspect='auto', zorder=5, clip_on=False)


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
    scores_df, ranks_df = interpolate_and_rank(data, steps_per_year, smooth_a, smooth_b)
    country_colors = assign_colors(data.columns, theme.accent_palette)

    # ── Background animation (lava-lamp + tension pulse) ─────────────────
    bg_anim_cfg = render_cfg.get('background_animation', {}) or {}
    bg_anim_enabled = bool(bg_anim_cfg.get('enabled', False)) and \
        isinstance(theme.background, tuple) and theme.background[0] == 'lava'
    _bg_cache: dict = {}
    if bg_anim_enabled:
        rank_mat = ranks_df.to_numpy(dtype=np.float32)
        drank = np.abs(np.diff(rank_mat, axis=0, prepend=rank_mat[:1]))
        raw = np.sum(drank, axis=1)
        win = max(1, int(fps))
        tension_arr = pd.Series(raw).rolling(win, min_periods=1).sum().to_numpy()
        tmax = float(tension_arr.max()) or 1.0
        tension_arr = tension_arr / tmax
    else:
        tension_arr = None

    total_countries = len(data.columns)

    # Precompute total-trend series (sum across countries per frame).
    if show_total_trend:
        trend_series = scores_df.fillna(0).sum(axis=1).to_numpy()
    else:
        trend_series = None

    # ── Spotlight (right-side callout for significant non-top-N mover) ──
    spotlight_cfg = render_cfg.get('spotlight', {}) or {}
    spotlight_enabled = bool(spotlight_cfg.get('enabled', False))
    spotlight_deltas = None
    spotlight_signed_deltas = None
    rate_window_years = float(spotlight_cfg.get('rate_window_years', 3)) if spotlight_cfg else 3.0
    spotlight_threshold = 0.0  # absolute |Δvalue| floor, computed from data
    spotlight_min_screen_frames = int(
        float(spotlight_cfg.get('min_screen_seconds', 2.0)) * fps)
    spotlight_fade_frames = int(spotlight_cfg.get('fade_frames', 12))
    spotlight_label_text = str(spotlight_cfg.get('label', 'BIG MOVER')).upper()
    # How strongly a challenger must outscore the current pick to trigger an
    # early switch (before min_screen_seconds elapses). Higher = stickier.
    spotlight_switch_ratio = float(spotlight_cfg.get('switch_ratio', 2.0))
    # Curated mode: if a curated_file is configured and parses, skip the
    # percentile scoring and drive the spotlight straight from the kept list.
    spotlight_curated: list = []
    curated_file_raw = spotlight_cfg.get('curated_file')
    if spotlight_enabled and curated_file_raw:
        curated_path = Path(curated_file_raw)
        if not curated_path.is_absolute():
            curated_path = Path.cwd() / curated_path
        if curated_path.exists():
            spotlight_curated = load_curated(curated_path)
            print(f"Spotlight curated mode · {len(spotlight_curated)} kept event(s) "
                  f"from {curated_path}")
        else:
            print(f"[spotlight] curated_file {curated_path} not found — "
                  "falling back to auto-selection.")

    if spotlight_enabled and not spotlight_curated:
        rate_window_years = float(spotlight_cfg.get('rate_window_years', 3))
        rate_window_frames = max(1, int(rate_window_years * steps_per_year))
        spotlight_signed_deltas = scores_df.diff(periods=rate_window_frames)
        spotlight_deltas = spotlight_signed_deltas.abs()
        # Dataset-wide threshold: only the top (100 - percentile)% of all
        # |Δvalue| observations across every country/frame ever qualify. This
        # keeps the callout reserved for genuinely huge moves instead of
        # firing on mid-level fluctuations in every era.
        percentile = float(spotlight_cfg.get('percentile', 99.7))
        flat = spotlight_deltas.to_numpy().ravel()
        flat = flat[np.isfinite(flat) & (flat > 0)]
        if flat.size > 0:
            spotlight_threshold = float(np.percentile(flat, percentile))
        # Legacy absolute floor (raw |Δ|). If set, take the max of the two.
        min_abs = spotlight_cfg.get('min_abs_delta')
        if min_abs is not None:
            spotlight_threshold = max(spotlight_threshold, float(min_abs))
        print(f"Spotlight enabled · percentile={percentile} threshold=|Δ|≥{spotlight_threshold:,.0f}")

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
        'spotlight_target': None,
        'spotlight_adopted_frame': -10**9,
        'spotlight_prev': None,
        'spotlight_prev_start': -10**9,
        'spotlight_active_label': None,
        'spotlight_prev_label': None,
        'spotlight_active_subtext': '',
        'spotlight_prev_subtext': '',
    }

    start_year = int(float(data.index.min()))
    end_year = int(float(data.index.max()))

    n_frames_total = len(scores_df)

    def update(frame_idx):
        ax.clear()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        if bg_anim_enabled:
            t_val = float(tension_arr[frame_idx]) if tension_arr is not None else 0.0
            _draw_background(ax, theme, frame_idx=frame_idx, fps=fps,
                             tension=t_val, anim_cfg=bg_anim_cfg,
                             cache=_bg_cache)
        else:
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

        # Per-country weight (value/max, floored).
        def weight_of(c):
            v = float(scores[c])
            if not np.isfinite(v) or v <= 0:
                return row_min_weight
            return max(row_min_weight, v / max_val)

        # Normalization denominator: the *true* top-N by smoothed rank, drawn
        # from all countries (not the entry-fade subset). Slicing top_n out of
        # an already-filtered visible set caused a one-frame count mismatch
        # whenever a country's smoothed dr flickered across the visibility
        # threshold (e.g. Canada around 1991), which rescaled every row.
        true_top_n = sorted(display_ranks_all.keys(),
                            key=lambda c: display_ranks_all[c])[:n_on_screen]
        w_norm = sum(weight_of(c) for c in true_top_n) or 1.0

        # Keep countries within entry-fade band (dr <= n_on_screen + 1.2). The
        # small extra margin keeps a rank-crossing country drawn through its
        # transition so rows 8-10 don't visibly re-stack.
        visible = [c for c, dr in display_ranks_all.items()
                   if dr <= n_on_screen + 1.2]
        if not visible:
            return

        weights = {c: weight_of(c) for c in visible}

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
                min_allowed_left = columns.track_left + 0.025

                # Decide the side using the *final* (non-intro-scaled) geometry so the
                # value text doesn't flip sides as the row scales up during intro.
                draw_h_final = (card_h_i / race_intro_scale) * 0.96 if race_intro_scale > 0 else draw_h
                draw_w_final = draw_h_final * (iw / ih) * (FIG_H_PX / FIG_W_PX)
                fx_final = track_position(
                    value, max_val,
                    columns.track_left, columns.track_right,
                    draw_w_final,
                )
                s_final = (card_h_i / race_intro_scale) / max_card_h_render if (
                    race_intro_scale > 0 and max_card_h_render > 0) else s
                value_fs_final = _lerp(14, 24, s_final)
                approx_text_w_final = len(value_str) * (value_fs_final * 0.68 / FIG_W_PX)
                place_left = (fx_final - gap - approx_text_w_final) >= min_allowed_left

                trailing_x = fx - gap
                if place_left:
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

        # ── Spotlight: curated-mode OR auto-select non-top-N mover ──────
        if spotlight_enabled:
            cur = state['spotlight_target']
            active_label = spotlight_label_text

            def _switch(new_target, *, label=None, subtext=''):
                if cur is not None:
                    state['spotlight_prev'] = cur
                    state['spotlight_prev_start'] = state['frame']
                    state['spotlight_prev_label'] = state.get('spotlight_active_label',
                                                              spotlight_label_text)
                    state['spotlight_prev_subtext'] = state.get('spotlight_active_subtext', '')
                state['spotlight_target'] = new_target
                state['spotlight_adopted_frame'] = state['frame']
                state['spotlight_active_label'] = label or spotlight_label_text
                state['spotlight_active_subtext'] = subtext or ''

            if spotlight_curated:
                # Curated mode: the active event is determined purely by the
                # current year. Whichever kept event covers `year_float` wins;
                # earliest start_year breaks ties.
                year_float = float(scores_df.index[frame_idx])
                top_n_set = set(true_top_n)
                active = None
                for ev in spotlight_curated:
                    if ev.start_year <= year_float <= ev.end_year:
                        # Don't show a curated event while its subject is on-screen.
                        if ev.country in top_n_set:
                            continue
                        active = ev
                        break
                active_country = active.country if active else None
                active_label = (active.label_override if active and active.label_override
                                else spotlight_label_text)
                active_subtext = active.subtext if active else ''
                if active_country != cur:
                    _switch(active_country, label=active_label, subtext=active_subtext)
            elif spotlight_deltas is not None:
                # Auto-select mode: same logic as before — biggest qualifying
                # |Δ| per frame, sticky via screen-hold and switch-ratio.
                top_n_set = set(true_top_n)
                row = spotlight_deltas.iloc[frame_idx]
                best_c, best_delta = None, 0.0
                for c in row.index:
                    if c in top_n_set:
                        continue
                    d = float(row[c]) if np.isfinite(row[c]) else 0.0
                    if d <= 0:
                        continue
                    if d > best_delta:
                        best_c, best_delta = c, d
                qualifies = best_c is not None and best_delta >= spotlight_threshold

                cur_delta = 0.0
                if cur is not None and cur in row.index:
                    cv = float(row[cur]) if np.isfinite(row[cur]) else 0.0
                    cur_delta = cv if cv > 0 else 0.0
                held = (state['frame'] - state['spotlight_adopted_frame']) < spotlight_min_screen_frames

                def _auto_subtext(country):
                    if country is None or spotlight_signed_deltas is None:
                        return ''
                    try:
                        signed = float(spotlight_signed_deltas.iloc[frame_idx][country])
                        v_now = float(scores_df.iloc[frame_idx][country])
                    except (KeyError, IndexError, ValueError):
                        return ''
                    if not np.isfinite(signed) or not np.isfinite(v_now):
                        return ''
                    v_before = v_now - signed
                    if v_before <= 0:
                        return ''
                    pct = abs(signed) / v_before * 100.0
                    direction = 'UP' if signed > 0 else 'DOWN'
                    yrs = int(round(rate_window_years))
                    return f"{direction} {pct:.0f}% IN {yrs}Y"

                if cur is None:
                    if qualifies:
                        _switch(best_c, subtext=_auto_subtext(best_c))
                elif not held:
                    if cur_delta < spotlight_threshold and qualifies:
                        _switch(best_c, subtext=_auto_subtext(best_c))
                    elif cur_delta < spotlight_threshold:
                        _switch(None)
                    elif best_c != cur and qualifies and best_delta > cur_delta * spotlight_switch_ratio:
                        _switch(best_c, subtext=_auto_subtext(best_c))

            # ── Draw current + previous (shared across both modes) ──────
            cur = state['spotlight_target']
            if cur is not None:
                since = state['frame'] - state['spotlight_adopted_frame']
                alpha_in = min(1.0, max(0.0, since / max(1, spotlight_fade_frames)))
                v = float(scores[cur]) if np.isfinite(scores[cur]) else 0.0
                dr_cur = display_ranks_all.get(cur)
                rk = int(round(dr_cur)) if dr_cur is not None else 0
                _draw_spotlight(ax, theme, country=cur,
                                display_name_str=display_name(cur),
                                rank_int=rk, value=v, icon=get_flag(cur),
                                alpha=alpha_in,
                                label_text=state.get('spotlight_active_label',
                                                     spotlight_label_text),
                                subtext=state.get('spotlight_active_subtext', ''),
                                value_format=value_format)

            prev = state['spotlight_prev']
            if prev is not None:
                since_out = state['frame'] - state['spotlight_prev_start']
                alpha_out = 1.0 - min(1.0, max(0.0, since_out / max(1, spotlight_fade_frames)))
                if alpha_out > 0.0 and prev != state['spotlight_target']:
                    v = float(scores[prev]) if prev in scores.index and np.isfinite(scores[prev]) else 0.0
                    dr_prev = display_ranks_all.get(prev)
                    rk = int(round(dr_prev)) if dr_prev is not None else 0
                    _draw_spotlight(ax, theme, country=prev,
                                    display_name_str=display_name(prev),
                                    rank_int=rk, value=v, icon=get_flag(prev),
                                    alpha=alpha_out,
                                    label_text=state.get('spotlight_prev_label',
                                                         spotlight_label_text),
                                    subtext=state.get('spotlight_prev_subtext', ''),
                                    value_format=value_format)
                else:
                    state['spotlight_prev'] = None

    if preview_timeframe:
        y0, y1 = preview_timeframe
        idx = scores_df.index
        frames = [i for i, y in enumerate(idx) if y0 <= y <= y1]
        print(f"Preview mode: {len(frames)} frames ({y0}-{y1}) → {output_path}")
    else:
        frames = list(range(len(scores_df)))
        print(f"Rendering {len(frames)} frames → {output_path}")

    end_hold_seconds = float(render_cfg.get('end_hold_seconds', 0.0))
    if end_hold_seconds > 0 and frames:
        hold_frames = int(round(end_hold_seconds * fps))
        frames = frames + [frames[-1]] * hold_frames
        print(f"Holding last frame for {end_hold_seconds}s ({hold_frames} frames)")

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
