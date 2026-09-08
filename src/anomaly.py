"""Statistical anomaly detection for financial metrics.

No machine learning: every detector here is a classical statistical rule whose
threshold has an explicit meaning, which matters because a finance team has to
act on the output and defend it.

Four complementary detectors, because each one is blind to something the others
catch:

* **Global z-score** - flags a value far from the series mean.  Simple, but on
  a growing, seasonal series it mostly rediscovers "December is big".
* **Rolling z-score** - compares a value with its own recent history, so it
  catches a shift that a global test would miss once the series has drifted.
* **Seasonal-residual z-score** - flags a month that is unusual *after* the
  trend and seasonal components are removed.  This is the one that answers
  "was February genuinely bad, or just February?".
* **Tukey IQR fences** - distribution-free, applied to transaction-level values
  on the log scale where the data is roughly symmetric.

Every anomaly is reported with its expected range, so the reader can see the
size of the miss rather than just a flag.  The module finishes by scoring
itself against the events deliberately injected by the data generator - a
recall check that stops the detector from being graded on its own homework.

Run with:  python -m src.anomaly
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from src import config
from src.clean_pipeline import load_clean
from src.timeseries import build_monthly, fit_stl

RESULTS_PATH = config.REPORTS_DIR / "anomaly_report.json"
ANOMALY_CSV = config.PROCESSED_DIR / "anomalies.csv"


@dataclass
class Anomaly:
    period: str
    scope: str
    metric: str
    method: str
    actual: float
    expected: float
    expected_low: float
    expected_high: float
    deviation: float
    deviation_pct: float
    score: float          # z-score, or fence distance in IQRs
    severity: str
    material: bool        # did the move clear the materiality floor?
    interpretation: str

    def to_dict(self) -> dict:
        return asdict(self)


def _is_material(deviation_pct: float | None) -> bool:
    """Is the move large enough in relative terms to be worth someone's time?"""
    if deviation_pct is None or not np.isfinite(deviation_pct):
        return True
    return abs(deviation_pct) >= config.MIN_MATERIAL_DEVIATION_PCT


def _severity(score: float, deviation_pct: float | None = None) -> str:
    """Grade a flag on statistical extremity, then temper it with materiality.

    Without the second step the monitor is dominated by series that barely move:
    Rent & Facilities has ~2% natural month-to-month noise, so a 2.7% increase
    scores z=9 and would outrank a 48% collapse in revenue. An immaterial move
    still gets reported - it is real - but it is capped at Low so it cannot
    crowd the actionable findings out of the top of the list.
    """
    a = abs(score)
    base = ("Critical" if a >= 4.5 else "High" if a >= 3.5
            else "Medium" if a >= 3.0 else "Low")
    return base if _is_material(deviation_pct) else "Low"


def _fmt(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.2f}M"
    if abs(value) >= 1_000:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------
def zscore_detector(series: pd.Series, metric: str, scope: str = "Company-wide",
                    threshold: float = config.Z_THRESHOLD,
                    unit: str = "") -> list[Anomaly]:
    """Flag points more than `threshold` SDs from the series mean."""
    values = series.dropna()
    if len(values) < 6:
        return []
    mu, sd = values.mean(), values.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return []

    out = []
    for period, actual in values.items():
        z = (actual - mu) / sd
        if abs(z) < threshold:
            continue
        out.append(Anomaly(
            period=str(period)[:10], scope=scope, metric=metric,
            method=f"Global z-score (|z| > {threshold})",
            actual=round(float(actual), 2), expected=round(float(mu), 2),
            expected_low=round(float(mu - threshold * sd), 2),
            expected_high=round(float(mu + threshold * sd), 2),
            deviation=round(float(actual - mu), 2),
            deviation_pct=round(float((actual - mu) / mu * 100), 2) if mu else np.nan,
            score=round(float(z), 2),
            severity=_severity(z, (actual - mu) / mu * 100 if mu else None),
            material=_is_material((actual - mu) / mu * 100 if mu else None),
            interpretation=(
                f"{metric} of {_fmt(actual)}{unit} sits {abs(z):.1f} standard "
                f"deviations {'above' if z > 0 else 'below'} the series mean of "
                f"{_fmt(mu)}{unit}. On a trending, seasonal series a global "
                f"z-score is a coarse screen - check the seasonal-residual "
                f"result for the same period before acting."),
        ))
    return out


