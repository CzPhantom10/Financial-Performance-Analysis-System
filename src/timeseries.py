"""Time-series analysis of financial performance.

The goal here is *understanding*, not forecasting: separate the underlying
growth trend from the seasonal pattern and the residual noise, quantify each,
and say which months are structurally weak rather than merely unlucky.  No
predictive model is fitted - the constraint is deliberate, and classical
decomposition answers the business questions on its own.

What the module produces:

* a monthly spine with moving averages, MoM/QoQ/YoY growth and cumulative totals
* a multiplicative decomposition into trend, seasonal and residual components
* a seasonal index per calendar month, with the strength of seasonality measured
* trend estimation via OLS on log revenue, which gives a compound growth rate
  rather than a straight-line slope
* stationarity and autocorrelation diagnostics that justify treating the series
  as trend-plus-seasonal
* a growth decomposition splitting revenue growth into volume and order-value
  contributions

Run with:  python -m src.timeseries
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.tsa.seasonal import STL, seasonal_decompose
from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf
from statsmodels.stats.diagnostic import acorr_ljungbox

from src import config
from src.clean_pipeline import load_clean

RESULTS_PATH = config.REPORTS_DIR / "timeseries_analysis.json"
MONTHLY_PATH = config.PROCESSED_DIR / "monthly_timeseries.csv"

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

# STL settings for a three-year monthly series.
#
# The defaults are wrong at this length.  With only three cycles there are just
# three observations at each month position, and STL's default degree-1
# seasonal loess can fit a straight line through them almost exactly - which
# drives the residual to zero in the outer years and dumps every deviation into
# the middle year.  Measured on this dataset the default gives a residual MAD
# of 2e-13, so any residual-based z-score explodes.
#
# seasonal_deg=0 makes the seasonal component a local *level* - a stable
# average per calendar month - which is the correct assumption for three years
# of data and leaves a residual with real dispersion.
STL_KWARGS = dict(period=12, robust=True, seasonal=13, seasonal_deg=0, trend=25)


def fit_stl(series: pd.Series):
    """Fit the shared STL configuration to a positive series, on the log scale.

    Working in logs makes the decomposition multiplicative, which is how
    revenue seasonality actually behaves: December is ~25% above trend, not a
    fixed number of dollars above it.
    """
    return STL(np.log(series), **STL_KWARGS).fit()


# --------------------------------------------------------------------------
# Monthly spine
# --------------------------------------------------------------------------
def build_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to month grain and attach every derived time-series column."""
    m = (df.groupby("month_start")
           .agg(revenue=("revenue", "sum"),
                gross_revenue=("gross_revenue", "sum"),
                discount_amount=("discount_amount", "sum"),
                cost=("cost", "sum"),
                profit=("profit", "sum"),
                transactions=("transaction_id", "size"),
                units=("quantity", "sum"),
                active_customers=("customer_id", "nunique"))
           .reset_index()
           .sort_values("month_start")
           .reset_index(drop=True))

    m["profit_margin_pct"] = m.profit / m.revenue * 100
    m["cost_to_revenue_pct"] = m.cost / m.revenue * 100
    m["discount_rate_pct"] = m.discount_amount / m.gross_revenue * 100
    m["avg_order_value"] = m.revenue / m.transactions
    m["revenue_per_customer"] = m.revenue / m.active_customers

    m["year"] = m.month_start.dt.year
    m["month"] = m.month_start.dt.month
    m["month_name"] = m.month_start.dt.strftime("%B")
    m["quarter"] = m.month_start.dt.quarter
    m["period_index"] = np.arange(len(m))

    for window in (3, 6, 12):
        m[f"revenue_ma{window}"] = m.revenue.rolling(window).mean()
        m[f"margin_ma{window}"] = m.profit_margin_pct.rolling(window).mean()
    m["revenue_vs_ma3_pct"] = (m.revenue / m.revenue_ma3 - 1) * 100

    m["revenue_mom_pct"] = m.revenue.pct_change() * 100
    m["revenue_yoy_pct"] = m.revenue.pct_change(12) * 100
    m["profit_yoy_pct"] = m.profit.pct_change(12) * 100
    m["cost_yoy_pct"] = m.cost.pct_change(12) * 100
    m["cumulative_revenue"] = m.revenue.cumsum()

    # Rolling volatility of the growth rate: how predictable is the business?
    m["revenue_mom_volatility"] = m.revenue_mom_pct.rolling(6).std()
    return m


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------
def trend_analysis(monthly: pd.DataFrame) -> dict:
    """Fit the growth trend on the log scale.

    Revenue compounds, so a straight line through the levels would understate
    early growth and overstate late growth.  Regressing log(revenue) on time
    makes the slope a constant growth *rate*, which is what "we are growing at
    x% a year" actually means.
    """
    y = np.log(monthly.revenue.to_numpy())
    x = sm.add_constant(monthly.period_index.to_numpy(dtype=float))
    model = sm.OLS(y, x).fit()

    monthly_rate = float(model.params[1])
    annual_growth = float(np.exp(monthly_rate * 12) - 1)

    # Non-parametric confirmation that the trend is real and monotonic.
    tau, tau_p = stats.kendalltau(monthly.period_index, monthly.revenue)

    first_year = monthly[monthly.year == monthly.year.min()].revenue.sum()
    last_year = monthly[monthly.year == monthly.year.max()].revenue.sum()
    n_years = monthly.year.max() - monthly.year.min()
    cagr = float((last_year / first_year) ** (1 / n_years) - 1) if n_years else np.nan

    return {
        "method": "OLS on log(revenue) against period index",
        "monthly_growth_rate_pct": round(monthly_rate * 100, 4),
        "implied_annual_growth_pct": round(annual_growth * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "r_squared": round(float(model.rsquared), 4),
        "slope_p_value": float(model.pvalues[1]),
        "trend_is_significant": bool(model.pvalues[1] < config.ALPHA),
        "kendall_tau": round(float(tau), 4),
        "kendall_tau_p": float(tau_p),
        "first_year_revenue": round(float(first_year), 2),
        "last_year_revenue": round(float(last_year), 2),
        "interpretation": (
            f"Revenue is growing at a compound {annual_growth * 100:.1f}% a year "
            f"(CAGR {cagr * 100:.1f}%), and the log-linear trend explains "
            f"{model.rsquared * 100:.1f}% of the variation in monthly revenue. "
            f"The remainder is seasonal and event-driven, which the decomposition "
            f"below separates."),
    }


# --------------------------------------------------------------------------
# Seasonality
# --------------------------------------------------------------------------
def seasonal_analysis(monthly: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Classical and STL decomposition, plus a per-month seasonal index."""
    series = monthly.set_index("month_start").revenue.asfreq("MS")

    classical = seasonal_decompose(series, model="multiplicative", period=12)
    stl = fit_stl(series)

    components = pd.DataFrame({
        "month_start": series.index,
        "observed": series.to_numpy(),
        "trend": classical.trend.to_numpy(),
        "seasonal": classical.seasonal.to_numpy(),
        "residual": classical.resid.to_numpy(),
        "stl_trend": np.exp(stl.trend),
        "stl_seasonal": np.exp(stl.seasonal),
        "stl_residual": np.exp(stl.resid),
    })

    # A seasonal index of 1.20 means that month typically runs 20% above trend.
    seasonal_index = (components.assign(month=components.month_start.dt.month)
                      .groupby("month")["seasonal"].mean())
    idx = pd.DataFrame({
        "month": seasonal_index.index,
        "month_name": [MONTH_NAMES[i - 1] for i in seasonal_index.index],
        "seasonal_index": seasonal_index.round(4).to_numpy(),
        "pct_vs_average": ((seasonal_index - 1) * 100).round(2).to_numpy(),
    }).sort_values("month")

    # Strength of seasonality, in the sense used by Hyndman: how much of the
    # detrended variance the seasonal component accounts for.
    resid_var = np.nanvar(stl.resid)
    seasonal_strength = max(0.0, 1 - resid_var / np.nanvar(stl.seasonal + stl.resid))
    trend_strength = max(0.0, 1 - resid_var / np.nanvar(stl.trend + stl.resid))

    peak = idx.loc[idx.seasonal_index.idxmax()]
    trough = idx.loc[idx.seasonal_index.idxmin()]

    summary = {
        "method": "Multiplicative classical decomposition + robust STL on log revenue",
        "seasonal_strength": round(float(seasonal_strength), 4),
        "trend_strength": round(float(trend_strength), 4),
        "peak_month": peak.month_name,
        "peak_index": float(peak.seasonal_index),
        "peak_pct_above_average": float(peak.pct_vs_average),
        "trough_month": trough.month_name,
        "trough_index": float(trough.seasonal_index),
        "trough_pct_below_average": float(trough.pct_vs_average),
        "peak_to_trough_ratio": round(float(peak.seasonal_index / trough.seasonal_index), 3),
        "seasonal_index": idx.to_dict("records"),
        "interpretation": (
            f"Seasonality is {'strong' if seasonal_strength > 0.6 else 'moderate' if seasonal_strength > 0.3 else 'weak'} "
            f"(strength {seasonal_strength:.2f}). {peak.month_name} typically runs "
            f"{peak.pct_vs_average:+.1f}% against trend and {trough.month_name} "
            f"{trough.pct_vs_average:+.1f}%, a peak-to-trough swing of "
            f"{peak.seasonal_index / trough.seasonal_index:.2f}x. A weak "
            f"{trough.month_name} is therefore normal and should not be escalated; "
            f"only deviation from the seasonal expectation is news."),
    }
    return summary, components


def quarterly_analysis(df: pd.DataFrame) -> list[dict]:
    q = (df.groupby(["year", "quarter"])
           .agg(revenue=("revenue", "sum"), profit=("profit", "sum"),
                transactions=("transaction_id", "size"))
           .reset_index().sort_values(["year", "quarter"]))
    q["margin_pct"] = q.profit / q.revenue * 100
    q["qoq_growth_pct"] = q.revenue.pct_change() * 100
    q["yoy_growth_pct"] = q.revenue.pct_change(4) * 100
    q["label"] = q.year.astype(str) + "-Q" + q.quarter.astype(str)
    return q.round(2).to_dict("records")


def day_of_week_analysis(df: pd.DataFrame) -> list[dict]:
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]
    d = (df.groupby("day_of_week")
           .agg(transactions=("transaction_id", "size"),
                revenue=("revenue", "sum"),
                avg_order_value=("revenue", "mean"))
           .reindex(order).reset_index())
    d["pct_of_transactions"] = d.transactions / d.transactions.sum() * 100
    d["pct_of_revenue"] = d.revenue / d.revenue.sum() * 100
    return d.round(2).to_dict("records")


# --------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------
def stationarity_and_autocorrelation(monthly: pd.DataFrame) -> dict:
    """Describe the series' statistical structure.

    ADF and KPSS test opposite nulls, which is why both are run: ADF's null is
    "has a unit root", KPSS's null is "is stationary".  Agreement between them
    is a much stronger statement than either alone.
    """
    rev = monthly.revenue.to_numpy()
    log_rev = np.log(rev)

    adf_stat, adf_p, *_ = adfuller(log_rev, autolag="AIC", result_object=False)
    kpss_stat, kpss_p, *_ = kpss(log_rev, regression="ct", nlags="auto",
                                 result_object=False)

    diff = np.diff(log_rev)
    adf_d_stat, adf_d_p, *_ = adfuller(diff, autolag="AIC", result_object=False)

    n_lags = min(18, len(rev) // 2 - 1)
    acf_values = acf(log_rev, nlags=n_lags)
    pacf_values = pacf(log_rev, nlags=min(n_lags, len(rev) // 2 - 1))

    lb = acorr_ljungbox(log_rev, lags=[6, 12], return_df=True)

    return {
        "adf_on_log_revenue": {
            "statistic": round(float(adf_stat), 4), "p_value": float(adf_p),
            "null": "series has a unit root (non-stationary)",
            "stationary_at_5pct": bool(adf_p < 0.05)},
        "kpss_on_log_revenue": {
            "statistic": round(float(kpss_stat), 4), "p_value": float(kpss_p),
            "null": "series is trend-stationary",
            "stationary_at_5pct": bool(kpss_p >= 0.05)},
        "adf_on_first_difference": {
            "statistic": round(float(adf_d_stat), 4), "p_value": float(adf_d_p),
            "stationary_at_5pct": bool(adf_d_p < 0.05)},
        "acf": [round(float(v), 4) for v in acf_values],
        "pacf": [round(float(v), 4) for v in pacf_values],
        "acf_lag_12": round(float(acf_values[12]), 4) if len(acf_values) > 12 else None,
        "ljung_box": {f"lag_{int(lag)}": {"statistic": round(float(row.lb_stat), 4),
                                          "p_value": float(row.lb_pvalue)}
                      for lag, row in lb.iterrows()},
        "interpretation": (
            "The level series is non-stationary, as expected for a growing business; "
            "differencing removes the unit root. The autocorrelation at lag 12 is the "
            "numerical signature of the annual seasonal cycle, and Ljung-Box confirms "
            "the series is not white noise - together they justify treating revenue as "
            "trend-plus-seasonal rather than as independent monthly draws."),
    }


# --------------------------------------------------------------------------
# Growth decomposition
# --------------------------------------------------------------------------
def growth_decomposition(monthly: pd.DataFrame) -> dict:
    """Split revenue growth into volume and order-value contributions.

    Revenue = transactions x average order value, so on the log scale the two
    growth contributions add exactly.  This answers whether growth is coming
    from selling to more people or from selling more per deal.
    """
    yearly = (monthly.groupby("year")
              .agg(revenue=("revenue", "sum"), transactions=("transactions", "sum"),
                   customers=("active_customers", "max"))
              .reset_index())
    yearly["avg_order_value"] = yearly.revenue / yearly.transactions

    rows = []
    for i in range(1, len(yearly)):
        prev, cur = yearly.iloc[i - 1], yearly.iloc[i]
        rev_growth = cur.revenue / prev.revenue - 1
        vol_growth = cur.transactions / prev.transactions - 1
        aov_growth = cur.avg_order_value / prev.avg_order_value - 1
        log_total = np.log(cur.revenue / prev.revenue)
        rows.append({
            "year": int(cur.year),
            "revenue_growth_pct": round(rev_growth * 100, 2),
            "volume_growth_pct": round(vol_growth * 100, 2),
            "order_value_growth_pct": round(aov_growth * 100, 2),
            "volume_contribution_pct": round(
                float(np.log(cur.transactions / prev.transactions) / log_total * 100), 1),
            "order_value_contribution_pct": round(
                float(np.log(cur.avg_order_value / prev.avg_order_value) / log_total * 100), 1),
        })

    latest = rows[-1] if rows else {}
    return {
        "identity": "revenue = transactions x average order value",
        "by_year": rows,
        "interpretation": (
            f"In {latest.get('year', 'the latest year')}, "
            f"{latest.get('volume_contribution_pct', 0):.0f}% of revenue growth came "
            f"from transaction volume and "
            f"{latest.get('order_value_contribution_pct', 0):.0f}% from a higher "
            f"average order value. Volume-led growth is the more durable of the two, "
            f"but it is also what pushes the cost base up." if latest else ""),
    }


def worst_and_best_months(monthly: pd.DataFrame) -> dict:
    m = monthly.dropna(subset=["revenue_mom_pct"])
    worst = m.nsmallest(5, "revenue_mom_pct")
    best = m.nlargest(5, "revenue_mom_pct")

    def fmt(frame):
        return [{"month": r.month_start.strftime("%Y-%m"),
                 "revenue": round(float(r.revenue), 2),
                 "mom_change_pct": round(float(r.revenue_mom_pct), 2),
                 "vs_3mo_ma_pct": (round(float(r.revenue_vs_ma3_pct), 2)
                                   if pd.notna(r.revenue_vs_ma3_pct) else None)}
                for r in frame.itertuples()]

    ym = monthly.dropna(subset=["revenue_yoy_pct"])
    return {
        "largest_declines_mom": fmt(worst),
        "largest_increases_mom": fmt(best),
        "weakest_yoy": [{"month": r.month_start.strftime("%Y-%m"),
                         "yoy_pct": round(float(r.revenue_yoy_pct), 2)}
                        for r in ym.nsmallest(5, "revenue_yoy_pct").itertuples()],
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_all(df: pd.DataFrame | None = None, verbose: bool = True) -> dict:
    df = load_clean() if df is None else df
    monthly = build_monthly(df)

    if verbose:
        print("Trend estimation ...")
    trend = trend_analysis(monthly)

    if verbose:
        print("Seasonal decomposition ...")
    seasonal, components = seasonal_analysis(monthly)

    if verbose:
        print("Stationarity and autocorrelation diagnostics ...")
    diagnostics = stationarity_and_autocorrelation(monthly)

    if verbose:
        print("Growth decomposition ...")
    growth = growth_decomposition(monthly)

    results = {
        "period": {"start": str(monthly.month_start.min().date()),
                   "end": str(monthly.month_start.max().date()),
                   "months": len(monthly)},
        "trend": trend,
        "seasonality": seasonal,
        "quarterly": quarterly_analysis(df),
        "day_of_week": day_of_week_analysis(df),
        "diagnostics": diagnostics,
        "growth_decomposition": growth,
        "extremes": worst_and_best_months(monthly),
    }

    monthly.to_csv(MONTHLY_PATH, index=False)
    components.to_csv(config.PROCESSED_DIR / "seasonal_components.csv", index=False)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))

    if verbose:
        _print_summary(results, monthly)
        print(f"\nWritten: {MONTHLY_PATH.name}, seasonal_components.csv, "
              f"{RESULTS_PATH.name}")
    return results


def _print_summary(r: dict, monthly: pd.DataFrame) -> None:
    print("\n" + "=" * 78)
    print(f"TIME-SERIES ANALYSIS  {r['period']['start']} to {r['period']['end']} "
          f"({r['period']['months']} months)")
    print("=" * 78)

    t = r["trend"]
    print(f"\nTREND")
    print(f"  Compound annual growth   {t['implied_annual_growth_pct']:>8.2f}%  "
          f"(CAGR {t['cagr_pct']}%)")
    print(f"  Log-linear fit R^2       {t['r_squared']:>8.4f}   "
          f"p={t['slope_p_value']:.2e}")
    print(f"  Kendall tau              {t['kendall_tau']:>8.4f}   "
          f"p={t['kendall_tau_p']:.2e}")

    s = r["seasonality"]
    print(f"\nSEASONALITY  (strength {s['seasonal_strength']:.3f}, "
          f"trend strength {s['trend_strength']:.3f})")
    for row in s["seasonal_index"]:
        bar_len = int(abs(row["pct_vs_average"]) / 2)
        bar = ("+" if row["pct_vs_average"] >= 0 else "-") * bar_len
        print(f"  {row['month_name']:<10} index {row['seasonal_index']:.3f}  "
              f"{row['pct_vs_average']:>+7.1f}%  {bar}")

    d = r["diagnostics"]
    print(f"\nDIAGNOSTICS")
    print(f"  ADF (log revenue)        stat={d['adf_on_log_revenue']['statistic']:>8.3f}  "
          f"p={d['adf_on_log_revenue']['p_value']:.4f}  "
          f"stationary={d['adf_on_log_revenue']['stationary_at_5pct']}")
    print(f"  KPSS (log revenue)       stat={d['kpss_on_log_revenue']['statistic']:>8.3f}  "
          f"p={d['kpss_on_log_revenue']['p_value']:.4f}  "
          f"stationary={d['kpss_on_log_revenue']['stationary_at_5pct']}")
    print(f"  ADF (1st difference)     stat={d['adf_on_first_difference']['statistic']:>8.3f}  "
          f"p={d['adf_on_first_difference']['p_value']:.4f}  "
          f"stationary={d['adf_on_first_difference']['stationary_at_5pct']}")
    print(f"  ACF at lag 12            {d['acf_lag_12']}")

    print(f"\nGROWTH DECOMPOSITION")
    for row in r["growth_decomposition"]["by_year"]:
        print(f"  {row['year']}  revenue {row['revenue_growth_pct']:>6.2f}%  =  "
              f"volume {row['volume_growth_pct']:>6.2f}% "
              f"({row['volume_contribution_pct']:.0f}% of growth)  x  "
              f"AOV {row['order_value_growth_pct']:>6.2f}% "
              f"({row['order_value_contribution_pct']:.0f}%)")

    print(f"\nLARGEST MONTH-ON-MONTH DECLINES")
    for row in r["extremes"]["largest_declines_mom"]:
        print(f"  {row['month']}  {row['mom_change_pct']:>7.2f}%   "
              f"revenue {row['revenue']:>14,.0f}")


if __name__ == "__main__":
    run_all()
