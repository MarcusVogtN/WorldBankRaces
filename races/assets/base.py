"""AssetProvider contract: given an entity id, return an RGBA ndarray or None."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import numpy as np


class AssetProvider(ABC):
    def __init__(self, cfg: dict, cache_dir: Path):
        self.cfg = cfg
        self.cache_dir = Path(cache_dir)

    @abstractmethod
    def ensure(self, names: list, icon_ids: dict) -> None:
        """Download/cache assets for the given names."""

    @abstractmethod
    def load(self, name: str) -> Optional[np.ndarray]:
        """Return an RGBA ndarray, or None if unavailable."""
