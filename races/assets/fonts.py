"""Font loader — downloads Orbitron (SIL OFL) on first run, registers with matplotlib."""

from pathlib import Path
import urllib.request

from matplotlib import font_manager

ORBITRON_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/orbitron/Orbitron%5Bwght%5D.ttf"
ORBITRON_FILENAME = "Orbitron.ttf"


def ensure_orbitron(cache_dir: Path) -> Path:
    fonts_dir = cache_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    path = fonts_dir / ORBITRON_FILENAME
    if not path.exists():
        print(f"Downloading Orbitron → {path}")
        urllib.request.urlretrieve(ORBITRON_URL, path)
    font_manager.fontManager.addfont(str(path))
    print(f"Registered font: Orbitron ({path})")
    return path
