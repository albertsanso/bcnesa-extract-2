import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from actas_from_rtbtt import convert_pdf_to_json

convert_pdf_to_json.INPUT_ROOT = ROOT / "resources" / "actas-json-test"