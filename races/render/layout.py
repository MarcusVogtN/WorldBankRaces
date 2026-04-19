"""Fixed-column layout for the flag race.

Coordinates are in axes-fraction space (0..1). xlim/ylim = (0,1) in the renderer.

Column layout (left to right):

    [ name box: rank + country ][ gutter ][ ─── flag racing track ─── ]

Flags move horizontally within the track based on value. The name box is a
glassmorphic card that physically separates rank+name from the track; value
text can never cross into it.
"""

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np


@dataclass
class Columns:
    # Rank number sits inside the name box, right-aligned at rank_x.
    rank_x: float
    # Name text left-aligned at name_left.
    name_left: float
    # Glass name-box bounds (fixed, independent of text length).
    name_box_left: float
    name_box_right: float
    # Racing track bounds.
    track_left: float
    track_right: float


DEFAULT_COLUMNS = Columns(
    rank_x=0.085,
    name_left=0.100,
    name_box_left=0.040,
    name_box_right=0.310,
    track_left=0.330,
    track_right=0.820,
)


@dataclass
class RowSlot:
    country: str
    y_center: float
    y_bottom: float
    slot_h: float


@dataclass
class VerticalLayout:
    race_top: float
    race_bottom: float
    n_on_screen: int

    @property
    def race_height(self) -> float:
        return self.race_top - self.race_bottom

    def compute_rows(self,
                     ordered_countries: List[str],
                     ordered_values: List[float],
                     *,
                     min_weight: float = 0.35) -> List[RowSlot]:
        """Return RowSlots walking down from race_top in display-rank order.

        `ordered_countries`/`ordered_values` are already sorted #1..#N by display rank.
        Slot heights are proportional to max(min_weight, value/max_value) and sum
        to race_height. Values that are NaN/non-positive use min_weight.
        """
        max_v = max((v for v in ordered_values
                     if np.isfinite(v) and v > 0), default=0.0)

        weights = []
        for v in ordered_values:
            if max_v <= 0 or not np.isfinite(v) or v <= 0:
                weights.append(min_weight)
            else:
                weights.append(max(min_weight, float(v) / max_v))

        total_w = sum(weights) or 1.0
        race_h = self.race_height

        rows: List[RowSlot] = []
        cursor = self.race_top
        for country, w in zip(ordered_countries, weights):
            slot_h = race_h * w / total_w
            y_bottom = cursor - slot_h
            y_center = cursor - slot_h / 2
            rows.append(RowSlot(country, y_center, y_bottom, slot_h))
            cursor = y_bottom
        return rows


DEFAULT_VERTICAL = VerticalLayout(race_top=0.78, race_bottom=0.25, n_on_screen=10)


def track_position(value: float, max_value: float,
                    track_left: float, track_right: float,
                    flag_width: float, floor: float = 0.02) -> float:
    """Left edge x for a flag based on value.

    Rank #1 (value == max) places the flag's right edge at track_right.
    A small floor keeps zero/NaN values visible at the start line.
    """
    usable = max(track_right - track_left - flag_width, 0.0)
    if max_value <= 0 or not np.isfinite(value) or value <= 0:
        t = floor
    else:
        t = floor + (1.0 - floor) * float(np.clip(value / max_value, 0.0, 1.0))
    return track_left + t * usable


def smoothstep(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * (3 - 2 * t)
