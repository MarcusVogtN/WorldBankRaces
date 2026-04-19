"""Pipeline entry point.

Usage:
    python run.py                      # render using cached data
    python run.py --refetch            # re-download source + assets, then render
    python run.py --validate-layout    # print column bounds before rendering
"""

import argparse
from pathlib import Path

from races.pipeline import run


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='config.json')
    p.add_argument('--refetch', action='store_true',
                   help='Re-fetch source data (ignore cache)')
    p.add_argument('--validate-layout', action='store_true',
                   help='Print column pixel bounds to verify no overlap')
    args = p.parse_args()

    cfg_path = Path(args.config).resolve()
    run(cfg_path, refetch=args.refetch, validate_layout=args.validate_layout)


if __name__ == '__main__':
    main()
