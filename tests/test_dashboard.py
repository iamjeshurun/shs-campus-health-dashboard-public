"""
Privacy and validity tests for the processed dashboard output.

Run via:
    .venv/bin/python -m unittest tests.test_dashboard -v

or:
    .venv/bin/python tests/test_dashboard.py
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_JSON = ROOT / "data" / "processed" / "dashboard.json"

K_THRESHOLD = 5

# Column-name fragments that must NEVER appear in any processed output.
FORBIDDEN_COL_FRAGMENTS = (
    "patient_name", "first_name", "last_name", "full_name",
    "mrn", "medical_record",
    "date_of_birth", "birth_date", "birthdate", "dob",
    "ssn",
    "street_address", "home_address", "address_line",
    "phone_number", "email_address",
    "legal_sex",
)

# Regex patterns for PII that must NEVER appear as values.
PII_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b\d{5}(-\d{4})?\b"),
]


def load_dashboard() -> dict:
    if not DASHBOARD_JSON.exists():
        raise FileNotFoundError(
            f"{DASHBOARD_JSON} not found. Run src/build_dashboard.py first."
        )
    with open(DASHBOARD_JSON, encoding="utf-8") as f:
        return json.load(f)


def walk(obj, path="root"):
    """Yield (path, key_or_index, value) for every leaf."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, None, obj


class TestPrivacy(unittest.TestCase):
    """No PII columns or PII values may appear in any processed output."""

    @classmethod
    def setUpClass(cls):
        cls.d = load_dashboard()

    def test_no_forbidden_columns(self):
        for path, _, value in walk(self.d):
            if isinstance(value, (dict, list)):
                continue
            parent = path.rsplit(".", 1)[0] if "." in path else path
            for k in (parent.rsplit(".", 1)[-1], parent):
                klow = k.lower()
                for frag in FORBIDDEN_COL_FRAGMENTS:
                    self.assertNotIn(frag, klow,
                        f"Forbidden column fragment '{frag}' in key '{k}' at {path}")

    def test_no_pii_values(self):
        for path, _, value in walk(self.d):
            if isinstance(value, str):
                for pat in PII_PATTERNS:
                    self.assertIsNone(
                        pat.search(value),
                        f"PII-pattern value at {path}: {value[:80]!r}"
                    )



class TestPiiColumnFilter(unittest.TestCase):
    """Identifying raw columns are dropped before any aggregation."""

    def test_identifying_columns_are_dropped(self):
        import pandas as pd

        sys.path.insert(0, str(ROOT / "src"))
        from build_dashboard import _drop_pii_columns

        df = pd.DataFrame(columns=[
            "patient_name", "date_of_birth", "mrn", "email_address",
            "phone_number", "gender", "visit_date", "legal_sex",
        ])
        self.assertEqual(
            list(_drop_pii_columns(df).columns), ["gender", "visit_date", "legal_sex"]
        )


class TestSuppression(unittest.TestCase):
    """Aggregated cells must respect k-anonymity threshold."""

    @classmethod
    def setUpClass(cls):
        cls.d = load_dashboard()

    def _assert_k_anonymous_list(self, items, value_key, label_keys):
        for it in items:
            v = it.get(value_key)
            if v is None:
                continue
            self.assertGreaterEqual(
                v, K_THRESHOLD,
                f"Cell {it} violates k-anonymity (value < {K_THRESHOLD})"
            )

    def test_heatmap_total_k_anonymous(self):
        self._assert_k_anonymous_list(
            self.d["heatmap_total"], "value", ("day", "hour")
        )

    def test_monthly_volume_k_anonymous(self):
        """Monthly cells are either suppressed to 0 or safe to publish."""
        for entry in self.d["monthly"]:
            value = entry["visits"]
            self.assertTrue(
                value == 0 or value >= K_THRESHOLD,
                f"monthly[{entry['ym']}].visits = {value} violates k-anonymity",
            )

    def test_heatmap_noshow_k_anonymous(self):
        self._assert_k_anonymous_list(
            self.d["heatmap_noshow"], "value", ("day", "hour")
        )

    def test_gender_categories_k_anonymous(self):
        for key in ("gender_2023", "gender_2425"):
            for k, v in self.d[key].items():
                self.assertGreaterEqual(
                    v, K_THRESHOLD,
                    f"{key}.{k} = {v} violates k-anonymity"
                )

    def test_race_categories_k_anonymous(self):
        for key in ("race_2023", "race_2425"):
            for k, v in self.d[key].items():
                self.assertGreaterEqual(
                    v, K_THRESHOLD,
                    f"{key}.{k} = {v} violates k-anonymity"
                )

    def test_visit_types_k_anonymous(self):
        for key in ("visit_types_2023", "visit_types_2425"):
            for k, v in self.d[key].items():
                self.assertGreaterEqual(
                    v, K_THRESHOLD,
                    f"{key}.{k} = {v} violates k-anonymity"
                )

    def test_top_diagnoses_k_anonymous(self):
        for entry in self.d["top_diagnoses"]:
            self.assertGreaterEqual(
                entry["count"], K_THRESHOLD,
                f"Diagnosis '{entry['diagnosis']}' = {entry['count']} "
                f"violates k-anonymity"
            )

    def test_adhd_monthly_has_no_nulls(self):
        """After the pipeline, ADHD cells <K are written as 0, not null."""
        for entry in self.d["adhd"]:
            self.assertIsNotNone(
                entry["adhd"],
                f"adhd[{entry['ym']}].adhd is null (should be 0 or int)"
            )

    def test_infectious_monthly_has_no_nulls(self):
        for entry in self.d["infectious"]:
            for k in ("covid", "flu", "strep"):
                self.assertIsNotNone(
                    entry[k],
                    f"infectious[{entry['ym']}].{k} is null"
                )

    def test_status_year_cells_respect_threshold(self):
        for entry in self.d["status"]:
            for k in ("Completed", "Canceled", "No Show"):
                v = entry.get(k)
                self.assertIsNotNone(v, f"status[{entry['year']}].{k} is null")
                self.assertGreaterEqual(v, K_THRESHOLD,
                    f"status[{entry['year']}].{k} = {v} violates k-anonymity")


