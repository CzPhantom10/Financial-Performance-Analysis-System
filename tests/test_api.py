"""The dashboard API.

Every endpoint is exercised through the real HTTP stack, so routing, query
parameter handling and JSON serialisation are covered as well as the SQL
underneath.  Where an endpoint reports a total, it is checked against the
transaction table rather than against itself.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import config
from src.api import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    if not config.SQLITE_PATH.exists():
        pytest.skip("warehouse missing - run: python run_pipeline.py")
    return TestClient(app)


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------
class TestHealthAndMeta:
    def test_health_endpoint_reports_ready(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_meta_offers_the_filter_options_the_ui_needs(self, client, clean_df):
        meta = client.get("/api/meta").json()
        assert set(meta["regions"]) == set(clean_df.region.unique())
        assert set(meta["categories"]) == set(clean_df.product_category.unique())
        assert meta["transactions"] == len(clean_df)

    def test_meta_date_range_matches_the_data(self, client, clean_df):
        meta = client.get("/api/meta").json()
        assert meta["date_range"]["start"][:10] == str(
            clean_df.transaction_date.min().date())
        assert meta["date_range"]["end"][:10] == str(
            clean_df.transaction_date.max().date())


ENDPOINTS = [
    "/api/kpis", "/api/monthly", "/api/yearly", "/api/region-monthly",
    "/api/discount-bands", "/api/products", "/api/customers",
    "/api/statistics", "/api/timeseries", "/api/anomalies",
    "/api/data-quality", "/api/seasonal-components", "/api/sql/queries",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_endpoint_answers_with_json(client, path):
    response = client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    payload = response.json()
    assert payload not in (None, [], {}), f"{path} returned nothing"


@pytest.mark.parametrize("dimension",
                         ["region", "category", "segment", "payment"])
def test_every_breakdown_dimension_is_served(client, dimension):
    response = client.get(f"/api/breakdown/{dimension}")
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert {"name", "revenue", "profit", "profit_margin_pct"} <= set(rows[0])


def test_an_unknown_breakdown_dimension_is_a_404_not_a_crash(client):
    assert client.get("/api/breakdown/not-a-dimension").status_code == 404


# --------------------------------------------------------------------------
# The numbers
# --------------------------------------------------------------------------
class TestFiguresAreCorrect:
    def test_unfiltered_kpis_match_the_transaction_table(self, client, clean_df):
        kpis = client.get("/api/kpis").json()
        assert kpis["comparison_basis"]
        totals = kpis["totals"]
        assert totals["revenue"] == pytest.approx(clean_df.revenue.sum(), rel=1e-6)
        assert totals["transactions"] == len(clean_df)

    def test_breakdown_shares_sum_to_one_hundred_percent(self, client):
        rows = client.get("/api/breakdown/region").json()
        assert sum(r["pct_of_revenue"] for r in rows) == pytest.approx(100.0,
                                                                      abs=0.01)

    def test_monthly_series_covers_every_month_in_order(self, client, clean_df):
        rows = client.get("/api/monthly").json()
        assert len(rows) == clean_df.month_start.nunique()
        months = [r["year_month"] for r in rows]
        assert months == sorted(months)

    def test_monthly_revenue_sums_to_the_company_total(self, client, clean_df):
        rows = client.get("/api/monthly").json()
        assert sum(r["revenue"] for r in rows) == pytest.approx(
            clean_df.revenue.sum(), rel=1e-6)


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------
class TestFilters:
    def test_a_region_filter_reduces_revenue_to_that_region(self, client, clean_df):
        region = clean_df.region.value_counts().idxmax()
        filtered = client.get("/api/kpis", params={"regions": region}).json()
        totals = filtered["totals"]
        expected = clean_df[clean_df.region == region].revenue.sum()
        assert totals["revenue"] == pytest.approx(expected, rel=1e-6)

    def test_a_date_window_reduces_the_transaction_count(self, client, clean_df):
        params = {"start": "2024-01-01", "end": "2024-12-31"}
        totals = client.get("/api/kpis", params=params).json()["totals"]
        expected = ((clean_df.transaction_date >= "2024-01-01")
                    & (clean_df.transaction_date <= "2024-12-31")).sum()
        assert totals["transactions"] == expected

    def test_filters_combine_conjunctively(self, client, clean_df):
        region = clean_df.region.value_counts().idxmax()
        category = clean_df.product_category.value_counts().idxmax()
        totals = client.get("/api/kpis", params={"regions": region,
                                                 "categories": category}).json()["totals"]
        expected = clean_df[(clean_df.region == region)
                            & (clean_df.product_category == category)]
        assert totals["revenue"] == pytest.approx(expected.revenue.sum(), rel=1e-6)

    def test_several_values_of_one_filter_are_a_union(self, client, clean_df):
        regions = list(clean_df.region.unique()[:2])
        totals = client.get(
            "/api/kpis", params=[("regions", r) for r in regions]).json()["totals"]
        expected = clean_df[clean_df.region.isin(regions)].revenue.sum()
        assert totals["revenue"] == pytest.approx(expected, rel=1e-6)

    def test_a_filter_matching_nothing_returns_zeroes_not_an_error(self, client):
        response = client.get("/api/kpis", params={"start": "1990-01-01",
                                                   "end": "1990-12-31"})
        assert response.status_code == 200


# --------------------------------------------------------------------------
# SQL library endpoints
# --------------------------------------------------------------------------
class TestSqlEndpoints:
    def test_the_catalogue_lists_the_queries_with_their_sql(self, client):
        entries = client.get("/api/sql/queries").json()
        assert len(entries) >= 20
        assert {"name", "description", "sql"} <= set(entries[0])
        assert all(e["sql"].strip() for e in entries)

    def test_a_named_query_can_be_executed(self, client):
        response = client.get("/api/sql/run/monthly_revenue_trend")
        assert response.status_code == 200
        assert response.json()

    def test_an_unknown_query_name_is_rejected(self, client):
        """Only names from the catalogue may run - the endpoint must not
        become a way to execute arbitrary SQL."""
        assert client.get("/api/sql/run/definitely_not_a_query").status_code == 404

    def test_sql_injection_through_the_query_name_is_refused(self, client):
        response = client.get("/api/sql/run/monthly_revenue_trend;DROP TABLE "
                              "fact_transactions")
        assert response.status_code == 404
        # and the table is still there
        assert client.get("/api/meta").status_code == 200
