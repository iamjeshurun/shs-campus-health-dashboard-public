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
- A self-contained HTML page with embedded data, an embedded font and hand-built SVG charts, so it opens offline
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
embed safe JSON + font into the page template
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

## What the page shows

The public page is a single long-scroll "observatory". It opens with every synthetic appointment record drawn as a dot, 11,834
of them in monthly columns (from 2023 the records include canceled and no-show bookings), under a banner that labels the data as a synthetic public demo. A short explanation sits next
to the chart, and a five-step **Walk me through it** reading highlights one appointment, one month, one academic year, all six
years and finally why the data is synthetic. Below the opening:

- **Busiest hours:** appointments by weekday and hour, with a toggle for no-shows only. Cells under 5 show as 0, like
  every other suppressed count.
- **Outcomes:** completed, canceled and no-show shares by calendar year.
- **Seasonal illness:** COVID-19, influenza and strep throat by month.
- **Reasons for visits:** care categories, the most common diagnoses, visit types and ADHD follow-ups.
- **Who visits:** gender identity and race shares for each period.
- **Method and privacy:** the pipeline, what the synthetic data is, and what it cannot tell you.

Every chart has a plain-language title, a "how to read it" note, a source line and a **Show the numbers** table. The
page works with a keyboard and at phone width, and respects reduced-motion settings.

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
tests/test_dashboard_browser.py desktop and phone browser checks
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
and its font license to GitHub Pages; no raw or processed source files are
included in the site artifact.
