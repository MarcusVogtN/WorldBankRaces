"""Theme system — visual params separated from renderer logic."""

import hashlib
from dataclasses import dataclass, field
from typing import Literal, Tuple, Union

# Vivid Tailwind 400-series — reads well on dark backgrounds.
PALETTE = [
    '#f87171', '#60a5fa', '#4ade80', '#fbbf24', '#a78bfa',
    '#34d399', '#fb923c', '#f472b6', '#38bdf8', '#a3e635',
    '#818cf8', '#e879f9', '#2dd4bf', '#facc15', '#c084fc',
    '#22d3ee', '#86efac', '#fca5a5', '#93c5fd', '#fde68a',
]


# background: solid hex OR ("gradient", c_top, c_bottom) OR ("radial", c_center, c_edge)
BackgroundSpec = Union[str, Tuple[str, str, str]]


@dataclass
class Theme:
    name: str
    background: BackgroundSpec
    bar_style: Literal['glass', 'solid', 'gradient']
    bar_corner_radius_px: int
    bar_opacity: float
    bar_backdrop: bool            # translucent wider rect behind bar (frosted tint)
    bar_inner_gradient: bool      # light highlight band within bar
    row_card: bool
    row_card_color: str
    row_card_opacity: float
    row_card_corner_radius_px: int
    title_card: bool
    title_card_color: str
    title_card_opacity: float
    font_family: str
    accent_palette: list = field(default_factory=lambda: list(PALETTE))
    text_primary: str = '#ffffff'
    text_secondary: str = '#cbd5e1'
    show_sparkline: bool = True
    show_total: bool = True
    smooth_year_ticker: bool = True
    rank_flash: bool = True


GLASS_DARK = Theme(
    name='glass_dark',
    background=('radial', '#1e293b', '#000000'),
    bar_style='glass',
    bar_corner_radius_px=18,
    bar_opacity=0.55,
    bar_backdrop=True,
    bar_inner_gradient=True,
    row_card=True,
    row_card_color='#ffffff',
    row_card_opacity=0.04,
    row_card_corner_radius_px=22,
    title_card=True,
    title_card_color='#ffffff',
    title_card_opacity=0.08,
    font_family='Orbitron',
)

FLAT_LIGHT = Theme(
    name='flat_light',
    background='#f8fafc',
    bar_style='solid',
    bar_corner_radius_px=8,
    bar_opacity=1.0,
    bar_backdrop=False,
    bar_inner_gradient=False,
    row_card=False,
    row_card_color='#000000',
    row_card_opacity=0.0,
    row_card_corner_radius_px=0,
    title_card=False,
    title_card_color='#000000',
    title_card_opacity=0.0,
    font_family='DejaVu Sans',
    text_primary='#0f172a',
    text_secondary='#475569',
    show_sparkline=False,
)


THEMES = {
    GLASS_DARK.name: GLASS_DARK,
    FLAT_LIGHT.name: FLAT_LIGHT,
}


def get_theme(name: str) -> Theme:
    if name not in THEMES:
        raise ValueError(f"Unknown theme '{name}'. Available: {list(THEMES)}")
    return THEMES[name]


def assign_colors(names, palette) -> dict:
    """Deterministic color per name via MD5 hash — stable across re-renders."""
    out = {}
    for name in names:
        idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(palette)
        out[name] = palette[idx]
    return out
