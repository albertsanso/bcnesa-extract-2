#!/usr/bin/env python3
"""Parse FCTT HTML match reports (actas) into schema-validated JSON.

From 2026-2027 the RTBTT leagues are published on fctt.cat. The downloader
(``src/actas-html/download_actas_from_2026-2027.py``) stores one HTML file per match at::

    resources/actas-html/{season}/{category}/{group}/{phase}/acta_{home}-{away}_{jornada}.html

Each file holds the match's ``.match-container`` block from the FCTT league page. Once
the match is played, that block has a ``.match-results-table`` with one row per game
(the same markup parsed by ``fctt-extract/src/actas-html/parse_actas.py``). This script
turns every played match into ``resources/actas-json/{same path}.json``, following
``resources/actas-json/acta-model-definition.json``.

Matches that are not played yet, or whose acta is not published (the downloader's
placeholder files, which have no results table), are never skipped: they are written as
``"acta_publicada": false`` actas with the season, category, group, phase, ``id_partido``,
date, time, venue and teams, and empty ``partidos`` and ``alineaciones``. Every acta carries
``id_partido`` = ``{season}_{category}_{group}_{phase}_{home-away_jornada}``, for example
``2026-2027_Vet1a_G1_1aFase_151-247_2``.

An existing JSON is skipped while it is newer than its HTML, so refreshed placeholders (a
new date or venue) and actas that become published are re-parsed on the next run. A
published JSON (for example one converted from the PDF acta) is never replaced by an
unpublished one unless ``--force`` is given.

Usage::

    python src/actas-html/parse_actas_from_html_to_json.py --season 2026-2027
    python src/actas-html/parse_actas_from_html_to_json.py --season 2026-2027 \\
        --category "Segona _A_" --group G1 --phase "1a Fase" --force --log-file parse.log

The exit code is 0 when every file was handled, 1 when some files failed and 2 when the
run could not start (bad arguments, missing season directory or schema).

When the FCTT markup changes, update ``SELECTORS`` (CSS classes) first; the row parser
also falls back to the cell order of the table when the per-cell classes are missing.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag
from jsonschema import Draft202012Validator


DEFAULT_PHASE = "all"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_ROOT = PROJECT_ROOT / "resources" / "actas-html"
OUTPUT_ROOT = PROJECT_ROOT / "resources" / "actas-json"
SCHEMA_PATH = OUTPUT_ROOT / "acta-model-definition.json"
FEDERATION = "Federació Catalana de Tennis Taula"
STATUSES = ("published", "unpublished", "skipped", "errors")
LOGGER = logging.getLogger("parse_actas_from_html_to_json")

# CSS classes of the FCTT markup. Keep them here so a site redesign is a one-place change.
SELECTORS = {
    "match": ".match-container",
    "datetime": ".match-datetime",
    "home": ".team-home",
    "away": ".team-away",
    "score": ".match-score",
    "table": ".match-results-table",
    "field": ".field-info",
    "referee": ".referee-info",
    "position": "position",
    "player": "player-info",
    "game": "game",
    "result": "result",
    "global": "global",
}
LETTERS = {"A", "B", "C", "X", "Y", "Z"}
DOUBLES_LETTER = "Db"
SCORE_PATTERN = re.compile(r"(\d+)\s*-\s*(\d+)")


@dataclass(frozen=True)
class ActaLocation:
    """Where an acta sits in the ``season/category/group/phase/file`` tree."""

    season: str
    category: str
    group: str
    phase: str
    stem: str

    @classmethod
    def from_path(cls, relative_path: Path) -> "ActaLocation":
        if len(relative_path.parts) != 5:
            raise ValueError("HTML path must have season/category/group/phase/filename components")
        season, category, group, phase, filename = relative_path.parts
        return cls(season, category, group, phase, Path(filename).stem)


@dataclass
class GameRow:
    """One row of the results table, as read from the page (left column first)."""

    left_letter: str
    right_letter: str
    left_players: list[dict[str, str]]
    right_players: list[dict[str, str]]
    sets: list[tuple[int, int]] = field(default_factory=list)
    result: tuple[int, int] | None = None
    accumulated: tuple[int, int] | None = None

    @property
    def is_doubles(self) -> bool:
        return DOUBLES_LETTER.casefold() in {self.left_letter.casefold(), self.right_letter.casefold()}


# --- Command line and file discovery ---------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--season", required=True, help="Season, for example 2026-2027")
    parser.add_argument("--category", help="Category folder to parse, for example 'Segona _A_'")
    parser.add_argument("--group", help="Group to parse, for example G1")
    parser.add_argument("--phase", default=DEFAULT_PHASE, help=f"Phase (default: {DEFAULT_PHASE})")
    parser.add_argument("--force", action="store_true", help="Re-parse actas whose JSON already exists")
    parser.add_argument("--input-root", type=Path, default=INPUT_ROOT, help="Root folder of the HTML actas")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT, help="Root folder of the JSON actas")
    parser.add_argument("--log-file", type=Path, help="Also write the log to this file")
    return parser.parse_args(argv)


def validate_season(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{4})", value.strip())
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("season must look like YYYY-YYYY, for example 2026-2027")
    return value.strip()


def matches(value: str, expected: str | None) -> bool:
    """Compare folder names ignoring case, spaces and punctuation (``Segona "A"`` == ``Segona _A_``)."""
    if expected is None:
        return True
    normalise = lambda item: re.sub(r"[^a-z0-9]+", "", item.casefold())
    return normalise(value) == normalise(expected.strip())


def find_html_files(input_root: Path, season: str, category: str | None, group: str | None, phase: str) -> list[Path]:
    season_dir = input_root / season
    if not season_dir.is_dir():
        raise ValueError(f"season directory not found: {season_dir}")
    candidates = [path for path in season_dir.rglob("*.html") if len(path.relative_to(season_dir).parts) == 4]
    if category and not any(matches(path.relative_to(season_dir).parts[0], category) for path in candidates):
        raise ValueError(f"category not found: {category}")
    result = [
        path for path in candidates
        if matches(path.relative_to(season_dir).parts[0], category)
        and matches(path.relative_to(season_dir).parts[1], group)
        and matches(path.relative_to(season_dir).parts[2], None if phase.casefold() == "all" else phase)
    ]
    if not result:
        raise ValueError("no matching category, group, or phase found")
    return sorted(result)


def read_html(path: Path) -> str:
    """Read an acta; the downloader writes UTF-8, older FCTT pages were Windows-1252."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


