"""Financial KPI framework.

Defines the metric set once, computes it for any period, and attaches the
comparison that makes a number mean something.  A KPI without a prior-period
comparison and a direction convention is just a number on a slide.

Every KPI carries:

* its value and unit, and how to format it
* the prior-period value, the absolute change and the percentage change
* ``higher_is_better``, so the dashboard can colour a fall in cost green and a
  fall in margin red instead of colouring every decline the same way
* a short definition, so the metric is auditable

Run with:  python -m src.kpi
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src import config
from src.clean_pipeline import load_clean

RESULTS_PATH = config.REPORTS_DIR / "kpi_summary.json"
KPI_TIMESERIES_PATH = config.PROCESSED_DIR / "kpi_monthly.csv"


@dataclass
class KPI:
    name: str
    value: float
    unit: str
    definition: str
    higher_is_better: bool = True
    prior_value: float | None = None
    category: str = "General"

    @property
    def change(self) -> float | None:
        if self.prior_value is None or not np.isfinite(self.prior_value):
            return None
        return self.value - self.prior_value

    @property
    def change_pct(self) -> float | None:
        if self.prior_value in (None, 0) or not np.isfinite(self.prior_value or np.nan):
            return None
        return (self.value - self.prior_value) / abs(self.prior_value) * 100

    @property
    def direction(self) -> str:
        c = self.change
        if c is None:
            return "flat"
        return "up" if c > 0 else "down" if c < 0 else "flat"

    @property
    def is_favourable(self) -> bool | None:
        """Whether the movement is good news, given the metric's convention."""
        c = self.change
        if c is None or c == 0:
            return None
        return (c > 0) == self.higher_is_better

    def formatted(self) -> str:
        if self.unit == "currency":
            return f"${self.value:,.0f}"
        if self.unit == "percent":
            return f"{self.value:.2f}%"
        if self.unit == "days":
            return f"{self.value:.1f} days"
        if self.unit == "count":
            return f"{self.value:,.0f}"
        return f"{self.value:,.2f}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(change=self.change, change_pct=self.change_pct,
                 direction=self.direction, is_favourable=self.is_favourable,
                 formatted=self.formatted())
        return d


# --------------------------------------------------------------------------
# Component metrics
# --------------------------------------------------------------------------
def _core_metrics(df: pd.DataFrame) -> dict[str, float]:
    """The raw aggregates every KPI is derived from, for one slice of data."""
    if df.empty:
        return {}
    revenue = float(df.revenue.sum())
    cost = float(df.cost.sum())
    profit = float(df.profit.sum())
    gross_revenue = float(df.gross_revenue.sum())
    attributed = df[df.is_customer_attributed]

    customers = int(attributed.customer_id.nunique())
    top10_revenue = float(attributed.groupby("customer_id").revenue.sum()
                          .nlargest(10).sum())

    return {
        "revenue": revenue,
        "cost": cost,
        "gross_profit": profit,
        "gross_margin_pct": profit / revenue * 100 if revenue else np.nan,
        "cost_to_revenue_pct": cost / revenue * 100 if revenue else np.nan,
        "discount_rate_pct": (gross_revenue - revenue) / gross_revenue * 100
                             if gross_revenue else np.nan,
        "transactions": float(len(df)),
        "units_sold": float(df.quantity.sum()),
        "active_customers": float(customers),
        "avg_order_value": revenue / len(df) if len(df) else np.nan,
        "revenue_per_customer": revenue / customers if customers else np.nan,
        "top10_customer_share_pct": top10_revenue / revenue * 100 if revenue else np.nan,
        "loss_making_pct": float(df.is_loss_making.mean() * 100),
    }


def _retention_rate(df: pd.DataFrame, period_col: str, period, prior_period) -> float:
    """Share of the prior period's customers who bought again in this period."""
    if prior_period is None:
        return np.nan
    attributed = df[df.is_customer_attributed]
    prior = set(attributed.loc[attributed[period_col] == prior_period, "customer_id"])
    current = set(attributed.loc[attributed[period_col] == period, "customer_id"])
    if not prior:
        return np.nan
    return len(prior & current) / len(prior) * 100


def _new_customers(df: pd.DataFrame, period_col: str, period) -> float:
    """Customers whose first ever purchase falls in this period."""
    attributed = df[df.is_customer_attributed]
    first = attributed.groupby("customer_id")[period_col].min()
    return float((first == period).sum())


