import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "src" / "actas-pdf"
sys.path.insert(0, str(SCRIPT_DIR))

from bs4 import BeautifulSoup  # noqa: E402

MODULE_PATH = SCRIPT_DIR / "download_actas.py"
MODULE_SPEC = importlib.util.spec_from_file_location("download_actas", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
download_actas = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules["download_actas"] = download_actas
MODULE_SPEC.loader.exec_module(download_actas)


class DownloadActasTests(unittest.TestCase):
    def test_phase_name_recognises_veteran_phases_and_accents(self):
        self.assertEqual(download_actas.phase_name("TÍTOL"), "TITOL")
        self.assertEqual(download_actas.phase_name("Fase d'ASCENS"), "ASCENS")
        self.assertEqual(download_actas.phase_name("DESCENS Veterans"), "DESCENS")
        self.assertEqual(download_actas.phase_from_slug("VET_1A_G1_PLAY_OFF"), "Play Off Títol")
        self.assertEqual(download_actas.phase_name("Play Off", "Primera"), "Play Off Ascens")

    def test_phase_name_keeps_existing_phase_names(self):
        self.assertEqual(download_actas.phase_name("Lliga 1a fase"), "1a Fase")
        self.assertEqual(download_actas.phase_name("2a Fase"), "2a Fase")
        self.assertEqual(download_actas.phase_name("3ª Fase"), "3a Fase")

    def test_report_index_links_uses_phase_in_slug(self):
        html = """
        <a href="actes2425/PREF_G1.html">Preferent G1</a>
        <a href="actes2425/VET_1A_G1_TITOL.html">Veterans G1</a>
        <a href="actes2425/VET_1A_G1_DESCENS.html">Veterans G1 - Descens</a>
        <a href="actes2425/VET_1A_G1_PLAY_OFF.html">Veterans G1 - Play Off Títol</a>
        <a href="lligues2425/VET_1A_G1_ASCENS.html">Veterans G1 - Ascens</a>
        <a href="actes2425/PRIMERA_G1_PLAY_OFF.html">Primera G1 - Play Off Ascens</a>
        <a href="actes2425/2a fase/VET_1_TITOL/actes_VET_1_TITOL.html">TTOL</a>
        <a href="actes2425/2a fase/VET_1_DESCENS/actes_VET_1_DESCENS.html">DESCENS</a>
        <a href="actes2425/2a fase/VET_2_A_ASCENS/actes_VET_2_A_ASCENS.html">ASCENS</a>
        """
        with patch.object(download_actas, "fetch", return_value=BeautifulSoup(html, "html.parser")):  # type: ignore[attr-defined]
            links = download_actas.report_index_links(
                object(), "2024-2025", "https://www.rtbtt.com/", 0, download_actas.logging.getLogger()
            )

        self.assertEqual(
            [(link[0], link[1], link[2]) for link in links],
            [
                ("Preferent", "G1", "1a Fase"),
                ("Vet 1a", "G1", "TITOL"),
                ("Vet 1a", "G1", "DESCENS"),
                ("Vet 1a", "G1", "Play Off Títol"),
                ("Vet 1a", "G1", "ASCENS"),
                ("Primera", "G1", "Play Off Ascens"),
                ("Vet 1a", "", "TITOL"),
                ("Vet 1a", "", "DESCENS"),
                ("Vet 2a \"A\"", "", "ASCENS"),
            ],
        )

    def test_all_is_default_phase(self):
        args = download_actas.parse_args(["--season", "2024-2025"])
        self.assertEqual(args.phase, "all")

    def test_all_phase_filter_keeps_every_phase(self):
        entries = [
            ("Vet 1a", "G1", "1a Fase", "first.html"),
            ("Vet 1a", "G1", "TITOL", "title.html"),
            ("Vet 1a", "G1", "Play Off Títol", "playoff.html"),
        ]
        selected = download_actas.select_index_links(entries, "Vet 1a", "G1", "all")
        self.assertEqual([entry[2] for entry in selected], ["1a Fase", "TITOL", "Play Off Títol"])


if __name__ == "__main__":
    unittest.main()




