"""End-to-end browser smoke tests for the generated dashboard.

Requires the development dependencies in ``requirements-dev.txt`` and either
Google Chrome or a Playwright-installed Chromium browser.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = (ROOT / "SHS_Dashboard.html").resolve().as_uri()


class TestDashboardBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)
        except Exception:
            cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open_dashboard(self, viewport=None):
        page = self.browser.new_page(viewport=viewport or {"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(DASHBOARD, wait_until="load")
        return page, errors

    def test_all_tabs_render_charts_and_kpis(self):
        page, errors = self.open_dashboard()
        try:
            self.assertEqual(page.evaluate("typeof Chart"), "function")
            self.assertEqual(page.evaluate("typeof showTab"), "function")
            self.assertGreater(page.locator("#kpi-strip .kpi").count(), 0)
            self.assertNotIn("function buildOverview()", page.locator("body").inner_text())

            tabs = {
                "Overview": "tab-overview",
                "Visit Volume": "tab-volume",
                "Infectious Disease": "tab-infectious",
                "Operations": "tab-operations",
                "Top Diagnoses": "tab-diagnoses",
                "Demographics": "tab-demographics",
            }
            for label, section_id in tabs.items():
                page.get_by_role("tab", name=label).click()
                self.assertTrue(page.locator(f"#{section_id}").is_visible(), label)

            self.assertGreaterEqual(page.evaluate("Object.keys(Chart.instances).length"), 17)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_mobile_layout_and_accessibility_hooks(self):
        page, errors = self.open_dashboard({"width": 390, "height": 844})
        try:
            self.assertEqual(page.get_by_role("tab").count(), 6)
            self.assertEqual(page.get_by_role("tab", name="Overview").get_attribute("aria-selected"), "true")
            page.get_by_role("tab", name="Demographics").click()
            self.assertEqual(page.get_by_role("tab", name="Demographics").get_attribute("aria-selected"), "true")
            self.assertGreaterEqual(page.locator("canvas[role=img][aria-label]").count(), 8)
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 520)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_keyboard_tabs_and_toggle_states(self):
        page, errors = self.open_dashboard()
        try:
            overview = page.get_by_role("tab", name="Overview")
            overview.focus()
            overview.press("ArrowRight")
            volume = page.get_by_role("tab", name="Visit Volume")
            self.assertEqual(volume.get_attribute("aria-selected"), "true")
            self.assertEqual(volume.get_attribute("tabindex"), "0")
            self.assertTrue(page.locator("#tab-volume").is_visible())
            self.assertTrue(page.locator("#tab-overview").is_hidden())

            page.get_by_role("tab", name="Operations").click()
            no_shows = page.get_by_role("button", name="No-Shows Only")
            no_shows.click()
            self.assertEqual(no_shows.get_attribute("aria-pressed"), "true")
            self.assertEqual(
                page.get_by_role("button", name="Total Appointments").get_attribute("aria-pressed"),
                "false",
            )
            self.assertEqual(errors, [])
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
