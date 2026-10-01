import importlib.util
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "incremental" / "parse_actas_content_incremental.py"
MODULE_SPEC = importlib.util.spec_from_file_location("parse_actas_content_incremental", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
incremental = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules["parse_actas_content_incremental"] = incremental
MODULE_SPEC.loader.exec_module(incremental)


def player(code, name):
    return f'<a class="br-apic-player-link" href="?codi_jugador={code}&amp;jornada=1">{name}</a>'


def row(left, left_cell, right, right_cell, games, result, total):
    cells = "".join(f'<td class="game">{game}</td>' for game in games + [""] * (5 - len(games)))
    return (f'<tr><td class="position">{left}</td><td class="player-info">{left_cell}</td>'
            f'<td class="position">{right}</td><td class="player-info">{right_cell}</td>{cells}'
            f'<td class="result">{result}</td><td class="global">{total}</td></tr>')


def match(home_id, away_id, score, rows=None, acta=None):
    table = f'<table class="match-results-table"><thead><tr><th></th><th>HOME {home_id}</th><th></th><th>AWAY {away_id}</th></tr></thead><tbody>{"".join(rows)}</tbody></table>' if rows else ""
    acta_html = f'<div class="acta-info"><a class="acta-link" href="{acta}">Descarregar acta</a></div>' if acta else ""
    return (f'<div class="match-container"><div class="match-datetime">04/10/2026 · 11:00</div>'
            f'<div class="match-teams"><div class="team-home"><a href="?team_name_id={home_id}">HOME {home_id}</a></div>'
            f'<div class="match-score">{score}</div>'
            f'<div class="team-away"><a href="?team_name_id={away_id}">AWAY {away_id}</a></div></div>{table}'
            f'<div class="match-info"><div class="field-info"><strong>Terreny de joc:</strong> C/ MAJOR, 1,08001 BARCELONA</div>{acta_html}</div></div>')


SINGLES = [("A", "Y"), ("B", "X"), ("C", "Z"), ("A", "X"), ("C", "Y"), ("B", "Z")]
PLAYED_ROWS = [
    row(left, player(10 + index, f"HOME P{left}"), right, player(20 + index, f"AWAY P{right}"),
        ["11-5", "11-6", "11-7"], "3 - 0", f"{index} - 0")
    for index, (left, right) in enumerate(SINGLES, 1)
] + [row("Db", "UNLINKED ONE<br/>UNLINKED TWO", "Db", "OTHER ONE<br/>OTHER TWO",
         ["5-11", "6-11", "7-11"], "0 - 3", "6 - 1")]


def jornada(status, *matches):
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<meta name="acta-content-status" content="{status}"><meta name="acta-content-hash" content="h-{status}">'
            '<meta name="territory" content="Barcelona"><meta name="match-day" content="1">'
            f'</head><body><section class="jornada">{"".join(matches)}</section></body></html>')


class ParseIncrementalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.input_dir, self.output_dir = root / "in", root / "out"
        self.html = self.input_dir / "2026-2027" / "RTB VETERANS 1a" / "G1" / "1a Fase" / "jornada_01.html"
        self.html.parent.mkdir(parents=True)
        self.phase_dir = self.output_dir / "2026-2027" / "rtb-veterans-1a" / "G1" / "1a Fase"

    def acta(self, pair):
        home, away = pair.split("-")
        path = self.phase_dir / f"jornada_01_local_team_{home}_away_team_{away}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def tearDown(self):
        for handler in logging.getLogger().handlers[:]:  # Release the log file (Windows locks it).
            handler.close()
            logging.getLogger().removeHandler(handler)
        self.temp.cleanup()

    def run_main(self, *extra):
        return incremental.main(["--season", "2026-2027", "--input_dir", str(self.input_dir),
                                 "--output_dir", str(self.output_dir), "--log_file", str(Path(self.temp.name) / "log.txt"), *extra])

    def test_kebab_case(self):
        self.assertEqual(incremental.kebab_case("Vet 1a"), "vet-1a")
        self.assertEqual(incremental.kebab_case("RTB VETERANS 3a A"), "rtb-veterans-3a-a")

    def test_partial_jornada_writes_one_json_per_match(self):
        self.html.write_text(jornada("partial", match(1, 2, "6 - 1", PLAYED_ROWS, "https://x/partido/9/imprimir/acta"),
                                     match(3, 4, "- - -")), encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(len(list(self.phase_dir.glob("*.json"))), 2)
        played, scheduled = self.acta("1-2"), self.acta("3-4")
        self.assertEqual(played["id_partido"], "2026-2027_RTBVETERANS1a_G1_1aFase_1-2_1")
        self.assertTrue(played["acta_publicada"])
        self.assertEqual(len(played["partidos"]), 7)
        self.assertEqual(played["partidos"][0]["sets"][0], {"set": 1, "local": 11, "visitante": 5})
        self.assertEqual([p["nombre"] for p in played["dobles"]["local"]], ["UNLINKED ONE", "UNLINKED TWO"])
        self.assertEqual(played["resultado_final"]["marcador_partidos"], {"local": 6, "visitante": 1})
        self.assertFalse(scheduled["acta_publicada"])
        self.assertEqual((scheduled["fecha"], scheduled["hora"]), ("2026-10-04", "11:00"))
        self.assertEqual(scheduled["equipos"]["local"]["nombre"], "HOME 3")
        self.assertEqual(scheduled["lugar"]["ciudad"], "BARCELONA")
        self.assertEqual(scheduled["partidos"], [])

    def test_match_json_is_updated_in_place_when_played(self):
        self.html.write_text(jornada("partial", match(3, 4, "- - -")), encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        path = next(self.phase_dir.glob("*.json"))
        mtime = path.stat().st_mtime_ns
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(path.stat().st_mtime_ns, mtime)  # Unchanged content is not rewritten.
        self.html.write_text(jornada("complete", match(3, 4, "6 - 1", PLAYED_ROWS)), encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(list(self.phase_dir.glob("*.json")), [path])
        self.assertTrue(self.acta("3-4")["acta_publicada"])

    def test_published_acta_is_not_replaced_by_placeholder_unless_forced(self):
        self.html.write_text(jornada("complete", match(3, 4, "6 - 1", PLAYED_ROWS)), encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        self.html.write_text(jornada("partial", match(3, 4, "- - -")), encoding="utf-8")
        self.assertEqual(self.run_main(), 0)
        self.assertTrue(self.acta("3-4")["acta_publicada"])
        self.assertEqual(self.run_main("--force"), 0)
        self.assertFalse(self.acta("3-4")["acta_publicada"])

    def test_missing_season_returns_2(self):
        self.assertEqual(incremental.main(["--season", "2030-2031", "--input_dir", str(self.input_dir),
                                           "--log_file", str(Path(self.temp.name) / "log.txt")]), 2)


if __name__ == "__main__":
    unittest.main()
