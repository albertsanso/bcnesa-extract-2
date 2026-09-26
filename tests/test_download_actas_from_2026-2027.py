import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "src" / "actas-pdf"
sys.path.insert(0, str(SCRIPT_DIR))

from bs4 import BeautifulSoup  # noqa: E402

MODULE_PATH = SCRIPT_DIR / "download_actas_from_2026-2027.py"
MODULE_SPEC = importlib.util.spec_from_file_location("download_actas_2026_2027", MODULE_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
download_actas = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules["download_actas_2026_2027"] = download_actas
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

    def test_report_index_links_reads_2026_2027_season_table(self):
        html = """
        <table>
          <tr><td>Categoria</td><td>Lliga</td><td>2a FASE</td><td>3a FASE</td><td>Ranquing</td></tr>
          <tr><td>Segona "A"</td>
              <td>Actes: <a href="https://fctt.cat/lligues/rtb-seg-a-2/">G1</a> -
                  <a href="https://fctt.cat/lligues/rtb-seg-a/">G2</a></td>
              <td colspan="2"></td><td><a href="lligues2627/ranquing/SEGON_A.pdf">Individual</a></td></tr>
          <tr><td>1a Comarcal</td><td>Actes: <a href="https://fctt.cat/lligues/rtb-1a-com/">G1</a></td>
              <td colspan="2"></td><td></td></tr>
          <tr><td>Vet 1a</td><td>Actes: <a href="https://fctt.cat/lligues/rtb-vet-1a/">G1</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-vet-1a-titol/">TITOL</a>
                  <a href="https://fctt.cat/lligues/rtb-vet-1a-descens/">DESCENS</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-vet-1a-poff/">Play Off Titol</a></td><td></td></tr>
          <tr><td>Vet 4a C</td><td>Actes: <a href="https://fctt.cat/lligues/rtb-vet-4ac-3/">G3</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-vet-4ac-ascens/">ASCENS</a>
                  <a href="https://fctt.cat/lligues/rtb-vet-4ac-descens/">DESCENS</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-vet-4ac-poff/">Play Off Ascens</a></td><td></td></tr>
        </table>
        <a href="https://fctt.cat/calendari-competicions/">Calendari</a>
        """
        with patch.object(download_actas, "fetch", return_value=BeautifulSoup(html, "html.parser")):  # type: ignore[attr-defined]
            links = download_actas.report_index_links(
                object(), "2026-2027", "https://rtbtt.com/", 0, download_actas.logging.getLogger()
            )

        self.assertEqual(
            [link[:3] for link in links],
            [
                ('Segona "A"', "G1", "1a Fase"),
                ('Segona "A"', "G2", "1a Fase"),
                ("1a Comarcal", "G1", "1a Fase"),
                ("Vet 1a", "G1", "1a Fase"),
                ("Vet 1a", "", "TITOL"),
                ("Vet 1a", "", "DESCENS"),
                ("Vet 1a", "", "Play Off Títol"),
                ('Vet 4a "C"', "G3", "1a Fase"),
                ('Vet 4a "C"', "", "ASCENS"),
                ('Vet 4a "C"', "", "DESCENS"),
                ('Vet 4a "C"', "", "Play Off Ascens"),
            ],
        )
        self.assertEqual(links[0][3], "https://fctt.cat/lligues/rtb-seg-a-2/")

    def test_category_from_fctt_slug_is_a_fallback_for_layout_changes(self):
        self.assertEqual(download_actas.category_from_slug("rtb-seg-b-3"), 'Segona "B"')
        self.assertEqual(download_actas.category_from_slug("rtb-2a-com-2"), "2a Comarcal")
        self.assertEqual(download_actas.category_from_slug("rtb-vet-4ac"), 'Vet 4a "C"')
        self.assertEqual(download_actas.category_from_slug("rtb-vet-1a"), "Vet 1a")

    def test_parse_fctt_reports_links_actas_per_match_and_jornada(self):
        html = """
        <div>
          <h2 class="jornada-results-title"><a href="/lligues/rtb-pref/?jornada=1">Jornada 1</a></h2>
          <div class="match-container">
            <div class="team-home"><a href="?team_name_id=262">A</a></div>
            <div class="team-away"><a href="?team_name_id=266">B</a></div>
            <a href="/actes/2627/acta_1.pdf">Acta</a>
          </div>
          <div class="match-container">
            <div class="team-home"><a href="?team_name_id=131">C</a></div>
            <div class="team-away"><a href="?team_name_id=254">D</a></div>
          </div>
          <h2 class="jornada-results-title"><a href="/lligues/rtb-pref/?jornada=2">Jornada 2</a></h2>
          <div class="match-container">
            <div class="team-home"><a href="?team_name_id=266">B</a></div>
            <div class="team-away"><a href="?team_name_id=131">C</a></div>
            <a href="https://fctt.playoffinformatica.com/acta.php?id=9">Veure acta</a>
          </div>
        </div>
        """
        reports = download_actas.parse_fctt_reports(
            BeautifulSoup(html, "html.parser"), "Preferent", "G1", "1a Fase", "https://fctt.cat/lligues/rtb-pref/"
        )

        self.assertEqual(
            [(report.match_id, report.url, report.published) for report in reports],
            [
                ("262-266_1", "https://fctt.cat/actes/2627/acta_1.pdf", True),
                ("131-254_1", "", False),
                ("266-131_2", "https://fctt.playoffinformatica.com/acta.php?id=9", True),
            ],
        )
        self.assertIn("team_name_id=131", reports[1].snapshot)

    def test_main_logs_failing_index_and_continues(self):
        indexes = [
            ("Preferent", "G1", "1a Fase", "https://fctt.cat/lligues/rtb-pref/"),
            ("Preferent", "G2", "1a Fase", "https://fctt.cat/lligues/rtb-pref-2/"),
        ]
        report = download_actas.ReportLink("Preferent", "G2", "1a Fase", "https://x/acta.pdf", "1-2_1")

        def extract(session, category, group, phase, index_url, base_url, delay):
            if group == "G1":
                raise download_actas.requests.ConnectionError("boom")
            return [report]

        with patch.object(download_actas, "report_index_links", return_value=indexes), \
                patch.object(download_actas, "extract_reports", side_effect=extract), \
                patch.object(download_actas, "download_report", return_value="downloaded") as download, \
                patch.object(download_actas, "configure_logging", return_value=download_actas.logging.getLogger("t")), \
                patch("builtins.print") as printed:
            code = download_actas.main(["--season", "2026-2027", "--delay", "0"])

        self.assertEqual(code, 1)
        download.assert_called_once()
        stem = download.call_args.args[2]
        self.assertEqual(stem.parts[-5:], ("2026-2027", "Preferent", "G2", "1a Fase", "acta_1-2_1"))
        self.assertIn("1a Fase (1 downloaded, 0 skipped, 0 unpublished, 1 errors)", printed.call_args.args[0])

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

    def test_report_index_links_maps_all_phases_of_published_2026_2027_table(self):
        html = """
        <table>
          <tr><td>Categoria</td><td>Lliga</td><td>2a FASE</td><td>3a FASE</td><td>Ranquing Total</td></tr>
          <tr><td>Vet 1a</td>
              <td>Actes: <a href="https://fctt.cat/lligues/rtb-vet-1a/">G1</a> - <a href="https://fctt.cat/lligues/rtb-vet-1a-2/">G2</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-vet-1a-3/">TÍTOL</a> <a href="https://fctt.cat/lligues/rtb-vet-1a-4/">DESCENS</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-vet-1a-5/">Actes</a></td>
              <td><a href="lligues2627/ranquing/VET_1.pdf">Individual</a></td></tr>
          <tr><td>Preferent</td>
              <td>Actes: <a href="https://fctt.cat/lligues/rtb-pref/">G1</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-pref-asc/">ASCENS</a> <a href="https://fctt.cat/lligues/rtb-pref-desc/">DESCENS</a></td>
              <td><a href="https://fctt.cat/lligues/rtb-pref-po/">Play Off</a></td><td></td></tr>
          <tr><td>2a Comarcal</td><td>Actes: <a href="https://fctt.cat/lligues/rtb-2a-com/">G1</a></td>
              <td colspan="2"></td><td></td></tr>
        </table>
        """
        with patch.object(download_actas, "fetch", return_value=BeautifulSoup(html, "html.parser")):  # type: ignore[attr-defined]
            links = download_actas.report_index_links(
                object(), "2026-2027", "https://rtbtt.com/", 0, download_actas.logging.getLogger()
            )

        self.assertEqual(
            [link[:3] for link in links],
            [
                ("Vet 1a", "G1", "1a Fase"),
                ("Vet 1a", "G2", "1a Fase"),
                ("Vet 1a", "", "TITOL"),
                ("Vet 1a", "", "DESCENS"),
                ("Vet 1a", "", "Play Off Títol"),
                ("Preferent", "G1", "1a Fase"),
                ("Preferent", "", "ASCENS"),
                ("Preferent", "", "DESCENS"),
                ("Preferent", "", "Play Off Ascens"),
                ("2a Comarcal", "G1", "1a Fase"),
            ],
        )

    def test_expected_phases_per_competition(self):
        self.assertEqual(download_actas.expected_phases("Vet 1a"), ["1a Fase", "TITOL", "DESCENS", "Play Off Títol"])
        self.assertEqual(download_actas.expected_phases('Vet 2a "A"'), ["1a Fase", "ASCENS", "DESCENS", "Play Off Ascens"])
        self.assertEqual(download_actas.expected_phases("Preferent"), ["1a Fase", "ASCENS", "DESCENS", "Play Off Ascens"])

    def test_additional_phases_are_siblings_of_1a_fase(self):
        root = Path("out")
        stems = [
            download_actas.acta_stem(root, "2026-2027", download_actas.ReportLink("Vet 1a", group, phase, "", "1-2_1"))
            for group, phase in (("G1", "1a Fase"), ("Other", "TITOL"), ("Other", "DESCENS"), ("Other", "Play Off Títol"))
        ]
        self.assertEqual({stem.parents[2] for stem in stems}, {root / "2026-2027" / "Vet 1a"})
        self.assertEqual(
            [stem.relative_to(root).parts[2:] for stem in stems],
            [
                ("G1", "1a Fase", "acta_1-2_1"),
                ("Other", "TITOL", "acta_1-2_1"),
                ("Other", "DESCENS", "acta_1-2_1"),
                ("Other", "Play Off Títol", "acta_1-2_1"),
            ],
        )


class DownloadReportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.stem = Path(self.directory.name) / "2026-2027" / "Preferent" / "G1" / "1a Fase" / "acta_262-266_1"
        self.report = download_actas.ReportLink("Preferent", "G1", "1a Fase", "https://x/acta", "262-266_1")

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def session(body, content_type=""):
        response = MagicMock()
        response.headers = {"Content-Type": content_type}
        response.iter_content.return_value = iter([body[:4], body[4:]] if body else [])
        session = MagicMock()
        session.get.return_value = response
        return session

    def download(self, session, report=None, force=False):
        return download_actas.download_report(session, report or self.report, self.stem, force, 0)

    def test_downloads_pdf_acta(self):
        self.assertEqual(self.download(self.session(b"%PDF-1.7 data")), "downloaded")
        self.assertEqual((self.stem.parent / "acta_262-266_1.pdf").read_bytes(), b"%PDF-1.7 data")

    def test_downloads_html_acta(self):
        self.assertEqual(self.download(self.session(b"<html><body>acta</body></html>", "text/html")), "downloaded")
        path = self.stem.parent / "acta_262-266_1.html"
        self.assertEqual(path.read_bytes(), b"<html><body>acta</body></html>")
        self.assertFalse(download_actas.is_placeholder(path))

    def test_rejects_unknown_format(self):
        with self.assertRaises(ValueError):
            self.download(self.session(b"\x89PNG....", "image/png"))

    def test_unpublished_acta_is_saved_as_placeholder_without_network(self):
        report = download_actas.ReportLink(
            "Preferent", "G1", "1a Fase", "", "262-266_1", published=False,
            snapshot='<div class="match-container">A - B</div>',
        )
        session = MagicMock()
        self.assertEqual(self.download(session, report), "unpublished")
        session.get.assert_not_called()
        path = self.stem.parent / "acta_262-266_1.html"
        self.assertTrue(download_actas.is_placeholder(path))
        self.assertIn('<div class="match-container">A - B</div>', path.read_text(encoding="utf-8"))

    def test_empty_acta_is_saved_as_placeholder(self):
        self.assertEqual(self.download(self.session(b"", "application/pdf")), "unpublished")
        self.assertTrue(download_actas.is_placeholder(self.stem.parent / "acta_262-266_1.html"))

    def test_published_acta_replaces_placeholder_and_is_then_kept(self):
        unpublished = download_actas.ReportLink("Preferent", "G1", "1a Fase", "", "262-266_1", published=False)
        self.download(MagicMock(), unpublished)
        self.assertEqual(self.download(self.session(b"%PDF-1.7 data")), "downloaded")
        self.assertFalse((self.stem.parent / "acta_262-266_1.html").exists())
        session = MagicMock()
        self.assertEqual(self.download(session), "skipped")
        session.get.assert_not_called()
        # A later run where the link disappears must not overwrite the real acta.
        self.assertEqual(self.download(MagicMock(), unpublished), "skipped")
        self.assertTrue((self.stem.parent / "acta_262-266_1.pdf").exists())

    def test_main_summarises_unpublished_actas_by_phase(self):
        indexes = [("Vet 1a", "G1", "1a Fase", "a"), ("Vet 1a", "", "TITOL", "b")]
        reports = {
            "a": [download_actas.ReportLink("Vet 1a", "G1", "1a Fase", "", "1-2_1", published=False)],
            "b": [],
        }
        with patch.object(download_actas, "report_index_links", return_value=indexes), \
                patch.object(download_actas, "extract_reports", side_effect=lambda *args: reports[args[4]]), \
                patch.object(download_actas, "configure_logging", return_value=download_actas.logging.getLogger("t")), \
                patch("builtins.print") as printed:
            code = download_actas.main(["--season", "2026-2027", "--delay", "0", "--output-root", self.directory.name])

        self.assertEqual(code, 0)
        summary = printed.call_args.args[0]
        self.assertIn("1a Fase (0 downloaded, 0 skipped, 1 unpublished, 0 errors)", summary)
        self.assertIn("TITOL (0 downloaded, 0 skipped, 0 unpublished, 0 errors)", summary)
        self.assertTrue(download_actas.is_placeholder(
            Path(self.directory.name) / "2026-2027" / "Vet 1a" / "G1" / "1a Fase" / "acta_1-2_1.html"
        ))


if __name__ == "__main__":
    unittest.main()




