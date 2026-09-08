"""Central configuration: paths, database URL, and analysis constants.

Every module imports paths from here so the pipeline is reproducible from a
clean checkout and nothing hard-codes a machine-specific location.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
SQL_DIR = ROOT / "sql"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

for _d in (RAW_DIR, PROCESSED_DIR, REPORTS_DIR, FIGURES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Raw (deliberately messy) extracts
RAW_TRANSACTIONS = RAW_DIR / "transactions_raw.csv"
RAW_PRODUCTS = RAW_DIR / "products.csv"
RAW_CUSTOMERS = RAW_DIR / "customers.csv"
RAW_OPEX = RAW_DIR / "operating_expenses.csv"
RAW_MARKETING = RAW_DIR / "marketing_spend.csv"
RAW_HEADCOUNT = RAW_DIR / "employee_costs.csv"
RAW_BUDGETS = RAW_DIR / "monthly_budgets.csv"
RAW_AR = RAW_DIR / "accounts_receivable.csv"
INJECTED_EVENTS = RAW_DIR / "_injected_events.json"  # ground truth for anomalies

# Cleaned outputs
CLEAN_TRANSACTIONS = PROCESSED_DIR / "transactions_clean.csv"
REJECTED_TRANSACTIONS = PROCESSED_DIR / "transactions_rejected.csv"
CLEANING_REPORT = PROCESSED_DIR / "cleaning_report.json"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
# SQLite by default so the project runs with zero server setup. Every query in
# sql/ is written in portable ANSI SQL (CTEs + window functions), so pointing
# FINANCE_DB_URL at PostgreSQL or MySQL runs the same pipeline unchanged:
#   set FINANCE_DB_URL=postgresql+psycopg2://user:pw@localhost:5432/finance
SQLITE_PATH = DATA_DIR / "finance.db"
DB_URL = os.environ.get("FINANCE_DB_URL", f"sqlite:///{SQLITE_PATH.as_posix()}")

# --------------------------------------------------------------------------
# Analysis constants
# --------------------------------------------------------------------------
ALPHA = 0.05             # significance level for all hypothesis tests
CONFIDENCE = 0.95        # confidence level for interval estimates
Z_THRESHOLD = 3.0        # |z| beyond this flags a point anomaly
IQR_MULTIPLIER = 1.5     # Tukey fence multiplier
ROLLING_WINDOW = 3       # months, for moving averages / rolling stats
# Statistical extremity is not business materiality. A very low-variance series
# (fixed rent, say) yields huge z-scores for moves no finance team would act on,
# so an anomaly must clear BOTH the z threshold and this relative-change floor
# before it is allowed a severity above "Low".
MIN_MATERIAL_DEVIATION_PCT = 5.0
BOOTSTRAP_ITERATIONS = 10_000

FISCAL_YEAR_START_MONTH = 1  # calendar-aligned fiscal year

# Business rules used by both the cleaner and the validation tests
MAX_PLAUSIBLE_QUANTITY = 5_000
MAX_PLAUSIBLE_UNIT_PRICE = 100_000.0
MAX_PLAUSIBLE_DISCOUNT = 0.80
RECONCILIATION_TOLERANCE = 0.01  # currency units
