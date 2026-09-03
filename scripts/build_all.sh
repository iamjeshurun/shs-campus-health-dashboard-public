#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

.venv/bin/python src/generate_synthetic_data.py
.venv/bin/python src/build_dashboard.py
.venv/bin/python src/embed_data.py
.venv/bin/python -m unittest tests.test_dashboard -v
.venv/bin/python -m unittest tests.test_dashboard_html -v
.venv/bin/python -m unittest tests.test_dashboard_browser -v
echo "Synthetic build, privacy checks, and browser checks completed."
