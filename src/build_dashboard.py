"""
Stetson Health Services — Dashboard data pipeline.

Reads raw SHS Excel files from data/raw/, cleans them, aggregates them into the
shape required by SHS_Dashboard.html, applies privacy protection (k-anonymity,
PII exclusion), and writes safe, dashboard-ready files to data/processed/.

Privacy rules (see README.md for full description):
  * Raw PII columns are NEVER carried into processed outputs.
  * Aggregated cells with count < K_THRESHOLD are suppressed (set to null).
  * Rare demographic categories are bucketed as "Other".
  * Top diagnoses with count < K_THRESHOLD are rolled into "Other".
  * Row-level data is never written to data/processed/.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"

K_THRESHOLD = 5  # k-anonymity: any cell with count < 5 is suppressed


def build_timestamp() -> str:
    """Return a UTC build time, honoring reproducible-build conventions."""
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        return pd.Timestamp(int(source_date_epoch), unit="s", tz="UTC").isoformat()
    return pd.Timestamp.now("UTC").isoformat()

# Forbidden column-name substrings — these MUST NEVER appear in processed output.
FORBIDDEN_COL_FRAGMENTS = (
    "patient_name", "first_name", "last_name", "full_name",
    "mrn", "medical_record",
    "date_of_birth", "birth_date", "birthdate", "dob",
    "ssn",
    "street_address", "home_address", "address_line",
    "phone_number", "email_address",
)
# legal_sex is not listed: it is read only as an aggregated fallback for gender
# in the 2024-25 file (see build_demographics) and never written to output.
# Note: we do NOT block "id" alone — false-positive risk on dashboard keys like "covid".

# PII regex patterns — values matching these are scrubbed from any field.
PII_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),              # US phone
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                            # SSN
    re.compile(r"\b\d{5}(-\d{4})?\b"),                               # ZIP
]

# Visit-type normalization across years.
VISIT_TYPE_NORMALIZE = {
    # 2024-25 friendly names → canonical
    "TELEMEDICINE ESTABLISHED": "TELEMEDICINE",
    "TELEMEDICINE NEW": "TELEMEDICINE",
    "TELEMEDICINE HOSP FOLLOW UP": "TELEMEDICINE",
    "HOSPITAL FOLLOW UP": "HOSPITAL FOLLOW UP",
    "SUPPORT STAFF VISIT": "SUPPORT STAFF VISIT",
    "OFFICE VISIT": "OFFICE VISIT",
    "PHYSICAL": "PHYSICAL",
    "NEW PATIENT": "NEW PATIENT",
    "LAB": "LAB",
    "WELL WOMAN": "WELL WOMAN",
    "MEDICARE ANNUAL WELLNESS": "PHYSICAL",
    # 2023 names → canonical (already mostly canonical)
    "TELEMEDICINE VISIT": "TELEMEDICINE",
    "PAP SMEAR/PELVIC EXAM": "WELL WOMAN",
}

# CPT-code → visit-type mapping (used for 2019-2022 data only).
CPT_TO_VISIT_TYPE = {
    "99213": "OFFICE VISIT",     # OFFICE O/P EST LOW 20-29 MIN
    "99214": "OFFICE VISIT",     # OFFICE O/P EST MOD 30-39 MIN
    "99203": "NEW PATIENT",      # OFFICE O/P NEW LOW 30-44 MIN
    "99204": "NEW PATIENT",
    "99395": "PHYSICAL",         # PREV VISIT EST AGE 18-39
    "99396": "PHYSICAL",
    "99397": "PHYSICAL",
    "G0438": "PHYSICAL",
    "G0439": "PHYSICAL",
    "99406": "SUPPORT STAFF VISIT",  # BEHAV CHNG SMOKING
    "90471": "SUPPORT STAFF VISIT",  # IMMUNIZATION ADMIN
    "96372": "SUPPORT STAFF VISIT",  # THER/PROPH/DIAG INJ
    "87880": "LAB",
    "87426": "LAB",
    "86308": "LAB",
    "81003": "LAB",
    "36415": "LAB",
    "93000": "OFFICE VISIT",
    "90686": "SUPPORT STAFF VISIT",  # flu vaccine
    "90707": "SUPPORT STAFF VISIT",  # MMR
    "J0120": "SUPPORT STAFF VISIT",
    "J0696": "SUPPORT STAFF VISIT",
    "J1030": "SUPPORT STAFF VISIT",
    "3074F": "OFFICE VISIT",
    "3078F": "OFFICE VISIT",
}

# Health-pillar classification (keyword → pillar).
# Order matters: first match wins.
PILLAR_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Mental Health", ("anxiety", "depression", "mood", "adhd",
                       "attention", "psychiatric", "mental")),
    ("Infectious Disease", ("sore throat", "cough", "pharyngitis", "strep",
                            "flu", "influenza", "covid", "viral", "fever",
                            "sinusitis", "respiratory infection", "uri")),
    ("Preventive / Wellness", ("physical", "screening", "vaccine", "vaccin",
                               "well woman", "contraceptive", "pap",
                               "immuniz", "sti screening", "wellness")),
    ("Musculoskeletal", ("pain", "sprain", "strain", "injury", "fracture",
                         "back", "joint", "muscle", "spasm", "arthritis")),
    ("Chronic Disease", ("diabetes", "hypertension", "hyperlipid",
                         "asthma", "thyroid", "anemia", "migraine",
                         "reflux", "pcos", "ibs")),
]

# ──────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────

def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case, trim, and collapse internal whitespace in column names."""
    new_cols = []
    for c in df.columns:
        c = str(c).strip().lower()
        c = re.sub(r"\s+", "_", c)
        new_cols.append(c)
    df = df.copy()
    df.columns = new_cols
    return df