# --- Small text helpers ----------------------------------------------------------------------


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def node_text(node: Tag | None) -> str:
    return clean_text(node.get_text(" ", strip=True)) if node else ""


def parse_score(value: str) -> tuple[int, int] | None:
    match = SCORE_PATTERN.search(clean_text(value))
    return (int(match.group(1)), int(match.group(2))) if match else None


def score_dict(score: tuple[int, int] | None) -> dict[str, int] | None:
    return {"local": score[0], "visitante": score[1]} if score else None


def strip_label(value: str) -> str:
    """Drop a leading ``Label:`` such as ``Terreny de joc:`` or ``Àrbitre:``."""
    return re.sub(r"^[^:]{1,40}:\s*", "", clean_text(value)).strip()


def query_value(href: str | None, key: str) -> str | None:
    values = parse_qs(urlparse(href or "").query).get(key)
    return values[0] if values else None


def category_name(folder: str) -> str:
    """Undo the downloader's file-name cleaning: ``Segona _A_`` -> ``Segona "A"``."""
    return re.sub(r"_([A-Z])_$", r'"\1"', folder).strip()


def group_number(folder: str) -> int | None:
    match = re.fullmatch(r"G\s*(\d+)", folder.strip(), re.I)
    return int(match.group(1)) if match else None


