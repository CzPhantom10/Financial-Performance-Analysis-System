"""Time-series layer: aggregation, moving averages, trend and seasonality.

The trend and seasonality routines are given series whose answer is known by
construction - a fixed growth rate, a planted December peak - so a wrong answer
is unambiguous rather than a matter of opinion.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import config
from src.timeseries import (build_monthly, growth_decomposition,
                            quarterly_analysis, seasonal_analysis,
                            trend_analysis, worst_and_best_months)


def _transactions_from_monthly(revenue_by_month: list[float],
                               start: str = "2021-01-01") -> pd.DataFrame:
    """One transaction per month, carrying that month's whole revenue.

    Aggregation is not what is under test here, so one row per month keeps the
    expected monthly series exactly equal to the input.
    """
    dates = pd.date_range(start, periods=len(revenue_by_month), freq="MS")
    return pd.DataFrame({
        "transaction_id": [f"T{i}" for i in range(len(dates))],
        "transaction_date": dates,
        "month_start": dates,
        "customer_id": [f"C{i}" for i in range(len(dates))],
        "quantity": [1] * len(dates),
        "revenue": revenue_by_month,
        "gross_revenue": revenue_by_month,
        "discount_amount": [0.0] * len(dates),
        "cost": [r * 0.6 for r in revenue_by_month],
        "profit": [r * 0.4 for r in revenue_by_month],
    })


@pytest.fixture(scope="module")
def flat_monthly() -> pd.DataFrame:
    """36 months of perfectly flat revenue - the null case."""
    return build_monthly(_transactions_from_monthly([100_000.0] * 36))


@pytest.fixture(scope="module")
def growing_monthly() -> pd.DataFrame:
    """36 months compounding at exactly 1% a month."""
    revenue = [100_000.0 * (1.01 ** i) for i in range(36)]
    return build_monthly(_transactions_from_monthly(revenue))


class TestBuildMonthly:
    def test_one_row_per_month_in_chronological_order(self, clean_df):
        monthly = build_monthly(clean_df)
        assert monthly.month_start.is_monotonic_increasing
        assert monthly.month_start.duplicated().sum() == 0
        assert len(monthly) == clean_df.month_start.nunique()

    def test_monthly_revenue_sums_back_to_the_transaction_total(self, clean_df):
        monthly = build_monthly(clean_df)
        assert monthly.revenue.sum() == pytest.approx(clean_df.revenue.sum(), rel=1e-9)

    def test_derived_ratios_agree_with_their_components(self, clean_df):
        monthly = build_monthly(clean_df)
        assert np.allclose(monthly.profit_margin_pct,
                           monthly.profit / monthly.revenue * 100)
        assert np.allclose(monthly.avg_order_value,
                           monthly.revenue / monthly.transactions)

    def test_three_month_moving_average_is_the_mean_of_three_months(self):
        monthly = build_monthly(_transactions_from_monthly(
            [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]))
        assert pd.isna(monthly.revenue_ma3.iloc[0])   # not enough history yet
        assert pd.isna(monthly.revenue_ma3.iloc[1])
        assert monthly.revenue_ma3.iloc[2] == pytest.approx(200.0)   # (100+200+300)/3
        assert monthly.revenue_ma3.iloc[5] == pytest.approx(500.0)   # (400+500+600)/3

    def test_month_on_month_growth_matches_the_ratio(self):
        monthly = build_monthly(_transactions_from_monthly([100.0, 150.0, 300.0]))
        assert monthly.revenue_mom_pct.iloc[1] == pytest.approx(50.0)
        assert monthly.revenue_mom_pct.iloc[2] == pytest.approx(100.0)

    def test_cumulative_revenue_ends_at_the_grand_total(self, clean_df):
        monthly = build_monthly(clean_df)
        assert monthly.cumulative_revenue.iloc[-1] == pytest.approx(
            clean_df.revenue.sum(), rel=1e-9)


class TestTrend:
    def test_recovers_a_known_compound_growth_rate(self, growing_monthly):
        """The fit is on log(revenue), so a 1%/month series must come back as
        1%/month - roughly 12.7% annualised."""
        trend = trend_analysis(growing_monthly)
        assert trend["monthly_growth_rate_pct"] == pytest.approx(1.0, abs=0.05)
        assert trend["r_squared"] == pytest.approx(1.0, abs=1e-6)

    def test_flat_revenue_produces_no_growth(self, flat_monthly):
        trend = trend_analysis(flat_monthly)
        assert trend["monthly_growth_rate_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_direction_is_reported_for_a_declining_series(self):
        declining = build_monthly(_transactions_from_monthly(
            [100_000.0 * (0.98 ** i) for i in range(36)]))
        assert trend_analysis(declining)["monthly_growth_rate_pct"] < 0


class TestSeasonality:
    def test_finds_the_month_the_peak_was_planted_in(self):
        """Three years of flat revenue with every December doubled: the
        seasonal index must single December out."""
        revenue = []
        for _ in range(3):
            revenue += [100_000.0] * 11 + [200_000.0]
        monthly = build_monthly(_transactions_from_monthly(revenue))
        summary, _ = seasonal_analysis(monthly)
        assert summary["peak_month"] == "December"
        assert summary["peak_index"] > 1.0

    def test_index_averages_to_one_across_the_year(self, clean_df):
        """A seasonal index is a ratio to the average month, so the twelve
        values must average to 1 - otherwise it is carrying trend as well."""
        summary, _ = seasonal_analysis(build_monthly(clean_df))
        indices = [row["seasonal_index"] for row in summary["seasonal_index"]]
        assert len(indices) == 12
        assert np.mean(indices) == pytest.approx(1.0, abs=0.01)

    def test_stl_components_multiply_back_to_the_observed_series(self, clean_df):
        """The decomposition is multiplicative, so trend x seasonal x residual
        must return the observed value for every month."""
        _, components = seasonal_analysis(build_monthly(clean_df))
        rebuilt = (components.stl_trend * components.stl_seasonal
                   * components.stl_residual)
        assert np.allclose(rebuilt, components.observed, rtol=1e-6)

    def test_classical_components_multiply_back_where_the_trend_exists(self, clean_df):
        """The classical trend is a centred 12-month average, so it is
        undefined for the first and last six months - those are expected NaN,
        and everywhere else the identity must hold."""
        _, components = seasonal_analysis(build_monthly(clean_df))
        defined = components.dropna(subset=["trend", "residual"])
        assert len(defined) > 0
        rebuilt = defined.trend * defined.seasonal * defined.residual
        assert np.allclose(rebuilt, defined.observed, rtol=1e-6)


class TestQuarterlyAndExtremes:
    def test_every_quarter_in_the_data_is_reported(self, clean_df):
        quarters = quarterly_analysis(clean_df)
        assert len(quarters) == clean_df.year_quarter.nunique()

    def test_worst_month_really_is_the_largest_decline(self, clean_df):
        monthly = build_monthly(clean_df)
        result = worst_and_best_months(monthly)
        worst = result["largest_declines_mom"][0]
        assert worst["mom_change_pct"] == pytest.approx(
            monthly.revenue_mom_pct.min(), abs=0.01)

    def test_growth_decomposition_splits_a_real_change(self, clean_df):
        decomposition = growth_decomposition(build_monthly(clean_df))
        assert decomposition


class TestPublishedTimeseries:
    def test_saved_analysis_matches_a_fresh_computation(self, clean_df):
        path = config.REPORTS_DIR / "timeseries_analysis.json"
        if not path.exists():
            pytest.skip("run: python run_pipeline.py --stage timeseries")
        published = json.loads(path.read_text())
        fresh = trend_analysis(build_monthly(clean_df))
        assert published["trend"]["monthly_growth_rate_pct"] == pytest.approx(
            fresh["monthly_growth_rate_pct"], abs=0.01)
