"""Generate deterministic, fully synthetic Excel inputs for the portfolio demo.

Nothing here comes from real patients. Visits are drawn from a seeded random model of a
generic academic calendar, so the demo has the kind of structure real clinic data has
(semesters, breaks, a winter respiratory season) without describing any real campus:

* Volume follows the term: full during fall and spring semesters, lower in the summer,
  near zero over winter break, and reduced during Thanksgiving week and spring break.
* The clinic is closed at weekends; Mondays are busiest.
* The diagnosis mix shifts with the season: respiratory illness in winter, vaccines and
  physicals at the start of the fall term, mental-health visits rising toward midterms
  and finals.
* A few deliberately small groups (rare diagnoses, small demographic categories) fall
  below the k = 5 threshold so the build's suppression rules are exercised.

The three output files keep the different column layouts of the original exports, so the
build still has to reconcile them.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
SEED = 20250630
DAILY_BASE = 11.0  # expected visits on an ordinary semester Wednesday
WEEKDAY_FACTOR = [1.25, 1.1, 1.0, 0.95, 0.75, 0.0, 0.0]  # Monday .. Sunday
YEAR_FACTOR = {2019: 0.97, 2020: 1.0, 2021: 1.03, 2022: 1.0, 2023: 1.05, 2024: 1.02}  # by fall year

# name, ICD-10 code for the legacy export, category weight, seasonal profile
DIAGNOSES = [
    ("Sore throat", "J02.9", 9, "respiratory"),
    ("Acute cough", "R05.1", 8, "respiratory"),
    ("Acute pharyngitis, unspecified etiology", "J02.9", 5, "respiratory"),
    ("Strep pharyngitis", "J02.0", 3, "respiratory"),
    ("Influenza", "J11.1", 3, "flu"),
    ("COVID-19", "U07.1", 3, "covid"),
    ("Anxiety", "F41.9", 9, "term_stress"),
    ("Mixed anxiety and depressive disorder", "F41.8", 6, "term_stress"),
    ("ADHD follow-up", "F90.9", 4, "term_stress"),
    ("Insomnia", "G47.00", 2, "term_stress"),
    ("Annual physical exam", "Z00.00", 6, "term_start"),
    ("Flu vaccine need", "Z23", 5, "vaccine"),
    ("Mild intermittent asthma", "J45.20", 3, "flat"),
    ("Migraine", "G43.909", 3, "flat"),
    ("Ankle sprain", "S93.409A", 3, "flat"),
    ("Urinary tract infection", "N39.0", 3, "flat"),
    ("Contraception counseling", "Z30.09", 3, "flat"),
    ("Conjunctivitis", "H10.9", 0.15, "flat"),  # rare: mostly rolled into "Other"
    ("Mononucleosis", "B27.90", 0.12, "flat"),  # rare
]
RACES = (["White", "Black or African American", "Other Asian", "Multiple\nOther", "Decline to Answer",
          "American Indian or Alaska Native"], [0.56, 0.16, 0.1, 0.1, 0.07, 0.01])
GENDERS = (["Female", "Male", "Non-Binary", "Transgender Male", "Transgender Female"], [0.6, 0.35, 0.03, 0.015, 0.005])
STATUSES = (["Completed", "Canceled", "No Show"], [0.78, 0.12, 0.10])
VISIT_TYPES = (["OFFICE VISIT", "NEW PATIENT", "PHYSICAL", "SUPPORT STAFF VISIT"], [0.6, 0.12, 0.1, 0.18])
HOURS = (list(range(8, 17)), [0.09, 0.13, 0.14, 0.13, 0.07, 0.12, 0.12, 0.11, 0.09])
CPT_FOR_TYPE = {"OFFICE VISIT": "99213 - OFFICE VISIT", "NEW PATIENT": "99203 - NEW PATIENT",
                "PHYSICAL": "99395 - PHYSICAL", "SUPPORT STAFF VISIT": "90686 - FLU VACCINE"}


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def term_position(day: date) -> tuple[str, float]:
    """Which part of the academic year a day falls in, and how far through its semester (0..1)."""
    fall_year = day.year if day.month >= 8 else day.year - 1
    fall_start, fall_end = date(fall_year, 8, 19), date(fall_year, 12, 13)
    spring_start, spring_end = date(fall_year + 1, 1, 8), date(fall_year + 1, 5, 3)
    thanksgiving = nth_weekday(fall_year, 11, 3, 4)
    spring_break = nth_weekday(fall_year + 1, 3, 0, 2)
    if fall_start <= day <= fall_end:
        if thanksgiving - timedelta(days=3) <= day <= thanksgiving + timedelta(days=1):
            return "short_break", 0.0
        return "fall", (day - fall_start).days / (fall_end - fall_start).days
    if spring_start <= day <= spring_end:
        if spring_break <= day <= spring_break + timedelta(days=4):
            return "short_break", 0.0
        return "spring", (day - spring_start).days / (spring_end - spring_start).days
    if fall_end < day < spring_start:
        return "winter_break", 0.0
    return "summer", 0.0


TERM_FACTOR = {"fall": 1.0, "spring": 1.0, "short_break": 0.3, "winter_break": 0.06, "summer": 0.22}


def seasonal_weight(profile: str, day: date, term: str, progress: float) -> float:
    winter = np.exp(-(((day.timetuple().tm_yday + 20) % 365 - 40) / 32) ** 2)  # peaks in early February
    if profile == "respiratory":
        return 0.7 + 0.9 * winter
    if profile == "flu":
        return 0.1 + 2.6 * winter
    if profile == "covid":
        return 0.0 if day < date(2020, 9, 1) else 0.3 + 1.6 * winter
    if profile == "term_stress":  # rises through each semester toward midterms and finals
        return 0.6 + (0.9 * progress if term in ("fall", "spring") else 0.0)
    if profile == "term_start":
        return 2.5 if term == "fall" and progress < 0.12 else (1.4 if term == "summer" else 0.7)
    if profile == "vaccine":
        return 2.4 if day.month in (9, 10, 11) else 0.25
    return 1.0


def generate_visits(rng: np.random.Generator, start: date, end: date) -> list[dict]:
    visits = []
    day = start
    while day <= end:
        term, progress = term_position(day)
        fall_year = day.year if day.month >= 8 else day.year - 1
        rate = DAILY_BASE * WEEKDAY_FACTOR[day.weekday()] * TERM_FACTOR[term] * YEAR_FACTOR.get(fall_year, 1.0)
        if term == "fall" and progress < 0.08:
            rate *= 1.25  # start-of-year physicals and immunizations
        count = rng.poisson(rate) if rate > 0 else 0
        if count:
            weights = np.array([w * seasonal_weight(p, day, term, progress) for _, _, w, p in DIAGNOSES])
            weights /= weights.sum()
            finals = term in ("fall", "spring") and progress > 0.9
            status_p = [0.73, 0.12, 0.15] if finals else STATUSES[1]
            for _ in range(count):
                dx = DIAGNOSES[rng.choice(len(DIAGNOSES), p=weights)]
                visits.append({
                    "date": day,
                    "hour": int(rng.choice(HOURS[0], p=HOURS[1])),
                    "diagnosis": dx[0],
                    "code": dx[1],
                    "status": str(rng.choice(STATUSES[0], p=status_p)),
                    "visit_type": str(rng.choice(VISIT_TYPES[0], p=VISIT_TYPES[1])),
                    "race": str(rng.choice(RACES[0], p=RACES[1])),
                    "gender": str(rng.choice(GENDERS[0], p=GENDERS[1])),
                })
        day += timedelta(days=1)
    return visits


def modern_rows(visits: list[dict], with_legal_sex: bool, rng: np.random.Generator) -> list[dict]:
    rows = []
    for v in visits:
        row = {
            "Visit Date": pd.Timestamp(v["date"]),
            "Department": "Student Health Services",
            "Appointment Status": v["status"],
            "Visit Type": v["visit_type"],
            "Appointment Time": f"{v['hour']:02d}:{int(rng.choice([0, 15, 30, 45])):02d}:00",
            "Patient Race": v["race"],
            "Gender Identity": v["gender"],
            "Encounter Diagnosis (All)": v["diagnosis"],
            "Primary Diagnosis": v["diagnosis"],
            "Procedures Ordered": "Synthetic example",
        }
        if with_legal_sex:
            row["Legal Sex"] = "Male" if v["gender"] in ("Male", "Transgender Female") else "Female"
            row["Patient Ethnic Group"] = "Synthetic / Not applicable"
        rows.append(row)
    return rows


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    # 2019-2022 export: one diagnosis per row with its code, CPT procedure, binary gender field.
    legacy = generate_visits(rng, date(2019, 9, 1), date(2022, 12, 31))
    pd.DataFrame([
        {
            "Office/Location": "Student Health Services",
            "Date of Service": pd.Timestamp(v["date"]).strftime("%-m/%-d/%Y") + f" {((v['hour'] - 1) % 12) + 1}:00 {'AM' if v['hour'] < 12 else 'PM'}",
            "CPT Name Short": CPT_FOR_TYPE[v["visit_type"]],
            "ICD-9 1 Name": f"{v['code']} - {v['diagnosis'].upper()}",
            "Patient Gender": "Male" if v["gender"] in ("Male", "Transgender Female") else "Female",
        }
        for v in legacy
    ]).to_excel(RAW_DIR / "shs_2019_2022.xlsx", index=False)

    # 2023 export: header on the first row.
    visits_2023 = generate_visits(rng, date(2023, 1, 1), date(2023, 12, 31))
    pd.DataFrame(modern_rows(visits_2023, False, rng)).to_excel(RAW_DIR / "shs_2023.xlsx", index=False)

    # 2024-2025 export: a title row above the header, plus legal sex and ethnicity columns.
    visits_2024 = generate_visits(rng, date(2024, 1, 1), date(2025, 6, 30))
    pd.DataFrame(modern_rows(visits_2024, True, rng)).to_excel(RAW_DIR / "shs_2024_2025.xlsx", index=False, startrow=1)

    print(f"Generated {len(legacy) + len(visits_2023) + len(visits_2024)} synthetic visits in {RAW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
