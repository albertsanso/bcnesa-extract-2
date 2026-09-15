#!/usr/bin/env python3
"""Convert downloaded RTBTT match-report PDFs into schema-validated JSON."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber
from jsonschema import Draft202012Validator


DEFAULT_PHASE = "all"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_ROOT = PROJECT_ROOT / "resources" / "actas-pdf"
OUTPUT_ROOT = PROJECT_ROOT / "resources" / "actas-json"
SCHEMA_PATH = OUTPUT_ROOT / "acta-model-definition.json"
LOGGER = logging.getLogger("convert_pdf_to_json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, help="Season, for example 2024-2025")
    parser.add_argument("--category", help="Category to convert")
    parser.add_argument("--group", help="Group to convert, for example G1")
    parser.add_argument("--phase", default=DEFAULT_PHASE, help=f"Phase (default: {DEFAULT_PHASE})")
    parser.add_argument("--force", action="store_true", help="Re-convert existing JSON files")
    return parser.parse_args(argv)


def validate_season(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{4})", value.strip())
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("season must look like YYYY-YYYY, for example 2024-2025")
    return value.strip()


def matches(value: str, expected: str | None) -> bool:
    if expected is None:
        return True
    normalise = lambda item: re.sub(r"[^a-z0-9]+", "", item.casefold())
    return normalise(value) == normalise(expected.strip())


def find_pdfs(season: str, category: str | None, group: str | None, phase: str) -> list[Path]:
    season_dir = INPUT_ROOT / season
    if not season_dir.is_dir():
        raise ValueError(f"season directory not found: {season_dir}")
    result = [
        path for path in season_dir.rglob("*.pdf")
        if len(path.relative_to(season_dir).parts) == 4
        and matches(path.relative_to(season_dir).parts[0], category)
        and matches(path.relative_to(season_dir).parts[1], group)
        and matches(path.relative_to(season_dir).parts[2], None if phase.casefold() == "all" else phase)
    ]
    if category and not any(matches(p.relative_to(season_dir).parts[0], category) for p in season_dir.rglob("*.pdf")):
        raise ValueError(f"category not found: {category}")
    if not result:
        raise ValueError("no matching category, group, or phase found")
    return sorted(result)


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("�", "")).strip()


def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def participant(letter: str, licence: str, name: str) -> dict[str, str | None]:
    return {"letra": letter, "licencia": licence, "nombre": name or None}


def player(licence: str, name: str) -> dict[str, str]:
    return {"licencia": licence, "nombre": name}


def normalise_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKD", value).upper())


def common_prefix_length(left: str, right: str) -> int:
    length = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        length += 1
    return length


def abc_is_home(header_names: str, abc_team: str, xyz_team: str, games_line: tuple[int, int] | None,
                abc_games: int, xyz_games: int) -> bool | None:
    """Tell whether the ABC team is the home team.

    The ABC/XYZ line names the alignment sides, while the header lists home then away with no
    delimiter (and sometimes truncated), and the line after "Jocs" holds games won as home/away.
    The games line decides unless the match is tied; the header prefix decides otherwise.
    """
    if games_line and abc_games != xyz_games:
        if games_line == (abc_games, xyz_games):
            return True
        if games_line == (xyz_games, abc_games):
            return False
    names = normalise_name(header_names)
    abc_prefix = common_prefix_length(names, normalise_name(abc_team))
    xyz_prefix = common_prefix_length(names, normalise_name(xyz_team))
    if abc_prefix != xyz_prefix:
        return abc_prefix > xyz_prefix
    return None


def swap_score(score: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"local": score["visitante"], "visitante": score["local"]} if score else score


def swap_sides(game: dict[str, Any]) -> dict[str, Any]:
    swapped = dict(game)
    swapped["local"], swapped["visitante"] = game["visitante"], game["local"]
    swapped["sets"] = [{"set": item["set"], **swap_score(item)} for item in game["sets"]]
    swapped["resultado_juegos"] = swap_score(game["resultado_juegos"])
    if game["ganador"]:
        swapped["ganador"] = "visitante" if game["ganador"] == "local" else "local"
    return swapped


def parse_match(text: str, relative_path: Path) -> dict[str, Any]:
    if len(relative_path.parts) != 5:
        raise ValueError("PDF path must have season/category/group/phase/filename components")
    season, _, group_folder, phase, _ = relative_path.parts
    lines = [clean_text(line) for line in text.splitlines() if clean_text(line)]
    header = next((line for line in lines if re.search(r"\bActa\s+\d+\b", line, re.I)), "")
    header_match = re.search(r"Acta\s+(\d+)\s+(\d{2}/\d{2}/\d{2,4})\s+(.+)", header, re.I)
    if not header_match:
        raise ValueError("match header not found")
    date_value = datetime.strptime(header_match.group(2), "%d/%m/%y").date().isoformat()
    category_line = next((line for line in lines if line.casefold().startswith("categoria ")), "")
    group_match = re.search(r"Grup\s+(\d+)", category_line, re.I)
    if group_folder.casefold() == "other":
        group = None
    elif not group_match:
        raise ValueError("group not found")
    else:
        group = int(group_match.group(1))
    team_line = next((line for line in lines if line.startswith("ABC ")), "")
    team_match = re.match(r"ABC\s+(.+?)\s+XYZ\s+(.+)$", team_line)
    if not team_match:
        raise ValueError("team/alignment line not found")
    abc_team, xyz_team = team_match.groups()
    alignments: dict[str, dict[str, dict[str, str]]] = {"local": {}, "visitante": {}}
    games: list[dict[str, Any]] = []
    row_pattern = re.compile(r"([ABC])\s+(\d+)\s+(.+?)\s+([XYZ])\s+(\d+)\s+(.+?)\s+(\d+)\s+(\d+)$")
    doubles_pattern = re.compile(r"(D[12])\s+(\d+)\s+(.+?)\s+(D[12])\s+(\d+)\s+(.+?)(?:\s+(\d+)\s+(\d+))?$")
    individual_rows = [row_pattern.match(line) for line in lines]
    for match in (m for m in individual_rows if m):
        left_letter, left_lic, left_name, right_letter, right_lic, right_name, left_score, right_score = match.groups()
        if left_letter not in alignments["local"]:
            alignments["local"][left_letter] = player(left_lic, left_name)
        if right_letter not in alignments["visitante"]:
            alignments["visitante"][right_letter] = player(right_lic, right_name)
        games.append(make_game(len(games) + 1, "individual", left_letter, left_name, left_lic, right_letter, right_name, right_lic, int(left_score), int(right_score)))
    double_rows = [match for match in (doubles_pattern.match(line) for line in lines) if match]
    double_pairs: list[tuple[list[dict[str, str]], list[dict[str, str]], int | None, int | None]] = []
    for index, match in enumerate(double_rows):
        left_letter, left_lic, left_name, right_letter, right_lic, right_name, left_score, right_score = match.groups()
        if left_letter != "D1" or right_letter != "D1" or index + 1 >= len(double_rows):
            continue
        next_match = double_rows[index + 1]
        next_left_letter, next_left_lic, next_left_name, next_right_letter, next_right_lic, next_right_name, _, _ = next_match.groups()
        if next_left_letter != "D2" or next_right_letter != "D2":
            continue
        local_players = [player(left_lic, left_name), player(next_left_lic, next_left_name)]
        visitor_players = [player(right_lic, right_name), player(next_right_lic, next_right_name)]
        double_pairs.append((local_players, visitor_players, parse_int(left_score), parse_int(right_score)))
        games.append(make_doubles_game(len(games) + 1, local_players, visitor_players, parse_int(left_score), parse_int(right_score)))
    doubles = None
    if double_pairs:
        doubles = {"local": double_pairs[0][0], "visitante": double_pairs[0][1]}
    if len(alignments["local"]) != 3 or len(alignments["visitante"]) != 3:
        raise ValueError("could not identify three players for each team")

    # "Jocs" carries set totals in ABC/XYZ order; the line after it carries games won as home/away.
    jocs_index = next((index for index in range(len(lines) - 1, -1, -1) if re.search(r"\bJocs\s+\d+\s+\d+", lines[index], re.I)), None)
    jocs_match = re.search(r"Jocs\s+(\d+)\s+(\d+)", lines[jocs_index], re.I) if jocs_index is not None else None
    games_line_match = re.fullmatch(r"(\d+)\s+(\d+)", lines[jocs_index + 1]) if jocs_index is not None and jocs_index + 1 < len(lines) else None
    games_line = (int(games_line_match.group(1)), int(games_line_match.group(2))) if games_line_match else None
    abc_games = sum(game["ganador"] == "local" for game in games)
    xyz_games = sum(game["ganador"] == "visitante" for game in games)
    if jocs_match:
        abc_sets, xyz_sets = int(jocs_match.group(1)), int(jocs_match.group(2))
    else:
        abc_sets = sum(game["resultado_juegos"]["local"] for game in games if game["resultado_juegos"])
        xyz_sets = sum(game["resultado_juegos"]["visitante"] for game in games if game["resultado_juegos"])

    home_is_abc = abc_is_home(header_match.group(3), abc_team, xyz_team, games_line, abc_games, xyz_games)
    if home_is_abc is None:
        LOGGER.warning("%s: cannot tell whether %s or %s is the home team; keeping the ABC team as home",
                       relative_path, abc_team, xyz_team)
        home_is_abc = True
    if home_is_abc:
        local_name, visitor_name = abc_team, xyz_team
        home_games, away_games, home_sets, away_sets = abc_games, xyz_games, abc_sets, xyz_sets
    else:
        local_name, visitor_name = xyz_team, abc_team
        home_games, away_games, home_sets, away_sets = xyz_games, abc_games, xyz_sets, abc_sets
        alignments = {"local": alignments["visitante"], "visitante": alignments["local"]}
        if doubles:
            doubles = {"local": doubles["visitante"], "visitante": doubles["local"]}
        games = [swap_sides(game) for game in games]

    winner = local_name if home_games > away_games else visitor_name if away_games > home_games else None
    for index, game in enumerate(games, 1):
        game["numero"] = index
        game["marcador_acumulado"] = {"local": sum(g["ganador"] == "local" for g in games[:index]), "visitante": sum(g["ganador"] == "visitante" for g in games[:index])}
    return {"federacion": "Federació Catalana de Tennis Taula", "temporada": re.sub(r"-", "/", season), "competicion": clean_text(category_line.removeprefix("Categoria").split("Grup")[0]), "fase": phase, "grupo": group, "jornada": int(re.search(r"(\d+)$", relative_path.stem).group(1)) if re.search(r"(\d+)$", relative_path.stem) else 1, "fecha": date_value, "hora": None, "lugar": None, "equipos": {"local": {"id": None, "nombre": local_name, "delegado": None, "entrenador": None}, "visitante": {"id": None, "nombre": visitor_name, "delegado": None, "entrenador": None}}, "abc_es_local": home_is_abc, "arbitros": {"principal": None, "asistente": None}, "alineaciones": alignments, "dobles": doubles, "partidos": games, "resultado_final": {"ganador": winner, "marcador_partidos": {"local": home_games, "visitante": away_games}, "marcador_juegos": {"local": home_sets, "visitante": away_sets}}, "acta_protestada": False}


def make_game(number: int, kind: str, left_letter: str, left_name: str, left_lic: str, right_letter: str, right_name: str, right_lic: str, left_score: int | None, right_score: int | None) -> dict[str, Any]:
    played = left_score is not None and right_score is not None
    if played:
        assert left_score is not None and right_score is not None
        winner = "local" if left_score > right_score else "visitante" if right_score > left_score else None
    else:
        winner = None
    local = participant(left_letter, left_lic, left_name)
    visitante = participant(right_letter, right_lic, right_name)
    return {"numero": number, "tipo": kind, "cruce": f"{left_letter} vs {right_letter}", "local": local, "visitante": visitante, "sets": [], "resultado_juegos": {"local": left_score, "visitante": right_score} if played else None, "ganador": winner, "marcador_acumulado": {"local": 0, "visitante": 0}}


def make_doubles_game(number: int, local_players: list[dict[str, str]], visitor_players: list[dict[str, str]], left_score: int | None, right_score: int | None) -> dict[str, Any]:
    played = left_score is not None and right_score is not None
    if played:
        assert left_score is not None and right_score is not None
        winner = "local" if left_score > right_score else "visitante" if right_score > left_score else None
    else:
        winner = None
    return {"numero": number, "tipo": "dobles", "cruce": "Db vs Db", "local": {"letra": "Db", "jugadores": local_players}, "visitante": {"letra": "Db", "jugadores": visitor_players}, "sets": [], "resultado_juegos": {"local": left_score, "visitante": right_score} if played else None, "ganador": winner, "marcador_acumulado": {"local": 0, "visitante": 0}}


def output_path_for_page(output_path: Path, page_number: int, page_count: int) -> Path:
    """Return a stable output name without overwriting another page's acta."""
    if page_count == 1:
        return output_path
    return output_path.with_name(f"{output_path.stem}_page_{page_number}{output_path.suffix}")


