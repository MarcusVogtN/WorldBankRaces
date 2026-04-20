"""End-to-end orchestration: fetch source → download assets → render video."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from .sources import build_source
from .sources.world_bank import WorldBankSource
from .assets import build_provider
from .assets.fonts import ensure_orbitron
from .render import render, get_theme


def _archive_narration(cache_dir: Path) -> None:
    """Copy existing narration.json / narration.wav into a timestamped archive
    so they aren't overwritten by the next --generate-narration run."""
    json_path = cache_dir / 'narration.json'
    wav_path = cache_dir / 'narration.wav'
    if not json_path.exists() and not wav_path.exists():
        return
    archive_dir = cache_dir / 'narration_archive'
    archive_dir.mkdir(parents=True, exist_ok=True)

    ts = None
    if json_path.exists():
        try:
            meta = json.loads(json_path.read_text(encoding='utf-8')).get('meta', {})
            ts = meta.get('generated_at')
        except (OSError, json.JSONDecodeError):
            ts = None
    if not ts:
        src = json_path if json_path.exists() else wav_path
        ts = datetime.utcfromtimestamp(src.stat().st_mtime).strftime('%Y-%m-%dT%H:%M:%SZ')
    stamp = ts.replace(':', '').replace('-', '').replace('Z', '')  # safe filename

    if json_path.exists():
        shutil.copy2(json_path, archive_dir / f'narration_{stamp}.json')
    if wav_path.exists():
        shutil.copy2(wav_path, archive_dir / f'narration_{stamp}.wav')
    print(f"[narration] archived prior narration to {archive_dir} (stamp={stamp})")


