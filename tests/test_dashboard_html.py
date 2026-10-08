from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "SHS_Dashboard.html"


class TestGeneratedDashboardHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_scripts_are_balanced(self):
        self.assertEqual(self.html.count("<script"), self.html.count("</script>"))

    def test_dashboard_code_is_inside_script(self):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", self.html, flags=re.DOTALL)
        self.assertTrue(any("function buildPage()" in script for script in scripts))
        self.assertTrue(any("buildPage();" in script for script in scripts))

    def test_has_no_external_runtime_dependencies(self):
        # Scripts, styles, fonts and images are all embedded; the page works offline from file://.
        self.assertNotRegex(self.html, r"<script[^>]+src=")
        self.assertNotRegex(self.html, r"<link[^>]+href=")
        self.assertNotRegex(self.html, r"<img[^>]+src=")
        self.assertNotRegex(self.html, r"url\(\s*['\"]?https?:")
        # The only web addresses allowed are ordinary links a reader can choose to follow
        # (plus the SVG namespace identifier, which is never fetched).
        html = self.html.replace("http://www.w3.org/2000/svg", "")
        self.assertEqual(
            len(re.findall(r"https?://", html)),
            len(re.findall(r'<a [^>]*href="https://', self.html)),
        )

    def test_data_and_font_are_embedded(self):
        self.assertIn("const D = {", self.html)
        self.assertIn("src: url(data:font/woff2;base64,d09G", self.html)
        self.assertNotIn("Chart.js", self.html)

    def test_synthetic_and_suppression_notices_are_present(self):
        self.assertIn("Synthetic public demo.", self.html)
        self.assertIn("None describes Stetson University patients", self.html)
        self.assertIn("a published 0 can mean none or fewer than five", self.html)
        self.assertIn("built into the data generator", self.html)

    def test_suppressed_cells_are_never_marked(self):
        # Privacy contract: a published 0 must look the same whether it is a true zero or a count under 5.
        self.assertNotIn("&lt;5", self.html)
        self.assertNotIn("not shown", self.html)
        self.assertIn("published as 0", self.html)

    def test_headline_counts_appointments(self):
        # The 2023+ exports include canceled and no-show bookings, so the unit is appointments, not visits.
        self.assertIn("clinic appointments that never happened", self.html)
        self.assertNotIn("clinic visits that never happened", self.html)

    def test_accessibility_hooks_are_generated(self):
        self.assertIn('href="#dashboard-main"', self.html)
        self.assertIn('id="dashboard-main"', self.html)
        self.assertIn('aria-pressed="true"', self.html)
        self.assertIn("prefers-reduced-motion", self.html)
        self.assertEqual(len(re.findall(r'<section class="section"', self.html)), 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
