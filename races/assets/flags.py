"""Flag asset provider — downloads from flagcdn.com, pads to uniform aspect."""

import time
from pathlib import Path
from typing import Optional

import numpy as np
import requests
import urllib3
from PIL import Image

from .base import AssetProvider
from ..util import safe_filename

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FLAG_CDN = "https://flagcdn.com/w320/{iso2}.png"
FLAG_ASPECT = 5 / 3  # target w:h — padded with transparency, never stretched


def _normalize_aspect(img: np.ndarray, target_ratio: float = FLAG_ASPECT) -> np.ndarray:
    pil = Image.fromarray(img).convert('RGBA')
    w, h = pil.size
    current = w / h
    if abs(current - target_ratio) < 0.01:
        return img
    if current < target_ratio:
        new_w = round(h * target_ratio)
        canvas = Image.new('RGBA', (new_w, h), (0, 0, 0, 0))
        canvas.paste(pil, ((new_w - w) // 2, 0))
    else:
        new_h = round(w / target_ratio)
        canvas = Image.new('RGBA', (w, new_h), (0, 0, 0, 0))
        canvas.paste(pil, (0, (new_h - h) // 2))
    return np.array(canvas)


class FlagProvider(AssetProvider):
    def __init__(self, cfg, cache_dir):
        super().__init__(cfg, cache_dir)
        self.flags_dir = self.cache_dir / 'flags'
        self.flags_dir.mkdir(parents=True, exist_ok=True)
        self._memo: dict = {}

    def ensure(self, names, icon_ids):
        headers = {"User-Agent": "WorldBankRacePipeline/1.0"}
        downloaded = skipped = 0
        failed = []
        for name in names:
            iso2 = icon_ids.get(name, '').strip().lower()
            if not iso2:
                failed.append(name)
                continue
            path = self.flags_dir / (safe_filename(name) + '.png')
            if path.exists():
                skipped += 1
                continue
            try:
                resp = requests.get(FLAG_CDN.format(iso2=iso2),
                                    headers=headers, timeout=15, verify=False)
                if resp.status_code == 200:
                    path.write_bytes(resp.content)
                    downloaded += 1
                    print(f"  DL {name} [{iso2}]")
                else:
                    failed.append(name)
            except Exception as exc:
                print(f"  FAIL {name}: {exc}")
                failed.append(name)
            time.sleep(0.25)
        print(f"Flags: {downloaded} downloaded, {skipped} cached, {len(failed)} missing.")

    def load(self, name) -> Optional[np.ndarray]:
        if name in self._memo:
            return self._memo[name]
        path = self.flags_dir / (safe_filename(name) + '.png')
        if not path.exists():
            self._memo[name] = None
            return None
        raw = np.array(Image.open(path).convert('RGBA'))
        img = _normalize_aspect(raw)
        self._memo[name] = img
        return img
