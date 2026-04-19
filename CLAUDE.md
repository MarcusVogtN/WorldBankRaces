# CLAUDE.md

## Pipeline

```bash
python run.py                     # render from cache
python run.py --refetch           # re-download source data + flags
python run.py --validate-layout   # print column bounds before rendering
```

Outputs land in `output/`; intermediate data (CSV, flags) goes to `cache/`.

## Dependencies

```bash
pip install wbgapi pycountry pandas requests urllib3 numpy matplotlib Pillow imageio[ffmpeg]
```

FFmpeg must be installed and on PATH.

## Package layout

```
races/
├── pipeline.py              orchestrates source → assets → render
├── util.py                  safe_filename, format_value, DISPLAY_NAMES
├── sources/
│   ├── base.py              DataSource ABC + SourceResult dataclass
│   └── world_bank.py        WorldBankSource (wbgapi + pycountry)
├── assets/
│   ├── base.py              AssetProvider ABC
│   └── flags.py             FlagProvider (flagcdn.com + aspect normalization)
└── render/
    ├── theme.py             Theme dataclass, GLASS_DARK + FLAT_LIGHT, assign_colors
    ├── layout.py            Columns, VerticalLayout, track_position, smoothstep
    └── renderer.py          main FuncAnimation update loop
```

## config.json schema

| Field | Purpose |
|---|---|
| `video_title` | Main title. Any `" (…)"` suffix (e.g. a year range) is stripped — the range appears at the trend-line corners instead |
| `value_format` | `"currency"` (prepends `$`) or any other string |
| `output_filename` | `.mp4` name, written under `output/` |
| `theme` | Key from `races.render.theme.THEMES` (`glass_dark` default) |
| `preview_timeframe` | `[y0, y1]` to render a short clip; `null` for full video |
| `source.type` | `"world_bank"` (only source implemented) |
| `source.indicator` | World Bank indicator code (e.g. `MS.MIL.XPND.CD`) |
| `source.timeframe` | `[start_year, end_year]` |
| `assets.type` | `"flags"` (only provider implemented) |
| `assets.top_n_to_fetch` | How many flags to download (top by final-year value) |
| `render.top_n_on_screen` | Visible rows |
| `render.steps_per_year` | Sub-frames interpolated between years (60 = 2 s/year at 30 fps) |
| `render.fps`, `render.bitrate` | Video encoding |
| `render.rank_smooth_window_a` / `_b` | Rolling-window sizes for rank smoothing; larger = slower, more gliding transitions |
| `render.race_top`, `render.race_bottom` | Axes-fraction bounds for the race area |
| `render.row_min_weight` | Floor weight for a row (prevents bottom rank from becoming unreadable). Default `0.35` |
| `render.show_total_trend` | Draw the total-sum sparkline above the race |
| `render.trend_label` | Bold label rendered after the `TREND:` prefix above the total trend line |
| `render.flag_corner_radius_frac` | Rounded-corner radius as fraction of flag short side. `0` disables rounding |

## Architecture notes

**Value-weighted slot heights** (`renderer.update`): each visible row's height is proportional to `max(row_min_weight, value / max_value)`, normalized so the top `n_on_screen` rows fill the race area. Flag size and font sizes scale with `slot_h / max_slot_h`, so rank #1 is visibly dominant.

**Gliding rank transitions** (`renderer.update`): a country's `y_center` is computed from smoothstep-blended cumulative weight of all other visible countries by their fractional display rank — `cum_above = Σ smoothstep((dr_target − dr_other) + 0.5) × weight_other`. When two countries swap, their fractional ranks cross smoothly and they glide through each other's y-positions rather than popping. Transition speed is governed by `rank_smooth_window_a/_b`.

**Fixed-column layout with name-box barrier**: `[name_box][gutter][track]` (see `layout.DEFAULT_COLUMNS`). The name box is a glassmorphic card holding rank + country name; the gutter physically separates it from the flag track so value text can never cross into the name column. `run.py --validate-layout` asserts this and prints pixel bounds.

**Value text placement** (`renderer.update`): value trails left of the flag by default; if the estimated text width would cross `track_left + pad`, it flips to the right of the flag instead. Collisions with the name box are geometrically impossible.

**Rounded flag corners** (`renderer._round_image_corners`): applies a radial alpha mask to each RGBA flag (cached per country). `flag_corner_radius_frac` is a fraction of the flag's short side.

**Rank-change flash** (`renderer.update`): on integer-rank change, the country's name box and flag glow for ~20 frames. Color is semantic: green `#22c55e` when the country moved **up** (overtook) and red `#ef4444` when it moved **down** (was overtaken). Tracked via `state['flash_start']` + `state['flash_color']`.

**Per-country in-row sparklines** (`renderer.update`): each visible row draws a white, growing sparkline of that country's own history (normalized to its own max) inside the bottom ~35% of its name card. Precomputed once as `country_hist[c] = vals / vals.max()`, and drawn up to `frame_idx` each frame. Skipped when `card_h < 0.022` so compressed bottom rows stay clean.

**Header layout**: centered title card at the top (height tuned to hug the text). Below it, a single header row shows `TREND:` (secondary color) + `trend_label` (primary color, heavier weight) on the left — no card, no year counter on the right. Then a wide borderless total-sum sparkline (`Σ value` per frame) with a vertical guide + dot marking the current position. The **current year** floats directly above the indicator dot and tracks its x-position (alignment flips to `left`/`right` near the plot edges so it never clips). The **start/end years** sit at the trend line's bottom-left and bottom-right corners. When `show_total_trend` is false, a centered year card is drawn as a fallback.

**Equal top-N normalization** (`renderer.update`): row slot heights are normalized against the top `n_on_screen` countries by smoothed rank (`sorted(weights, key=dr)[:n]`), not a 0.5-threshold. This guarantees exactly 10 rows' worth of weight every frame, so rank swaps glide without the whole race area rescaling.

**Axes coordinate system**: `xlim = ylim = (0, 1)`. All positioning uses axes fractions. `_rounded_rect()` converts pixel radii to data units via `radius_px / FIG_W_PX`.

**Flag aspect normalization** (`assets/flags.py::_normalize_aspect`): pads each flag with transparent pixels to a 5:3 canvas. The flag design is never cropped or stretched — only padded.

**Color stability**: `assign_colors()` uses MD5 hash of the country name modulo palette length, so the same country always gets the same color across re-renders.

**Value formatting** (`util.format_value`): all tiers round to `:.0f` (e.g. `$1 T`, `$450 B`). Dropping decimals keeps the ticker readable during interpolation.

**DISPLAY_NAMES** (`util.py`): overrides for verbose World Bank country names (`"Russian Federation"` → `"Russia"`). Add entries for new countries that exceed 22 chars.

**Themes** (`render/theme.py`): swap visual style via config. `GLASS_DARK` uses a vertical gradient background plus glassy translucent cards; `FLAT_LIGHT` is a minimal light-mode alternative.

**Plugin seams**: add a new data source by subclassing `DataSource` and registering it in `races/sources/__init__.py::REGISTRY`. Add a new asset provider by subclassing `AssetProvider` and registering it. The renderer only calls `load_icon(name)` → RGBA or None, so it's source-agnostic.
