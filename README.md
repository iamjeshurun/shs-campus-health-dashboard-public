# SHS Campus Health Dashboard

A reproducible, privacy-focused analytics portfolio project that transforms
multi-year campus health exports into a standalone interactive dashboard.

**[View the live synthetic-data demo](https://iamjeshurun.github.io/shs-campus-health-dashboard-public/)**

The public repository uses deterministic synthetic inputs. No patient-level
records, institutional exports, or personally identifiable information are
included.

## What this demonstrates

- Multi-format Excel ingestion and schema normalization with pandas
- Diagnosis, visit-type, demographic, status, and time-series aggregation
- Build-time PII exclusion and k-anonymity with `k = 5`
- Automated privacy, schema, HTML, browser, responsive-layout, and keyboard-navigation tests
- A self-contained HTML deliverable with embedded data and Chart.js
- A controlled release process that separates internal inputs from public output

## Architecture

```text
synthetic Excel inputs
        ↓
load + normalize + remove forbidden fields
        ↓
aggregate + suppress cells below k = 5
        ↓
privacy/schema assertions
        ↓
embed safe JSON + Chart.js
        ↓
standalone SHS_Dashboard.html
```

## A concrete reconciliation example

The source exports did not share one clean schema. The pipeline converts
different date shapes, diagnosis representations, and demographic headers into
one internal model before aggregating them:

```text
2022–23 export                 2024–25 export              canonical field
"9/14/2022 10:30 AM"          "2024-09-14"                visit_date
"J02.9" (CPT/diagnosis code)   "Acute pharyngitis"         diagnosis
"Gender Identity"             "Gender"                    gender
```

This normalization is explicit in `src/build_dashboard.py`: it uses multiple
date parsers, falls back from diagnosis text to code mapping, and selects the
available gender field rather than assuming every year has identical columns.

## Run locally

Requires Python 3.10+.

```bash
bash scripts/bootstrap.sh
bash scripts/build_all.sh
```

Open `SHS_Dashboard.html` after the build. It works directly from `file://`
without a server or internet connection.

## Privacy design

- Raw source columns matching known PII fragments are dropped during loading.
- Processed output contains aggregates only—never row-level records.
- Public cells below five are omitted or replaced with zero so true zero and a
  suppressed small count cannot be distinguished.
- Output strings are scanned for common email, phone, SSN, and ZIP patterns.
- Tests fail the build if the privacy threshold or output contract regresses.

See [SYNTHETIC_DATA.md](SYNTHETIC_DATA.md) for the public-data boundary.

## Repository map

```text
src/build_dashboard.py          ingestion, cleaning, aggregation, privacy
src/generate_synthetic_data.py synthetic reproducible demo inputs
src/embed_data.py               standalone dashboard builder
tests/test_dashboard.py         privacy and schema regression tests
tests/test_dashboard_html.py    offline/self-contained HTML checks
tests/test_dashboard_browser.py six-tab desktop and mobile browser checks
SHS_Dashboard.template.html     dashboard HTML/CSS/JavaScript source
SHS_Dashboard.html              generated public dashboard
```

## Important interpretation note

The dashboard is descriptive, and its public counts are deliberately privacy
transformed. In particular:

- It does not establish prevalence, causality, clinical outcomes, access
  disparities, or recommended staffing levels without appropriate denominators
  and additional statistical analysis.
- A displayed zero can mean either a true zero or a count below `k = 5`; this is
  intentional, so readers cannot reverse-engineer small groups.
- Suppression means displayed subtotals may not add exactly to an unsuppressed
  overall total.
- The included dataset is synthetic and demonstrates the pipeline, not the
  health profile of a real campus population.

## Automated checks and deployment

Every push and pull request rebuilds the synthetic dataset and dashboard, runs
the privacy/schema/HTML/browser test suite, and verifies that the checked-in
HTML is reproducible. Pushes to `main` also publish only the generated dashboard
and its Chart.js license to GitHub Pages; no raw or processed source files are
included in the site artifact.
