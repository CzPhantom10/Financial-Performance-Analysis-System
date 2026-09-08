"""Cleaning pipeline: parsers, validators, and invariants on the output.

Two kinds of test live here.  The unit tests pin down the parsing helpers on
inputs chosen to be awkward.  The invariant tests assert properties that must
hold for *every* row of the delivered table - these are the ones that would
catch a silent corruption introduced months from now.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import config
from src.clean_pipeline import (CleaningLog, canonicalise, deduplicate,
                                normalise_customer_id, parse_dates,
                                parse_numeric, reconcile_and_derive, validate)


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
class TestParseNumeric:
    def test_strips_currency_and_thousands_separators(self):
        out = parse_numeric(pd.Series(["$1,200.50", "1 300", "2.5"]))
        assert out.tolist() == pytest.approx([1200.50, 1300.0, 2.5])

    def test_unparseable_becomes_nan_rather_than_raising(self):
        out = parse_numeric(pd.Series(["n/a", "", "abc"]))
        assert out.isna().all()

    def test_negative_values_survive_parsing(self):
        # They must reach validate() still negative, so it can reject them.
        out = parse_numeric(pd.Series(["-100"]))
        assert out.iloc[0] < 0


class TestParseDates:
    def test_parses_mixed_formats(self):
        out = parse_dates(pd.Series(["2024-01-15", "15/02/2024"]))
        assert out.notna().all()
        assert out.iloc[0] == pd.Timestamp("2024-01-15")

    def test_impossible_date_becomes_nat(self):
        out = parse_dates(pd.Series(["2024-13-45"]))
        assert out.isna().all()


class TestCanonicalise:
    def test_maps_aliases_to_one_spelling(self):
        aliases = {"namerica": "North America", "na": "North America"}
        out = canonicalise(pd.Series(["n. america", "NORTH AMERICA", "N/A"]),
                           aliases, ["North America", "Europe"])
        assert set(out) == {"North America"}

    def test_null_does_not_collide_with_the_north_america_alias(self):
        """str(pd.NA) normalises to 'na', which is a real alias.  A missing
        region must not be silently booked to the largest region."""
        out = canonicalise(pd.Series([None, np.nan, pd.NA]),
                           {"na": "North America"}, ["North America"])
        assert out.isna().all()


class TestNormaliseCustomerId:
    def test_one_account_written_four_ways_collapses_to_one_id(self):
        out = normalise_customer_id(
            pd.Series(["cust-001", "CUST_001", " CUST 001 ", "cust001"]))
        assert out.nunique() == 1


# --------------------------------------------------------------------------
# Validation and derivation
# --------------------------------------------------------------------------
def test_deduplicate_removes_the_repeated_transaction(raw_like):
    log = CleaningLog()
    out = deduplicate(raw_like, log)
    assert out.transaction_id.duplicated().sum() == 0
    assert len(out) < len(raw_like)


def test_validate_rejects_impossible_rows_without_dropping_good_ones():
    log = CleaningLog()
    df = pd.DataFrame({
        "transaction_id": ["OK", "NEGQTY", "HUGEQTY", "NODATE", "BIGDISC"],
        "transaction_date": pd.to_datetime(
            ["2024-01-01", "2024-01-02", "2024-01-03", None, "2024-01-05"]),
        "quantity": [5, -2, config.MAX_PLAUSIBLE_QUANTITY + 1, 3, 4],
        "unit_price": [100.0, 100.0, 100.0, 100.0, 100.0],
        "unit_cost": [60.0, 60.0, 60.0, 60.0, 60.0],
        "discount": [0.1, 0.1, 0.1, 0.1, 1.5],
        "product_id": ["PRD-01"] * 5,
    })
    kept, rejected = validate(df, log)
    assert "OK" in set(kept.transaction_id)
    assert {"NEGQTY", "HUGEQTY", "NODATE", "BIGDISC"} <= set(rejected.transaction_id)


def test_reconcile_recomputes_revenue_from_its_components():
    """The source system's revenue column is a claim to be checked, not truth:
    the recomputed figure must win, and the discrepancy must be flagged."""
    log = CleaningLog()
    df = pd.DataFrame({
        "transaction_id": ["T1"],
        "transaction_date": pd.to_datetime(["2024-01-01"]),
        "quantity": [10], "unit_price": [100.0], "unit_cost": [60.0],
        "discount": [0.20],
        "revenue": [9999.99],          # wrong on purpose
        "cost": [1.0], "profit": [9998.99],
        "region": ["North America"], "product_category": ["Hardware"],
        "customer_id": ["CUST-001"], "product_id": ["PRD-01"],
        "customer_segment": ["Enterprise"], "payment_type": ["Credit Card"],
    })
    out = reconcile_and_derive(df, log)
    row = out.iloc[0]
    assert row.revenue == pytest.approx(10 * 100.0 * 0.80)   # 800
    assert row.cost == pytest.approx(10 * 60.0)              # 600
    assert row.profit == pytest.approx(200.0)
    assert row.profit_margin_pct == pytest.approx(25.0)
    assert bool(row.had_reconciliation_error) is True


# --------------------------------------------------------------------------
# Invariants on the delivered table
# --------------------------------------------------------------------------
class TestCleanedDataInvariants:
    def test_transaction_ids_are_unique(self, clean_df):
        assert clean_df.transaction_id.duplicated().sum() == 0

    def test_no_nulls_in_analytical_key_columns(self, clean_df):
        keys = ["transaction_date", "region", "product_category", "quantity",
                "unit_price", "revenue", "cost", "profit"]
        assert clean_df[keys].isna().sum().sum() == 0

    def test_revenue_identity_holds_for_every_row(self, clean_df):
        expected = (clean_df.quantity * clean_df.unit_price
                    * (1 - clean_df.discount))
        assert np.allclose(clean_df.revenue, expected,
                           atol=config.RECONCILIATION_TOLERANCE)

    def test_profit_identity_holds_for_every_row(self, clean_df):
        assert np.allclose(clean_df.profit, clean_df.revenue - clean_df.cost,
                           atol=config.RECONCILIATION_TOLERANCE)

    def test_margin_identity_holds_for_every_row(self, clean_df):
        expected = clean_df.profit / clean_df.revenue * 100
        # the pipeline stores the margin rounded to 4 decimal places
        assert np.allclose(clean_df.profit_margin_pct, expected, atol=1e-3)

    def test_business_rule_bounds_are_respected(self, clean_df):
        assert clean_df.quantity.between(1, config.MAX_PLAUSIBLE_QUANTITY).all()
        assert clean_df.unit_price.between(0, config.MAX_PLAUSIBLE_UNIT_PRICE).all()
        assert clean_df.discount.between(0, config.MAX_PLAUSIBLE_DISCOUNT).all()

    def test_dates_fall_inside_the_declared_reporting_period(self, clean_df):
        assert clean_df.transaction_date.min() >= pd.Timestamp("2023-01-01")
        assert clean_df.transaction_date.max() <= pd.Timestamp("2025-12-31")

    def test_categoricals_are_standardised_not_free_text(self, clean_df):
        for column in ["region", "product_category", "payment_type",
                       "customer_segment"]:
            values = clean_df[column].dropna().unique()
            assert len(values) <= 12, f"{column} looks unstandardised"
            assert all(v == v.strip() for v in values)

    def test_derived_date_parts_agree_with_the_timestamp(self, clean_df):
        sample = clean_df.sample(500, random_state=0)
        assert (sample.year == sample.transaction_date.dt.year).all()
        assert (sample.month == sample.transaction_date.dt.month).all()
        assert (sample.quarter == sample.transaction_date.dt.quarter).all()

    def test_rejected_rows_were_kept_for_audit(self):
        assert config.REJECTED_TRANSACTIONS.exists()
