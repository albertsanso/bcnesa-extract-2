import importlib.util
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "src" / "actas-pdf"
sys.path.insert(0, str(SCRIPT_DIR))

MODULE_PATH = SCRIPT_DIR / "convert_pdf_to_json.py"
MODULE_SPEC = importlib.util.spec_from_file_location("convert_pdf_to_json", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
convert_pdf_to_json = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules["convert_pdf_to_json"] = convert_pdf_to_json
MODULE_SPEC.loader.exec_module(convert_pdf_to_json)


MATCH_TEXT = """\
Categoria Segona Grup 1
Acta 1 17/05/26 EQUIP LOCAL EQUIP VISITANT
ABC EQUIP LOCAL XYZ EQUIP VISITANT
A 100 LOCAL A X 200 VISITANTE X 3 0
B 101 LOCAL B Y 201 VISITANTE Y 3 1
C 102 LOCAL C Z 202 VISITANTE Z 3 2
A 100 LOCAL A X 201 VISITANTE Y 3 0
C 102 LOCAL C Y 200 VISITANTE X 3 1
B 101 LOCAL B Z 202 VISITANTE Z 3 2
EQUIP LOCAL EQUIP VISITANT Jocs 6 0
"""


ABC_AWAY_TEXT = """\
Categoria Preferent Grup 1 Observacions:
Acta 32 25/04/21 CTT DELS HORTS 2000 CTT RIPOLLET
ABC CTT RIPOLLET XYZ CTT DELS HORTS 2000
A 8089 VILALLONGA Nurjan Y 4016 OLAYA Joaquin 0 3
B 7663 PASTRANA Juan Manuel X 687 BARCOJO Antonio 3 2
C 9026 MORENO Pol Z 196 GUZMAN Josep Maria 0 3
A 8089 VILALLONGA Nurjan X 687 BARCOJO Antonio 3 0
C 9026 MORENO Pol Y 4016 OLAYA Joaquin 0 3
B 7663 PASTRANA Juan Manuel Z 196 GUZMAN Josep Maria 0 3
CTT DELS HORTS 2000 CTT RIPOLLET Jocs 6 14
4 2
"""

TIED_TRUNCATED_HEADER_TEXT = """\
Categoria Preferent Grup 1 Observacions:
Acta 5 10/10/21 CTT SANT QUINTI DE MEDION CTT POBLENOU
ABC CTT POBLENOU XYZ CTT SANT QUINTI DE MEDIONA 13 2
A 100 POBLENOU A Y 200 QUINTI Y 3 0
B 101 POBLENOU B X 201 QUINTI X 0 3
C 102 POBLENOU C Z 202 QUINTI Z 3 1
A 100 POBLENOU A X 201 QUINTI X 1 3
C 102 POBLENOU C Y 200 QUINTI Y 3 2
B 101 POBLENOU B Z 202 QUINTI Z 2 3
CTT SANT QUINTI DE MEDION CTT POBLENOU Jocs 12 12
3 3
"""

UNDECIDABLE_TEXT = """\
Categoria Preferent Grup 1 Observacions:
Acta 6 10/10/21 CLUB UNKNOWN CLUB OTHER
ABC TEAM ONE XYZ TEAM TWO
A 100 ONE A Y 200 TWO Y 3 0
B 101 ONE B X 201 TWO X 0 3
C 102 ONE C Z 202 TWO Z 3 1
A 100 ONE A X 201 TWO X 1 3
C 102 ONE C Y 200 TWO Y 3 2
B 101 ONE B Z 202 TWO Z 2 3
CLUB UNKNOWN CLUB OTHER Jocs 12 12
3 3
"""

PATH = Path("2020-2021/Preferent/G1/1a Fase/acta_10.pdf")


class OrientationTests(unittest.TestCase):
    def test_writes_real_home_side_when_abc_team_is_away(self):
        data = convert_pdf_to_json.parse_match(ABC_AWAY_TEXT, PATH)

        self.assertEqual(data["equipos"]["local"]["nombre"], "CTT DELS HORTS 2000")
        self.assertEqual(data["equipos"]["visitante"]["nombre"], "CTT RIPOLLET")
        self.assertFalse(data["abc_es_local"])
        self.assertEqual(sorted(data["alineaciones"]["local"]), ["X", "Y", "Z"])
        self.assertEqual(data["alineaciones"]["local"]["Y"]["nombre"], "OLAYA Joaquin")
        self.assertEqual(data["alineaciones"]["visitante"]["A"]["nombre"], "VILALLONGA Nurjan")
        first = data["partidos"][0]
        self.assertEqual(first["cruce"], "A vs Y")
        self.assertEqual(first["local"]["letra"], "Y")
        self.assertEqual(first["visitante"]["letra"], "A")
        self.assertEqual(first["resultado_juegos"], {"local": 3, "visitante": 0})
        self.assertEqual(first["ganador"], "local")
        self.assertEqual(data["resultado_final"], {
            "ganador": "CTT DELS HORTS 2000",
            "marcador_partidos": {"local": 4, "visitante": 2},
            "marcador_juegos": {"local": 14, "visitante": 6},
        })
        self.assertEqual(data["partidos"][-1]["marcador_acumulado"], {"local": 4, "visitante": 2})

    def test_keeps_abc_team_home_and_reports_games_and_sets_separately(self):
        data = convert_pdf_to_json.parse_match(MATCH_TEXT, Path("2025-2026/Preferent/G1/1a Fase/acta_1.pdf"))

        self.assertTrue(data["abc_es_local"])
        self.assertEqual(data["equipos"]["local"]["nombre"], "EQUIP LOCAL")
        self.assertEqual(sorted(data["alineaciones"]["local"]), ["A", "B", "C"])
        self.assertEqual(data["resultado_final"]["marcador_partidos"], {"local": 6, "visitante": 0})
        self.assertEqual(data["resultado_final"]["ganador"], "EQUIP LOCAL")

    def test_uses_truncated_header_prefix_when_the_match_is_tied(self):
        data = convert_pdf_to_json.parse_match(TIED_TRUNCATED_HEADER_TEXT, PATH)

        self.assertFalse(data["abc_es_local"])
        self.assertEqual(data["equipos"]["local"]["nombre"], "CTT SANT QUINTI DE MEDIONA 13 2")
        self.assertEqual(sorted(data["alineaciones"]["local"]), ["X", "Y", "Z"])
        self.assertEqual(data["resultado_final"]["marcador_partidos"], {"local": 3, "visitante": 3})
        self.assertIsNone(data["resultado_final"]["ganador"])

    def test_keeps_abc_team_home_and_warns_when_orientation_is_undecidable(self):
        with self.assertLogs("convert_pdf_to_json", level="WARNING"):
            data = convert_pdf_to_json.parse_match(UNDECIDABLE_TEXT, PATH)

        self.assertTrue(data["abc_es_local"])
        self.assertEqual(data["equipos"]["local"]["nombre"], "TEAM ONE")

    def test_reoriented_output_matches_model_schema(self):
        with Path(convert_pdf_to_json.SCHEMA_PATH).open(encoding="utf-8") as stream:
            schema = json.load(stream)
        for text in (ABC_AWAY_TEXT, TIED_TRUNCATED_HEADER_TEXT):
            data = convert_pdf_to_json.parse_match(text, PATH)
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(data)), [])


