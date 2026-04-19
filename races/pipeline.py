"""End-to-end orchestration: fetch source → download assets → render video."""

import json
from pathlib import Path

from .sources import build_source
from .sources.world_bank import WorldBankSource
from .assets import build_provider
from .assets.fonts import ensure_orbitron
from .render import render, get_theme


def run(config_path: Path, *, refetch: bool = False,
        validate_layout: bool = False) -> None:
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
    # Only fetch flags for the top-60 by final-year value (covers any screen size).
    final = result.data.iloc[-1].dropna().sort_values(ascending=False)
    top_names = final.head(asset_cfg.get('top_n_to_fetch', 60)).index.tolist()
    provider.ensure(top_names, result.icon_ids)

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