def _dso(period_end: pd.Timestamp, revenue: float, days: int) -> dict[str, float]:
    """Days sales outstanding, plus the average realised days-to-pay.

    Classic DSO uses the closing receivables balance over revenue for the
    period.  The average days-to-pay on settled invoices is reported next to it
    because the two answer different questions: DSO is a balance-sheet
    position, days-to-pay is collections behaviour.
    """
    ar = pd.read_csv(config.RAW_AR, keep_default_na=False, na_values=[""],
                     parse_dates=["invoice_date", "due_date", "paid_date"])
    issued = ar[ar.invoice_date <= period_end]
    outstanding = issued[issued.paid_date.isna() | (issued.paid_date > period_end)]
    balance = float(outstanding.invoice_amount.sum())

    settled = ar[(ar.paid_date.notna()) & (ar.paid_date <= period_end) &
                 (ar.invoice_date > period_end - pd.Timedelta(days=days))]
    days_to_pay = float((settled.paid_date - settled.invoice_date).dt.days.mean()) \
        if len(settled) else np.nan

    return {"receivables_balance": balance,
            "dso_days": balance / revenue * days if revenue else np.nan,
            "avg_days_to_pay": days_to_pay}


# --------------------------------------------------------------------------
# KPI assembly
# --------------------------------------------------------------------------
def build_kpis(current: dict, prior: dict, extras: dict,
               prior_extras: dict) -> list[KPI]:
    """Turn raw aggregates into the defined KPI set."""
    def prev(key):
        v = prior.get(key)
        return v if v is not None and np.isfinite(v) else None

    specs = [
        ("Total Revenue", "revenue", "currency", True, "Revenue",
         "Net revenue after discount: quantity x unit price x (1 - discount)."),
        ("Total Cost", "cost", "currency", False, "Cost",
         "Cost of goods sold: quantity x unit cost."),
        ("Gross Profit", "gross_profit", "currency", True, "Profitability",
         "Net revenue less cost of goods sold."),
        ("Gross Margin", "gross_margin_pct", "percent", True, "Profitability",
         "Gross profit as a percentage of net revenue."),
        ("Cost-to-Revenue Ratio", "cost_to_revenue_pct", "percent", False, "Cost",
         "Cost of goods sold as a percentage of net revenue."),
        ("Discount Rate", "discount_rate_pct", "percent", False, "Revenue",
         "Discount given as a percentage of gross (list-price) revenue."),
        ("Transactions", "transactions", "count", True, "Volume",
         "Count of completed transactions in the period."),
        ("Units Sold", "units_sold", "count", True, "Volume",
         "Total quantity across all transactions."),
        ("Active Customers", "active_customers", "count", True, "Customers",
         "Distinct customers with at least one attributed purchase."),
        ("Average Order Value", "avg_order_value", "currency", True, "Revenue",
         "Net revenue divided by transaction count."),
        ("Revenue per Customer", "revenue_per_customer", "currency", True, "Customers",
         "Net revenue divided by active customers."),
        ("Top 10 Customer Share", "top10_customer_share_pct", "percent", False,
         "Customers",
         "Share of revenue from the ten largest customers - a concentration risk "
         "measure, so lower is safer."),
        ("Loss-Making Transactions", "loss_making_pct", "percent", False,
         "Profitability",
         "Percentage of transactions sold below cost."),
    ]

    kpis = [KPI(name=name, value=current.get(key, np.nan), unit=unit,
                higher_is_better=hib, category=cat, definition=definition,
                prior_value=prev(key))
            for name, key, unit, hib, cat, definition in specs]

    extra_specs = [
        ("New Customers", "new_customers", "count", True, "Customers",
         "Customers making their first ever purchase in the period."),
        ("Customer Retention Rate", "retention_pct", "percent", True, "Customers",
         "Share of the prior period's customers who purchased again this period."),
        ("Receivables Balance", "receivables_balance", "currency", False, "Cash",
         "Value of invoices issued but unpaid at the period end."),
        ("Days Sales Outstanding", "dso_days", "days", False, "Cash",
         "Closing receivables divided by period revenue, scaled to days."),
        ("Average Days to Pay", "avg_days_to_pay", "days", False, "Cash",
         "Mean invoice-to-payment interval for invoices settled in the period."),
    ]
    for name, key, unit, hib, cat, definition in extra_specs:
        kpis.append(KPI(name=name, value=extras.get(key, np.nan), unit=unit,
                        higher_is_better=hib, category=cat, definition=definition,
                        prior_value=prior_extras.get(key)))
    return kpis


