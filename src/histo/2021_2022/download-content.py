import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from actas_from_rtbtt import download_actas  # noqa: E402

download_actas.OUTPUT_ROOT = ROOT / "resources" / "actas-json-test"
raise SystemExit(download_actas.main(
    ["--season", "2021-2022"])
)
