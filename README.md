# SHS Campus Health Dashboard

A reproducible, privacy-focused analytics portfolio project that transforms
multi-year campus health exports into a standalone interactive dashboard.

The public repository uses deterministic synthetic inputs. No patient-level
records, institutional exports, or personally identifiable information are
included.

## What this demonstrates

- Multi-format Excel ingestion and schema normalization with pandas
- Diagnosis, visit-type, demographic, status, and time-series aggregation
- Build-time PII exclusion and k-anonymity with `k = 5`
- Automated privacy, schema, HTML, browser, and responsive-layout tests
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

The dashboard is descriptive. It does not establish prevalence, causality,
clinical outcomes, access disparities, or recommended staffing levels without
appropriate denominators and additional statistical analysis.