def rolling_zscore_detector(series: pd.Series, metric: str,
                            scope: str = "Company-wide",
                            window: int = 6, threshold: float = config.Z_THRESHOLD,
                            unit: str = "") -> list[Anomaly]:
    """Compare each point with the mean and SD of the preceding `window` points.

    The window is shifted by one so the point being tested never contributes to
    its own expectation - otherwise a large enough outlier hides itself.
    """
    values = series.dropna()
    if len(values) < window + 2:
        return []
    rolling_mean = values.rolling(window).mean().shift(1)
    rolling_sd = values.rolling(window).std(ddof=1).shift(1)

    out = []
    for period in values.index:
        actual, mu, sd = values[period], rolling_mean.get(period), rolling_sd.get(period)
        if pd.isna(mu) or pd.isna(sd) or sd == 0:
            continue
        z = (actual - mu) / sd
        if abs(z) < threshold:
            continue
        out.append(Anomaly(
            period=str(period)[:10], scope=scope, metric=metric,
            method=f"Rolling z-score ({window}-period trailing window, |z| > {threshold})",
            actual=round(float(actual), 2), expected=round(float(mu), 2),
            expected_low=round(float(mu - threshold * sd), 2),
            expected_high=round(float(mu + threshold * sd), 2),
            deviation=round(float(actual - mu), 2),
            deviation_pct=round(float((actual - mu) / mu * 100), 2) if mu else np.nan,
            score=round(float(z), 2),
            severity=_severity(z, (actual - mu) / mu * 100 if mu else None),
            material=_is_material((actual - mu) / mu * 100 if mu else None),
            interpretation=(
                f"{metric} came in at {_fmt(actual)}{unit} against a trailing "
                f"{window}-month expectation of {_fmt(mu)}{unit} "
                f"({(actual - mu) / mu * 100:+.1f}%). Because the benchmark is "
                f"recent history rather than the whole series, this detects a "
                f"break from the current regime - a level shift or a sudden stop."),
        ))
    return out


def seasonal_residual_detector(monthly: pd.DataFrame, value_col: str, metric: str,
                               scope: str = "Company-wide",
                               threshold: float = 2.5, unit: str = "") -> list[Anomaly]:
    """Flag months whose value is unusual after removing trend and seasonality.

    This is the detector that earns its keep on financial data: a 35% fall in
    February is normal here, and only the residual says whether *this*
    February was abnormal.
    """
    series = monthly.set_index("month_start")[value_col].asfreq("MS").dropna()
    if len(series) < 24:  # STL needs two full seasonal cycles
        return []

    stl = fit_stl(series)
    resid = pd.Series(stl.resid, index=series.index)
    expected = np.exp(stl.trend + stl.seasonal)

    # Robust scale: MAD is not dragged around by the very outliers being hunted.
    # The floor matters - if the decomposition ever fits the series too closely
    # the MAD collapses toward zero and every residual looks infinitely
    # significant, so fall back to the standard deviation.
    mad = float(np.median(np.abs(resid - np.median(resid))))
    scale = mad * 1.4826
    if not np.isfinite(scale) or scale < 1e-4:
        scale = float(resid.std(ddof=1))
    if not np.isfinite(scale) or scale <= 0:
        return []

    out = []
    for period, r in resid.items():
        z = float(r / scale)
        if abs(z) < threshold:
            continue
        actual = float(series[period])
        exp = float(expected[period])
        band = float(np.exp(np.log(exp) + threshold * scale) - exp)
        out.append(Anomaly(
            period=str(period.date()), scope=scope, metric=metric,
            method=f"Seasonal-residual z-score (STL, robust MAD scale, |z| > {threshold})",
            actual=round(actual, 2), expected=round(exp, 2),
            expected_low=round(exp - band, 2), expected_high=round(exp + band, 2),
            deviation=round(actual - exp, 2),
            deviation_pct=round((actual - exp) / exp * 100, 2),
            score=round(z, 2),
            severity=_severity(z, (actual - exp) / exp * 100),
            material=_is_material((actual - exp) / exp * 100),
            interpretation=(
                f"After stripping out the growth trend and the normal seasonal "
                f"pattern, {metric} for this month was {_fmt(actual)}{unit} against "
                f"a seasonally adjusted expectation of {_fmt(exp)}{unit} "
                f"({(actual - exp) / exp * 100:+.1f}%). Seasonality is already "
                f"accounted for, so this is a genuine break rather than a calendar "
                f"effect."),
        ))
    return out


