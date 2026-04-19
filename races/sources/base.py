"""DataSource plugin contract.

A source yields a Year-indexed DataFrame (columns = entity names) plus an
icon-id map (name -> identifier the AssetProvider understands, e.g. ISO2 for
flags, ticker symbol for stocks).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import pandas as pd


@dataclass
class SourceResult:
    data: pd.DataFrame           # index = Year (int), columns = entity display names
    icon_ids: dict               # display name -> icon id (e.g. 'us')
    source_credit: str           # shown in video footer, e.g. 'Source: World Bank'


class DataSource(ABC):
    def __init__(self, cfg: dict):
        self.cfg = cfg

    @abstractmethod
    def fetch(self) -> SourceResult:
        ...
