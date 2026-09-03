"""Build the self-contained SHS dashboard HTML.

The checked-in ``SHS_Dashboard.template.html`` file is the canonical visual
template. This builder replaces its placeholder data object with the latest
privacy-safe JSON and embeds Chart.js, so the output works from ``file://``
without a server or network connection.

The template marks the two spots this script writes into with explicit,
literal markers (not regex patterns tied to surrounding formatting):

  * DATA_INJECTION_POINT_START / _END   — wraps the placeholder `const D = {}`
  * <!--CHART_JS_INJECTION_POINT--> / <!--/CHART_JS_INJECTION_POINT-->
                                          — wraps the CDN <script> tag

Editing the template's styling, comments, or surrounding JS is safe as long
as these marker lines stay intact — the build only looks for exact string
matches, so it fails loudly if a marker goes missing instead of silently
writing to the wrong place.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "SHS_Dashboard.html"
TEMPLATE_PATH = ROOT / "SHS_Dashboard.template.html"
DATA_PATH = ROOT / "SHS_Dashboard.data.json"
CHART_PATH = ROOT / "vendor" / "chart.umd.min.js"

DATA_START = "// DATA_INJECTION_POINT_START"
DATA_END = "// DATA_INJECTION_POINT_END"
CHART_START = "<!--CHART_JS_INJECTION_POINT-->"
CHART_END = "<!--/CHART_JS_INJECTION_POINT-->"


def _replace_between(html: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """Replace content between two literal markers while retaining the markers."""
    start_idx = html.find(start_marker)
    end_idx = html.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        raise ValueError(
            f"markers {start_marker!r}/{end_marker!r} not found in expected order"
        )
    content_start = start_idx + len(start_marker)
    return html[:content_start] + "\n" + replacement + "\n" + html[end_idx:]


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

    chart_block = (
        "<script>\n/* Chart.js 4.4.1 — MIT license; see vendor/CHARTJS_LICENSE.md */\n"
        + chart_js
        + "\n</script>"
    )

    try:
        html = _replace_between(html, DATA_START, DATA_END, f"const D = {data_json};")
        html = _replace_between(html, CHART_START, CHART_END, chart_block)
    except ValueError as exc:
        print(f"ERROR: dashboard template marker problem: {exc}", file=sys.stderr)
        return 3

    HTML_PATH.write_text(html, encoding="utf-8")
    print(
        f"Built {HTML_PATH.name} with {len(data_json):,} bytes of safe data "
        f"and embedded Chart.js."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
