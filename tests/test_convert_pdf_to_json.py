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

