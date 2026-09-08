"""Build the analytical database from the cleaned files.

Creates the star schema, bulk-loads the fact and dimension tables, then adds
indexes and views.  Uses SQLAlchemy throughout, so the same code targets
SQLite (the zero-setup default) or PostgreSQL/MySQL via ``FINANCE_DB_URL``.

Run with:  python -m src.db_load
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src import config

FACT_COLUMNS = [
    "transaction_id", "transaction_date", "year", "quarter", "year_quarter",
    "month", "year_month", "month_start", "day_of_week", "is_weekend",
    "customer_id", "is_customer_attributed", "customer_segment", "region",
    "product_id", "product_category", "payment_type", "quantity", "unit_price",
    "unit_cost", "discount", "gross_revenue", "discount_amount", "revenue",
    "cost", "profit", "profit_margin_pct", "unit_margin",
    "cost_to_revenue_ratio", "is_loss_making", "had_reconciliation_error",
]


def get_engine() -> Engine:
    return create_engine(config.DB_URL, future=True)


def execute_script(engine: Engine, sql_path) -> None:
    """Run a multi-statement .sql file.

    DBAPI drivers only accept one statement per execute(), so the file is split
    on semicolons. Comment-only fragments are skipped.
    """
    script = sql_path.read_text()
    statements = [s.strip() for s in script.split(";")]
    with engine.begin() as conn:
        for stmt in statements:
            body = "\n".join(line for line in stmt.splitlines()
                             if not line.strip().startswith("--")).strip()
            if body:
                conn.execute(text(stmt))


def to_date_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Store DATE columns as 'YYYY-MM-DD' rather than full timestamps.

    SQLite has no native date type and would otherwise persist
    '2024-10-01 00:00:00.000000', which is noisy to read and breaks plain
    string comparison against a literal like '2024-10-01'.  PostgreSQL and
    MySQL parse the short form into a real DATE, so this keeps one load path
    correct on every engine.
    """
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d")
    return df


def enrich_receivables(ar: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Materialise the day counts and status labels the AR queries need.

    ``as_of`` is the reporting date - the last day covered by the ledger.
    Anything still unpaid on that date is an open item, and its age is measured
    from the invoice date rather than left undefined.
    """
    ar = ar.copy()
    paid = ar["paid_date"].notna()

    ar["days_to_pay"] = (ar["paid_date"] - ar["invoice_date"]).dt.days
    ar["is_open"] = (~paid).astype(int)

    days_late = (ar["paid_date"] - ar["due_date"]).dt.days
    days_open = (as_of - ar["due_date"]).dt.days
    ar["days_overdue"] = days_late.where(paid, days_open).clip(lower=0)

    ar["payment_status"] = np.select(
        [paid & (days_late <= 0), paid & (days_late > 0), ~paid & (days_open > 0)],
        ["Paid on time", "Paid late", "Open - overdue"],
        default="Open - current")

    age = (as_of - ar["invoice_date"]).dt.days
    ar["aging_bucket"] = np.select(
        [~paid & (age <= 30), ~paid & (age <= 60), ~paid & (age <= 90), ~paid],
        ["0-30 days", "31-60 days", "61-90 days", "90+ days"],
        default="Settled")
    return ar


def build_date_dimension(txns: pd.DataFrame) -> pd.DataFrame:
    days = pd.date_range(txns["transaction_date"].min(),
                         txns["transaction_date"].max(), freq="D")
    d = pd.DataFrame({"date_key": days})
    d["year"] = d.date_key.dt.year
    d["quarter"] = d.date_key.dt.quarter
    d["year_quarter"] = d.year.astype(str) + "-Q" + d.quarter.astype(str)
    d["month"] = d.date_key.dt.month
    d["year_month"] = d.date_key.dt.strftime("%Y-%m")
    d["month_start"] = d.date_key.dt.to_period("M").dt.to_timestamp()
    d["month_name"] = d.date_key.dt.strftime("%B")
    d["day_of_week"] = d.date_key.dt.day_name()
    d["is_weekend"] = (d.date_key.dt.weekday >= 5).astype(int)
    return d


def load(verbose: bool = True) -> Engine:
    engine = get_engine()

    if verbose:
        print(f"Target database: {config.DB_URL}")
        print("Creating schema ...")
    execute_script(engine, config.SQL_DIR / "schema.sql")

    txns = pd.read_csv(config.CLEAN_TRANSACTIONS,
                       parse_dates=["transaction_date", "month_start"])
    for col in ["is_weekend", "is_customer_attributed", "is_loss_making",
                "had_reconciliation_error"]:
        txns[col] = txns[col].astype(int)

    customers = pd.read_csv(config.RAW_CUSTOMERS, keep_default_na=False,
                            na_values=[""])
    products = pd.read_csv(config.RAW_PRODUCTS)
    opex = pd.read_csv(config.RAW_OPEX, parse_dates=["month"])
    marketing = pd.read_csv(config.RAW_MARKETING, parse_dates=["month"])
    payroll = pd.read_csv(config.RAW_HEADCOUNT, parse_dates=["month"])
    budget = pd.read_csv(config.RAW_BUDGETS, parse_dates=["month"])
    ar = pd.read_csv(config.RAW_AR, keep_default_na=False, na_values=[""],
                     parse_dates=["invoice_date", "due_date", "paid_date"])

    ar = enrich_receivables(ar, as_of=txns["transaction_date"].max())

    # An unattributed transaction has no row in dim_customer; add a sentinel so
    # the foreign key still resolves and revenue totals stay complete.
    if (txns.customer_id == "UNATTRIBUTED").any():
        customers = pd.concat([customers, pd.DataFrame([{
            "customer_id": "UNATTRIBUTED", "customer_segment": "Unknown",
            "region": "Unknown", "signup_date": None, "churn_date": None}])],
            ignore_index=True)

    tables = {
        "dim_date": build_date_dimension(txns),
        "dim_customer": customers,
        "dim_product": products,
        "fact_transactions": txns[FACT_COLUMNS],
        "fact_operating_expenses": opex,
        "fact_marketing_spend": marketing,
        "fact_employee_costs": payroll,
        "fact_budget": budget,
        "fact_accounts_receivable": ar,
    }

    if verbose:
        print("Loading tables ...")
    for name, frame in tables.items():
        # Default executemany, not method="multi": a multi-row VALUES clause
        # would bind chunksize x n_columns parameters in one statement and
        # blow past SQLite's SQLITE_MAX_VARIABLE_NUMBER limit.
        to_date_strings(frame).to_sql(name, engine, if_exists="append",
                                      index=False, chunksize=5_000)
        if verbose:
            print(f"  {name:<28} {len(frame):>8,} rows")

    if verbose:
        print("Creating indexes and views ...")
    execute_script(engine, config.SQL_DIR / "indexes_and_views.sql")

    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM fact_transactions")).scalar()
        rev = conn.execute(text("SELECT SUM(revenue) FROM fact_transactions")).scalar()
    if verbose:
        print(f"\nDatabase ready: {n:,} transactions, {rev:,.0f} total revenue")
    return engine


def query(sql: str, engine: Engine | None = None, **params) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame - the workhorse for notebooks."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or None)


if __name__ == "__main__":
    load()