def output_files_exist(pdf_path: Path, output_path: Path) -> bool:
    """Check the complete set of outputs, including the PDF page count."""
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
    return all(
        output_path_for_page(output_path, page_number, page_count).exists()
        for page_number in range(1, page_count + 1)
    )


def write_json(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)


def convert_file(pdf_path: Path, output_path: Path, validator: Draft202012Validator) -> int:
    """Convert each PDF page independently and return the number of actas written."""
    with pdfplumber.open(pdf_path) as pdf:
        page_texts = [page.extract_text() or "" for page in pdf.pages]

    if not page_texts:
        raise ValueError("PDF contains no pages")

    relative_path = pdf_path.relative_to(INPUT_ROOT)
    parsed_pages = [parse_match(text, relative_path) for text in page_texts]
    for data in parsed_pages:
        errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
        if errors:
            raise ValueError("schema validation failed: " + "; ".join(error.message for error in errors[:3]))

    if len(parsed_pages) > 1 and output_path.exists():
        output_path.unlink()
    for page_number, data in enumerate(parsed_pages, 1):
        page_output_path = output_path_for_page(output_path, page_number, len(parsed_pages))
        write_json(data, page_output_path)
    return len(parsed_pages)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        season = validate_season(args.season)
        with SCHEMA_PATH.open(encoding="utf-8") as stream:
            validator = Draft202012Validator(json.load(stream))
        pdfs = find_pdfs(season, args.category, args.group, args.phase)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    converted = skipped = errors = 0
    for pdf_path in pdfs:
        output_path = OUTPUT_ROOT / pdf_path.relative_to(INPUT_ROOT).with_suffix(".json")
        if output_path.name == SCHEMA_PATH.name:
            continue
        if not args.force and output_files_exist(pdf_path, output_path):
            skipped += 1
            continue
        try:
            converted += convert_file(pdf_path, output_path, validator)
            LOGGER.info("converted %s", pdf_path)
        except Exception as exc:  # Continue with other reports.
            errors += 1
            LOGGER.error("%s: %s", pdf_path, exc)
    print(f"Summary: {converted} converted, {skipped} skipped, {errors} errors ({len(pdfs)} PDFs found).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
