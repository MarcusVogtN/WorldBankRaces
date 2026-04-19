from .base import DataSource, SourceResult
from .world_bank import WorldBankSource

REGISTRY = {
    'world_bank': WorldBankSource,
}


def build_source(cfg: dict) -> DataSource:
    kind = cfg.get('type', 'world_bank')
    if kind not in REGISTRY:
        raise ValueError(f"Unknown source type: {kind}")
    return REGISTRY[kind](cfg)
