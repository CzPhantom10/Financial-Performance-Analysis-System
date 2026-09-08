"""Shared fixtures.

The expensive artefacts - the cleaned transaction table and the warehouse
connection - are built once per session and shared, because every test that
needs them needs the *same* ones.  Anything a test might mutate is handed over
as a copy.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import config


@pytest.fixture(scope="session")
def clean_df() -> pd.DataFrame:
    """The cleaned transaction table produced by the pipeline."""
    if not config.CLEAN_TRANSACTIONS.exists():
        pytest.skip("cleaned data missing - run: python run_pipeline.py")
    from src.clean_pipeline import load_clean
    return load_clean()


@pytest.fixture(scope="session")
def engine():
    """A connection to the SQLite warehouse."""
    if not config.SQLITE_PATH.exists():
        pytest.skip("warehouse missing - run: python run_pipeline.py --stage database")
    from src.db_load import get_engine
    return get_engine()


@pytest.fixture
def raw_like() -> pd.DataFrame:
    """A tiny, deliberately messy frame in the shape of the raw extract.

    Hand-written rather than sampled, so each row exercises one specific defect
    the cleaner is supposed to find.
    """
    return pd.DataFrame({
        "transaction_id": ["TXN-1", "TXN-2", "TXN-2", "TXN-3", "TXN-4"],
        "transaction_date": ["2024-01-15", "15/02/2024", "15/02/2024",
                             "2024-13-45", "2024-03-01"],
        "customer_id": ["cust-001", "CUST_002", "CUST_002", " cust003 ", "CUST-004"],
        "product_id": ["PRD-01", "PRD-02", "PRD-02", "PRD-03", "PRD-04"],
        "product_category": ["hardware", "Cloud services", "Cloud services",
                             "HARDWARE", "networking"],
        "region": ["n. america", "EMEA", "EMEA", "apac", None],
        "quantity": ["5", "3", "3", "-2", "4"],
        "unit_price": ["100.00", "1,200.50", "1,200.50", "50", "0"],
        "unit_cost": ["60", "800", "800", "30", "10"],
        "discount": ["0.10", "0.05", "0.05", "0.0", "0.95"],
        "payment_type": ["credit card", "Wire Transfer", "Wire Transfer",
                         "CREDIT CARD", "ach"],
        "revenue": ["450.00", "3421.43", "3421.43", "-100", "0"],
    })