class TestShape(unittest.TestCase):
    """Sanity checks on the dashboard's expected schema."""

    @classmethod
    def setUpClass(cls):
        cls.d = load_dashboard()

    def test_top_level_keys(self):
        expected = {
            "summary", "monthly", "pillars", "status", "top_diagnoses",
            "visit_types_2023", "visit_types_2425",
            "adhd", "infectious", "heatmap_total", "heatmap_noshow",
            "gender_2023", "gender_2425", "race_2023", "race_2425",
            "_meta",
        }
        self.assertTrue(expected.issubset(set(self.d.keys())),
            f"Missing keys: {expected - set(self.d.keys())}")

    def test_summary_has_required_fields(self):
        for k in ("total_records", "years_covered", "completion_rate_2425",
                  "noshow_rate_2425", "noshow_rate_2023", "new_patient_growth",
                  "peak_month", "top_condition"):
            self.assertIn(k, self.d["summary"], f"summary.{k} missing")

    def test_monthly_is_sorted_ascending(self):
        keys = [m["ym"] for m in self.d["monthly"]]
        self.assertEqual(keys, sorted(keys),
            "monthly is not sorted ascending by ym")

    def test_monthly_has_visits_key(self):
        for m in self.d["monthly"]:
            self.assertIn("visits", m)
            self.assertIsInstance(m["visits"], int)
            self.assertGreaterEqual(m["visits"], 0)

    def test_status_has_required_keys(self):
        for s in self.d["status"]:
            for k in ("year", "Completed", "Canceled", "No Show", "total"):
                self.assertIn(k, s, f"status entry missing {k}: {s}")

    def test_pillars_have_category_and_count(self):
        for p in self.d["pillars"]:
            self.assertIn("category", p)
            self.assertIn("count", p)
            self.assertIsInstance(p["count"], int)
            self.assertGreater(p["count"], 0)

    def test_top_diagnoses_have_diagnosis_and_count(self):
        for t in self.d["top_diagnoses"]:
            self.assertIn("diagnosis", t)
            self.assertIn("count", t)

    def test_infectious_months_sorted(self):
        keys = [i["ym"] for i in self.d["infectious"]]
        self.assertEqual(keys, sorted(keys))

    def test_adhd_months_sorted(self):
        keys = [a["ym"] for a in self.d["adhd"]]
        self.assertEqual(keys, sorted(keys))

    def test_summary_total_records_consistent(self):
        """The public monthly total may be lower due to suppressed cells."""
        total = sum(m["visits"] for m in self.d["monthly"])
        self.assertGreater(total, 1000,
            f"Total monthly visits {total} seems too low")
        raw_total = self.d["summary"]["total_records"]
        self.assertLessEqual(total, raw_total)
        self.assertLess(raw_total - total, K_THRESHOLD * len(self.d["monthly"]))

    def test_meta_block_present(self):
        self.assertIn("_meta", self.d)
        self.assertEqual(self.d["_meta"]["k_threshold"], K_THRESHOLD)
        self.assertIn("generated_at", self.d["_meta"])
        self.assertRegex(
            self.d["_meta"]["generated_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00$",
        )
        self.assertEqual(len(self.d["_meta"]["sources"]), 3)



if __name__ == "__main__":
    # Allow running directly: `python tests/test_dashboard.py`
    unittest.main(verbosity=2)
