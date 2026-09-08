"""FastAPI backend for the analytics dashboard.

Serves two things from one process:

* ``/api/*`` - JSON endpoints, every one of which answers by running SQL
  against the warehouse rather than by filtering a DataFrame in Python.  The
  aggregation happens in the database, so the browser receives tens of rows
  instead of tens of thousands, and the SQL layer stays the analytical engine
  of the project rather than a box that got ticked once during loading.
* ``/`` - the built React frontend from ``frontend/dist``, when it exists.

That second part is deliberate: a machine with only Python installed can run
``python -m src.api`` and get the complete dashboard.  Node is needed only to
*rebuild* the interface, not to use it.

Run with:  python -m src.api           (http://127.0.0.1:8000)
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from src import config
from src.db_load import get_engine

FRONTEND_DIST = config.ROOT / "frontend" / "dist"

app = FastAPI(title="Financial Performance Analytics API", version="1.0.0")

# The Vite dev server runs on a different port, so development needs CORS.
# The built app is same-origin and does not.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def q(sql: str, params: dict | None = None) -> list[dict]:
    """Run a SELECT and return JSON-ready records."""
    with engine().connect() as conn:
        frame = pd.read_sql_query(text(sql), conn, params=params or {})
    return json.loads(frame.to_json(orient="records", date_format="iso"))


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------
def build_filter(start: str | None, end: str | None, regions: list[str] | None,
                 categories: list[str] | None, segments: list[str] | None,
                 alias: str = "") -> tuple[str, dict]:
    """Compose a parameterised WHERE clause from the dashboard filters.

    Values are always bound as parameters, never interpolated - the filter
    values arrive from the query string, and string-formatting them into SQL
    would be an injection hole even in a local tool.
    """
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if start:
        clauses.append(f"{prefix}transaction_date >= :start")
        params["start"] = start
    if end:
        clauses.append(f"{prefix}transaction_date <= :end")
        params["end"] = end

    for name, values in (("region", regions), ("product_category", categories),
                         ("customer_segment", segments)):
        if values:
            keys = []
            for i, value in enumerate(values):
                key = f"{name}_{i}"
                params[key] = value
                keys.append(f":{key}")
            clauses.append(f"{prefix}{name} IN ({', '.join(keys)})")

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def filter_params(
    start: str | None = Query(None), end: str | None = Query(None),
    regions: list[str] | None = Query(None),
    categories: list[str] | None = Query(None),
    segments: list[str] | None = Query(None),
) -> tuple[str, dict]:
    return build_filter(start, end, regions, categories, segments)


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------
@app.get("/api/meta")
def meta() -> dict:
    """Filter options and dataset extent - the first call the frontend makes."""
    bounds = q("""SELECT MIN(transaction_date) AS min_date,
                         MAX(transaction_date) AS max_date,
                         COUNT(*) AS transactions
                  FROM fact_transactions""")[0]
    return {
        "date_range": {"start": bounds["min_date"], "end": bounds["max_date"]},
        "transactions": bounds["transactions"],
        "regions": [r["region"] for r in q(
            "SELECT DISTINCT region FROM fact_transactions ORDER BY region")],
        "categories": [r["product_category"] for r in q(
            "SELECT DISTINCT product_category FROM fact_transactions "
            "ORDER BY product_category")],
        "segments": [r["customer_segment"] for r in q(
            "SELECT DISTINCT customer_segment FROM fact_transactions "
            "ORDER BY customer_segment")],
    }


# --------------------------------------------------------------------------
# Headline KPIs
# --------------------------------------------------------------------------
@app.get("/api/kpis")
def kpis(start: str | None = None, end: str | None = None,
         regions: list[str] | None = Query(None),
         categories: list[str] | None = Query(None),
         segments: list[str] | None = Query(None)) -> dict:
    """Totals for the selection, plus a trailing-twelve-month comparison.

    TTM against the preceding twelve months rather than calendar year-to-date:
    both windows then contain exactly one of every calendar month, so the
    comparison is immune to the seasonality that dominates this business.
    """
    where, params = build_filter(start, end, regions, categories, segments)

    totals = q(f"""
        SELECT COUNT(*)                     AS transactions,
               COUNT(DISTINCT customer_id)  AS customers,
               SUM(quantity)                AS units,
               SUM(revenue)                 AS revenue,
               SUM(gross_revenue)           AS gross_revenue,
               SUM(discount_amount)         AS discount_amount,
               SUM(cost)                    AS cost,
               SUM(profit)                  AS profit,
               SUM(is_loss_making)          AS loss_making
        FROM fact_transactions WHERE {where}""", params)[0]

    months = q(f"""SELECT DISTINCT year_month FROM fact_transactions
                   WHERE {where} ORDER BY year_month""", params)
    labels = [m["year_month"] for m in months]

    def window_totals(window: list[str]) -> dict:
        if not window:
            return {}
        keys = {f"m{i}": m for i, m in enumerate(window)}
        placeholders = ", ".join(f":{k}" for k in keys)
        return q(f"""
            SELECT COUNT(*) AS transactions,
                   COUNT(DISTINCT customer_id) AS customers,
                   SUM(revenue) AS revenue, SUM(cost) AS cost,
                   SUM(profit) AS profit
            FROM fact_transactions
            WHERE {where} AND year_month IN ({placeholders})""",
                 {**params, **keys})[0]

    current = window_totals(labels[-12:]) if len(labels) >= 13 else {}
    prior = window_totals(labels[-24:-12]) if len(labels) >= 24 else {}

    revenue = totals["revenue"] or 0
    gross = totals["gross_revenue"] or 0
    return {
        "totals": {
            **totals,
            "gross_margin_pct": (totals["profit"] / revenue * 100) if revenue else None,
            "cost_to_revenue_pct": (totals["cost"] / revenue * 100) if revenue else None,
            "discount_rate_pct": (totals["discount_amount"] / gross * 100) if gross else None,
            "avg_order_value": (revenue / totals["transactions"])
                               if totals["transactions"] else None,
            "revenue_per_customer": (revenue / totals["customers"])
                                    if totals["customers"] else None,
            "loss_making_pct": (totals["loss_making"] / totals["transactions"] * 100)
                               if totals["transactions"] else None,
        },
        "ttm": current,
        "prior_ttm": prior,
        "comparison_basis": (
            "Trailing twelve months against the preceding twelve months."
            if prior else
            "Not enough history in the current selection for a "
            "trailing-twelve-month comparison."),
    }


# --------------------------------------------------------------------------
# Time series
# --------------------------------------------------------------------------
@app.get("/api/monthly")
def monthly(start: str | None = None, end: str | None = None,
            regions: list[str] | None = Query(None),
            categories: list[str] | None = Query(None),
            segments: list[str] | None = Query(None)) -> list[dict]:
    """Monthly spine with moving average and growth, computed in SQL."""
    where, params = build_filter(start, end, regions, categories, segments)
    return q(f"""
        WITH m AS (
            SELECT month_start, year_month, year,
                   SUM(revenue) AS revenue, SUM(cost) AS cost,
                   SUM(profit) AS profit, SUM(gross_revenue) AS gross_revenue,
                   SUM(discount_amount) AS discount_amount,
                   COUNT(*) AS transactions, SUM(quantity) AS units,
                   COUNT(DISTINCT customer_id) AS customers
            FROM fact_transactions
            WHERE {where}
            GROUP BY month_start, year_month, year
        )
        SELECT
            month_start, year_month, year, revenue, cost, profit,
            transactions, units, customers,
            profit * 100.0 / NULLIF(revenue, 0)                  AS profit_margin_pct,
            cost * 100.0 / NULLIF(revenue, 0)                    AS cost_to_revenue_pct,
            discount_amount * 100.0 / NULLIF(gross_revenue, 0)   AS discount_rate_pct,
            revenue * 1.0 / NULLIF(transactions, 0)              AS avg_order_value,
            AVG(revenue) OVER (ORDER BY month_start
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)        AS revenue_ma3,
            (revenue - LAG(revenue) OVER w) * 100.0
                / NULLIF(LAG(revenue) OVER w, 0)                 AS revenue_mom_pct,
            (revenue - LAG(revenue, 12) OVER w) * 100.0
                / NULLIF(LAG(revenue, 12) OVER w, 0)             AS revenue_yoy_pct,
            SUM(revenue) OVER (ORDER BY month_start
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_revenue
        FROM m
        WINDOW w AS (ORDER BY month_start)
        ORDER BY month_start""", params)


@app.get("/api/yearly")
def yearly(start: str | None = None, end: str | None = None,
           regions: list[str] | None = Query(None),
           categories: list[str] | None = Query(None),
           segments: list[str] | None = Query(None)) -> list[dict]:
    where, params = build_filter(start, end, regions, categories, segments)
    return q(f"""
        WITH y AS (
            SELECT year, SUM(revenue) AS revenue, SUM(cost) AS cost,
                   SUM(profit) AS profit, COUNT(*) AS transactions,
                   COUNT(DISTINCT customer_id) AS customers
            FROM fact_transactions WHERE {where} GROUP BY year
        )
        SELECT year, revenue, cost, profit, transactions, customers,
               profit * 100.0 / NULLIF(revenue, 0) AS gross_margin_pct,
               revenue * 1.0 / NULLIF(transactions, 0) AS avg_order_value,
               (revenue - LAG(revenue) OVER w) * 100.0
                   / NULLIF(LAG(revenue) OVER w, 0) AS revenue_growth_pct,
               (cost - LAG(cost) OVER w) * 100.0
                   / NULLIF(LAG(cost) OVER w, 0)    AS cost_growth_pct,
               (profit - LAG(profit) OVER w) * 100.0
                   / NULLIF(LAG(profit) OVER w, 0)  AS profit_growth_pct,
               (transactions - LAG(transactions) OVER w) * 100.0
                   / NULLIF(LAG(transactions) OVER w, 0) AS volume_growth_pct
        FROM y WINDOW w AS (ORDER BY year) ORDER BY year""", params)


@app.get("/api/region-monthly")
def region_monthly(start: str | None = None, end: str | None = None,
                   regions: list[str] | None = Query(None),
                   categories: list[str] | None = Query(None),
                   segments: list[str] | None = Query(None)) -> list[dict]:
    where, params = build_filter(start, end, regions, categories, segments)
    return q(f"""
        SELECT region, month_start, year_month,
               SUM(revenue) AS revenue, SUM(profit) AS profit,
               SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0) AS profit_margin_pct
        FROM fact_transactions WHERE {where}
        GROUP BY region, month_start, year_month
        ORDER BY region, month_start""", params)


# --------------------------------------------------------------------------
# Breakdowns
# --------------------------------------------------------------------------
DIMENSIONS = {"region": "region", "category": "product_category",
              "segment": "customer_segment", "payment": "payment_type"}


@app.get("/api/breakdown/{dimension}")
def breakdown(dimension: str, start: str | None = None, end: str | None = None,
              regions: list[str] | None = Query(None),
              categories: list[str] | None = Query(None),
              segments: list[str] | None = Query(None)) -> list[dict]:
    """Revenue, profit, margin and share for any of the four dimensions."""
    if dimension not in DIMENSIONS:
        raise HTTPException(404, f"Unknown dimension '{dimension}'. "
                                 f"Valid: {', '.join(DIMENSIONS)}")
    column = DIMENSIONS[dimension]
    where, params = build_filter(start, end, regions, categories, segments)
    return q(f"""
        SELECT {column} AS name,
               COUNT(*)                    AS transactions,
               COUNT(DISTINCT customer_id) AS customers,
               SUM(quantity)               AS units,
               SUM(revenue)                AS revenue,
               SUM(cost)                   AS cost,
               SUM(profit)                 AS profit,
               SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0)  AS profit_margin_pct,
               SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER () AS pct_of_revenue,
               SUM(profit)  * 100.0 / SUM(SUM(profit))  OVER () AS pct_of_profit,
               SUM(revenue) * 1.0 / NULLIF(COUNT(*), 0)       AS avg_order_value,
               SUM(discount_amount) * 100.0
                   / NULLIF(SUM(gross_revenue), 0)           AS discount_rate_pct
        FROM fact_transactions WHERE {where}
        GROUP BY {column} ORDER BY revenue DESC""", params)


@app.get("/api/discount-bands")
def discount_bands(start: str | None = None, end: str | None = None,
                   regions: list[str] | None = Query(None),
                   categories: list[str] | None = Query(None),
                   segments: list[str] | None = Query(None)) -> list[dict]:
    where, params = build_filter(start, end, regions, categories, segments)
    return q(f"""
        WITH banded AS (
            SELECT CASE WHEN discount = 0     THEN '0%'
                        WHEN discount <= 0.05 THEN '0-5%'
                        WHEN discount <= 0.10 THEN '5-10%'
                        WHEN discount <= 0.15 THEN '10-15%'
                        WHEN discount <= 0.25 THEN '15-25%'
                        WHEN discount <= 0.40 THEN '25-40%'
                        ELSE '40%+' END AS band,
                   CASE WHEN discount = 0     THEN 1
                        WHEN discount <= 0.05 THEN 2
                        WHEN discount <= 0.10 THEN 3
                        WHEN discount <= 0.15 THEN 4
                        WHEN discount <= 0.25 THEN 5
                        WHEN discount <= 0.40 THEN 6
                        ELSE 7 END AS band_order,
                   revenue, gross_revenue, discount_amount, profit, quantity,
                   is_loss_making
            FROM fact_transactions WHERE {where}
        )
        SELECT band, band_order,
               COUNT(*)                  AS transactions,
               AVG(quantity)             AS avg_quantity,
               SUM(gross_revenue)        AS gross_revenue,
               SUM(discount_amount)      AS discount_given,
               SUM(revenue)              AS revenue,
               SUM(profit)               AS profit,
               SUM(profit) * 100.0 / NULLIF(SUM(revenue), 0) AS profit_margin_pct,
               AVG(revenue)              AS avg_order_value,
               SUM(is_loss_making)       AS loss_making,
               SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER () AS pct_of_revenue
        FROM banded GROUP BY band, band_order ORDER BY band_order""", params)


# --------------------------------------------------------------------------
# Products and customers
# --------------------------------------------------------------------------
@app.get("/api/products")
def products(start: str | None = None, end: str | None = None,
             regions: list[str] | None = Query(None),
             categories: list[str] | None = Query(None),
             segments: list[str] | None = Query(None)) -> list[dict]:
    """Every product with the percentile ranks the investigation screen uses."""
    where, params = build_filter(start, end, regions, categories, segments, alias="f")
    return q(f"""
        WITH p AS (
            SELECT f.product_id, p.product_name, f.product_category,
                   COUNT(*) AS transactions, SUM(f.quantity) AS units,
                   SUM(f.revenue) AS revenue, SUM(f.cost) AS cost,
                   SUM(f.profit) AS profit,
                   SUM(f.gross_revenue) AS gross_revenue,
                   SUM(f.discount_amount) AS discount_amount
            FROM fact_transactions f
            JOIN dim_product p ON p.product_id = f.product_id
            WHERE {where}
            GROUP BY f.product_id, p.product_name, f.product_category
        )
        SELECT *,
               profit * 100.0 / NULLIF(revenue, 0)          AS profit_margin_pct,
               discount_amount * 100.0
                   / NULLIF(gross_revenue, 0)              AS discount_rate_pct,
               revenue * 1.0 / NULLIF(units, 0)            AS avg_realised_price,
               PERCENT_RANK() OVER (ORDER BY revenue) * 100 AS revenue_percentile,
               PERCENT_RANK() OVER (
                   ORDER BY profit * 1.0 / NULLIF(revenue, 0)) * 100
                                                           AS margin_percentile
        FROM p ORDER BY revenue DESC""", params)


@app.get("/api/customers")
def customers(limit: int = 30, start: str | None = None, end: str | None = None,
              regions: list[str] | None = Query(None),
              categories: list[str] | None = Query(None),
              segments: list[str] | None = Query(None)) -> dict:
    """Top accounts, revenue deciles and the Lorenz curve, all from SQL.

    Unattributed transactions are excluded here but remain in company revenue
    totals, which is why the customer revenue sum is slightly below the
    headline figure. The response reports that gap rather than hiding it.
    """
    where, params = build_filter(start, end, regions, categories, segments)
    attributed = f"{where} AND is_customer_attributed = 1"

    top = q(f"""
        WITH c AS (
            SELECT customer_id, customer_segment, region,
                   COUNT(*) AS orders, COUNT(DISTINCT year_month) AS active_months,
                   SUM(revenue) AS revenue, SUM(profit) AS profit,
                   SUM(gross_revenue) AS gross_revenue,
                   SUM(discount_amount) AS discount_amount
            FROM fact_transactions WHERE {attributed}
            GROUP BY customer_id, customer_segment, region
        ),
        ranked AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY revenue DESC) AS rank,
                   SUM(revenue) OVER (ORDER BY revenue DESC
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                                                    AS cumulative_revenue,
                   SUM(revenue) OVER ()             AS total_revenue
            FROM c
        )
        SELECT rank, customer_id, customer_segment, region, orders,
               active_months, revenue, profit,
               profit * 100.0 / NULLIF(revenue, 0)     AS profit_margin_pct,
               revenue * 1.0 / NULLIF(orders, 0)       AS avg_order_value,
               discount_amount * 100.0
                   / NULLIF(gross_revenue, 0)         AS discount_rate_pct,
               revenue * 100.0 / total_revenue        AS pct_of_revenue,
               cumulative_revenue * 100.0 / total_revenue AS cumulative_pct
        FROM ranked WHERE rank <= :limit ORDER BY rank""",
            {**params, "limit": limit})

    deciles = q(f"""
        WITH c AS (
            SELECT customer_id, SUM(revenue) AS revenue, SUM(profit) AS profit
            FROM fact_transactions WHERE {attributed} GROUP BY customer_id
        ),
        d AS (SELECT *, NTILE(10) OVER (ORDER BY revenue DESC) AS decile FROM c)
        SELECT decile, COUNT(*) AS customers, SUM(revenue) AS revenue,
               SUM(profit) AS profit, AVG(revenue) AS avg_revenue,
               SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER () AS pct_of_revenue,
               SUM(SUM(revenue)) OVER (ORDER BY decile
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) * 100.0
                   / SUM(SUM(revenue)) OVER ()  AS cumulative_pct
        FROM d GROUP BY decile ORDER BY decile""", params)

    bands = q(f"""
        WITH c AS (
            SELECT customer_id, COUNT(*) AS orders, SUM(revenue) AS revenue
            FROM fact_transactions WHERE {attributed} GROUP BY customer_id
        )
        SELECT CASE WHEN orders = 1 THEN '1 order'
                    WHEN orders <= 5 THEN '2-5'
                    WHEN orders <= 20 THEN '6-20'
                    WHEN orders <= 50 THEN '21-50'
                    ELSE '50+' END AS band,
               CASE WHEN orders = 1 THEN 1 WHEN orders <= 5 THEN 2
                    WHEN orders <= 20 THEN 3 WHEN orders <= 50 THEN 4
                    ELSE 5 END AS band_order,
               COUNT(*) AS customers, SUM(revenue) AS revenue,
               AVG(revenue) AS avg_lifetime_revenue, AVG(orders) AS avg_orders,
               COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () AS pct_of_customers,
               SUM(revenue) * 100.0 / SUM(SUM(revenue)) OVER () AS pct_of_revenue
        FROM c GROUP BY band, band_order ORDER BY band_order""", params)

    # Lorenz curve, thinned to ~200 points: the browser cannot draw 1,200
    # distinct points meaningfully, and the shape is identical.
    lorenz = q(f"""
        WITH c AS (
            SELECT customer_id, SUM(revenue) AS revenue
            FROM fact_transactions WHERE {attributed} GROUP BY customer_id
        ),
        r AS (
            SELECT ROW_NUMBER() OVER (ORDER BY revenue DESC) AS rank,
                   COUNT(*) OVER () AS total_customers,
                   SUM(revenue) OVER (ORDER BY revenue DESC
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum_revenue,
                   SUM(revenue) OVER () AS total_revenue
            FROM c
        )
        SELECT rank * 100.0 / total_customers AS customer_pct,
               cum_revenue * 100.0 / total_revenue AS revenue_pct
        FROM r
        WHERE rank % (CASE WHEN total_customers > 200
                           THEN total_customers / 200 ELSE 1 END) = 0
           OR rank = total_customers
        ORDER BY rank""", params)

    summary = q(f"""
        SELECT COUNT(DISTINCT customer_id) AS customers,
               COUNT(*) AS transactions, SUM(revenue) AS revenue
        FROM fact_transactions WHERE {attributed}""", params)[0]
    unattributed = q(f"""
        SELECT COUNT(*) AS transactions, SUM(revenue) AS revenue
        FROM fact_transactions
        WHERE {where} AND is_customer_attributed = 0""", params)[0]

    return {"top": top, "deciles": deciles, "order_bands": bands,
            "lorenz": lorenz, "summary": summary, "unattributed": unattributed}


# --------------------------------------------------------------------------
# Pre-computed analysis artefacts
# --------------------------------------------------------------------------
def _artefact(path, missing: str) -> dict:
    if not path.exists():
        raise HTTPException(503, missing)
    return json.loads(path.read_text())


@app.get("/api/statistics")
def statistics() -> dict:
    return _artefact(config.REPORTS_DIR / "statistical_analysis.json",
                     "Statistical results not found. Run: python -m src.stats_analysis")


@app.get("/api/timeseries")
def timeseries() -> dict:
    return _artefact(config.REPORTS_DIR / "timeseries_analysis.json",
                     "Time-series results not found. Run: python -m src.timeseries")


@app.get("/api/anomalies")
def anomalies() -> dict:
    report = _artefact(config.REPORTS_DIR / "anomaly_report.json",
                       "Anomaly results not found. Run: python -m src.anomaly")
    csv_path = config.PROCESSED_DIR / "anomalies.csv"
    rows = []
    if csv_path.exists():
        rows = json.loads(pd.read_csv(csv_path).to_json(orient="records"))
    return {**report, "rows": rows,
            "materiality_threshold_pct": config.MIN_MATERIAL_DEVIATION_PCT}


@app.get("/api/data-quality")
def data_quality() -> dict:
    return _artefact(config.CLEANING_REPORT,
                     "Cleaning report not found. Run: python -m src.clean_pipeline")


@app.get("/api/seasonal-components")
def seasonal_components() -> list[dict]:
    path = config.PROCESSED_DIR / "seasonal_components.csv"
    if not path.exists():
        return []
    return json.loads(pd.read_csv(path).to_json(orient="records"))


# --------------------------------------------------------------------------
# SQL library
# --------------------------------------------------------------------------
@app.get("/api/sql/queries")
def sql_queries() -> list[dict]:
    from src.sql_analysis import load_queries
    return [{"name": name, "description": spec["description"], "sql": spec["sql"]}
            for name, spec in load_queries().items()]


@app.get("/api/sql/run/{name}")
def sql_run(name: str, limit: int = 500) -> dict:
    """Execute one query from the library.

    Only names already present in ``sql/analysis_queries.sql`` can be run - the
    endpoint takes a key into the library, never SQL text from the client, so
    there is no path from the browser to arbitrary SQL.
    """
    from src.sql_analysis import load_queries
    queries = load_queries()
    if name not in queries:
        raise HTTPException(404, f"Unknown query '{name}'")
    with engine().connect() as conn:
        frame = pd.read_sql_query(text(queries[name]["sql"]), conn)
    truncated = len(frame) > limit
    return {
        "name": name,
        "description": queries[name]["description"],
        "sql": queries[name]["sql"],
        "columns": list(frame.columns),
        "row_count": len(frame),
        "truncated": truncated,
        "rows": json.loads(frame.head(limit).to_json(orient="records",
                                                     date_format="iso")),
    }


@app.get("/api/health")
def health() -> dict:
    try:
        n = q("SELECT COUNT(*) AS n FROM fact_transactions")[0]["n"]
        return {"status": "ok", "transactions": n, "database": config.DB_URL}
    except Exception as exc:
        return JSONResponse(status_code=503,
                            content={"status": "error", "detail": str(exc)})


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"),
              name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve the built React app, falling back to index.html.

        The fallback is what makes client-side routing work: a deep link like
        /products is not a file on disk, so it must return the shell and let
        the router resolve the path.
        """
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    def no_frontend() -> dict:
        return {
            "message": "API is running, but the frontend has not been built.",
            "build_it": "cd frontend && npm install && npm run build",
            "api_docs": "/docs",
        }


def main() -> None:
    import uvicorn
    if not FRONTEND_DIST.exists():
        print("NOTE: frontend/dist not found - serving the API only.")
        print("      Build the UI with:  cd frontend && npm install && npm run build\n")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
