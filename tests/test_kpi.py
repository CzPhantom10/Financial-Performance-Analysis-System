"""KPI framework: the arithmetic, and its agreement with the source data.

A KPI that is wrong by a few percent is worse than no KPI, because nobody
notices.  These tests recompute each headline figure from the transaction rows
independently and require the published number to match.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src import config
from src.kpi import _core_metrics, compute_period_kpis, kpi_timeseries


@pytest.fixture(scope="module")
def toy() -> pd.DataFrame:
    """Four transactions with numbers chosen so every KPI is checkable by hand.

    Revenue 1000 + 2000 + 3000 + 4000 = 10,000
    Cost     600 + 1500 + 1800 + 3000 =  6,900
    Profit                              3,100  ->  31.0% margin
    AOV      10,000 / 4               =  2,500
    """
    return pd.DataFrame({
        "transaction_id": ["T1", "T2", "T3", "T4"],
        "transaction_date": pd.to_datetime(
            ["2024-01-10", "2024-02-10", "2024-03-10", "2024-04-10"]),
        "year": [2024] * 4, "quarter": [1, 1, 1, 2],
        "month": [1, 2, 3, 4],
        "year_month": ["2024-01", "2024-02", "2024-03", "2024-04"],
        "month_start": pd.to_datetime(
            ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]),
        "customer_id": ["C1", "C1", "C2", "C3"],
        "is_customer_attributed": [True] * 4,
        "region": ["North America", "Europe", "APAC", "Europe"],
        "product_category": ["Hardware"] * 4,
        "product_id": ["P1", "P2", "P3", "P4"],
        "customer_segment": ["Enterprise"] * 4,
        "payment_type": ["Credit Card"] * 4,
        "quantity": [10, 20, 30, 40],
        "unit_price": [100.0, 100.0, 100.0, 100.0],
        "unit_cost": [60.0, 75.0, 60.0, 75.0],
        "discount": [0.0, 0.0, 0.0, 0.0],
        "gross_revenue": [1000.0, 2000.0, 3000.0, 4000.0],
        "discount_amount": [0.0, 0.0, 0.0, 0.0],
        "revenue": [1000.0, 2000.0, 3000.0, 4000.0],
        "cost": [600.0, 1500.0, 1800.0, 3000.0],
        "profit": [400.0, 500.0, 1200.0, 1000.0],
        "is_loss_making": [False] * 4,
    })


class TestKpiArithmetic:
    """_core_metrics is the aggregation every published KPI is derived from."""

    def test_headline_totals_match_hand_computation(self, toy):
        k = _core_metrics(toy)
        assert k["revenue"] == pytest.approx(10_000.0)
        assert k["cost"] == pytest.approx(6_900.0)
        assert k["gross_profit"] == pytest.approx(3_100.0)

    def test_gross_margin_is_profit_over_revenue(self, toy):
        k = _core_metrics(toy)
        assert k["gross_margin_pct"] == pytest.approx(31.0, abs=0.01)

    def test_average_order_value_is_revenue_over_transactions(self, toy):
        k = _core_metrics(toy)
        assert k["avg_order_value"] == pytest.approx(2_500.0, abs=0.01)

    def test_customer_count_is_distinct_not_row_count(self, toy):
        """C1 bought twice; the customer count must be 3, not 4."""
        k = _core_metrics(toy)
        assert k["active_customers"] == 3

    def test_cost_to_revenue_and_margin_sum_to_one_hundred(self, toy):
        k = _core_metrics(toy)
        assert k["gross_margin_pct"] + k["cost_to_revenue_pct"] == pytest.approx(100.0,
                                                                                abs=0.02)


class TestPeriodKpis:
    def test_returns_named_kpi_objects_with_a_prior_comparison(self, toy):
        kpis = compute_period_kpis(toy, period="month")
        assert kpis, "expected at least one KPI"
        by_name = {k.name: k for k in kpis}
        assert "Total Revenue" in by_name or "Revenue" in by_name
        revenue = next(k for k in kpis if "Revenue" in k.name)
        # April is the latest month; March is its comparison period.
        assert revenue.value == pytest.approx(4_000.0)
        assert revenue.prior_value == pytest.approx(3_000.0)
        assert revenue.change_pct == pytest.approx(100 / 3, abs=0.01)


class TestKpiTimeseries:
    def test_one_row_per_month_present_in_the_data(self, toy):
        ts = kpi_timeseries(toy)
        assert len(ts) == 4
        assert ts.revenue.sum() == pytest.approx(10_000.0)

    def test_months_come_back_in_chronological_order(self, clean_df):
        ts = kpi_timeseries(clean_df)
        assert ts.month_start.is_monotonic_increasing


@pytest.fixture(scope="module")
def published() -> dict:
    path = config.REPORTS_DIR / "kpi_summary.json"
    if not path.exists():
        pytest.skip("run: python run_pipeline.py --stage kpi")
    return json.loads(path.read_text())


class TestPublishedKpiSummary:
    """The committed kpi_summary.json must still agree with the clean data."""

    def test_revenue_matches_the_transaction_table(self, published, clean_df):
        assert published["all_time"]["revenue"] == pytest.approx(
            clean_df.revenue.sum(), rel=1e-6)

    def test_gross_profit_matches_the_transaction_table(self, published, clean_df):
        assert published["all_time"]["gross_profit"] == pytest.approx(
            clean_df.profit.sum(), rel=1e-6)

    def test_transaction_count_matches(self, published, clean_df):
        assert published["all_time"]["transactions"] == len(clean_df)

    def test_margin_is_internally_consistent(self, published):
        a = published["all_time"]
        assert a["gross_margin_pct"] == pytest.approx(
            a["gross_profit"] / a["revenue"] * 100, abs=0.01)

    def test_declared_period_matches_the_data(self, published, clean_df):
        assert published["period_covered"]["start"] == str(
            clean_df.transaction_date.min().date())
        assert published["period_covered"]["end"] == str(
            clean_df.transaction_date.max().date())
