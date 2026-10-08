"""End-to-end browser tests for the generated dashboard.

Requires the development dependencies in ``requirements-dev.txt`` and either
Google Chrome or a Playwright-installed Chromium browser.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = (ROOT / "SHS_Dashboard.html").resolve().as_uri()
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


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

    def open_dashboard(self, viewport=None, reduced_motion="reduce"):
        page = self.browser.new_page(viewport=viewport or DESKTOP, reduced_motion=reduced_motion)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda msg: msg.type == "error" and errors.append(msg.text))
        page.goto(DASHBOARD, wait_until="load")
        return page, errors

    def test_opening_draws_one_dot_per_published_visit(self):
        page, errors = self.open_dashboard()
        try:
            months = page.evaluate("D.monthly.length")
            self.assertEqual(page.locator("#field path.col").count(), months)
            dots = page.evaluate("[...document.querySelectorAll('#field path.col')].reduce((n, p) => n + (p.getAttribute('d').match(/M/g) || []).length, 0)")
            self.assertEqual(dots, page.evaluate("D.monthly.reduce((n, m) => n + m.visits, 0)"))
            self.assertTrue(page.evaluate("document.fonts.check('900 40px Archivo')"))
            banner = page.get_by_role("note", name="Synthetic public demo").bounding_box()
            self.assertLess(banner["y"] + banner["height"], DESKTOP["height"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_walk_through_steps_and_returns(self):
        page, errors = self.open_dashboard()
        try:
            desk = page.locator("#explain-desk")
            desk.get_by_role("button", name="Walk me through it").click()
            self.assertIn("Step 1 of 5", desk.inner_text())
            self.assertTrue(desk.get_by_role("button", name="Back").is_disabled())
            self.assertEqual(page.evaluate("[...document.querySelectorAll('#field path.col')].filter(p => p.getAttribute('opacity') === '1').length"), 0)
            for expected in ("Step 2 of 5", "Step 3 of 5", "Step 4 of 5", "Step 5 of 5"):
                desk.get_by_role("button", name="Next").click()
                self.assertIn(expected, desk.inner_text())
            self.assertIn("synthetic", desk.inner_text())
            desk.get_by_role("button", name="Finish").click()
            self.assertTrue(desk.get_by_role("button", name="Walk me through it").is_visible())
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_slider_reads_any_month(self):
        page, errors = self.open_dashboard()
        try:
            page.locator("#month-slider").fill("1")
            readout = page.locator("#readout").inner_text()
            self.assertRegex(readout, r"^[A-Z][a-z]{2} \d{4}: \d+ synthetic appointments")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_sections_render_values_and_tables(self):
        page, errors = self.open_dashboard()
        try:
            self.assertEqual(page.locator("#outcome-bars .stack-row").count(), page.evaluate("D.status.length"))
            self.assertEqual(page.locator("#illness-charts figure").count(), 3)
            self.assertEqual(page.locator("#pillar-bars .bar-row").count(), page.evaluate("D.pillars.length"))
            self.assertGreater(page.locator("#dx-bars .bar-row").count(), 5)
            self.assertGreater(page.locator("#heatmap tbody td").count(), 40)
            for table in ("outcome-table", "illness-table", "type-table", "who-table"):
                self.assertGreater(page.locator(f"#{table} tbody tr").count(), 2, table)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_heatmap_toggle_states(self):
        page, errors = self.open_dashboard()
        try:
            no_shows = page.get_by_role("button", name="No-Shows Only")
            no_shows.click()
            self.assertEqual(no_shows.get_attribute("aria-pressed"), "true")
            self.assertEqual(page.get_by_role("button", name="Total Appointments").get_attribute("aria-pressed"), "false")
            self.assertIn("No-show appointments", page.locator("#heat-title").inner_text())
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_omitted_cells_render_as_zero_like_true_zeros(self):
        page, errors = self.open_dashboard()
        try:
            # The build omits heatmap cells under 5; drop one to simulate that and re-render.
            page.evaluate("D.heatmap_total.splice(D.heatmap_total.findIndex(c => c.day === 'Monday' && c.hour === 8), 1); renderHeat('total')")
            first_cell = page.locator("#heatmap tbody tr").first.locator("td").first
            self.assertEqual(first_cell.inner_text().strip(), "0")
            body = page.locator("body").inner_text()
            self.assertNotIn("<5", body)
            self.assertNotIn("not shown", body)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_headline_matches_reconciled_record_count(self):
        page, errors = self.open_dashboard()
        try:
            total = page.evaluate("D.summary.total_records")
            self.assertEqual(total, page.evaluate("D.monthly.reduce((n, m) => n + m.visits, 0)"))
            self.assertIn(f"{total:,} clinic appointments", page.locator("h1").inner_text())
            page.locator("#explain-desk").get_by_role("button", name="Walk me through it").click()
            canceled = page.evaluate("D.status.reduce((n, y) => n + y.Canceled + y['No Show'], 0)")
            legacy = page.evaluate("D._meta.sources.find(x => x.file.includes('2019')).rows")
            step = page.locator("#explain-desk").inner_text()
            self.assertIn(f"mark {canceled:,} of them as canceled or no-shows", step)
            # The 2019-2022 export has no outcome field, so no "visits that happened" total is claimed.
            self.assertIn(f"its {legacy:,} records cannot be split", step)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_phone_shows_the_chart_in_the_first_screen(self):
        page, errors = self.open_dashboard(PHONE)
        try:
            self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), PHONE["width"])
            self.assertTrue(page.locator("#phone-field svg").is_visible())
            self.assertTrue(page.locator("#field").is_hidden())
            chart_top = page.locator("#phone-field").bounding_box()["y"]
            self.assertLess(chart_top, PHONE["height"] * 0.75)
            chips = page.locator("#year-chips button")
            chips.first.click()
            self.assertEqual(page.locator("#year-chips button").first.get_attribute("aria-pressed"), "true")
            page.locator("#month-buttons button").nth(1).click()
            self.assertRegex(page.locator("#phone-readout").inner_text(), r"^Oct \d{4}: \d+ synthetic appointments")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_keyboard_can_start_the_walk_through(self):
        page, errors = self.open_dashboard()
        try:
            button = page.locator("#explain-desk").get_by_role("button", name="Walk me through it")
            button.focus()
            page.keyboard.press("Enter")
            self.assertIn("Step 1 of 5", page.locator("#explain-desk").inner_text())
            self.assertEqual(page.evaluate("document.activeElement.textContent.trim()"), "Next")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_animation_runs_when_motion_is_allowed(self):
        page, errors = self.open_dashboard(reduced_motion="no-preference")
        try:
            self.assertTrue(page.locator("#field.grow").count() == 1)
            self.assertEqual(errors, [])
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
