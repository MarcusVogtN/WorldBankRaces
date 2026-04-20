# CLAUDE.md

## Pipeline

```bash
python run.py                     # render from cache
python run.py --refetch           # re-download source data + flags
python run.py --validate-layout   # print column bounds before rendering
python run.py --extract-movers    # write cache/big_movers.json and exit (no render)
python run.py --generate-narration  # LLM script + ElevenLabs TTS → cache/narration.{json,wav}
python run.py --mux-narration     # mux cache/narration.wav onto output/*.mp4 → *_narrated.mp4
```

Narration env vars (auto-loaded from `./.env` at repo root if present): `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`. Typical full flow:
`--extract-movers` → hand-curate `cache/big_movers.json` → `--generate-narration` (read + optionally edit `cache/narration.json`, re-run to re-synthesize only changed cues) → plain `python run.py` → `--mux-narration`.

Outputs land in `output/`; intermediate data (CSV, flags) goes to `cache/`.

## Dependencies

```bash
pip install wbgapi pycountry pandas requests urllib3 numpy matplotlib Pillow imageio[ffmpeg] anthropic elevenlabs pydub python-dotenv
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
| `render.spotlight.enabled` | When true, draws a right-side callout for the non-top-N country with the biggest rate-of-change (default `false`) |
| `render.spotlight.label` | Banner text shown in the callout (default `"BIG MOVER"`) |
| `render.spotlight.rate_window_years` | Window in years used to compute \|Δvalue\| (default `3`) |
| `render.spotlight.percentile` | Percentile of all positive \|Δvalue\| observations across the whole dataset that sets the qualifying threshold — `99.7` means only the top 0.3% of moves ever fire (default `99.7`) |
| `render.spotlight.min_abs_delta` | Optional absolute \|Δvalue\| floor (raw units). Final threshold is `max(percentile, min_abs_delta)` |
| `render.spotlight.switch_ratio` | How strongly a challenger must outscore the current pick to trigger an early switch before `min_screen_seconds` elapses (default `2.0`) |
| `render.spotlight.min_screen_seconds` | Minimum on-screen hold after adoption before the target can switch or drop (default `4.0`) |
| `render.spotlight.fade_frames` | Cross-fade length when the target changes (default `12`) |
| `render.spotlight.curated_file` | Path to a curated `big_movers.json`. When set and parseable, auto-selection is skipped and only kept events appear (default `null`) |
| `render.spotlight.event_threshold_percentile` | Percentile used by `--extract-movers` when emitting candidate events — typically lower than `percentile` so the reviewer sees more options (default `95.0`) |
| `render.spotlight.event_merge_gap_years` | Gap in years below which adjacent runs for the same country merge into one event during extraction (default `2.0`) |
| `render.spotlight.max_events` | Cap on how many candidate events are written to `big_movers.json` (default `50`) |
| `render.narration.enabled` | Reserved; flags in `run.py` drive narration directly. When false, narration files still generate if you pass the flag. |
| `render.narration.model` | Anthropic model id (default `claude-opus-4-7`) |
| `render.narration.tts.voice_id` | ElevenLabs voice id (required for `--generate-narration`) |
| `render.narration.tts.model_id` | ElevenLabs model (default `eleven_turbo_v2_5`) |
| `render.narration.tts.stability` / `style` / `similarity_boost` | ElevenLabs voice settings |
| `render.narration.tone` | Free-form persona description fed into the system prompt |
| `render.narration.words_per_second` | Used to sanity-check cue text length (default `2.7`) |
| `render.narration.min_gap_seconds` | Minimum silence the LLM must leave between cues (default `1.5`) |
| `render.narration.max_speech_coverage` | Hard cap on (total speech) / (video duration) (default `0.6`) |
| `render.narration.suggest_trim` | If true, LLM may emit a `suggested_trim` when the early years are flat. Never auto-applied. |

## Architecture notes

**Value-weighted slot heights** (`renderer.update`): each visible row's height is proportional to `max(row_min_weight, value / max_value)`, normalized so the top `n_on_screen` rows fill the race area. Flag size and font sizes scale with `slot_h / max_slot_h`, so rank #1 is visibly dominant.

**Gliding rank transitions** (`renderer.update`): a country's `y_center` is computed from smoothstep-blended cumulative weight of all other visible countries by their fractional display rank — `cum_above = Σ smoothstep((dr_target − dr_other) + 0.5) × weight_other`. When two countries swap, their fractional ranks cross smoothly and they glide through each other's y-positions rather than popping. Transition speed is governed by `rank_smooth_window_a/_b`.

**Fixed-column layout with name-box barrier**: `[name_box][gutter][track]` (see `layout.DEFAULT_COLUMNS`). The name box is a glassmorphic card holding rank + country name; the gutter physically separates it from the flag track so value text can never cross into the name column. `run.py --validate-layout` asserts this and prints pixel bounds.

**Value text placement** (`renderer.update`): value trails left of the flag by default; if the estimated text width would cross `track_left + pad`, it flips to the right of the flag instead. Collisions with the name box are geometrically impossible. The side decision uses the *final* (non-intro-scaled) flag width and font size, so the text lands on the correct side from the first frame and never flips sides while the row bounces in.

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

**Themes** (`render/theme.py`): swap visual style via config. `GLASS_DARK` uses a radial vignette background (lighter center fading to pure black at the edges) plus glassy translucent cards; `FLAT_LIGHT` is a minimal light-mode alternative. The background spec supports three forms: solid hex (`"#..."`), `("gradient", c_top, c_bottom)` vertical gradient, or `("radial", c_center, c_edge)` elliptical vignette.

**Curated spotlight events** (`races/render/big_movers.py`): two-step workflow for hand-picking which big movers appear in the video.

1. `python run.py --extract-movers` runs the data + rank pipeline (reusing `big_movers.interpolate_and_rank`, also used by the renderer so the signal pipeline is identical), detects contiguous runs where a non-top-N country's windowed `|Δvalue|` exceeds `event_threshold_percentile`, merges runs within `event_merge_gap_years`, caps at `max_events`, and writes `cache/big_movers.json`. Each entry includes a data-derived `description_hint` (growth multiplier, rank climb, "top-5 move in the dataset") so a reviewing LLM has context.
2. The reviewer (LLM or human) flips `keep: true/false` per event, optionally overrides `label_override` (banner text) or trims `start_year`/`end_year`. Freeform `note` is preserved across re-runs.
3. Point `render.spotlight.curated_file` at the JSON. The renderer loads kept events via `big_movers.load_curated`; at each frame it picks the earliest-starting event whose `[start_year, end_year]` covers the current year and whose subject is not already in the top-N. Auto-selection (percentile/switch-ratio/screen-hold) is bypassed, but `fade_frames` still drives the cross-fade when the active event changes. Missing or malformed curated files fall back to auto-selection with a warning instead of crashing.

JSON schema (per event): `id`, `country`, `display_name`, `start_year`, `peak_year`, `end_year`, `delta`, `delta_pct`, `value_before`, `value_at_peak`, `rank_before`, `rank_at_peak`, `direction` (`"up"`/`"down"`), `description_hint`, `keep` (null until reviewed), `label_override`, `note`.

**Spotlight callout** (`renderer._draw_spotlight` + the spotlight block in `renderer.update`): when `render.spotlight.enabled` is true, a tall glass card at `x ∈ [0.575, 0.820]`, `y ∈ [0.115, 0.295]` (sits above `race_bottom = 0.11` so it never overlaps rank 10, spanning the y band of rows 7–9) surfaces a non-top-N country with a significant rate-of-change. Score is the raw `|scores_df[c].diff(rate_window_frames)|`, restricted to countries outside `true_top_n`. Qualifying threshold is computed once at startup as `np.percentile(all_positive_deltas, percentile)` across every country × frame observation, so only the top (100−percentile)% of moves in the entire dataset ever fire. The adopted target is held for at least `min_screen_seconds`; early switches require a challenger with `|Δ| > switch_ratio × current_|Δ|`. Transitions cross-fade over `fade_frames`. Layout inside the card: top banner (`label`), country name centered, optional subtext line (e.g. `"DOWN 91% IN 4Y"` — from `subtext_override` in the curated JSON, or derived from `direction` + `delta_pct` + span) between name and flag, flag centered, value at the bottom, rank pinned to the top-right corner. The card sits well inside `SAFE_RIGHT = 0.86`, preserving the YouTube Shorts social-button zone. Flags are reused via `get_flag(country)`; if the asset provider hasn't fetched the flag (bump `assets.top_n_to_fetch` to include deeper ranks), the callout renders text-only.

**Top-N normalization stability** (`renderer.update`): `w_norm` sums the weights of the *true* top-N countries by smoothed rank (sourced from `display_ranks_all`, not from the entry-fade-filtered `visible` list). Slicing the denominator from `visible` used to produce one-frame row rescaling when a country's smoothed `dr` flickered across the `dr ≤ n + 1` threshold (e.g. Canada around 1991). The visibility band itself is nudged to `dr ≤ n + 1.2` so a rank-crossing country stays drawn through its transition.

**Narration** (`races/narration/`): optional sports-commentator voiceover. `stats.build_stat_pack` and `timeline.build_timeline` produce a curated stats menu + frame-keyed event spine (reusing `big_movers.interpolate_and_rank` so timings match the render exactly). `script.generate_script` calls Claude (`claude-opus-4-7`) with prompt caching on the system prompt and a `emit_script` tool-use schema that forces structured output — cues are non-overlapping `(start_seconds, end_seconds, text, kind, anchor)` and may include a `suggested_trim` when `early_boring.score` is high. The system prompt enforces plain 12-year-old-reading-level language and expects a one-sentence real-world "why" for significant events (e.g. "the Soviet Union just collapsed"), with hard rules against dwelling on casualties/conflicts/current figures. `voice.synthesize` calls ElevenLabs per cue, caches clips by `sha256(text|voice_id|model_id)[:16]` under `cache/narration_clips/`, and mixes them onto a silent full-length base WAV with pydub → `cache/narration.wav`. `mux.mux_audio` uses `imageio_ffmpeg.get_exe()` to AAC-encode + mux onto the rendered mp4 via `-c:v copy -map 0:v:0 -map 1:a:0 -shortest`. Editing a single cue's text in `cache/narration.json` and re-running `--generate-narration` only re-synthesizes that cue. Each run's script carries `meta.generated_at` (ISO-8601 UTC); on every subsequent `--generate-narration`, the existing `cache/narration.json` + `cache/narration.wav` are copied to `cache/narration_archive/narration_<timestamp>.{json,wav}` before being overwritten — previous takes are never lost.

**Animated background** (`renderer._draw_lava_background`): opt-in "blurred lava lamp" effect. Enable by selecting the `glass_dark_lava` theme (or any theme whose `background` is `("lava", c_center, c_edge, c_blob)`) and setting `render.background_animation.enabled = true`. Config knobs: `blob_count` (3–5 works), `base_period_seconds` (drift period of the slowest blob), `pulse_gain` (tension-brightness scale), `regen_every_frames` (canvas cache cadence, default 6). Tension per frame is a rolling sum of `|Δranks_df|` over one second, normalized to `[0,1]` — quiet stretches look steady, big-mover years pulse brighter. Canvas is rendered at 240×135 and bilinear-upscaled, so regen cost stays cheap.

**Intro animations** (`renderer._draw_title_year_trend` + `renderer.update`): a single back-ease-out bounce (`title_scale`, driven by `t_title = frames/18`) scales in four groups of elements in place. (1) Main title scales around its center. (2) Each flag-race row scales vertically via `race_intro_scale` applied to `card_h_i`, which cascades to flag size and font sizes — y-centers stay anchored so rows grow in place rather than sliding. (3) The total trend line scales vertically around `plot_y0` (baseline), with the current-position dot, vertical guide, and floating year-above-dot label all following the pop. The trend line also keeps a separate left-to-right draw-in sweep driven by `t_draw`. (4) The header row `TREND:` prefix, `trend_label`, and live total-value text scale via `fontsize *= title_scale` (floored at `1e-3` to avoid matplotlib zero-size warnings on frame 0). All these elements render at full opacity — no alpha fade-in. Only the bottom source-credit line keeps the legacy `t_ease` alpha fade.

**Plugin seams**: add a new data source by subclassing `DataSource` and registering it in `races/sources/__init__.py::REGISTRY`. Add a new asset provider by subclassing `AssetProvider` and registering it. The renderer only calls `load_icon(name)` → RGBA or None, so it's source-agnostic.
