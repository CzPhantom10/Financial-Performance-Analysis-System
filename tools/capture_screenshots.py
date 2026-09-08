"""Capture dashboard screenshots for the README.

The dashboard is a React app whose charts animate on mount, so a naive headless
screenshot catches half-drawn bars.  This waits for the network to go quiet and
then for the chart SVGs to stop changing, which is what "the page has finished
rendering" actually means here.

    python -m src.api                      # in one terminal
    python tools/capture_screenshots.py    # in another

Requires Playwright, which is a tool for producing the screenshots rather than a
dependency of the project itself:

    pip install playwright && playwright install chromium
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "screenshots"
BASE_URL = "http://127.0.0.1:8000"
VIEWPORT = {"width": 1600, "height": 1000}

PAGES = [
    ("01_executive_overview", "/", "Executive overview"),
    ("02_revenue_analysis", "/revenue", "Revenue analysis"),
    ("03_profitability", "/profitability", "Profitability analysis"),
    ("04_customers", "/customers", "Customer analysis"),
    ("05_products", "/products", "Product analysis"),
    ("06_anomaly_monitor", "/anomalies", "Anomaly monitor"),
    ("07_statistical_analysis", "/statistics", "Statistical analysis"),
    ("08_sql_library", "/sql", "SQL library and data quality"),
]


def wait_until_charts_settle(page, timeout_s: float = 15.0) -> None:
    """Poll the rendered SVG until two consecutive reads are byte-identical.

    Recharts animates on mount, and line series animate by sweeping
    stroke-dashoffset rather than by adding geometry - so the markup has to be
    compared in full.  Comparing its *length* looks settled immediately while
    the line is still drawing itself across the chart.
    """
    page.wait_for_timeout(1_800)          # recharts' own animation runs ~1.5s
    deadline = time.time() + timeout_s
    previous = None
    while time.time() < deadline:
        current = page.evaluate(
            "() => Array.from(document.querySelectorAll('svg'))"
            ".map(s => s.innerHTML).join('|')")
        if current and current == previous:
            return
        previous = current
        page.wait_for_timeout(500)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        # Pin the colour scheme so re-runs produce comparable images
        # rather than following whatever the host machine prefers.
        context = browser.new_context(viewport=VIEWPORT,
                                      device_scale_factor=2,
                                      color_scheme="light")
        page = context.new_page()

        try:
            page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)
        except Exception:
            print(f"Could not reach {BASE_URL}.  Start the dashboard first:\n"
                  f"    python -m src.api", file=sys.stderr)
            return 1

        for name, path, title in PAGES:
            page.goto(f"{BASE_URL}{path}", wait_until="networkidle",
                      timeout=30_000)
            wait_until_charts_settle(page)
            target = OUT_DIR / f"{name}.png"
            page.screenshot(path=str(target), full_page=True)
            size_kb = target.stat().st_size / 1024
            print(f"  {title:<30} -> {target.name} ({size_kb:,.0f} KB)")

        browser.close()

    print(f"\nWrote {len(PAGES)} screenshots to "
          f"{OUT_DIR.relative_to(ROOT).as_posix()}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