def compact(value: str) -> str:
    """``Play Off Títol`` -> ``PlayOffTitol``: accents and non-alphanumerics removed."""
    value = "".join(char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn")
    return re.sub(r"[^A-Za-z0-9]+", "", value) or "Other"


def match_id(location: ActaLocation) -> str:
    """Unique match id, e.g. ``2026-2027_Vet1a_G1_1aFase_151-247_2`` for ``acta_151-247_2``."""
    stem = re.sub(r"^acta_", "", location.stem)
    return "_".join([location.season, compact(location.category), compact(location.group), compact(location.phase), stem])


# --- Field extraction ------------------------------------------------------------------------


def parse_date_time(value: str) -> tuple[str | None, str | None]:
    """Parse ``04/10/2026 · 11:00`` or ``27/09/2025<br>17:00`` into ISO date and HH:MM."""
    date_value = hour_value = None
    date_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", value)
    if date_match:
        day, month, year = date_match.groups()
        year_format = "%Y" if len(year) == 4 else "%y"
        try:
            date_value = datetime.strptime(f"{day}/{month}/{year}", f"%d/%m/{year_format}").date().isoformat()
        except ValueError:
            LOGGER.debug("invalid date %r", value)
    time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", value)
    if time_match and int(time_match.group(1)) < 24 and int(time_match.group(2)) < 60:
        hour_value = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"
    return date_value, hour_value


def parse_venue(container: Tag) -> dict[str, str | None] | None:
    """Split ``PASSEIG ... 198-200, 08860 CASTELLDEFELS`` into venue and town (after the postcode)."""
    venue = strip_label(node_text(container.select_one(SELECTORS["field"])))
    if not venue:
        return None
    town = re.search(r"\b\d{5}\s+([^,]+?)\s*$", venue)
    return {"ciudad": town.group(1).strip() if town else None, "recinto": venue}


def parse_referee(container: Tag) -> dict[str, str | None] | None:
    name = strip_label(node_text(container.select_one(SELECTORS["referee"])))
    return {"nombre": name, "licencia": None} if name else None


def parse_team(cell: Tag | None) -> dict[str, Any]:
    anchor = cell.find("a", href=True) if cell else None
    return {
        "id": query_value(str(anchor["href"]), "team_name_id") if anchor else None,
        "nombre": node_text(cell) or None,
        "delegado": None,
        "entrenador": None,
    }


def parse_players(cell: Tag | None) -> list[dict[str, str]]:
    """Return the players linked in a ``.player-info`` cell (two for doubles).

    FCTT identifies players by ``codi_jugador``, which is used as the licence as well.
    """
    if cell is None:
        return []
    players = []
    for anchor in cell.find_all("a"):
        name = node_text(anchor)
        code = query_value(str(anchor.get("href", "")), "codi_jugador")
        if not name:
            continue
        player = {"nombre": name, "licencia": code if code and code.isdigit() else "0"}
        if code and code.isdigit():
            player["id"] = code
        players.append(player)
    if not players and node_text(cell):
        players = [{"nombre": name, "licencia": "0"} for name in re.split(r"\s*/\s*", node_text(cell)) if name]
    return players


def parse_row(row: Tag) -> GameRow | None:
    """Read one results row by cell classes, falling back to the cell order.

    The expected order is: letter, player(s), letter, player(s), set scores..., result, global.
    Header, spacer and malformed rows return None.
    """
    cells = row.find_all("td", recursive=False)
    by_class = lambda name: [cell for cell in cells if name in (cell.get("class") or [])]
    positions, players = by_class(SELECTORS["position"]), by_class(SELECTORS["player"])
    if len(positions) >= 2 and len(players) >= 2:
        games = [node_text(cell) for cell in by_class(SELECTORS["game"])]
        result = node_text(by_class(SELECTORS["result"])[0]) if by_class(SELECTORS["result"]) else ""
        accumulated = node_text(by_class(SELECTORS["global"])[0]) if by_class(SELECTORS["global"]) else ""
    elif len(cells) >= 6:
        positions, players = [cells[0], cells[2]], [cells[1], cells[3]]
        games = [node_text(cell) for cell in cells[4:-2]]
        result, accumulated = node_text(cells[-2]), node_text(cells[-1])
    else:
        return None
    left_letter, right_letter = node_text(positions[0]), node_text(positions[1])
    if not left_letter and not right_letter:
        return None
    sets = [score for score in (parse_score(game) for game in games) if score]
    return GameRow(
        left_letter, right_letter, parse_players(players[0]), parse_players(players[1]),
        sets, parse_score(result), parse_score(accumulated),
    )


def parse_rows(table: Tag) -> list[GameRow]:
    body = table.find("tbody") or table
    return [game for game in (parse_row(row) for row in body.find_all("tr")) if game]


def header_team_names(table: Tag) -> tuple[str, str]:
    """Team names written above the left and right player columns, if present."""
    header = table.find("thead")
    cells = [node_text(cell) for cell in header.find_all("th")] if header else []
    return (cells[1], cells[3]) if len(cells) >= 4 else ("", "")


def normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def left_is_home(table: Tag, rows: list[GameRow], home: str, away: str, final: tuple[int, int] | None) -> bool:
    """Tell whether the left (usually A/B/C) column of the table is the home team.

    The column headers name the teams; if they are missing, the last running score is
    compared with the final score, which is always written home - away.
    """
    left_name, right_name = (normalise_name(name) for name in header_team_names(table))
    home_name, away_name = normalise_name(home), normalise_name(away)
    if left_name and home_name and away_name and home_name != away_name:
        if left_name == away_name or right_name == home_name:
            return False
        if left_name == home_name or right_name == away_name:
            return True
    last = next((row.accumulated for row in reversed(rows) if row.accumulated), None)
    if final and last and final[0] != final[1] and last == (final[1], final[0]):
        return False
    return True


# --- JSON building ---------------------------------------------------------------------------


def participant(letter: str, players: list[dict[str, str]], doubles: bool) -> dict[str, Any]:
    if doubles:
        return {"letra": DOUBLES_LETTER, "jugadores": players}
    return {"letra": letter, **players[0]} if players else {"letra": letter, "nombre": None}


def build_game(number: int, row: GameRow, previous: dict[str, int]) -> dict[str, Any]:
    """Build a ``partido`` with the left column as local; ``swap_sides`` flips it if needed."""
    doubles = row.is_doubles
    accumulated = score_dict(row.accumulated) or dict(previous)
    game: dict[str, Any] = {
        "numero": number,
        "tipo": "dobles" if doubles else "individual",
        "cruce": f"{row.left_letter} vs {row.right_letter}",
        "local": participant(row.left_letter, row.left_players, doubles),
        "visitante": participant(row.right_letter, row.right_players, doubles),
        "sets": [{"set": index, "local": left, "visitante": right} for index, (left, right) in enumerate(row.sets, 1)],
        "resultado_juegos": score_dict(row.result),
        "ganador": None,
        "marcador_acumulado": accumulated,
    }
    if row.result and row.result[0] != row.result[1]:
        game["ganador"] = "local" if row.result[0] > row.result[1] else "visitante"
    if not row.result or row.result == (0, 0) and not row.sets:
        game.update(sets=[], resultado_juegos=None, ganador=None, no_disputado=True, motivo="Resultado no disponible")
    return game


def swap_score(score: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"local": score["visitante"], "visitante": score["local"]} if score else score


def swap_sides(game: dict[str, Any]) -> dict[str, Any]:
    swapped = dict(game)
    swapped["local"], swapped["visitante"] = game["visitante"], game["local"]
    swapped["sets"] = [{"set": item["set"], **swap_score(item)} for item in game["sets"]]
    swapped["resultado_juegos"] = swap_score(game["resultado_juegos"])
    swapped["marcador_acumulado"] = swap_score(game["marcador_acumulado"])
    if game["ganador"]:
        swapped["ganador"] = "visitante" if game["ganador"] == "local" else "local"
    return swapped


def lineups(rows: list[GameRow]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Collect the left/right line-ups by letter and the doubles pairs (left first)."""
    left: dict[str, Any] = {}
    right: dict[str, Any] = {}
    doubles = None
    for row in rows:
        if row.is_doubles:
            doubles = {"local": row.left_players, "visitante": row.right_players}
            continue
        if row.left_letter in LETTERS and row.left_players:
            left.setdefault(row.left_letter, row.left_players[0])
        if row.right_letter in LETTERS and row.right_players:
            right.setdefault(row.right_letter, row.right_players[0])
    return left, right, doubles


def jornada_number(location: ActaLocation, container: Tag) -> int:
    """The downloader names files ``acta_{home}-{away}_{jornada}``; the page may also say it."""
    match = re.search(r"_(\d+)$", location.stem)
    if not match:
        match = re.search(r"(\d+)", str(container.get("data-jornada", ""))) or next(
            (found for anchor in container.find_all("a", href=True)
             if (found := re.search(r"[?&]jornada=(\d+)", str(anchor["href"])))),
            None,
        )
    if not match or int(match.group(1)) < 1:
        raise ValueError(f"cannot determine the jornada of {location.stem}")
    return int(match.group(1))


def match_header(location: ActaLocation, container: Tag) -> dict[str, Any]:
    """Fields known before the match is played: where, when and who (published or not)."""
    date_value, hour_value = parse_date_time(node_text(container.select_one(SELECTORS["datetime"])))
    return {
        "id_partido": match_id(location),
        "federacion": FEDERATION,
        "temporada": location.season.replace("-", "/"),
        "competicion": category_name(location.category),
        "fase": location.phase,
        "grupo": group_number(location.group),
        "jornada": jornada_number(location, container),
        "fecha": date_value,
        "hora": hour_value,
        "lugar": parse_venue(container),
        "equipos": {
            "local": parse_team(container.select_one(SELECTORS["home"])),
            "visitante": parse_team(container.select_one(SELECTORS["away"])),
        },
        "arbitros": {"principal": parse_referee(container), "asistente": None},
    }


def final_result(header: dict[str, Any], final: tuple[int, int] | None,
                 games: list[dict[str, Any]]) -> dict[str, Any]:
    """``resultado_final`` from the header score (home - away) and the parsed games."""
    teams = header["equipos"]
    winner = None
    if final and final[0] != final[1]:
        winner = teams["local"]["nombre"] if final[0] > final[1] else teams["visitante"]["nombre"]
    played = [game["resultado_juegos"] for game in games if game["resultado_juegos"]]
    return {
        "ganador": winner,
        "marcador_partidos": score_dict(final),
        "marcador_juegos": {
            "local": sum(score["local"] for score in played),
            "visitante": sum(score["visitante"] for score in played),
        } if played else None,
    }


def unpublished_acta(header: dict[str, Any], final: tuple[int, int] | None) -> dict[str, Any]:
    """An acta for a match that is not played yet or whose results are not published.

    Only the header is known, so line-ups and games are empty. The header score is kept in
    case the page shows a result without the game-by-game table (for example a walkover).
    """
    return {
        "acta_publicada": False,
        **header,
        "abc_es_local": None,
        "alineaciones": {"local": {}, "visitante": {}},
        "dobles": None,
        "partidos": [],
        "resultado_final": final_result(header, final, []),
        "acta_protestada": False,
    }


def published_acta(header: dict[str, Any], final: tuple[int, int] | None,
                   table: Tag, rows: list[GameRow]) -> dict[str, Any]:
    """An acta with its results table: line-ups, games and running scores."""
    teams = header["equipos"]
    home_is_left = left_is_home(table, rows, teams["local"]["nombre"] or "", teams["visitante"]["nombre"] or "", final)
    left, right, doubles = lineups(rows)
    games: list[dict[str, Any]] = []
    previous = {"local": 0, "visitante": 0}
    for number, row in enumerate(rows, 1):
        game = build_game(number, row, previous)
        previous = game["marcador_acumulado"]
        games.append(game)
    if not home_is_left:
        left, right = right, left
        doubles = {"local": doubles["visitante"], "visitante": doubles["local"]} if doubles else None
        games = [swap_sides(game) for game in games]
    if final is None:
        last = games[-1]["marcador_acumulado"]
        final = (last["local"], last["visitante"])
    return {
        "acta_publicada": True,
        **header,
        # The left column holds A/B/C, so ABC is local exactly when the left column is local.
        "abc_es_local": home_is_left == (rows[0].left_letter.upper() in {"A", "B", "C"}),
        "alineaciones": {"local": left, "visitante": right},
        "dobles": doubles,
        "partidos": games,
        "resultado_final": final_result(header, final, games),
        "acta_protestada": False,
    }


def parse_acta(html: str, relative_path: Path) -> dict[str, Any]:
    """Parse the HTML of one acta into a dict that follows the acta model.

    Matches without a results table become unpublished actas. Raises ValueError when the
    page does not contain a recognisable match.
    """
    location = ActaLocation.from_path(relative_path)
    container = BeautifulSoup(html, "html.parser").select_one(SELECTORS["match"])
    if container is None:
        raise ValueError("no match found in the HTML")
    header = match_header(location, container)
    final = parse_score(node_text(container.select_one(SELECTORS["score"])))
    table = container.select_one(SELECTORS["table"])
    rows = parse_rows(table) if table else []
    if table is None or not rows:
        return unpublished_acta(header, final)
    return published_acta(header, final, table, rows)


# --- Output ------------------------------------------------------------------------------------


def validate(data: dict[str, Any], validator: Draft202012Validator) -> None:
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, error.path)) or '(root)'}: {error.message}" for error in errors[:3])
        raise ValueError("schema validation failed: " + details)


def write_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def is_published_json(path: Path) -> bool:
    """True for an existing JSON with results (from this parser or the PDF converter)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("acta_publicada", True) is not False
    except (OSError, ValueError, AttributeError):
        return False


def is_up_to_date(html_path: Path, output_path: Path) -> bool:
    """The JSON exists and is not older than its HTML (the downloader refreshes placeholders)."""
    return output_path.exists() and output_path.stat().st_mtime >= html_path.stat().st_mtime


def convert_file(html_path: Path, input_root: Path, output_path: Path, validator: Draft202012Validator,
                 force: bool = False) -> str:
    """Parse, validate and write one acta; return its status: published, unpublished or skipped."""
    data = parse_acta(read_html(html_path), html_path.relative_to(input_root))
    validate(data, validator)
    if not data["acta_publicada"] and not force and is_published_json(output_path):
        LOGGER.warning("%s: keeping the published JSON; the HTML is only a placeholder", output_path)
        return "skipped"
    write_json(data, output_path)
    return "published" if data["acta_publicada"] else "unpublished"


def configure_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers, force=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_file)
    try:
        season = validate_season(args.season)
        with SCHEMA_PATH.open(encoding="utf-8") as stream:
            validator = Draft202012Validator(json.load(stream))
        html_files = find_html_files(args.input_root, season, args.category, args.group, args.phase)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.error("%s", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    totals = dict.fromkeys(STATUSES, 0)
    for html_path in html_files:
        relative_path = html_path.relative_to(args.input_root)
        output_path = args.output_root / relative_path.with_suffix(".json")
        if not args.force and is_up_to_date(html_path, output_path):
            totals["skipped"] += 1
            continue
        try:
            status = convert_file(html_path, args.input_root, output_path, validator, args.force)
            totals[status] += 1
            LOGGER.debug("%s %s", status, relative_path)
        except Exception as exc:  # Keep processing the remaining actas.
            totals["errors"] += 1
            LOGGER.error("%s: %s", relative_path, exc)
    summary = ", ".join(f"{totals[status]} {status}" for status in STATUSES)
    LOGGER.info("Summary: %s (%d HTML files found).", summary, len(html_files))
    print(f"Summary: {summary} ({len(html_files)} HTML files found).")
    return 1 if totals["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