def iqr_detector(values: pd.Series, metric: str, scope: str,
                 k: float = config.IQR_MULTIPLIER, log_scale: bool = True,
                 unit: str = "") -> tuple[list[Anomaly], dict]:
    """Tukey fences on transaction-level values.

    Transaction values are lognormal, so the fences are computed on the log
    scale; applied to raw currency they would classify a quarter of ordinary
    large orders as outliers.  Returns a summary plus only the most extreme
    individual cases, because a list of 3,000 flags is not actionable.
    """
    x = values.dropna()
    x = x[x > 0] if log_scale else x
    if len(x) < 20:
        return [], {}

    work = np.log(x) if log_scale else x
    q1, q3 = np.percentile(work, [25, 75])
    iqr = q3 - q1
    lo_fence, hi_fence = q1 - k * iqr, q3 + k * iqr

    flagged = x[(work < lo_fence) | (work > hi_fence)]
    lo_value = float(np.exp(lo_fence) if log_scale else lo_fence)
    hi_value = float(np.exp(hi_fence) if log_scale else hi_fence)
    median = float(x.median())

    summary = {
        "metric": metric, "scope": scope,
        "method": f"Tukey IQR fences (k={k}){' on log scale' if log_scale else ''}",
        "n_evaluated": int(len(x)), "n_flagged": int(len(flagged)),
        "pct_flagged": round(len(flagged) / len(x) * 100, 2),
        "lower_fence": round(lo_value, 2), "upper_fence": round(hi_value, 2),
        "median": round(median, 2),
        "flagged_value_total": round(float(flagged.sum()), 2),
    }

    out = []
    for idx, actual in flagged.nlargest(10).items():
        distance = (np.log(actual) - hi_fence) / iqr if log_scale else (actual - hi_fence) / iqr
        out.append(Anomaly(
            period=str(idx), scope=scope, metric=metric,
            method=summary["method"], actual=round(float(actual), 2),
            expected=round(median, 2), expected_low=round(lo_value, 2),
            expected_high=round(hi_value, 2),
            deviation=round(float(actual - median), 2),
            deviation_pct=round(float((actual - median) / median * 100), 2),
            score=round(float(3.0 + distance), 2),
            severity=_severity(3.0 + distance, (actual - median) / median * 100),
            material=_is_material((actual - median) / median * 100),
            interpretation=(
                f"Transaction {idx} recorded {metric} of {_fmt(actual)}{unit}, above "
                f"the upper Tukey fence of {_fmt(hi_value)}{unit} (median "
                f"{_fmt(median)}{unit}). Worth confirming as a genuine bulk order "
                f"rather than a keying error before it distorts the averages."),
        ))
    return out, summary


