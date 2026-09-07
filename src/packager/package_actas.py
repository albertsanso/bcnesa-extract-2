#!/usr/bin/env python3
"""Package actas JSON files into a ZIP archive."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "resources" / "actas-json"
DEFAULT_OUTPUT_FILE = PROJECT_ROOT / "resources" / "actas-json.zip"
SEASON_PATTERN = re.compile(r"^\d{4}-\d{4}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=Path,
        help="Directory containing the JSON files (default: resources/actas-json)",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Output ZIP path (default: resources/actas-json.zip)",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing ZIP")
    parser.add_argument(
        "--season",
        help="One or more seasons separated by commas, for example 2023-2024,2024-2025",
    )
    return parser.parse_args(argv)


def normalise_seasons(value: str | None) -> list[str] | None:
    """Validate, trim, and de-duplicate the seasons supplied by the user."""
    if value is None:
        return None

    seasons: list[str] = []
    for item in value.split(","):
        season = item.strip()
        if not season or not SEASON_PATTERN.fullmatch(season):
            raise ValueError(
                "season must use the YYYY-YYYY format; multiple seasons are comma-separated"
            )
        if season not in seasons:
            seasons.append(season)
    return seasons


def resolve_path(path: Path | None, default: Path) -> Path:
    """Resolve an explicitly supplied path from the current directory."""
    return (path if path is not None else default).expanduser().resolve()


def find_json_files(input_dir: Path, seasons: list[str] | None = None) -> list[tuple[Path, PurePosixPath]]:
    """Return JSON files and their POSIX paths relative to ``input_dir``."""
    files: list[tuple[Path, PurePosixPath]] = []
    for path in input_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        relative = path.relative_to(input_dir)
        if seasons is not None and (not relative.parts or relative.parts[0] not in seasons):
            continue
        archive_path = PurePosixPath("actas-json", *relative.parts)
        files.append((path, archive_path))
    return sorted(files, key=lambda item: item[1].as_posix())


def build_manifest(archive_paths: list[PurePosixPath]) -> dict[str, object]:
    """Build the manifest for the selected archive paths."""
    seasons = sorted(
        {
            path.parts[1]
            for path in archive_paths
            if len(path.parts) > 2 and SEASON_PATTERN.fullmatch(path.parts[1])
        }
    )
    return {
        "source": "BCNESA",
        "seasons": seasons,
        "assets": {"ACTAS": {"files": [path.as_posix() for path in archive_paths]}},
    }


def package_actas(input_dir: Path, output_file: Path, force: bool = False, seasons: list[str] | None = None) -> int:
    """Create the actas ZIP archive and return its number of JSON files."""
    if not input_dir.is_dir():
        raise ValueError(f"input directory not found: {input_dir}")
    if output_file.exists() and not force:
        raise FileExistsError(f"output file already exists: {output_file} (use --force to replace it)")

    json_files = find_json_files(input_dir, seasons)
    archive_paths = [archive_path for _, archive_path in json_files]
    manifest = build_manifest(archive_paths)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source_path, archive_path in json_files:
            archive.write(source_path, archive_path.as_posix())
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        archive.writestr("manifest.json", manifest_json.encode("utf-8"))

    return len(json_files)


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface."""
    args = parse_args(argv)
    try:
        seasons = normalise_seasons(args.season)
        input_dir = resolve_path(args.input_dir, DEFAULT_INPUT_DIR)
        if args.output_file is not None:
            output_file = resolve_path(args.output_file, DEFAULT_OUTPUT_FILE)
        elif seasons is not None:
            season_suffix = ",".join(seasons)
            output_file = PROJECT_ROOT / "resources" / f"actas-json-{season_suffix}.zip"
        else:
            output_file = DEFAULT_OUTPUT_FILE
        count = package_actas(input_dir, output_file, args.force, seasons)
    except (FileExistsError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Created {output_file} with {count} JSON file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

