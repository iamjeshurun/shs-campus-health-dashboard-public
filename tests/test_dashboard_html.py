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
        self.assertTrue(any("function showTab(name, button)" in script for script in scripts))
        self.assertTrue(any("buildOverview();" in script for script in scripts))

    def test_has_no_external_runtime_dependencies(self):
        self.assertNotRegex(self.html, r'<script[^>]+src=')
        self.assertNotRegex(self.html, r'<link[^>]+href=["\']https?://')
        self.assertNotIn("https://", self.html)
        self.assertNotIn("http://", self.html)

    def test_data_and_chart_library_are_embedded(self):
        self.assertIn("const D = {", self.html)
        self.assertIn("Chart.js 4.4.1", self.html)

    def test_accessible_tab_structure_is_generated(self):
        self.assertEqual(len(re.findall(r'<button[^>]+role="tab"', self.html)), 6)
        self.assertEqual(len(re.findall(r'<div[^>]+role="tabpanel"', self.html)), 6)
        self.assertIn('href="#dashboard-main"', self.html)
        self.assertIn("event.key==='ArrowRight'", self.html)
        self.assertIn('aria-pressed="true"', self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
