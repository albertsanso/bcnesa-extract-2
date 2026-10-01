#!/usr/bin/env python3
"""Incrementally parse the current season's downloaded actas content into JSON.

Input, written by ``src/incremental/download_actas_content_incremental.py``::

    resources/actas-incremental-content/<season>/<category>/<group>/<phase>/jornada_NN.html
    resources/actas-incremental-content/<season>/<category>/<group>/<phase>/jornada_NN/<match_id>.pdf

Every jornada HTML holds one ``.match-container`` per match plus ``<meta>`` tags with the
season, territory, match day and ``acta-content-status`` (``complete`` when every match of
the jornada is played with its acta published, ``partial`` otherwise). PDF actas are
ignored for now.

Output, one JSON per match with the category folder in kebab-case::

    resources/actas-incremental-json/<season>/<category-kebab>/<group>/<phase>/jornada_NN_local_team_<id>_away_team_<id>.json

The team ids are FCTT's ``team_name_id`` values (``equipos.local.id`` / ``equipos.visitante.id``);
a match whose team links are missing falls back to its position, e.g. ``..._local_team_m3_away_team_m3``.

Each file is one acta following (and validated against) ``docs/acta-model-definition.json``.
Matches without a results table (not played yet) are written with ``"acta_publicada": false``
and only the minimal fields: season, category, group, phase, id, date, time, teams and
venue. Played matches also carry line-ups, games with their sets, sets won and running
scores, and the referee when the page names one. A ``partial`` jornada usually mixes both,
so the decision is taken per match, not per file.

``id_partido`` is ``<season>_<category>_<group>_<phase>_<home id>-<away id>_<jornada>``
(e.g. ``2026-2027_RTBVETERANS1a_G1_1aFase_151-247_2``): it is built from the team ids, so neither
it nor the file name changes when the match is played and its JSON is updated in place.

The parse is incremental: a match JSON is only written when its content changes, and a
published acta is never replaced by an unpublished one (the site sometimes drops results
temporarily) unless ``--force`` is given.

The per-match parsing is shared with ``src/actas-html/parse_actas_from_html_to_json.py``,
which reads the same FCTT ``.match-container`` markup.

The exit code is 0 when every match was handled, 1 when some failed and 2 when the run
could not start (bad arguments, missing season directory or schema).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, cast

from bs4 import BeautifulSoup, Tag
from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = REPO_ROOT / "resources" / "actas-incremental-content"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "resources" / "actas-incremental-json"
DEFAULT_LOG_FILE = REPO_ROOT / "logs" / "parse_actas_content_incremental.log"
SCHEMA_PATH = REPO_ROOT / "docs" / "acta-model-definition.json"
STATUS_META = "acta-content-status"
LOGGER = logging.getLogger("parse_actas_content_incremental")


def _load_acta_parser():
    """Import the per-match FCTT parser (its folder name is not a valid package name)."""
    path = REPO_ROOT / "src" / "actas-html" / "parse_actas_from_html_to_json.py"
    spec = importlib.util.spec_from_file_location("parse_actas_from_html_to_json", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


acta_parser = _load_acta_parser()


# --------------------------------------------------------------------------- arguments


def current_season(today: date | None = None) -> str:
    today = today or date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{start + 1}"


def parse_match_days(value: str) -> set[int]:
    days: set[int] = set()
    for part in filter(None, (piece.strip() for piece in value.split(","))):
        bounds = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not bounds:
            raise argparse.ArgumentTypeError(f"invalid match day: {part!r} (use 3, 1,4 or 2-5)")
        first, last = int(bounds.group(1)), int(bounds.group(2) or bounds.group(1))
        days.update(range(min(first, last), max(first, last) + 1))
    return days


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", default=current_season(), help="Season, e.g. 2026-2027 (default: current season)")
    parser.add_argument("--category", help="Category, e.g. 'RTB PREFERENT', 'PREFERENT' or 'rtb-preferent' (default: all)")
    parser.add_argument("--group", help="Group, e.g. G1 or 1 (default: all)")
    parser.add_argument("--phase", help="Phase, e.g. '1a Fase' (default: all)")
    parser.add_argument("--match_day", type=parse_match_days, help="Match day(s): 3, 1,4 or 2-5 (default: all)")
    parser.add_argument("--input_dir", type=Path, default=DEFAULT_INPUT_DIR, help=f"Downloaded content (default: {DEFAULT_INPUT_DIR})")
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"JSON output (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--log_file", type=Path, default=DEFAULT_LOG_FILE, help=f"Log file (default: {DEFAULT_LOG_FILE})")
    parser.add_argument("--force", action="store_true", help="Rewrite every JSON, even unchanged or published ones")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"\d{4}-\d{4}", args.season) or int(args.season[5:]) != int(args.season[:4]) + 1:
        parser.error("--season must look like 2026-2027")
    return args


def configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers, force=True)


# --------------------------------------------------------------------------- discovery


def fold(text: str) -> str:
    """Lower-case, accent-free, alphanumeric-only text for comparisons."""
    text = unicodedata.normalize("NFD", text.replace("ª", "a"))
    text = "".join(character for character in text if unicodedata.category(character) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def kebab_case(value: str) -> str:
    """``RTB VETERANS 1a`` -> ``rtb-veterans-1a``; accents and punctuation are dropped."""
    value = unicodedata.normalize("NFD", value.replace("ª", "a"))
    value = "".join(character for character in value if unicodedata.category(character) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "unknown"


def normalise_group(value: str) -> str:
    match = re.fullmatch(r"(?:g|grup)?\s*(\d+)", value.strip(), re.I)
    return f"G{match.group(1)}" if match else value.strip().upper()


def category_matches(folder: str, wanted: str | None) -> bool:
    if not wanted:
        return True
    short = re.sub(r"^rt[bglt]", "", fold(folder))
    return fold(wanted) in {fold(folder), short}


def day_from_name(path: Path) -> int | None:
    match = re.search(r"(\d+)$", path.stem)
    return int(match.group(1)) if match else None


def find_jornada_files(input_dir: Path, args: argparse.Namespace) -> list[Path]:
    """Jornada HTML files at ``<season>/<category>/<group>/<phase>/jornada_NN.html`` matching the filters."""
    season_dir = input_dir / args.season
    if not season_dir.is_dir():
        raise ValueError(f"season directory not found: {season_dir}")
    files = []
    for path in season_dir.glob("*/*/*/*.html"):
        category, group, phase, _ = path.relative_to(season_dir).parts
        if not category_matches(category, args.category):
            continue
        if args.group and normalise_group(group) != normalise_group(args.group):
            continue
        if args.phase and fold(phase) != fold(args.phase):
            continue
        if args.match_day and day_from_name(path) not in args.match_day:
            continue
        files.append(path)
    return sorted(files)


# --------------------------------------------------------------------------- parsing


def read_meta(soup: BeautifulSoup) -> dict[str, str]:
    return {cast(str, tag["name"]): cast(str, tag.get("content", "")) for tag in soup.find_all("meta", attrs={"name": True})}


def match_stem(container: Tag, position: int, day: int) -> str:
    """``acta_{home id}-{away id}_{jornada}``, the stem the per-match parser turns into ``id_partido``."""
    ids = []
    for selector in (".team-home a[href]", ".team-away a[href]"):
        anchor = container.select_one(selector)
        ids.append(acta_parser.query_value(str(anchor["href"]), "team_name_id") if anchor else None)
    pair = "-".join(cast(list[str], ids)) if all(ids) else f"m{position}"
    return f"acta_{pair}_{day}"


def parse_match(container: Tag, season: str, category: str, group: str, phase: str,
                day: int, position: int) -> dict[str, Any]:
    """One ``.match-container`` -> one acta following the acta model.

    A match without a results table (not played yet, or acta not published) only gets the
    minimal fields and ``acta_publicada: false``.
    """
    location = acta_parser.ActaLocation(season, category, group, phase, match_stem(container, position, day))
    header = acta_parser.match_header(location, container)
    final = acta_parser.parse_score(acta_parser.node_text(container.select_one(acta_parser.SELECTORS["score"])))
    table = container.select_one(acta_parser.SELECTORS["table"])
    rows = acta_parser.parse_rows(table) if table else []
    if table is None or not rows:
        return acta_parser.unpublished_acta(header, final)
    return acta_parser.published_acta(header, final, table, rows)


def parse_jornada(html: str, relative_path: Path) -> tuple[str, list[dict[str, Any] | Exception]]:
    """Parse a jornada HTML; return its content status and one acta (or the error) per match."""
    soup = BeautifulSoup(html, "html.parser")
    meta = read_meta(soup)
    # The folders are authoritative: they are what the filters and output paths use.
    season, category, group, phase, _ = relative_path.parts
    day_value = meta.get("match-day") or str(day_from_name(relative_path) or "")
    if not day_value.isdigit() or int(day_value) < 1:
        raise ValueError("cannot determine the match day")
    status = meta.get(STATUS_META) or "partial"
    if status not in ("partial", "complete"):
        LOGGER.warning("%s: unknown %s %r, treated as partial", relative_path, STATUS_META, status)
        status = "partial"
    containers = soup.select(acta_parser.SELECTORS["match"])
    if not containers:
        raise ValueError("no match found in the HTML")
    results: list[dict[str, Any] | Exception] = []
    for position, container in enumerate(containers, start=1):
        try:
            results.append(parse_match(container, season, category, group, phase, int(day_value), position))
        except Exception as exc:  # Keep the other matches of the jornada.
            results.append(exc)
    return status, results


# --------------------------------------------------------------------------- output


def phase_output_dir(output_dir: Path, relative_path: Path) -> Path:
    season, category, group, phase, _ = relative_path.parts
    return output_dir / season / kebab_case(category) / group / phase


def acta_filename(acta: dict[str, Any], position: int) -> str:
    """``jornada_02_local_team_151_away_team_247.json``, from the team ids of the acta."""
    home, away = (acta["equipos"][side].get("id") or f"m{position}" for side in ("local", "visitante"))
    return f"jornada_{acta['jornada']:02d}_local_team_{home}_away_team_{away}.json"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_acta(acta: dict[str, Any], output_path: Path, force: bool) -> str:
    """Write one acta unless nothing changed; return new, updated, unchanged or kept."""
    saved = read_json(output_path) if output_path.exists() else None
    if saved is not None and not force:
        if saved == acta:
            return "unchanged"
        if saved.get("acta_publicada", True) and not acta["acta_publicada"]:
            LOGGER.warning("%s: keeping the published acta; the page no longer shows its results", output_path)
            return "kept"
    acta_parser.write_json(acta, output_path)
    return "new" if saved is None else "updated"


def process_file(html_path: Path, input_dir: Path, output_dir: Path, validator: Draft202012Validator,
                 force: bool, stats: Counter) -> None:
    relative_path = html_path.relative_to(input_dir)
    status, results = parse_jornada(acta_parser.read_html(html_path), relative_path)
    target_dir = phase_output_dir(output_dir, relative_path)
    outcomes: Counter = Counter()
    for position, result in enumerate(results, start=1):
        try:
            if isinstance(result, Exception):
                raise result
            acta_parser.validate(result, validator)
            if status == "complete" and not result["acta_publicada"]:
                LOGGER.warning("%s: %s is in a complete jornada but has no results table", relative_path, result["id_partido"])
            outcome = write_acta(result, target_dir / acta_filename(result, position), force)
        except Exception as exc:
            stats["matches failed"] += 1
            LOGGER.error("%s: match %d: %s", relative_path, position, exc)
            continue
        outcomes[outcome] += 1
        stats[f"matches {outcome}"] += 1
        stats["matches published" if result["acta_publicada"] else "matches not published"] += 1
    stats["jornadas parsed"] += 1
    detail = ", ".join(f"{count} {name}" for name, count in sorted(outcomes.items())) or "nothing written"
    LOGGER.info("%s (%s) -> %s: %s", relative_path, status, target_dir.relative_to(output_dir), detail)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_file)
    try:
        validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        files = find_jornada_files(args.input_dir, args)
    except (OSError, ValueError) as exc:
        LOGGER.error("%s", exc)
        return 2
    if not files:
        LOGGER.error("No jornada HTML matches the category/group/phase/match day filters")
        return 2
    LOGGER.info("Parsing %d jornada file(s) for season %s (force=%s)", len(files), args.season, args.force)

    stats: Counter = Counter()
    for html_path in files:
        try:
            process_file(html_path, args.input_dir, args.output_dir, validator, args.force, stats)
        except Exception as exc:  # Keep processing the remaining jornadas.
            stats["jornadas failed"] += 1
            LOGGER.error("%s: %s", html_path.relative_to(args.input_dir), exc)
    summary = ", ".join(f"{count} {name}" for name, count in sorted(stats.items())) or "nothing to do"
    LOGGER.info("Summary: %s", summary)
    return 1 if stats["jornadas failed"] or stats["matches failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
