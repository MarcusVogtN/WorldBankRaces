"""Shared utilities: filename sanitization, value formatting, display-name overrides."""

import re
import pandas as pd


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def format_value(v: float, fmt: str) -> str:
    if pd.isna(v) or v == 0:
        return ''
    prefix = '$' if fmt == 'currency' else ''
    # Aim for ~3 significant digits: when the leading number is single-digit,
    # show 2 decimals (e.g. $2.30 T); otherwise drop decimals (e.g. $12 T).
    def _fmt(n: float, suffix: str) -> str:
        decimals = 2 if n < 10 else 0
        return f'{prefix}{n:.{decimals}f} {suffix}'
    if v >= 1e12:
        return _fmt(v / 1e12, 'T')
    if v >= 1e9:
        return _fmt(v / 1e9, 'B')
    if v >= 1e6:
        return _fmt(v / 1e6, 'M')
    if v >= 1e3:
        return _fmt(v / 1e3, 'K')
    return f'{prefix}{v:,.0f}'


DISPLAY_NAMES = {
    'United States':                      'USA',
    'United Kingdom':                     'UK',
    'Russian Federation':                 'Russia',
    'Korea, Rep.':                        'South Korea',
    "Korea, Dem. People's Rep.":          'North Korea',
    'Iran, Islamic Rep.':                 'Iran',
    'Egypt, Arab Rep.':                   'Egypt',
    'Syrian Arab Republic':               'Syria',
    'Venezuela, RB':                      'Venezuela',
    'Yemen, Rep.':                        'Yemen',
    'Kyrgyz Republic':                    'Kyrgyzstan',
    'Lao PDR':                            'Laos',
    'Micronesia, Fed. Sts.':              'Micronesia',
    'Congo, Dem. Rep.':                   'DR Congo',
    'Congo, Rep.':                        'Congo',
    'Central African Republic':           'C.A.R.',
    'Trinidad and Tobago':                'Trinidad & Tobago',
    'Bosnia and Herzegovina':             'Bosnia & Herz.',
    'North Macedonia':                    'N. Macedonia',
    'United Arab Emirates':               'UAE',
    'Papua New Guinea':                   'Papua N.G.',
    'Equatorial Guinea':                  'Eq. Guinea',
    'São Tomé and Príncipe':              'São Tomé',
    'Antigua and Barbuda':                'Antigua & Barbuda',
    'Saint Kitts and Nevis':              'St. Kitts & Nevis',
    'Saint Vincent and the Grenadines':   'St. Vincent',
    'Saint Lucia':                        'St. Lucia',
    'Turks and Caicos Islands':           'Turks & Caicos',
    'Virgin Islands (U.S.)':              'US Virgin Islands',
    'Brunei Darussalam':                  'Brunei',
    'Turkiye':                            'Türkiye',
    'Viet Nam':                           'Vietnam',
    'Slovak Republic':                    'Slovakia',
    'Czech Republic':                     'Czechia',
}


def display_name(name: str, max_chars: int = 22) -> str:
    short = DISPLAY_NAMES.get(name, name)
    return short if len(short) <= max_chars else short[:max_chars - 2] + '..'