def _parse_date(series: pd.Series) -> pd.Series:
    """Parse a date column tolerating both ISO strings and US M/D/YYYY."""
    return pd.to_datetime(series, format="mixed", errors="coerce")


def _parse_time(series: pd.Series) -> pd.Series:
    """Parse a time-of-day column → integer hour 0-23, NaN on failure."""
    parsed = pd.to_datetime(series.astype(str), format="%H:%M:%S", errors="coerce").dt.hour
    fallback = pd.to_datetime(series.astype(str), format="%H:%M", errors="coerce").dt.hour
    return parsed.fillna(fallback)


def _drop_pii_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop any column whose name contains a forbidden fragment."""
    keep = [c for c in df.columns if not any(frag in c for frag in FORBIDDEN_COL_FRAGMENTS)]
    return df[keep]


def load_2019_2022() -> pd.DataFrame:
    """2019-2022 file: Office, Date, CPT, ICD-9, Gender."""
    path = RAW_DIR / "shs_2019_2022.xlsx"
    df = pd.read_excel(path)
    df = _normalize_columns(df)
    df = df.rename(columns={
        "office/location": "office",
        "date_of_service": "visit_date",
        "cpt_name_short": "cpt",
        "icd-9_1_name": "diagnosis",
        "patient_gender": "gender",
    })
    df["visit_date"] = _parse_date(df["visit_date"])
    df["diagnosis"] = df["diagnosis"].fillna("").astype(str).str.strip()
    # Strip leading "CODE - " from "J02.9 - ACUTE PHARYNGITIS, UNSPECIFIED"
    df["diagnosis_clean"] = df["diagnosis"].str.replace(
        r"^[A-Z]\d{1,3}(\.\d+)?\s*-\s*", "", regex=True
    ).str.strip()
    df["gender"] = df["gender"].astype(str).str.strip().str.title()
    df["source_file"] = "2019_2022"
    return _drop_pii_columns(df)


def load_2023() -> pd.DataFrame:
    """2023 file: header on row 0 of the only sheet.
    Has Visit Date, Department, Procedures, Primary Diagnosis, Status,
    Visit Type, Appointment Time, Race, Gender Identity, Encounter Dx."""
    path = RAW_DIR / "shs_2023.xlsx"
    df = pd.read_excel(path, header=0)
    df = _normalize_columns(df)
    df = df.rename(columns={
        "appointment_status": "status",
        "appointment_time": "visit_time",
        "patient_race": "race",
        "gender_identity": "gender",
        "encounter_diagnosis_(all)": "encounter_dx",
        "primary_diagnosis": "primary_dx",
        "procedures_ordered": "procedures",
    })
    df["visit_date"] = _parse_date(df["visit_date"])
    df["visit_time"] = _parse_time(df["visit_time"])
    # Encounter diagnoses are '\n'-separated; keep raw, also explode for classification.
    df["encounter_dx"] = df["encounter_dx"].fillna("").astype(str)
    df["primary_dx"] = df["primary_dx"].fillna("").astype(str).str.strip()
    df["race"] = df["race"].fillna("").astype(str).str.strip()
    df["gender"] = df["gender"].fillna("").astype(str).str.strip().str.title()
    df["status"] = df["status"].fillna("").astype(str).str.strip()
    df["visit_type"] = df["visit_type"].fillna("").astype(str).str.strip()
    df["source_file"] = "2023"
    return _drop_pii_columns(df)


def load_2024_2025() -> pd.DataFrame:
    """2024-2025 file: header on row 1.
    Has Visit Date, Legal Sex, Department, Status, Visit Type, Appointment Time,
    Race, Ethnic Group, Gender Identity, Encounter Dx."""
    path = RAW_DIR / "shs_2024_2025.xlsx"
    df = pd.read_excel(path, header=1)
    df = _normalize_columns(df)
    df = df.rename(columns={
        "visit_date": "visit_date",
        "legal_sex": "legal_sex",
        "appointment_status": "status",
        "visit_type": "visit_type",
        "appointment_time": "visit_time",
        "patient_race": "race",
        "patient_ethnic_group": "ethnicity",
        "gender_identity": "gender",
        "encounter_diagnosis_(all)": "encounter_dx",
    })
    df["visit_date"] = _parse_date(df["visit_date"])
    df["visit_time"] = _parse_time(df["visit_time"])
    df["encounter_dx"] = df["encounter_dx"].fillna("").astype(str)
    df["race"] = df["race"].fillna("").astype(str).str.strip()
    df["gender"] = df["gender"].fillna("").astype(str).str.strip().str.title()
    df["legal_sex"] = df["legal_sex"].fillna("").astype(str).str.strip().str.title()
    df["status"] = df["status"].fillna("").astype(str).str.strip()
    df["visit_type"] = df["visit_type"].fillna("").astype(str).str.strip()
    df["source_file"] = "2024_2025"
    return _drop_pii_columns(df)


# ──────────────────────────────────────────────────────────────────────
# Cleaning helpers
# ──────────────────────────────────────────────────────────────────────

def split_encounter_dx(s: str) -> list[str]:
    """Split encounter_dx on '\n', trim, drop empties, dedupe preserving order."""
    if not isinstance(s, str) or not s.strip():
        return []
    seen = set()
    out = []
    for part in s.split("\n"):
        p = part.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def normalize_visit_type(s: str) -> str:
    s = (s or "").strip().upper()
    return VISIT_TYPE_NORMALIZE.get(s, s)


def cpt_to_visit_type(cpt: str) -> str:
    code = (cpt or "").split(" - ", 1)[0].strip().upper()
    return CPT_TO_VISIT_TYPE.get(code, "OTHER")


def classify_pillar(dx: str) -> str:
    """Classify a single diagnosis string into a Health Pillar."""
    dl = (dx or "").lower()
    for pillar, kws in PILLAR_KEYWORDS:
        if any(k in dl for k in kws):
            return pillar
    return "Other"


def is_adhd(dx: str) -> bool:
    dl = (dx or "").lower()
    return ("adhd" in dl or "attention-deficit" in dl or "attention deficit" in dl
            or "hyperactivity" in dl or "f90" in dl)


def is_covid(dx: str) -> bool:
    dl = (dx or "").lower()
    return "covid" in dl


def is_flu(dx: str) -> bool:
    dl = (dx or "").lower()
    return ("influenza" in dl or "flu" == dl.strip() or dl.strip().startswith("flu ")
            or "flu," in dl or "flu." in dl)


def is_strep(dx: str) -> bool:
    dl = (dx or "").lower()
    return ("strep" in dl or "pharyngitis" in dl)


def collapse_race(r: str) -> str:
    """Bucket multi-race and 'Decline to Answer' / 'Unknown' / rare categories."""
    r = (r or "").strip()
    if not r:
        return "Unknown"
    if "\n" in r:
        return "Multiple / Other"
    if r in ("Decline to Answer", "Unknown"):
        return "Unknown"
    if r in ("American Indian or Alaska Native", "Native Hawaiian or Other Pacific Islander",
             "Other Pacific Islander", "Filipino American", "Other Asian American",
             "Guamanian or Chamorro", "Samoan"):
        return "Other"
    return r


def collapse_gender(g: str) -> str:
    g = (g or "").strip()
    if not g:
        return "Unknown"
    if g in ("Female", "Male", "Transgender Male", "Transgender Female", "Non-Binary",
             "Other", "Prefer Not To Say", "Decline To Answer", "Unknown"):
        return g.title() if g.lower() != "non-binary" else "Non-Binary"
    return "Other"


# ──────────────────────────────────────────────────────────────────────
# Privacy helpers
# ──────────────────────────────────────────────────────────────────────

def suppress(v: int | float) -> int | None:
    """Apply k-anonymity: suppress counts below threshold."""
    if v is None:
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    if v < K_THRESHOLD:
        return None
    return v


def assert_no_pii(dashboard: dict) -> None:
    """Walk the dashboard JSON; fail if any forbidden column fragment or PII value appears."""
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                klow = str(k).lower()
                if any(frag in klow for frag in FORBIDDEN_COL_FRAGMENTS):
                    raise AssertionError(
                        f"Forbidden column '{k}' at {path}.{k}"
                    )
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str):
            for pat in PII_PATTERNS:
                if pat.search(obj):
                    raise AssertionError(
                        f"PII-pattern value at {path}: {obj[:80]!r}"
                    )
    walk(dashboard)


# ──────────────────────────────────────────────────────────────────────
# Aggregation
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Sources:
    a: pd.DataFrame   # 2019-2022
    b: pd.DataFrame   # 2023
    c: pd.DataFrame   # 2024-2025


def build_monthly(s: Sources) -> list[dict]:
    counts: dict[str, int] = defaultdict(int)
    for df in (s.a, s.b, s.c):
        if "visit_date" not in df.columns:
            continue
        for d in df["visit_date"].dropna():
            key = f"{d.year:04d}-{d.month:02d}"
            counts[key] += 1
    # A zero means either no visits or a suppressed count below K. This keeps
    # the time axis continuous without exposing small cells.
    out = [
        {"ym": k, "visits": int(v) if v >= K_THRESHOLD else 0}
        for k, v in sorted(counts.items())
    ]
    return out


def build_pillars(s: Sources) -> list[dict]:
    """2019-2022 baseline: classify each ICD diagnosis into a pillar.
    File A rows have one diagnosis per row."""
    counts: dict[str, int] = defaultdict(int)
    for dx in s.a["diagnosis_clean"]:
        pillar = classify_pillar(dx)
        counts[pillar] += 1
    # Order pillars for display (largest first).
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    return [{"category": k, "count": int(v)} for k, v in items]


def build_status_by_year(s: Sources) -> list[dict]:
    """Per-year {Completed, Canceled, "No Show", total} across 2023 + 2024-25."""
    per_year: dict[str, dict[str, int]] = defaultdict(lambda: {"Completed": 0, "Canceled": 0, "No Show": 0})
    for df in (s.b, s.c):
        if "status" not in df.columns or "visit_date" not in df.columns:
            continue
        for _, row in df[["status", "visit_date"]].dropna(subset=["visit_date"]).iterrows():
            yr = f"{int(row['visit_date'].year)}"
            st = str(row["status"]).strip()
            if st == "Completed":
                per_year[yr]["Completed"] += 1
            elif st == "Canceled":
                per_year[yr]["Canceled"] += 1
            elif st in ("No Show", "No-Show", "NoShow"):
                per_year[yr]["No Show"] += 1
            # "Scheduled" treated as not-yet-completed and dropped from outcomes
    out = []
    for yr in sorted(per_year.keys()):
        d = per_year[yr]
        d["total"] = d["Completed"] + d["Canceled"] + d["No Show"]
        # Apply k-anonymity to per-year status cells
        d["Completed"] = suppress(d["Completed"]) or 0
        d["Canceled"] = suppress(d["Canceled"]) or 0
        d["No Show"] = suppress(d["No Show"]) or 0
        out.append({"year": yr, **d})
    return out


def build_top_diagnoses(s: Sources, n: int = 20) -> list[dict]:
    """2023 + 2024-25: split multi-dx cells, count, take top n."""
    counts: dict[str, int] = defaultdict(int)
    for df in (s.b, s.c):
        if "encounter_dx" not in df.columns:
            continue
        for cell in df["encounter_dx"]:
            for dx in split_encounter_dx(cell):
                counts[dx] += 1
    # Roll up suppressed diagnoses into "Other"
    above = [(d, c) for d, c in counts.items() if c >= K_THRESHOLD]
    above.sort(key=lambda kv: -kv[1])
    out = [{"diagnosis": d, "count": int(c)} for d, c in above[:n]]
    if len(above) > n:
        # 'Other' = everything outside the top n (already k-suppressed clean)
        other = sum(c for d, c in above[n:])
        out.append({"diagnosis": "Other", "count": int(other)})
    return out


def build_visit_types(s: Sources) -> tuple[dict, dict]:
    """Per-year {visit_type: count}. 2023 from 2023 file; 2024-25 from 2024-25 file."""
    vt_23: dict[str, int] = defaultdict(int)
    for vt in s.b.get("visit_type", pd.Series(dtype=object)).dropna():
        v = normalize_visit_type(vt)
        if v:
            vt_23[v] += 1
    vt_2425: dict[str, int] = defaultdict(int)
    for vt in s.c.get("visit_type", pd.Series(dtype=object)).dropna():
        v = normalize_visit_type(vt)
        if v:
            vt_2425[v] += 1
    # Suppress rare types (count < K_THRESHOLD) → "Other"
    def collapse(d):
        out = {}
        other = 0
        for k, v in d.items():
            if v < K_THRESHOLD:
                other += v
            else:
                out[k] = v
        if other >= K_THRESHOLD:
            out["Other"] = other
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
    return collapse(vt_23), collapse(vt_2425)


def build_adhd_monthly(s: Sources) -> list[dict]:
    """Monthly ADHD-encounter counts from 2023 + 2024-25 (where diagnosis text exists).
    Cells below K_THRESHOLD are written as 0 (privacy-safe — no real difference is
    revealed between '0 visits' and '<5 suppressed visits' for monthly aggregates)."""
    counts: dict[str, int] = defaultdict(int)
    for df in (s.b, s.c):
        if "encounter_dx" not in df.columns or "visit_date" not in df.columns:
            continue
        for _, row in df[["encounter_dx", "visit_date"]].dropna(subset=["visit_date"]).iterrows():
            if any(is_adhd(d) for d in split_encounter_dx(row["encounter_dx"])):
                key = f"{int(row['visit_date'].year):04d}-{int(row['visit_date'].month):02d}"
                counts[key] += 1
    out = []
    for k in sorted(counts.keys()):
        v = counts[k]
        if v < K_THRESHOLD:
            v = 0  # suppress small cells to a safe floor
        out.append({"ym": k, "adhd": int(v)})
    return out


def build_infectious(s: Sources) -> list[dict]:
    """Monthly COVID/Flu/Strep counts from 2023 + 2024-25.
    Cells below K_THRESHOLD are written as 0 (privacy-safe — see build_adhd_monthly)."""
    cov: dict[str, int] = defaultdict(int)
    flu: dict[str, int] = defaultdict(int)
    strp: dict[str, int] = defaultdict(int)
    for df in (s.b, s.c):
        if "encounter_dx" not in df.columns or "visit_date" not in df.columns:
            continue
        for _, row in df[["encounter_dx", "visit_date"]].dropna(subset=["visit_date"]).iterrows():
            dxs = split_encounter_dx(row["encounter_dx"])
            key = f"{int(row['visit_date'].year):04d}-{int(row['visit_date'].month):02d}"
            if any(is_covid(d) for d in dxs):
                cov[key] += 1
            if any(is_flu(d) for d in dxs):
                flu[key] += 1
            if any(is_strep(d) for d in dxs):
                strp[key] += 1
    months = sorted(set(cov) | set(flu) | set(strp))
    out = []
    for k in months:
        c = cov[k] if cov[k] >= K_THRESHOLD else 0
        f = flu[k] if flu[k] >= K_THRESHOLD else 0
        s_ = strp[k] if strp[k] >= K_THRESHOLD else 0
        out.append({"ym": k, "covid": int(c), "flu": int(f), "strep": int(s_)})
    return out


def build_heatmap(s: Sources) -> tuple[list[dict], list[dict]]:
    """Day × hour (8-16, Mon-Fri) totals and no-shows, from 2023 + 2024-25.
    Returns ([{day, hour, value}], [{day, hour, value}])."""
    total: dict[tuple[str, int], int] = defaultdict(int)
    noshow: dict[tuple[str, int], int] = defaultdict(int)
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for df in (s.b, s.c):
        if "visit_date" not in df.columns or "visit_time" not in df.columns or "status" not in df.columns:
            continue
        sub = df[["visit_date", "visit_time", "status"]].dropna(subset=["visit_date", "visit_time"])
        for _, row in sub.iterrows():
            hour = int(row["visit_time"])
            if hour < 8 or hour > 16:
                continue
            day = days[int(row["visit_date"].weekday())]
            if day not in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
                continue
            total[(day, hour)] += 1
            if str(row["status"]).strip() in ("No Show", "No-Show", "NoShow"):
                noshow[(day, hour)] += 1
    def to_list(d):
        out = []
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            for hour in range(8, 17):
                v = suppress(d.get((day, hour), 0))
                if v is not None:
                    out.append({"day": day, "hour": hour, "value": v})
        return out
    return to_list(total), to_list(noshow)


def build_demographics(s: Sources) -> dict:
    """Gender & race by year. For the 2024-25 file, fall back to `legal_sex`
    when `gender identity` is blank, since the EHR often leaves the latter
    blank when it matches the legal sex."""
    def gender(df, fallback_col: str | None = None):
        c: dict[str, int] = defaultdict(int)
        for _, row in df[["gender"] + ([fallback_col] if fallback_col and fallback_col in df.columns else [])].iterrows():
            g = str(row["gender"]).strip()
            if (not g or g.lower() == "nan") and fallback_col and fallback_col in df.columns:
                g = str(row[fallback_col]).strip()
            if not g or g.lower() == "nan":
                continue
            cg = collapse_gender(g)
            c[cg] += 1
        # Apply k-anonymity
        out = {}
        for k, v in c.items():
            sv = suppress(v)
            if sv is not None:
                out[k] = sv
        return out
    def race(df):
        c: dict[str, int] = defaultdict(int)
        for r in df.get("race", pd.Series(dtype=object)).dropna():
            cr = collapse_race(str(r))
            c[cr] += 1
        out = {}
        for k, v in c.items():
            sv = suppress(v)
            if sv is not None:
                out[k] = sv
        return out
    return {
        "gender_2023": gender(s.b),
        "gender_2425": gender(s.c, fallback_col="legal_sex"),
        "race_2023": race(s.b),
        "race_2425": race(s.c),
    }


def build_summary(s: Sources, monthly: list[dict], status: list[dict]) -> dict:
    """Recompute summary KPIs from data."""
    # Overall source totals are safe high-level aggregates. Do not derive this
    # KPI by summing the public monthly series because suppressed cells are 0.
    total = len(s.a) + len(s.b) + len(s.c)
    years = sorted({m["ym"][:4] for m in monthly})
    years_covered = f"{years[0]} – {years[-1]}" if years else ""
    peak = max(monthly, key=lambda m: m["visits"]) if monthly else None
    peak_str = ""
    if peak:
        month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        try:
            y, m = peak["ym"].split("-")
            peak_str = f"{month_names[int(m)]} {y}"
        except Exception:
            peak_str = peak["ym"]

    # Completion / no-show rates from latest year
    latest_year = max((d["year"] for d in status), default=None)
    completion_rate = 0.0
    noshow_rate = 0.0
    noshow_rate_2023 = 0.0
    if latest_year:
        for d in status:
            if d["year"] == latest_year and d["total"]:
                completion_rate = round(d["Completed"] / d["total"] * 100, 1)
                noshow_rate = round(d["No Show"] / d["total"] * 100, 1)
            if d["year"] == "2023" and d["total"]:
                noshow_rate_2023 = round(d["No Show"] / d["total"] * 100, 1)

    # New patient growth: count "NEW PATIENT" visit types between years.
    # Compare 2023 (full year) to 2024 (full year). 2025 is partial so we exclude it.
    new_patient_by_year: dict[str, int] = defaultdict(int)
    for df in (s.b, s.c):
        if "visit_type" not in df.columns or "visit_date" not in df.columns:
            continue
        for _, row in df[["visit_type", "visit_date"]].dropna(subset=["visit_date"]).iterrows():
            if normalize_visit_type(row["visit_type"]) == "NEW PATIENT":
                new_patient_by_year[f"{int(row['visit_date'].year):04d}"] += 1
    np_2023 = new_patient_by_year.get("2023", 0)
    np_2024 = new_patient_by_year.get("2024", 0)
    growth = round((np_2024 / np_2023 - 1) * 100, 1) if np_2023 else 0.0

    # Top condition: highest-count diagnosis from build_top_diagnoses
    top_dx = ""
    if s.b["encounter_dx"].notna().any() or s.c["encounter_dx"].notna().any():
        counts: dict[str, int] = defaultdict(int)
        for df in (s.b, s.c):
            for cell in df["encounter_dx"]:
                for d in split_encounter_dx(cell):
                    counts[d] += 1
        if counts:
            top_dx = max(counts.items(), key=lambda kv: kv[1])[0]

    return {
        "total_records": int(total),
        "years_covered": years_covered,
        "completion_rate_2425": completion_rate,
        "noshow_rate_2425": noshow_rate,
        "noshow_rate_2023": noshow_rate_2023,
        "new_patient_growth": growth,
        "peak_month": peak_str,
        "top_condition": top_dx,
    }


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    if not RAW_DIR.exists():
        print(f"ERROR: {RAW_DIR} does not exist. Place Excel files there.", file=sys.stderr)
        return 2

    print("Loading raw files…")
    a = load_2019_2022()
    b = load_2023()
    c = load_2024_2025()
    print(f"  2019-2022: {len(a)} rows")
    print(f"  2023:      {len(b)} rows")
    print(f"  2024-2025: {len(c)} rows")

    s = Sources(a=a, b=b, c=c)

    print("Aggregating…")
    monthly = build_monthly(s)
    pillars = build_pillars(s)
    status = build_status_by_year(s)
    top_diagnoses = build_top_diagnoses(s, n=20)
    vt_23, vt_2425 = build_visit_types(s)
    adhd = build_adhd_monthly(s)
    infectious = build_infectious(s)
    heatmap_total, heatmap_noshow = build_heatmap(s)
    demo = build_demographics(s)
    summary = build_summary(s, monthly, status)

    dashboard = {
        "summary": summary,
        "monthly": monthly,
        "pillars": pillars,
        "status": status,
        "top_diagnoses": top_diagnoses,
        "visit_types_2023": vt_23,
        "visit_types_2425": vt_2425,
        "adhd": adhd,
        "infectious": infectious,
        "heatmap_total": heatmap_total,
        "heatmap_noshow": heatmap_noshow,
        **demo,
        "_meta": {
            "k_threshold": K_THRESHOLD,
            "generated_at": build_timestamp(),
            "sources": [
                {"file": "shs_2019_2022.xlsx", "rows": len(a)},
                {"file": "shs_2023.xlsx", "rows": len(b)},
                {"file": "shs_2024_2025.xlsx", "rows": len(c)},
            ],
        },
    }

    print("Validating privacy…")
    assert_no_pii(dashboard)
    print("  ✓ no forbidden columns or PII values found")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "dashboard.json"
    csv_path = OUT_DIR / "dashboard.csv"

    # Write JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    print(f"  wrote {json_path}")

    # Write a flat CSV summarizing key series (handy for spot-checks)
    flat_rows = []
    for m in monthly:
        flat_rows.append({"series": "monthly_visits", "key": m["ym"], "value": m["visits"]})
    for p in pillars:
        flat_rows.append({"series": "pillar", "key": p["category"], "value": p["count"]})
    for d in status:
        flat_rows.append({"series": f"status_{d['year']}_completed", "key": d["year"], "value": d["Completed"]})
        flat_rows.append({"series": f"status_{d['year']}_canceled", "key": d["year"], "value": d["Canceled"]})
        flat_rows.append({"series": f"status_{d['year']}_noshow", "key": d["year"], "value": d["No Show"]})
    pd.DataFrame(flat_rows).to_csv(csv_path, index=False)
    print(f"  wrote {csv_path}")

    # Also write an embedded copy next to the HTML so it can be opened via file://
    embed_path = ROOT / "SHS_Dashboard.data.json"
    with open(embed_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2, ensure_ascii=False)
    print(f"  wrote {embed_path} (frontend fallback for file:// open)")

    # Privacy log summary (counts only — no row-level data)
    print()
    print("Privacy summary:")
    print(f"  k-anonymity threshold:    {K_THRESHOLD}")
    print(f"  monthly points:          {len(monthly)}")
    print(f"  heatmap total cells:     {len(heatmap_total)}")
    print(f"  heatmap noshow cells:    {len(heatmap_noshow)}")
    print(f"  infectious monthly:      {len(infectious)}")
    print(f"  adhd monthly:            {len(adhd)}")
    print(f"  top diagnoses:           {len(top_diagnoses)}")
    print(f"  gender_2023 cats:        {len(demo['gender_2023'])}")
    print(f"  gender_2425 cats:        {len(demo['gender_2425'])}")
    print(f"  race_2023 cats:          {len(demo['race_2023'])}")
    print(f"  race_2425 cats:          {len(demo['race_2425'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
