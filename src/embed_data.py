"""Build the self-contained SHS dashboard HTML.

The checked-in ``SHS_Dashboard.template.html`` file is the canonical visual
template. This builder replaces its placeholder data object with the latest
privacy-safe JSON and embeds Chart.js, so the output works from ``file://``
without a server or network connection.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "SHS_Dashboard.html"
TEMPLATE_PATH = ROOT / "SHS_Dashboard.template.html"
DATA_PATH = ROOT / "SHS_Dashboard.data.json"
CHART_PATH = ROOT / "vendor" / "chart.umd.min.js"

DATA_PATTERN = re.compile(
    r"const D = \{.*?\};(?=\s*// [═]+\s*// HELPERS)",
    flags=re.DOTALL,
)
CHART_TAG_PATTERN = re.compile(
    r'<script\s+src="https://cdnjs\.cloudflare\.com/ajax/libs/Chart\.js/'
    r'[^"]+/chart\.umd\.min\.js"></script>'
)


def main() -> int:
    required = (TEMPLATE_PATH, DATA_PATH, CHART_PATH)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("ERROR: missing required file(s): " + ", ".join(missing), file=sys.stderr)
        return 2

    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_json = DATA_PATH.read_text(encoding="utf-8").strip()
    chart_js = CHART_PATH.read_text(encoding="utf-8").strip()

    # Prevent any future string value from terminating the surrounding script.
    data_json = data_json.replace("</script", "<\\/script")

    html, data_replacements = DATA_PATTERN.subn(
        lambda _: f"const D = {data_json};", html, count=1
    )
    chart_block = (
        "<script>\n/* Chart.js 4.4.1 — MIT license; see vendor/CHARTJS_LICENSE.md */\n"
        + chart_js
        + "\n</script>"
    )
    html, chart_replacements = CHART_TAG_PATTERN.subn(
        lambda _: chart_block,
        html,
        count=1,
    )
    if data_replacements != 1 or chart_replacements != 1:
        print(
            "ERROR: dashboard template markers were not found exactly once "
            f"(data={data_replacements}, chart={chart_replacements}).",
            file=sys.stderr,
        )
        return 3

    HTML_PATH.write_text(html, encoding="utf-8")
    print(
        f"Built {HTML_PATH.name} with {len(data_json):,} bytes of safe data "
        f"and embedded Chart.js."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