# --------------------------------------------------------------------------
# Application to the business metrics
# --------------------------------------------------------------------------
def detect_monthly_anomalies(monthly: pd.DataFrame) -> list[Anomaly]:
    """Run the time-series detectors over the headline monthly metrics."""
    m = monthly.set_index("month_start")
    found: list[Anomaly] = []

    specs = [
        ("revenue", "Monthly revenue", ""),
        ("profit", "Monthly profit", ""),
        ("profit_margin_pct", "Profit margin", "%"),
        ("cost_to_revenue_pct", "Cost-to-revenue ratio", "%"),
        ("discount_rate_pct", "Discount rate", "%"),
        ("avg_order_value", "Average order value", ""),
        ("transactions", "Transaction volume", ""),
    ]
    for col, label, unit in specs:
        found += rolling_zscore_detector(m[col], label, unit=unit)
        found += zscore_detector(m[col], label, unit=unit)

    # Seasonal adjustment only makes sense for the volume-driven series.
    for col, label, unit in [("revenue", "Monthly revenue", ""),
                             ("profit", "Monthly profit", ""),
                             ("transactions", "Transaction volume", "")]:
        found += seasonal_residual_detector(monthly, col, label, unit=unit)

    return found


def detect_category_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    """Per-category margin and discount monitoring.

    A category-level shock can be invisible in the company total - the Hardware
    cost spike moves the group margin by two points but the Hardware margin by
    twenty - so each category is monitored against its own history.
    """
    found: list[Anomaly] = []
    grouped = (df.groupby(["product_category", "month_start"])
                 .agg(revenue=("revenue", "sum"), profit=("profit", "sum"),
                      gross_revenue=("gross_revenue", "sum"),
                      discount_amount=("discount_amount", "sum"))
                 .reset_index())
    grouped["margin_pct"] = grouped.profit / grouped.revenue * 100
    grouped["discount_rate_pct"] = grouped.discount_amount / grouped.gross_revenue * 100

    for category, sub in grouped.groupby("product_category"):
        s = sub.set_index("month_start").sort_index()
        found += rolling_zscore_detector(s["margin_pct"], "Category profit margin",
                                         scope=f"Category: {category}", unit="%")
        found += rolling_zscore_detector(s["discount_rate_pct"], "Category discount rate",
                                         scope=f"Category: {category}", unit="%")
    return found


def detect_region_anomalies(df: pd.DataFrame) -> list[Anomaly]:
    found: list[Anomaly] = []
    grouped = (df[df.region != "Unknown"]
               .groupby(["region", "month_start"])
               .agg(revenue=("revenue", "sum"), profit=("profit", "sum"),
                    gross_revenue=("gross_revenue", "sum"),
                    discount_amount=("discount_amount", "sum"))
               .reset_index())
    grouped["discount_rate_pct"] = grouped.discount_amount / grouped.gross_revenue * 100
    grouped["margin_pct"] = grouped.profit / grouped.revenue * 100

    for region, sub in grouped.groupby("region"):
        s = sub.set_index("month_start").sort_index()
        found += rolling_zscore_detector(s["discount_rate_pct"], "Regional discount rate",
                                         scope=f"Region: {region}", unit="%")
        found += rolling_zscore_detector(s["revenue"], "Regional revenue",
                                         scope=f"Region: {region}")
    return found


def detect_expense_anomalies() -> list[Anomaly]:
    """Monitor the operating cost lines and marketing spend."""
    found: list[Anomaly] = []

    opex = pd.read_csv(config.RAW_OPEX, parse_dates=["month"])
    for category, sub in opex.groupby("expense_category"):
        s = sub.set_index("month").sort_index()["amount"]
        found += rolling_zscore_detector(s, "Operating expense",
                                         scope=f"Expense: {category}")

    marketing = pd.read_csv(config.RAW_MARKETING, parse_dates=["month"])
    total = marketing.groupby("month")["spend"].sum().sort_index()
    found += rolling_zscore_detector(total, "Marketing spend", scope="Marketing (all regions)")

    # Spend as a share of revenue: catches overspend that a raw-spend test
    # would excuse as "we were growing".
    txns = load_clean()
    revenue = txns.groupby("month_start")["revenue"].sum().sort_index()
    ratio = (total / revenue * 100).dropna()
    found += rolling_zscore_detector(ratio, "Marketing spend as % of revenue",
                                     scope="Marketing efficiency", unit="%")
    return found


