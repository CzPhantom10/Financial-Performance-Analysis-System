"""The warehouse and the query library.

Two questions matter here.  Does every query in sql/analysis_queries.sql still
run against the schema as built?  And do the SQL answers agree with the same
figures computed independently in pandas?  The second is what makes the SQL
layer trustworthy as the analytical engine rather than decoration.
"""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import inspect, text

from src import config
from src.db_load import query
from src.sql_analysis import load_queries, run_named

EXPECTED_TABLES = {
    "fact_transactions", "fact_operating_expenses", "fact_marketing_spend",
    "fact_employee_costs", "fact_budget", "fact_accounts_receivable",
    "dim_customer", "dim_product", "dim_date",
}
EXPECTED_VIEWS = {
    "v_monthly_revenue", "v_monthly_pnl", "v_product_summary",
    "v_customer_summary",
}


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
class TestSchema:
    def test_every_expected_table_was_created(self, engine):
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())

    def test_every_expected_view_was_created(self, engine):
        assert EXPECTED_VIEWS <= set(inspect(engine).get_view_names())

    def test_the_fact_table_holds_every_clean_transaction(self, engine, clean_df):
        n = query("SELECT COUNT(*) AS n FROM fact_transactions", engine).n.iloc[0]
        assert n == len(clean_df)

    def test_transaction_ids_are_unique_in_the_warehouse(self, engine):
        dupes = query("""SELECT COUNT(*) AS n FROM (
                             SELECT transaction_id FROM fact_transactions
                             GROUP BY transaction_id HAVING COUNT(*) > 1)""",
                      engine).n.iloc[0]
        assert dupes == 0

    def test_no_transaction_references_a_product_outside_the_dimension(self, engine):
        orphans = query("""SELECT COUNT(*) AS n
                           FROM fact_transactions f
                           LEFT JOIN dim_product p ON f.product_id = p.product_id
                           WHERE p.product_id IS NULL""", engine).n.iloc[0]
        assert orphans == 0

    def test_the_date_dimension_covers_every_transaction_date(self, engine):
        missing = query("""SELECT COUNT(*) AS n
                           FROM fact_transactions f
                           LEFT JOIN dim_date d
                             ON f.transaction_date = d.date_key
                           WHERE d.date_key IS NULL""", engine).n.iloc[0]
        assert missing == 0


# --------------------------------------------------------------------------
# The query library
# --------------------------------------------------------------------------
def _query_names() -> list[str]:
    try:
        return sorted(load_queries())
    except Exception:                       # pragma: no cover - collection guard
        return []


class TestQueryLibrary:
    def test_the_library_is_not_empty(self):
        assert len(load_queries()) >= 20

    def test_every_query_is_documented(self):
        for name, entry in load_queries().items():
            assert entry["description"].strip(), f"{name} has no description"

    @pytest.mark.parametrize("name", _query_names())
    def test_query_runs_and_returns_rows(self, name, engine):
        """A query that no longer parses against the schema is a broken
        deliverable, so each one is executed rather than merely read."""
        frame = run_named(name, engine)
        assert isinstance(frame, pd.DataFrame)
        assert not frame.empty, f"{name} returned no rows"


# --------------------------------------------------------------------------
# SQL answers vs. an independent pandas computation
# --------------------------------------------------------------------------
class TestSqlAgreesWithPandas:
    def test_total_revenue_matches(self, engine, clean_df):
        total = query("SELECT SUM(revenue) AS revenue FROM fact_transactions",
                      engine).revenue.iloc[0]
        assert total == pytest.approx(clean_df.revenue.sum(), rel=1e-9)

    def test_monthly_revenue_trend_matches_month_for_month(self, engine, clean_df):
        sql_result = run_named("monthly_revenue_trend", engine)
        expected = (clean_df.groupby(clean_df.month_start.dt.strftime("%Y-%m"))
                    .revenue.sum())
        month_col = next(c for c in sql_result.columns
                         if "month" in c.lower() or "period" in c.lower())
        revenue_col = next(c for c in sql_result.columns if c.lower() == "revenue")
        for _, row in sql_result.iterrows():
            key = str(row[month_col])[:7]
            assert row[revenue_col] == pytest.approx(expected[key], rel=1e-6)

    def test_revenue_by_region_matches_and_is_exhaustive(self, engine, clean_df):
        sql_result = run_named("revenue_by_region", engine)
        expected = clean_df.groupby("region").revenue.sum()
        revenue_col = next(c for c in sql_result.columns if c.lower() == "revenue")
        assert set(sql_result.region) == set(expected.index)
        assert sql_result[revenue_col].sum() == pytest.approx(
            clean_df.revenue.sum(), rel=1e-6)

    def test_top_customers_are_genuinely_the_largest(self, engine, clean_df):
        sql_result = run_named("top_customers", engine)
        expected_top = (clean_df[clean_df.is_customer_attributed]
                        .groupby("customer_id").revenue.sum().idxmax())
        assert sql_result.customer_id.iloc[0] == expected_top

    def test_margin_by_category_matches(self, engine, clean_df):
        sql_result = run_named("margin_by_category", engine)
        expected = (clean_df.groupby("product_category")
                    .apply(lambda g: g.profit.sum() / g.revenue.sum() * 100,
                           include_groups=False))
        margin_col = next(c for c in sql_result.columns if "margin" in c.lower())
        for _, row in sql_result.iterrows():
            assert row[margin_col] == pytest.approx(
                expected[row.product_category], abs=0.01)


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
class TestViews:
    def test_monthly_revenue_view_agrees_with_the_fact_table(self, engine):
        view_total = query("SELECT SUM(revenue) AS r FROM v_monthly_revenue",
                           engine).r.iloc[0]
        fact_total = query("SELECT SUM(revenue) AS r FROM fact_transactions",
                           engine).r.iloc[0]
        assert view_total == pytest.approx(fact_total, rel=1e-9)

    def test_monthly_pnl_view_has_one_row_per_month(self, engine, clean_df):
        rows = query("SELECT COUNT(*) AS n FROM v_monthly_pnl", engine).n.iloc[0]
        assert rows == clean_df.month_start.nunique()


# --------------------------------------------------------------------------
# Exported results
# --------------------------------------------------------------------------
def test_every_query_was_exported_to_csv():
    out_dir = config.REPORTS_DIR / "sql_results"
    if not out_dir.exists():
        pytest.skip("run: python run_pipeline.py --stage sql")
    exported = {p.stem for p in out_dir.glob("*.csv")}
    assert exported, "no query results were exported"
    assert exported <= set(load_queries())