class ConvertPdfToJsonTests(unittest.TestCase):
    def test_parse_match_reads_phase_from_path(self):
        data = convert_pdf_to_json.parse_match(
            MATCH_TEXT,
            Path("2025-2026/Preferent/G1/1a Fase/acta_1.pdf"),
        )

        self.assertEqual(data["fase"], "1a Fase")
        self.assertEqual(data["grupo"], 1)
        self.assertEqual(data["temporada"], "2025/2026")

    def test_other_group_is_null_and_keeps_special_phase(self):
        data = convert_pdf_to_json.parse_match(
            MATCH_TEXT.replace("Categoria Segona Grup 1", "Categoria Segona Grup Play-Off Repesca"),
            Path("2025-2026/Segona/Other/Play Off Ascens/acta_1.pdf"),
        )

        self.assertEqual(data["fase"], "Play Off Ascens")
        self.assertIsNone(data["grupo"])

    def test_output_matches_model_schema(self):
        schema_path = Path(convert_pdf_to_json.SCHEMA_PATH)
        with schema_path.open(encoding="utf-8") as stream:
            schema = json.load(stream)
        data = convert_pdf_to_json.parse_match(
            MATCH_TEXT,
            Path("2025-2026/Preferent/G1/1a Fase/acta_1.pdf"),
        )

        self.assertEqual(list(Draft202012Validator(schema).iter_errors(data)), [])


if __name__ == "__main__":
    unittest.main()