def detect_transaction_anomalies(df: pd.DataFrame) -> tuple[list[Anomaly], list[dict]]:
    found: list[Anomaly] = []
    summaries: list[dict] = []

    indexed = df.set_index("transaction_id")
    a, s = iqr_detector(indexed["revenue"], "Transaction revenue", "All transactions")
    found += a
    summaries.append(s)

    a, s = iqr_detector(indexed["quantity"], "Transaction quantity", "All transactions")
    found += a
    summaries.append(s)

    # Margin is already a bounded percentage, so no log transform.
    a, s = iqr_detector(indexed["profit_margin_pct"], "Transaction profit margin",
                        "All transactions", log_scale=False, unit="%")
    found += a
    summaries.append(s)

    for category, sub in df.groupby("product_category"):
        _, s = iqr_detector(sub.set_index("transaction_id")["revenue"],
                            "Transaction revenue", f"Category: {category}")
        if s:
            summaries.append(s)
    return found, summaries


# --------------------------------------------------------------------------
# Scoring against ground truth
# --------------------------------------------------------------------------
def score_against_ground_truth(anomalies: list[Anomaly]) -> dict:
    """Check which injected events the detectors actually recovered.

    The generator wrote every event it introduced to _injected_events.json.
    Comparing against it turns "the detector found some anomalies" into a
    measurable recall, and makes a missed event visible instead of invisible.
    """
    if not config.INJECTED_EVENTS.exists():
        return {"available": False,
                "note": "Ground-truth file not found; run src.generate_data first."}

    truth = json.loads(config.INJECTED_EVENTS.read_text())["events"]
    frame = pd.DataFrame([a.to_dict() for a in anomalies])
    frame["period_ts"] = pd.to_datetime(frame["period"], errors="coerce")

    results, recovered = [], 0
    for event in truth:
        start = pd.Timestamp(event["start"])
        end = pd.Timestamp(event["end"])
        scope_value = next(iter(event["scope"].values()), None)

        # A monthly flag is stamped at the month start, so widen the window by
        # a month at each end to avoid an off-by-one miss.
        in_window = frame["period_ts"].between(start - pd.Timedelta(days=31),
                                               end + pd.Timedelta(days=31))
        matches = frame[in_window]
        if scope_value:
            matches = matches[matches["scope"].str.contains(scope_value, case=False,
                                                            regex=False)
                              | matches["scope"].eq("Company-wide")]

        # The quantity-outlier event is transaction-level, not dated monthly.
        if event["kind"] == "outlier_transactions":
            matches = frame[frame["metric"].str.contains("quantity", case=False)]

        found = len(matches) > 0
        recovered += int(found)
        results.append({
            "event_id": event["event_id"], "kind": event["kind"],
            "window": f"{event['start']} to {event['end']}",
            "scope": event["scope"] or "company-wide",
            "description": event["description"],
            "detected": found,
            "n_matching_flags": int(len(matches)),
            "example_flags": matches.nlargest(3, "score", keep="first")[
                ["period", "scope", "metric", "method", "score", "severity"]
            ].to_dict("records") if found else [],
        })

    return {
        "available": True,
        "events_injected": len(truth),
        "events_recovered": recovered,
        "recall_pct": round(recovered / len(truth) * 100, 1),
        "events": results,
        "note": ("Recall is measured against events the data generator recorded when "
                 "it created the dataset. Precision is deliberately not reported: "
                 "flags outside the injected windows are not necessarily false - "
                 "ordinary business volatility produces real outliers too."),
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_all(df: pd.DataFrame | None = None, verbose: bool = True) -> dict:
    df = load_clean() if df is None else df
    monthly = build_monthly(df)

    if verbose:
        print("Scanning monthly metrics ...")
    anomalies = detect_monthly_anomalies(monthly)

    if verbose:
        print("Scanning categories and regions ...")
    anomalies += detect_category_anomalies(df)
    anomalies += detect_region_anomalies(df)

    if verbose:
        print("Scanning operating expenses and marketing ...")
    anomalies += detect_expense_anomalies()

    if verbose:
        print("Scanning transaction-level distributions ...")
    txn_anomalies, distribution_summaries = detect_transaction_anomalies(df)
    anomalies += txn_anomalies

    frame = pd.DataFrame([a.to_dict() for a in anomalies])
    severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    frame["severity_rank"] = frame["severity"].map(severity_order)
    frame = (frame.sort_values(["severity_rank", "score"],
                               key=lambda s: s if s.name == "severity_rank" else s.abs(),
                               ascending=[True, False])
                  .drop(columns="severity_rank")
                  .reset_index(drop=True))
    frame.to_csv(ANOMALY_CSV, index=False)

    if verbose:
        print("Scoring against injected ground truth ...")
    scoring = score_against_ground_truth(anomalies)

    results = {
        "thresholds": {"z_threshold": config.Z_THRESHOLD,
                       "iqr_multiplier": config.IQR_MULTIPLIER,
                       "seasonal_residual_threshold": 2.5},
        "total_anomalies": len(frame),
        "by_severity": frame["severity"].value_counts().to_dict(),
        "material_flags": int(frame["material"].sum()),
        "immaterial_flags": int((~frame["material"]).sum()),
        "by_method": frame["method"].value_counts().to_dict(),
        "by_metric": frame["metric"].value_counts().to_dict(),
        "top_anomalies": frame.head(30).to_dict("records"),
        "distribution_summaries": distribution_summaries,
        "ground_truth_scoring": scoring,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))

    if verbose:
        _print_summary(results, frame)
        print(f"\nWritten: {ANOMALY_CSV.name}, {RESULTS_PATH.name}")
    return results