def run(config_path: Path, *, refetch: bool = False,
        validate_layout: bool = False,
        extract_movers: bool = False,
        generate_narration: bool = False,
        mux_narration: bool = False) -> None:
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    repo_root = config_path.parent
    cache_dir = repo_root / 'cache'
    output_dir = repo_root / 'output'
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_cfg = cfg['source']
    asset_cfg = cfg.get('assets', {'type': 'flags'})
    render_cfg = cfg.get('render', {})
    theme = get_theme(cfg.get('theme', 'glass_dark'))
    value_format = cfg.get('value_format', 'currency')
    title = cfg.get('video_title', 'Race')
    output_name = cfg.get('output_filename', 'race.mp4')
    preview = cfg.get('preview_timeframe')
    preview = tuple(preview) if preview else None

    # ── Source (fetch or load from cache) ────────────────────────────────────
    source = build_source(source_cfg)
    cache_ready = (cache_dir / 'race_data.csv').exists() and (cache_dir / 'icon_ids.json').exists()
    if refetch or not cache_ready:
        result = source.fetch()
        WorldBankSource.write_cache(result, cache_dir)
    else:
        print("Using cached source data (pass --refetch to re-download).")
        result = WorldBankSource.read_cache(cache_dir, source.source_credit)

    # ── Assets ───────────────────────────────────────────────────────────────
    provider = build_provider(asset_cfg, cache_dir)
    # Fetch flags for every country we have an icon id for, so the spotlight
    # (which surfaces non-top-N movers) never renders text-only. top_n_to_fetch
    # is kept as a lower bound but no longer caps the set.
    final = result.data.iloc[-1].dropna().sort_values(ascending=False)
    ranked_all = [c for c in final.index if c in result.icon_ids]
    extra = [c for c in result.icon_ids.keys() if c not in ranked_all]
    all_names = ranked_all + extra
    provider.ensure(all_names, result.icon_ids)

    # Warn about any country that appears in the data but has no flag on disk.
    from .util import safe_filename
    missing = [c for c in result.data.columns
               if result.data[c].notna().any()
               and not (cache_dir / 'flags' / (safe_filename(c) + '.png')).exists()]
    if missing:
        print(f"[flags] WARNING: {len(missing)} country/countries in the dataset have no flag:")
        for c in missing[:20]:
            iso = result.icon_ids.get(c, '?')
            print(f"  - {c}  (iso2={iso})")
        if len(missing) > 20:
            print(f"  ...and {len(missing) - 20} more")

    # ── Extract big-mover candidates and exit (no render) ──────────────────
    if extract_movers:
        from .render.big_movers import extract_and_write
        extract_and_write(
            data=result.data,
            render_cfg=render_cfg,
            value_format=value_format,
            source_indicator=source_cfg.get('indicator', ''),
            out_path=cache_dir / 'big_movers.json',
        )
        return

    # ── Generate narration (script + TTS) and exit ───────────────────────
    if generate_narration:
        from .render.big_movers import interpolate_and_rank
        from .narration.stats import build_stat_pack
        from .narration.timeline import build_timeline
        from .narration.script import generate_script
        from .narration.voice import synthesize

        narration_cfg = render_cfg.get('narration', {})
        steps_per_year = int(render_cfg.get('steps_per_year', 60))
        fps = int(render_cfg.get('fps', 30))
        smooth_a = int(render_cfg.get('rank_smooth_window_a', 25))
        smooth_b = int(render_cfg.get('rank_smooth_window_b', 35))
        n_on_screen = int(render_cfg.get('top_n_on_screen', 10))

        scores_df, ranks_df = interpolate_and_rank(
            result.data, steps_per_year, smooth_a, smooth_b)

        stat_pack = build_stat_pack(
            scores_df, ranks_df,
            steps_per_year=steps_per_year,
            value_format=value_format,
            video_title=title,
            n_on_screen=n_on_screen,
        )
        spotlight_cfg = render_cfg.get('spotlight', {}) or {}
        curated_rel = spotlight_cfg.get('curated_file')
        curated_path = (repo_root / curated_rel) if curated_rel else None
        end_hold_seconds = float(render_cfg.get('end_hold_seconds', 0.0))
        timeline = build_timeline(
            scores_df, ranks_df,
            steps_per_year=steps_per_year,
            fps=fps,
            n_on_screen=n_on_screen,
            curated_movers_path=curated_path,
            preview_timeframe=preview,
            end_hold_seconds=end_hold_seconds,
        )

        _archive_narration(cache_dir)

        script_doc = generate_script(
            stat_pack=stat_pack,
            timeline=timeline,
            narration_cfg=narration_cfg,
            out_path=cache_dir / 'narration.json',
        )
        if script_doc.get('suggested_trim'):
            st = script_doc['suggested_trim']
            print(f"[narration] suggested_trim: start_year={st.get('start_year')} "
                  f"— {st.get('reason')} (not applied; update config.json manually)")

        synthesize(
            script_doc=script_doc,
            narration_cfg=narration_cfg,
            video_duration_seconds=timeline['video_duration_seconds'],
            clips_dir=cache_dir / 'narration_clips',
            out_wav_path=cache_dir / 'narration.wav',
            repo_root=repo_root,
        )
        return

    # ── Mux narration onto rendered video and exit ───────────────────────
    if mux_narration:
        from .narration.mux import mux_audio
        video_path = output_dir / output_name
        stem = Path(output_name).stem
        ext = Path(output_name).suffix or '.mp4'
        out_path = output_dir / f'{stem}_narrated{ext}'
        mux_audio(video_path, cache_dir / 'narration.wav', out_path)
        return

    # ── Layout validation (optional) ─────────────────────────────────────────
    if validate_layout:
        from .render.renderer import validate_layout as vl
        bounds = vl()
        print("Column bounds (px):")
        for k, (l, r) in bounds.items():
            print(f"  {k:6s} {l:7.1f} → {r:7.1f}  (width {r - l:6.1f})")

    # ── Fonts ────────────────────────────────────────────────────────────────
    ensure_orbitron(cache_dir)

    # ── Render ───────────────────────────────────────────────────────────────
    render(
        data=result.data,
        load_icon=provider.load,
        title=title,
        value_format=value_format,
        source_credit=result.source_credit,
        theme=theme,
        output_path=output_dir / output_name,
        render_cfg=render_cfg,
        preview_timeframe=preview,
    )
