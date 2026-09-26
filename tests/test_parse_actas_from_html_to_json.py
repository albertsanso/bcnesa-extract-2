import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jsonschema import Draft202012Validator


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "src" / "actas-html"
MODULE_PATH = SCRIPT_DIR / "parse_actas_from_html_to_json.py"
MODULE_SPEC = importlib.util.spec_from_file_location("parse_actas_from_html_to_json", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
parser = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules["parse_actas_from_html_to_json"] = parser
MODULE_SPEC.loader.exec_module(parser)

VALIDATOR = Draft202012Validator(json.loads(parser.SCHEMA_PATH.read_text(encoding="utf-8")))
RELATIVE = Path("2026-2027", "Segona _A_", "G2", "1a Fase", "acta_151-247_3.html")


def player_cell(*players):
    links = "<br>".join(
        f'<a href="?codi_jugador={code}&amp;jugador_nom=x&amp;jornada=3" class="br-apic-player-link">{name}</a>'
        for code, name in players
    )
    return f'<td class="player-info">{links}</td>'


def row(left, left_players, right, right_players, games, result, total):
    game_cells = "".join(f'<td class="game">{game}</td>' for game in games)
    return (
        f'<tr><td class="position">{left}</td>{player_cell(*left_players)}'
        f'<td class="position">{right}</td>{player_cell(*right_players)}{game_cells}'
        f'<td class="result">{result}</td><td class="global">{total}</td></tr>'
    )


HOME_ABC_ROWS = [
    ("A", [("1", "HOME A")], "X", [("11", "AWAY X")], ["11-5", "11-6", "11-7", ""], "3 - 0", "1 - 0"),
    ("B", [("2", "HOME B")], "Y", [("12", "AWAY Y")], ["5-11", "11-9", "8-11", "7-11"], "1 - 3", "1 - 1"),
    ("C", [("3", "HOME C")], "Z", [("13", "AWAY Z")], ["11-9", "11-9", "11-9", ""], "3 - 0", "2 - 1"),
    ("Db", [("1", "HOME A"), ("2", "HOME B")], "Db", [("11", "AWAY X"), ("12", "AWAY Y")],
     ["11-3", "11-4", "11-5", ""], "3 - 0", "3 - 1"),
    ("A", [("1", "HOME A")], "Y", [("12", "AWAY Y")], ["11-2", "11-2", "11-2", ""], "3 - 0", "4 - 1"),
]


def match_html(rows, score="4 - 1", header=("HOME TEAM", "AWAY TEAM"), table=True, extra_info=True):
    thead = (
        f"<thead><tr><th></th><th>{header[0]}</th><th></th><th>{header[1]}</th>"
        "<th>J1</th><th>J2</th><th>J3</th><th>J4</th><th>Res.</th><th>Global</th></tr></thead>"
        if header else ""
    )
    results = f'<table class="match-results-table">{thead}<tbody>{"".join(row(*item) for item in rows)}</tbody></table>'
    info = (
        '<div class="field-info"><strong>Terreny de joc:</strong> PAVELLÓ MUNICIPAL, C/ MAJOR 1, 08860 CASTELLDEFELS</div>'
        '<div class="referee-info"><strong>Àrbitre:</strong> PERE ÀRBITRE</div>'
        if extra_info else ""
    )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>'
        '<div class="match-container"><div class="match-datetime">04/10/2026 · 11:00</div>'
        '<div class="match-teams"><div class="team-home"><a href="?team_name_id=151">HOME TEAM</a></div>'
        f'<div class="match-score">{score}</div>'
        '<div class="team-away"><a href="?team_name_id=247">AWAY TEAM</a></div></div>'
        f'{results if table else ""}<div class="match-info">{info}</div></div></body></html>'
    )


def swap_row(item):
    left, left_players, right, right_players, games, result, total = item
    flip = lambda value: " - ".join(reversed(value.split(" - ")))
    games = ["-".join(reversed(game.split("-"))) if game else "" for game in games]
    return right, right_players, left, left_players, games, flip(result), flip(total)


PLACEHOLDER = (
    '<!DOCTYPE html>\n<html><head><meta charset="utf-8"><meta name="acta-status" content="not-published">'
    "<title>t</title></head>\n<body><h1>t</h1>\n<p>Acta status: not published</p>\n"
    '<div class="match-container"><div class="match-datetime">04/10/2026 · 11:00</div>'
    '<div class="match-teams"><div class="team-home"><a href="?team_name_id=151">HOME TEAM</a></div>'
    '<div class="match-score">- - -</div><div class="team-away"><a href="?team_name_id=247">AWAY TEAM</a></div></div>'
    '<div class="match-info"><div class="field-info"><strong>Terreny de joc:</strong> CARRER 1, 08860 CASTELLDEFELS</div>'
    "</div></div>\n</body></html>\n"
)


