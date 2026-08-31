#!/usr/bin/env python3
"""Package the actas JSON files and a manifest into a ZIP archive."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "resources" / "actas-json"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "resources" / "actas-json.zip"
MANIFEST_NAME = "manifest.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing JSON files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help=f"ZIP file to create (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace the output ZIP file if it already exists",
    )
    parser.add_argument(
        "--season",
        help="Package only JSON files under this season directory (for example, 2025-2026)",
    )
    return parser.parse_args(argv)


def json_files(input_dir: Path, season: str | None = None) -> list[Path]:
    """Return regular JSON files below *input_dir*, optionally limited to a season."""
    search_dir = input_dir / season if season is not None else input_dir
    return sorted(
        [
            path
            for path in search_dir.rglob("*.json")
            if path.is_file() and not path.is_symlink()
        ],
        key=lambda path: path.relative_to(input_dir).as_posix(),
    )


def manifest_entries(files: list[Path], input_dir: Path) -> list[dict[str, int | str]]:
    """Build manifest entries containing POSIX relative paths and byte sizes."""
    return [
        {
            "path": path.relative_to(input_dir).as_posix(),
            "size": path.stat().st_size,
        }
        for path in files
    ]


def create_archive(
    input_dir: Path,
    output_file: Path,
    force: bool = False,
    season: str | None = None,
) -> int:
    """Create an archive and return the number of JSON files packaged."""
    input_dir = input_dir.expanduser()
    output_file = output_file.expanduser()

    if not input_dir.is_dir():
        raise ValueError(f"input directory not found: {input_dir}")
    if season is not None:
        season_path = input_dir / season
        if (
            not season
            or Path(season).name != season
            or season in {".", ".."}
            or not season_path.is_dir()
        ):
            raise ValueError(f"season directory not found: {season}")
    if output_file.exists() and not force:
        raise FileExistsError(
            f"output file already exists: {output_file}; use --force to replace it"
        )
    if output_file.exists() and output_file.is_dir():
        raise IsADirectoryError(f"output path is a directory: {output_file}")

    files = json_files(input_dir, season)
    entries = manifest_entries(files, input_dir)
    manifest = {"source": "BCNESA","files": entries}
    output_file.parent.mkdir(parents=True, exist_ok=True)

    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output_file.name}.", suffix=".tmp", dir=output_file.parent
    )
    os.close(temporary_fd)
    temporary_path = Path(temporary_name)
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(input_dir).as_posix())
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )

        os.replace(temporary_path, output_file)
    finally:
        temporary_path.unlink(missing_ok=True)

    return len(files)


def main(argv: list[str] | None = None) -> int:
    """Run the packager command."""
    args = parse_args(argv)
    output_file = args.output_file
    if args.season is not None and output_file == DEFAULT_OUTPUT_FILE:
        output_file = DEFAULT_OUTPUT_FILE.with_name(f"actas-json-{args.season}.zip")
    try:
        count = create_archive(args.input_dir, output_file, args.force, args.season)
    except (FileExistsError, IsADirectoryError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Created {output_file} with {count} JSON file(s) and {MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



