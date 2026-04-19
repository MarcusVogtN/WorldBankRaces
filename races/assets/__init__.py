from .base import AssetProvider
from .flags import FlagProvider

REGISTRY = {
    'flags': FlagProvider,
}


def build_provider(cfg: dict, cache_dir) -> AssetProvider:
    kind = cfg.get('type', 'flags')
    if kind not in REGISTRY:
        raise ValueError(f"Unknown asset provider: {kind}")
    return REGISTRY[kind](cfg, cache_dir)