class ParseActaTests(unittest.TestCase):
    def assert_valid(self, data):
        errors = [error.message for error in VALIDATOR.iter_errors(data)]
        self.assertEqual(errors, [])

    def test_played_match_with_abc_at_home(self):
        data = parser.parse_acta(match_html(HOME_ABC_ROWS), RELATIVE)

        self.assert_valid(data)
        self.assertEqual(data["temporada"], "2026/2027")
        self.assertEqual(data["competicion"], 'Segona "A"')
        self.assertEqual((data["fase"], data["grupo"], data["jornada"]), ("1a Fase", 2, 3))
        self.assertEqual((data["fecha"], data["hora"]), ("2026-10-04", "11:00"))
        self.assertEqual(data["lugar"], {"ciudad": "CASTELLDEFELS", "recinto": "PAVELLÓ MUNICIPAL, C/ MAJOR 1, 08860 CASTELLDEFELS"})
        self.assertEqual(data["arbitros"]["principal"], {"nombre": "PERE ÀRBITRE", "licencia": None})
        self.assertEqual(data["equipos"]["local"]["id"], "151")
        self.assertTrue(data["abc_es_local"])
        self.assertEqual(data["alineaciones"]["local"]["A"], {"nombre": "HOME A", "licencia": "1", "id": "1"})
        self.assertEqual(sorted(data["alineaciones"]["visitante"]), ["X", "Y", "Z"])
        self.assertEqual([item["nombre"] for item in data["dobles"]["local"]], ["HOME A", "HOME B"])
        doubles = data["partidos"][3]
        self.assertEqual((doubles["tipo"], doubles["cruce"]), ("dobles", "Db vs Db"))
        self.assertEqual(len(doubles["local"]["jugadores"]), 2)
        self.assertEqual(data["partidos"][1]["ganador"], "visitante")
        self.assertEqual(data["partidos"][1]["sets"][1], {"set": 2, "local": 11, "visitante": 9})
        self.assertEqual(
            data["resultado_final"],
            {"ganador": "HOME TEAM", "marcador_partidos": {"local": 4, "visitante": 1},
             "marcador_juegos": {"local": 13, "visitante": 3}},
        )

    def test_abc_away_is_detected_from_the_column_headers(self):
        html = match_html(HOME_ABC_ROWS, header=("AWAY TEAM", "HOME TEAM"), score="1 - 4")
        data = parser.parse_acta(html, RELATIVE)

        self.assert_valid(data)
        self.assertFalse(data["abc_es_local"])
        self.assertEqual(sorted(data["alineaciones"]["local"]), ["X", "Y", "Z"])
        self.assertEqual(data["partidos"][0]["local"]["letra"], "X")
        self.assertEqual(data["partidos"][0]["resultado_juegos"], {"local": 0, "visitante": 3})
        self.assertEqual(data["partidos"][0]["ganador"], "visitante")
        self.assertEqual(data["partidos"][-1]["marcador_acumulado"], {"local": 1, "visitante": 4})
        self.assertEqual(data["resultado_final"]["ganador"], "AWAY TEAM")

    def test_abc_away_without_headers_uses_the_final_score(self):
        data = parser.parse_acta(match_html(HOME_ABC_ROWS, header=None, score="1 - 4"), RELATIVE)

        self.assert_valid(data)
        self.assertFalse(data["abc_es_local"])
        self.assertEqual(data["alineaciones"]["visitante"]["A"]["nombre"], "HOME A")

    def test_xyz_in_left_column_at_home(self):
        rows = [swap_row(item) for item in HOME_ABC_ROWS]
        data = parser.parse_acta(match_html(rows, score="1 - 4"), RELATIVE)

        self.assert_valid(data)
        self.assertFalse(data["abc_es_local"])
        self.assertEqual(sorted(data["alineaciones"]["local"]), ["X", "Y", "Z"])
        self.assertEqual(data["resultado_final"]["ganador"], "AWAY TEAM")

    def test_game_without_result_is_marked_not_played(self):
        rows = HOME_ABC_ROWS[:4] + [("A", [("1", "HOME A")], "Y", [("12", "AWAY Y")], ["", "", "", ""], "", "")]
        data = parser.parse_acta(match_html(rows, score="3 - 1"), RELATIVE)

        self.assert_valid(data)
        last = data["partidos"][-1]
        self.assertTrue(last["no_disputado"])
        self.assertEqual((last["sets"], last["resultado_juegos"], last["ganador"]), ([], None, None))
        self.assertEqual(last["marcador_acumulado"], {"local": 3, "visitante": 1})

    def test_rows_without_cell_classes_are_read_by_position(self):
        html = match_html(HOME_ABC_ROWS)
        for name in ("position", "player-info", "game", "result", "global"):
            html = html.replace(f'<td class="{name}">', "<td>")
        data = parser.parse_acta(html, RELATIVE)

        self.assert_valid(data)
        self.assertEqual(len(data["partidos"]), 5)
        self.assertEqual(data["partidos"][3]["tipo"], "dobles")

    def test_missing_optional_fields_are_null(self):
        html = match_html(HOME_ABC_ROWS, extra_info=False).replace("04/10/2026 · 11:00", "")
        data = parser.parse_acta(html, Path("2026-2027", "Segona _A_", "Other", "1a Fase", "acta_1_3.html"))

        self.assert_valid(data)
        self.assertEqual((data["fecha"], data["hora"], data["lugar"], data["grupo"]), (None, None, None, None))
        self.assertIsNone(data["arbitros"]["principal"])

    def test_placeholder_becomes_an_unpublished_acta(self):
        data = parser.parse_acta(PLACEHOLDER, Path("2026-2027", "Vet 1a", "G1", "Play Off Títol", "acta_151-247_2.html"))

        self.assert_valid(data)
        self.assertFalse(data["acta_publicada"])
        self.assertEqual(data["id_partido"], "2026-2027_Vet1a_G1_PlayOffTitol_151-247_2")
        self.assertEqual((data["temporada"], data["competicion"], data["grupo"], data["fase"]),
                         ("2026/2027", "Vet 1a", 1, "Play Off Títol"))
        self.assertEqual((data["jornada"], data["fecha"], data["hora"]), (2, "2026-10-04", "11:00"))
        self.assertEqual(data["equipos"]["local"]["nombre"], "HOME TEAM")
        self.assertEqual(data["equipos"]["visitante"]["nombre"], "AWAY TEAM")
        self.assertEqual(data["lugar"]["ciudad"], "CASTELLDEFELS")
        self.assertEqual((data["partidos"], data["alineaciones"], data["abc_es_local"]),
                         ([], {"local": {}, "visitante": {}}, None))
        self.assertEqual(data["resultado_final"], {"ganador": None, "marcador_partidos": None, "marcador_juegos": None})

    def test_score_without_results_table_is_kept(self):
        data = parser.parse_acta(PLACEHOLDER.replace("- - -", "4 - 0"), RELATIVE)

        self.assert_valid(data)
        self.assertFalse(data["acta_publicada"])
        self.assertEqual(data["resultado_final"]["marcador_partidos"], {"local": 4, "visitante": 0})
        self.assertEqual(data["resultado_final"]["ganador"], "HOME TEAM")

    def test_played_acta_is_published_and_strictly_validated(self):
        data = parser.parse_acta(match_html(HOME_ABC_ROWS), RELATIVE)
        self.assertTrue(data["acta_publicada"])
        self.assertEqual(data["id_partido"], "2026-2027_SegonaA_G2_1aFase_151-247_3")

        data["alineaciones"]["local"].pop("A")
        self.assertTrue(list(VALIDATOR.iter_errors(data)))
        data["partidos"] = []
        data["alineaciones"] = {"local": {}, "visitante": {}}
        self.assertTrue(list(VALIDATOR.iter_errors(data)))

    def test_page_without_match_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "no match found"):
            parser.parse_acta("<html><body>Not found</body></html>", RELATIVE)

    def test_path_must_have_five_components(self):
        with self.assertRaisesRegex(ValueError, "season/category/group/phase"):
            parser.parse_acta(match_html(HOME_ABC_ROWS), Path("2026-2027", "acta_1_3.html"))

    def test_helpers(self):
        self.assertEqual(parser.parse_date_time("27/09/2025 17:00"), ("2025-09-27", "17:00"))
        self.assertEqual(parser.parse_date_time("7/9/25 9:05"), ("2025-09-07", "09:05"))
        self.assertEqual(parser.parse_date_time("31/02/2026 · 25:00"), (None, None))
        self.assertEqual(parser.category_name("Vet 4a _C_"), 'Vet 4a "C"')
        self.assertEqual(parser.category_name("1a Comarcal"), "1a Comarcal")
        self.assertEqual(parser.group_number("G3"), 3)
        self.assertIsNone(parser.group_number("Other"))
        self.assertTrue(parser.matches("Segona _A_", 'Segona "A"'))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.input_root, self.output_root = root / "html", root / "json"
        folder = self.input_root / "2026-2027" / "Segona _A_" / "G2" / "1a Fase"
        folder.mkdir(parents=True)
        (folder / "acta_151-247_3.html").write_text(match_html(HOME_ABC_ROWS), encoding="utf-8")
        (folder / "acta_247-151_4.html").write_text(PLACEHOLDER, encoding="utf-8")

    def run_main(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["--season", "2026-2027", "--input-root", str(self.input_root), "--output-root", str(self.output_root), *extra]
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = parser.main(argv)
        return code, stdout.getvalue()

    def output(self, name):
        return self.output_root / "2026-2027" / "Segona _A_" / "G2" / "1a Fase" / name

    def test_writes_played_and_unpublished_actas(self):
        code, output = self.run_main()

        self.assertEqual(code, 0)
        self.assertIn("1 published, 1 unpublished, 0 skipped, 0 errors (2 HTML files found)", output)
        self.assertEqual(json.loads(self.output("acta_151-247_3.json").read_text(encoding="utf-8"))["jornada"], 3)
        placeholder = json.loads(self.output("acta_247-151_4.json").read_text(encoding="utf-8"))
        self.assertEqual((placeholder["acta_publicada"], placeholder["jornada"]), (False, 4))

    def test_up_to_date_json_is_skipped_unless_forced(self):
        self.run_main()
        _, output = self.run_main()
        self.assertIn("0 published, 0 unpublished, 2 skipped", output)
        _, output = self.run_main("--force")
        self.assertIn("1 published, 1 unpublished, 0 skipped", output)

    def test_refreshed_placeholder_is_parsed_again(self):
        self.run_main()
        html = self.input_root / "2026-2027" / "Segona _A_" / "G2" / "1a Fase" / "acta_247-151_4.html"
        json_path = self.output("acta_247-151_4.json")
        html.write_text(PLACEHOLDER.replace("04/10/2026", "05/10/2026"), encoding="utf-8")
        os.utime(json_path, (html.stat().st_mtime - 10, html.stat().st_mtime - 10))

        _, output = self.run_main()

        self.assertIn("0 published, 1 unpublished, 1 skipped", output)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["fecha"], "2026-10-05")

    def test_placeholder_does_not_replace_a_published_json(self):
        json_path = self.output("acta_247-151_4.json")
        json_path.parent.mkdir(parents=True)
        json_path.write_text('{"partidos": [{"numero": 1}]}', encoding="utf-8")
        html = self.input_root / "2026-2027" / "Segona _A_" / "G2" / "1a Fase" / "acta_247-151_4.html"
        os.utime(json_path, (html.stat().st_mtime - 10, html.stat().st_mtime - 10))

        with self.assertLogs(parser.LOGGER, level="WARNING"):
            _, output = self.run_main()

        self.assertIn("1 published, 0 unpublished, 1 skipped", output)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), {"partidos": [{"numero": 1}]})

    def test_broken_acta_is_logged_and_sets_exit_code(self):
        broken = self.input_root / "2026-2027" / "Segona _A_" / "G2" / "1a Fase" / "acta_1-2_5.html"
        broken.write_text("<html><body>error</body></html>", encoding="utf-8")
        with self.assertLogs(parser.LOGGER, level="ERROR") as logs:
            code, output = self.run_main()

        self.assertEqual(code, 1)
        self.assertIn("1 errors", output)
        self.assertIn("no match found", "\n".join(logs.output))

    def test_filters_and_bad_arguments(self):
        self.assertEqual(self.run_main("--category", 'Segona "A"', "--group", "g2", "--phase", "1a fase")[0], 0)
        self.assertEqual(self.run_main("--category", "Primera")[0], 2)
        self.assertEqual(self.run_main("--phase", "ASCENS")[0], 2)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(parser.main(["--season", "2026", "--input-root", str(self.input_root)]), 2)


if __name__ == "__main__":
    unittest.main()
