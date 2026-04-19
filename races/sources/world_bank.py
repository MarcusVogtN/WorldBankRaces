"""World Bank indicator source (ports s1_world_bank_data.py)."""

import json
import sys
import warnings
from pathlib import Path

import pandas as pd
import urllib3

from .base import DataSource, SourceResult

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Patch requests.get to skip SSL verification — api.worldbank.org trips
# SSLEOFError on some networks. Applied at import time.
import requests
_orig_get = requests.get
def _no_verify_get(url, **kwargs):
    kwargs.setdefault('verify', False)
    return _orig_get(url, **kwargs)
requests.get = _no_verify_get


class WorldBankSource(DataSource):
    source_credit = 'Source: World Bank'

    def fetch(self) -> SourceResult:
        try:
            import wbgapi as wb
        except ImportError:
            sys.exit("Missing dependency. Run: pip install wbgapi")
        try:
            import pycountry
        except ImportError:
            sys.exit("Missing dependency. Run: pip install pycountry")

        indicator = self.cfg['indicator']
        start, end = self.cfg['timeframe']

        print(f"Indicator : {indicator}")
        print(f"Timeframe : {start}-{end}")

        # Economy metadata — filter aggregates, build name/iso2 maps
        iso3_to_name, iso3_to_iso2 = {}, {}
        for e in wb.economy.info().items:
            if e.get('aggregate', True):
                continue
            iso3 = e['id']
            if not e.get('capitalCity', '').strip():
                continue
            pc = pycountry.countries.get(alpha_3=iso3)
            iso3_to_name[iso3] = e['value']
            iso3_to_iso2[iso3] = pc.alpha_2.lower() if pc else ''

        print(f"  {len(iso3_to_name)} actual countries found.")

        # Fetch indicator data
        print(f"\nFetching {indicator} ({start}-{end})...")
        raw = wb.data.DataFrame(indicator, economy='all', time=range(start, end + 1))

        col_sample = str(raw.columns[0])
        if col_sample.startswith('YR') or (col_sample.isdigit() and len(col_sample) == 4):
            raw.columns = pd.Index([str(c).replace('YR', '') for c in raw.columns]).astype(int)
        else:
            raw.index = pd.Index([str(i).replace('YR', '') for i in raw.index]).astype(int)
            raw = raw.T
            raw.columns = raw.columns.astype(int)

        raw = raw[raw.index.isin(iso3_to_name)]
        raw.index = [iso3_to_name[c] for c in raw.index]
        raw = raw.dropna(how='all')

        df = raw.T
        df.index.name = 'Year'
        df = df.sort_index().ffill().bfill().dropna(axis=1, how='all')

        name_to_iso2 = {iso3_to_name[c]: iso3_to_iso2[c]
                        for c in iso3_to_name if iso3_to_iso2.get(c)}
        icon_ids = {name: name_to_iso2[name] for name in df.columns if name in name_to_iso2}

        print(f"  {len(df.columns)} countries × {len(df)} years.")
        return SourceResult(data=df, icon_ids=icon_ids, source_credit=self.source_credit)

    @staticmethod
    def write_cache(result: SourceResult, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        result.data.to_csv(cache_dir / 'race_data.csv')
        with open(cache_dir / 'icon_ids.json', 'w', encoding='utf-8') as f:
            json.dump(result.icon_ids, f, indent=2, ensure_ascii=False)

    @staticmethod
    def read_cache(cache_dir: Path, source_credit: str) -> SourceResult:
        df = pd.read_csv(cache_dir / 'race_data.csv', index_col='Year')
        with open(cache_dir / 'icon_ids.json', 'r', encoding='utf-8') as f:
            icon_ids = json.load(f)
        return SourceResult(data=df, icon_ids=icon_ids, source_credit=source_credit)
