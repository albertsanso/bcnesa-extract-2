#!/usr/bin/env python3
"""Download every category's actas content of a territory for one jornada.

Thin wrapper around ``download_actas_content_incremental.py``: by default it downloads
all Barcelona categories and groups for jornada 1. Any other option of the incremental
downloader (``--no-skip_pdf``, ``--force``, ``--output_dir``...) is passed through.

Examples::

    python src/incremental/download_by_jornada.py
    python src/incremental/download_by_jornada.py --jornada 2 --no-skip_pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import download_actas_content_incremental as downloader  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jornada", default="1", help="Jornada (match day) to download (default: 1)")
    parser.add_argument("--territory", default="Barcelona", help="Territory to download (default: Barcelona)")
    args, passthrough = parser.parse_known_args(argv)
    return downloader.main(["--territory", args.territory, "--match_day", args.jornada, *passthrough])


if __name__ == "__main__":
    sys.exit(main())