def _print_summary(r: dict, frame: pd.DataFrame) -> None:
    print("\n" + "=" * 92)
    print(f"ANOMALY DETECTION - {r['total_anomalies']} flags")
    print("=" * 92)
    print("  By severity: " + ", ".join(f"{k}={v}" for k, v in r["by_severity"].items()))
    print(f"  Material (moved at least {config.MIN_MATERIAL_DEVIATION_PCT:.0f}%): "
          f"{r['material_flags']}   below materiality floor: {r['immaterial_flags']}")

    print("\nTOP 15 ANOMALIES")
    print("-" * 92)
    for row in r["top_anomalies"][:15]:
        print(f"  {row['period']}  {row['severity']:<9} z={row['score']:>7.2f}  "
              f"{row['scope']:<30} {row['metric']}")
        print(f"      actual {_fmt(row['actual'])}  vs expected {_fmt(row['expected'])} "
              f"[{_fmt(row['expected_low'])}, {_fmt(row['expected_high'])}]  "
              f"({row['deviation_pct']:+.1f}%)")

    s = r["ground_truth_scoring"]
    if s.get("available"):
        print("\n" + "=" * 92)
        print(f"GROUND-TRUTH RECALL: {s['events_recovered']}/{s['events_injected']} "
              f"injected events recovered ({s['recall_pct']}%)")
        print("=" * 92)
        for e in s["events"]:
            mark = "FOUND  " if e["detected"] else "MISSED "
            print(f"  [{mark}] {e['event_id']} {e['kind']:<22} {e['window']:<26} "
                  f"{e['n_matching_flags']:>3} flags")


if __name__ == "__main__":
    run_all()