def compute_period_kpis(df: pd.DataFrame, period: str = "year",
                        which: int | str | None = None) -> list[KPI]:
    """KPIs for one period, compared with the immediately preceding one.

    ``period`` is 'year' or 'month'; ``which`` selects the period (defaults to
    the most recent complete one in the data).
    """
    col = "year" if period == "year" else "year_month"
    periods = sorted(df[col].unique())
    target = which if which is not None else periods[-1]
    idx = periods.index(target)
    prior = periods[idx - 1] if idx > 0 else None

    current_df = df[df[col] == target]
    prior_df = df[df[col] == prior] if prior is not None else df.iloc[0:0]

    current = _core_metrics(current_df)
    prior_metrics = _core_metrics(prior_df)

    days = int((current_df.transaction_date.max()
                - current_df.transaction_date.min()).days) + 1
    extras = {
        "new_customers": _new_customers(df, col, target),
        "retention_pct": _retention_rate(df, col, target, prior),
        **_dso(current_df.transaction_date.max(), current.get("revenue", 0), days),
    }
    if prior is not None and not prior_df.empty:
        prior_days = int((prior_df.transaction_date.max()
                          - prior_df.transaction_date.min()).days) + 1
        prior_extras = {
            "new_customers": _new_customers(df, col, prior),
            "retention_pct": _retention_rate(
                df, col, prior, periods[idx - 2] if idx > 1 else None),
            **_dso(prior_df.transaction_date.max(),
                   prior_metrics.get("revenue", 0), prior_days),
        }
    else:
        prior_extras = {}

    return build_kpis(current, prior_metrics, extras, prior_extras)


def kpi_timeseries(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly KPI history - the series behind every dashboard trend chart."""
    rows = []
    months = sorted(df.year_month.unique())
    for i, month in enumerate(months):
        sub = df[df.year_month == month]
        metrics = _core_metrics(sub)
        metrics["year_month"] = month
        metrics["month_start"] = sub.month_start.iloc[0]
        metrics["new_customers"] = _new_customers(df, "year_month", month)
        metrics["retention_pct"] = _retention_rate(
            df, "year_month", month, months[i - 1] if i > 0 else None)
        rows.append(metrics)

    out = pd.DataFrame(rows).sort_values("month_start").reset_index(drop=True)
    out["revenue_mom_pct"] = out.revenue.pct_change() * 100
    out["revenue_yoy_pct"] = out.revenue.pct_change(12) * 100
    out["profit_yoy_pct"] = out.gross_profit.pct_change(12) * 100
    out["revenue_3mo_ma"] = out.revenue.rolling(3).mean()
    return out


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_all(df: pd.DataFrame | None = None, verbose: bool = True) -> dict:
    df = load_clean() if df is None else df

    if verbose:
        print("Computing KPI time series ...")
    series = kpi_timeseries(df)
    series.to_csv(KPI_TIMESERIES_PATH, index=False)

    if verbose:
        print("Computing period scorecards ...")
    latest_year = compute_period_kpis(df, "year")
    latest_month = compute_period_kpis(df, "month")

    overall = _core_metrics(df)
    results = {
        "period_covered": {"start": str(df.transaction_date.min().date()),
                           "end": str(df.transaction_date.max().date())},
        "all_time": {k: (round(v, 2) if isinstance(v, float) else v)
                     for k, v in overall.items()},
        "latest_year": {"period": int(df.year.max()),
                        "kpis": [k.to_dict() for k in latest_year]},
        "latest_month": {"period": str(sorted(df.year_month.unique())[-1]),
                         "kpis": [k.to_dict() for k in latest_month]},
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))

    if verbose:
        _print_scorecard(latest_year, f"FULL YEAR {df.year.max()} vs {df.year.max() - 1}")
        _print_scorecard(latest_month,
                         f"LATEST MONTH {sorted(df.year_month.unique())[-1]} "
                         f"vs prior month")
        print(f"\nWritten: {KPI_TIMESERIES_PATH.name}, {RESULTS_PATH.name}")
    return results


def _print_scorecard(kpis: list[KPI], title: str) -> None:
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)
    print(f"  {'KPI':<28} {'Value':>16} {'Prior':>16} {'Change':>12}  Verdict")
    print("  " + "-" * 84)
    for k in kpis:
        prior = (f"{k.prior_value:,.2f}" if k.prior_value is not None
                 and np.isfinite(k.prior_value) else "-")
        change = f"{k.change_pct:+.2f}%" if k.change_pct is not None else "-"
        verdict = ("favourable" if k.is_favourable
                   else "unfavourable" if k.is_favourable is False else "")
        print(f"  {k.name:<28} {k.formatted():>16} {prior:>16} {change:>12}  {verdict}")


if __name__ == "__main__":
    run_all()
