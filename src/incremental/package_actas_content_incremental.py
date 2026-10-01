#!/usr/bin/env python3
"""Package the current season's incremental actas JSON into a ZIP archive.

Input, written by ``src/incremental/parse_actas_content_incremental.py``::

    resources/actas-incremental-json/<season>/<category>/<group>/<phase>/jornada_NN_local_team_<id>_away_team_<id>.json

Output, ``resources/actas-json-<season>.zip``::

    manifest.json
    actas-json/<season>/<category>/<group>/<phase>/jornada_NN_local_team_<id>_away_team_<id>.json

``manifest.json`` lists every packaged file under ``assets.ACTAS.files`` with the same
``/``-separated path it has inside the ZIP, sorted alphabetically::

    {"source": "BCNESA", "seasons": ["<season>"], "assets": {"ACTAS": {"files": [...]}}}

File selection: every ``*.json`` file below the input directory is packaged unless it
matches an ``--exclude`` pattern; a file matching an ``--include`` pattern is always
packaged, overriding both the exclusions and the JSON-only default. Patterns are
shell-style (``fnmatch``) and are tried against the file name and against its path
relative to the input directory (e.g. ``rtb-1a-comarcal/*`` or ``*_m?_*.json``).

The exit code is 0 when the package (or manifest) was written, 1 when it could not be
written and 2 when the run could not start (bad arguments, missing input directory).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import re
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[2]
RESOURCES_DIR = REPO_ROOT / "resources"
INCREMENTAL_JSON_DIR = RESOURCES_DIR / "actas-incremental-json"
ARCHIVE_ROOT = "actas-json"
MANIFEST_NAME = "manifest.json"
LOGGER = logging.getLogger("package_actas_content_incremental")


# --------------------------------------------------------------------------- arguments


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{start + 1}"


def parse_patterns(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", default=current_season(), help="Season, e.g. 2026-2027 (default: current season)")
    parser.add_argument("--input-dir", type=Path, help="JSON files to package (default: resources/actas-incremental-json/<season>)")
    parser.add_argument("--output-file", type=Path, help="Output ZIP (default: resources/actas-json-<season>.zip)")
    parser.add_argument("--verbose", action="store_true", help="Log every packaged, excluded and skipped file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be packaged without writing anything")
    parser.add_argument("--include-empty", action="store_true", help="Add directories without packaged files as empty ZIP entries")
    parser.add_argument("--exclude", type=parse_patterns, default=[], help="Comma-separated patterns to leave out, e.g. '*.tmp,*.bak'")
    parser.add_argument("--include", type=parse_patterns, default=[], help="Comma-separated patterns always packaged, overriding --exclude")
    parser.add_argument("--log-file", type=Path, help="Write logs to this file instead of the console")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output without asking")
    manifest = parser.add_mutually_exclusive_group()
    manifest.add_argument("--no-manifest", action="store_true", help="Do not add manifest.json to the ZIP")
    manifest.add_argument("--manifest-only", action="store_true",
                          help="Only write the manifest, next to the ZIP path as <name>.manifest.json")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{4}", args.season) or int(args.season[5:]) != int(args.season[:4]) + 1:
        parser.error("--season must look like 2026-2027")
    args.input_dir = (args.input_dir or INCREMENTAL_JSON_DIR / args.season).expanduser().resolve()
    args.output_file = (args.output_file or RESOURCES_DIR / f"actas-json-{args.season}.zip").expanduser().resolve()
    return args


def configure_logging(log_file: Path | None, verbose: bool) -> None:
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler()
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", handlers=[handler], force=True)


# --------------------------------------------------------------------------- selection


def matches_any(relative: PurePosixPath, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative.name, pattern) or fnmatch.fnmatch(relative.as_posix(), pattern)
               for pattern in patterns)


def is_excluded_dir(relative: PurePosixPath, patterns: list[str]) -> bool:
    """A directory is excluded when it matches a pattern as is or with a trailing ``/`` (``cat/*`` excludes ``cat``)."""
    return any(fnmatch.fnmatch(relative.as_posix(), pattern) or fnmatch.fnmatch(f"{relative.as_posix()}/", pattern)
               for pattern in patterns)


def select_files(input_dir: Path, season: str, include: list[str],
                 exclude: list[str]) -> tuple[list[tuple[Path, str]], list[str]]:
    """Return the ``(source, archive path)`` pairs to package and the empty directories' archive paths."""
    selected: list[tuple[Path, str]] = []
    directories: dict[PurePosixPath, bool] = {}
    for path in sorted(input_dir.rglob("*")):
        relative = PurePosixPath(path.relative_to(input_dir).as_posix())
        if path.is_dir():
            directories.setdefault(relative, False)
            continue
        if matches_any(relative, include):
            reason = None
        elif path.suffix.lower() != ".json":
            reason = "not JSON"
        elif matches_any(relative, exclude):
            reason = "excluded"
        else:
            reason = None
        if reason:
            LOGGER.debug("Skipped %s (%s)", relative, reason)
            continue
        selected.append((path, f"{ARCHIVE_ROOT}/{season}/{relative.as_posix()}"))
        LOGGER.debug("Selected %s", relative)
        for parent in relative.parents:
            directories[parent] = True
    selected.sort(key=lambda item: item[1])
    empty = sorted(f"{ARCHIVE_ROOT}/{season}/{directory.as_posix()}/"
                   for directory, has_files in directories.items()
                   if not has_files and not is_excluded_dir(directory, exclude))
    return selected, empty


# --------------------------------------------------------------------------- output


def build_manifest(season: str, archive_paths: list[str]) -> str:
    manifest = {"source": "BCNESA", "seasons": [season], "assets": {"ACTAS": {"files": sorted(archive_paths)}}}
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def confirm_overwrite(target: Path, force: bool) -> bool:
    if not target.exists() or force:
        return True
    if not sys.stdin.isatty():
        LOGGER.error("%s already exists (use --force to overwrite it)", target)
        return False
    try:
        answer = input(f"{target} already exists. Overwrite it? [y/N] ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        LOGGER.error("Not overwriting %s", target)
        return False
    return True


def write_atomically(target: Path, write) -> None:
    """Call ``write(temp_path)`` and move the result over ``target`` only if it succeeds."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        write(temp_path)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def write_zip(target: Path, files: list[tuple[Path, str]], empty_dirs: list[str], manifest: str | None) -> None:
    def write(temp_path: Path) -> None:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if manifest is not None:
                archive.writestr(MANIFEST_NAME, manifest.encode("utf-8"))
            for source, archive_path in files:
                archive.write(source, archive_path)
            for directory in empty_dirs:
                archive.writestr(zipfile.ZipInfo(directory), b"")
    write_atomically(target, write)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_file, args.verbose)
    if not args.input_dir.is_dir():
        LOGGER.error("Input directory not found: %s", args.input_dir)
        return 2

    files, empty_dirs = select_files(args.input_dir, args.season, args.include, args.exclude)
    if not args.include_empty:
        empty_dirs = []
    if not files:
        LOGGER.warning("No files to package in %s", args.input_dir)
    manifest = None if args.no_manifest else build_manifest(args.season, [path for _, path in files])
    target = args.output_file.with_suffix(".manifest.json") if args.manifest_only else args.output_file
    LOGGER.info("Season %s: %d file(s)%s from %s", args.season, len(files),
                f" and {len(empty_dirs)} empty directory(ies)" if empty_dirs else "", args.input_dir)

    if args.dry_run:
        for _, archive_path in files:
            LOGGER.info("Would add %s", archive_path)
        for directory in empty_dirs:
            LOGGER.info("Would add empty directory %s", directory)
        LOGGER.info("Dry run: %s %s not written%s", "manifest" if args.manifest_only else "ZIP", target,
                    "" if args.manifest_only or manifest is not None else " (without manifest)")
        return 0

    if not confirm_overwrite(target, args.force):
        return 1
    try:
        if args.manifest_only:
            write_atomically(target, lambda temp_path: temp_path.write_text(manifest, encoding="utf-8", newline="\n"))
        else:
            write_zip(target, files, empty_dirs, manifest)
    except OSError as exc:
        LOGGER.error("Could not write %s: %s", target, exc)
        return 1
    LOGGER.info("Wrote %s with %d file(s)%s", target, len(files),
                "" if args.manifest_only or manifest is not None else " and no manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
