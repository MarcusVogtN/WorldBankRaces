"""Pipeline entry point.

Usage:
    python run.py                      # render using cached data
    python run.py --refetch            # re-download source + assets, then render
    python run.py --validate-layout    # print column bounds before rendering
    python run.py --extract-movers     # write cache/big_movers.json and exit
    python run.py --generate-narration # write cache/narration.{json,wav} and exit
    python run.py --mux-narration      # mux cache/narration.wav onto the rendered mp4
"""

import argparse
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except ImportError:
    pass

from races.pipeline import run


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='config.json')
    p.add_argument('--refetch', action='store_true',
                   help='Re-fetch source data (ignore cache)')
    p.add_argument('--validate-layout', action='store_true',
                   help='Print column pixel bounds to verify no overlap')
    p.add_argument('--extract-movers', action='store_true',
                   help='Extract candidate big-mover events to cache/big_movers.json and exit')
    p.add_argument('--generate-narration', action='store_true',
                   help='Generate commentator script + TTS audio to cache/ and exit')
    p.add_argument('--mux-narration', action='store_true',
                   help='Mux cache/narration.wav onto the rendered mp4 into output/*_narrated.mp4')
    args = p.parse_args()

    cfg_path = Path(args.config).resolve()
    run(cfg_path,
        refetch=args.refetch,
        validate_layout=args.validate_layout,
        extract_movers=args.extract_movers,
        generate_narration=args.generate_narration,
        mux_narration=args.mux_narration)


if __name__ == '__main__':
    main()
