"""Generate deterministic, fully synthetic Excel inputs for the portfolio demo."""
from __future__ import annotations

from itertools import cycle
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

DIAGNOSES = [
    "Sore throat", "Acute cough", "Mixed anxiety and depressive disorder",
    "Anxiety", "Annual physical exam", "Flu vaccine need",
    "Acute pharyngitis, unspecified etiology", "Mild intermittent asthma",
]
RACES = ["White", "Black or African American", "Other Asian", "Multiple\nOther"]
GENDERS = ["Female", "Male", "Non-Binary", "Transgender Male"]
STATUSES = ["Completed", "Completed", "Completed", "Canceled", "No Show"]
VISIT_TYPES = ["OFFICE VISIT", "NEW PATIENT", "PHYSICAL", "SUPPORT STAFF VISIT"]


def rows_for_dates(dates, modern: bool) -> list[dict]:
    dxs, races, genders = cycle(DIAGNOSES), cycle(RACES), cycle(GENDERS)
    statuses, visit_types = cycle(STATUSES), cycle(VISIT_TYPES)
    rows = []
    for index, date in enumerate(dates):
        diagnosis = next(dxs)
        row = {
            "Visit Date": date,
            "Department": "Student Health Services",
            "Appointment Status": next(statuses),
            "Visit Type": next(visit_types),
            "Appointment Time": f"{8 + index % 9:02d}:00:00",
            "Patient Race": next(races),
            "Gender Identity": next(genders),
            "Encounter Diagnosis (All)": diagnosis,
            "Primary Diagnosis": diagnosis,
            "Procedures Ordered": "Synthetic example",
        }
        if modern:
            row["Legal Sex"] = "Female" if index % 3 else "Male"
            row["Patient Ethnic Group"] = "Synthetic / Not applicable"
        rows.append(row)
    return rows


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    dates_a = pd.date_range("2019-09-01", "2022-12-31", periods=480)
    cpts = cycle(["99213 - OFFICE VISIT", "99395 - PHYSICAL", "99203 - NEW PATIENT"])
    dxs, genders = cycle(DIAGNOSES), cycle(["Female", "Male"])
    legacy = pd.DataFrame([
        {
            "Office/Location": "Student Health Services",
            "Date of Service": date,
            "CPT Name Short": next(cpts),
            "ICD-9 1 Name": next(dxs),
            "Patient Gender": next(genders),
        }
        for date in dates_a
    ])
    legacy.to_excel(RAW_DIR / "shs_2019_2022.xlsx", index=False)

    dates_b = pd.date_range("2023-01-01", "2023-12-31", periods=360)
    pd.DataFrame(rows_for_dates(dates_b, modern=False)).to_excel(
        RAW_DIR / "shs_2023.xlsx", index=False
    )

    dates_c = pd.date_range("2024-01-01", "2025-06-30", periods=480)
    pd.DataFrame(rows_for_dates(dates_c, modern=True)).to_excel(
        RAW_DIR / "shs_2024_2025.xlsx", index=False, startrow=1
    )

    print(f"Generated synthetic demo inputs in {RAW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
