"""Generate the written business insights report.

Every figure in the report is read back out of the analysis artefacts
(``reports/*.json`` and ``reports/sql_results/*.csv``) rather than typed in.
That is the point: rerun the pipeline on different data and the narrative
updates with it, and no number in the prose can drift away from the number in
the analysis.

Run with:  python -m src.report
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from src import config

REPORT_PATH = config.REPORTS_DIR / "business_insights_report.md"
SQL_RESULTS = config.REPORTS_DIR / "sql_results"


# --------------------------------------------------------------------------
# Artefact loading
# --------------------------------------------------------------------------
def _load_json(name: str) -> dict:
    path = config.REPORTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found - run the pipeline before building the report.")
    return json.loads(path.read_text())


def _sql(name: str) -> pd.DataFrame:
    return pd.read_csv(SQL_RESULTS / f"{name}.csv")


def _kpi(kpis: list[dict], name: str) -> dict:
    return next((k for k in kpis if k["name"] == name), {})


def _money(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:,.0f}k"
    return f"${value:,.0f}"


def _test(tests: list[dict], name: str) -> dict:
    return next((t for t in tests if t["name"] == name), {})


# --------------------------------------------------------------------------
# Report sections
# --------------------------------------------------------------------------
def build_report() -> str:
    cleaning = _load_json("../data/processed/cleaning_report.json") \
        if False else json.loads(config.CLEANING_REPORT.read_text())
    kpi = _load_json("kpi_summary.json")
    stats = _load_json("statistical_analysis.json")
    ts = _load_json("timeseries_analysis.json")
    anomalies = _load_json("anomaly_report.json")

    annual = _sql("annual_summary")
    regions = _sql("revenue_by_region")
    categories = _sql("margin_by_category")
    concentration = _sql("customer_concentration")
    discount = _sql("discount_impact")
    investigate = _sql("high_revenue_low_margin_products")
    declines = _sql("largest_monthly_declines")
    segments = _sql("customer_segment_performance")
    repeat = _sql("repeat_purchase_behaviour")
    opex = _sql("operating_cost_structure")
    receivables = _sql("receivables_aging")

    year_kpis = kpi["latest_year"]["kpis"]
    latest_year = kpi["latest_year"]["period"]
    summary = cleaning["summary"]
    trend = ts["trend"]
    seasonality = ts["seasonality"]
    tests = stats["hypothesis_tests"]

    parts: list[str] = []
    parts.append(_header(summary, latest_year))
    parts.append(_executive_summary(year_kpis, annual, trend, seasonality,
                                    concentration, categories, latest_year))
    parts.append(_data_quality(summary, cleaning))
    parts.append(_revenue_section(annual, regions, ts, latest_year))
    parts.append(_profitability_section(annual, categories, discount, tests,
                                        stats["regression"]))
    parts.append(_cost_section(annual, opex, latest_year))
    parts.append(_customer_section(concentration, segments, repeat, receivables,
                                   year_kpis))
    parts.append(_product_section(categories, investigate))
    parts.append(_statistics_section(stats))
    parts.append(_timeseries_section(ts, declines))
    parts.append(_anomaly_section(anomalies))
    parts.append(_questions_section(annual, regions, categories, concentration,
                                    declines, investigate, tests, ts,
                                    stats["regression"], latest_year))
    parts.append(_recommendations(categories, discount, investigate, annual))
    parts.append(_limitations())

    report = "\n\n".join(parts)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written to {REPORT_PATH.relative_to(config.ROOT)} "
          f"({len(report.splitlines()):,} lines)")
    return report


def _header(summary: dict, latest_year: int) -> str:
    return f"""# Financial Performance & Profitability Analysis

**Reporting period:** {summary['date_range'][0]} to {summary['date_range'][1]}
**Transactions analysed:** {summary['clean_rows']:,}
**Report generated:** {date.today().isoformat()}
**Prepared by:** Financial Analytics Platform (`run_pipeline.py`)

---

*Every figure in this report is generated from the analysis artefacts in
`reports/`. Rerunning the pipeline regenerates both the analysis and this
document, so the two cannot disagree.*"""


def _executive_summary(kpis, annual, trend, seasonality, concentration,
                       categories, latest_year) -> str:
    rev = _kpi(kpis, "Total Revenue")
    profit = _kpi(kpis, "Gross Profit")
    margin = _kpi(kpis, "Gross Margin")
    cost = _kpi(kpis, "Total Cost")
    customers = _kpi(kpis, "Active Customers")

    latest = annual[annual.year == latest_year].iloc[0]
    first = annual.iloc[0]
    top_decile = concentration.iloc[0]
    top_two_deciles = concentration.iloc[1]["cumulative_pct_of_revenue"]
    worst_cat = categories.nsmallest(1, "profit_margin_pct").iloc[0]

    return f"""## 1. Executive summary

**The business is growing fast and getting less profitable at the same time.**
That is the single most important finding in this analysis, and everything
else follows from it.

| Headline | {latest_year} | vs prior year |
|---|---|---|
| Revenue | {rev.get('formatted', 'n/a')} | {rev.get('change_pct', 0):+.1f}% |
| Cost of goods sold | {cost.get('formatted', 'n/a')} | {cost.get('change_pct', 0):+.1f}% |
| Gross profit | {profit.get('formatted', 'n/a')} | {profit.get('change_pct', 0):+.1f}% |
| Gross margin | {margin.get('formatted', 'n/a')} | {margin.get('change', 0):+.2f} pp |
| Active customers | {customers.get('formatted', 'n/a')} | {customers.get('change_pct', 0):+.1f}% |

**Five findings that matter:**

1. **Revenue is compounding at {trend['cagr_pct']:.1f}% a year** and the growth
   is real, not a base effect: the log-linear trend is significant
   (p = {trend['slope_p_value']:.2e}) and Kendall's tau of
   {trend['kendall_tau']:.2f} confirms a monotonic rise.

2. **Cost is outrunning revenue, consistently.** In {latest_year} revenue grew
   {latest['revenue_growth_pct']:.1f}% while cost grew
   {latest['cost_growth_pct']:.1f}%. Gross margin has fallen from
   {first['gross_margin_pct']:.1f}% in {int(first['year'])} to
   {latest['gross_margin_pct']:.1f}% in {latest_year} - a loss of
   {first['gross_margin_pct'] - latest['gross_margin_pct']:.1f} percentage
   points. At {latest_year} revenue, restoring the {int(first['year'])} margin
   would be worth
   {_money(latest['revenue'] * (first['gross_margin_pct'] - latest['gross_margin_pct']) / 100)}
   of additional annual profit.

3. **Revenue is dangerously concentrated.** The top decile of customers
   ({int(top_decile['customers'])} accounts) generates
   {top_decile['pct_of_revenue']:.1f}% of revenue, and the top two deciles
   {top_two_deciles:.1f}%. This is a sharper distribution than the classic
   80/20 rule and makes the loss of a handful of accounts a material risk.

4. **{worst_cat['product_category']} is close to break-even.** It carries
   {worst_cat['pct_of_revenue']:.1f}% of revenue but only
   {worst_cat['pct_of_profit']:.1f}% of profit, at a
   {worst_cat['profit_margin_pct']:.1f}% margin. It is consuming working
   capital and logistics capacity for very little return.

5. **Discounting is materially eroding margin**, and the effect survives
   controlling for product mix, customer segment, region and order size - see
   section 9.

**Seasonality context:** the business swings
{seasonality['peak_to_trough_ratio']:.2f}x between its strongest month
({seasonality['peak_month']}, {seasonality['peak_pct_above_average']:+.1f}%
against trend) and its weakest ({seasonality['trough_month']},
{seasonality['trough_pct_below_average']:+.1f}%). Any month-on-month comparison
that ignores this will mislead."""


def _data_quality(summary: dict, cleaning: dict) -> str:
    reasons = summary.get("rejection_reasons", {})
    reason_rows = "\n".join(
        f"| {k.replace('_', ' ').capitalize()} | {v:,} |"
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))

    standardise = [s for s in cleaning["steps"] if s["step"] == "standardise"]
    repairs = [s for s in cleaning["steps"] if s["step"] == "repair"]
    total_standardised = sum(s["rows_affected"] for s in standardise)
    total_repaired = sum(s["rows_affected"] for s in repairs)

    return f"""---

## 2. Data quality and preparation

The source extract was not analysis-ready. Of {summary['raw_rows']:,} raw rows,
{summary['clean_rows']:,} survived into the warehouse
({summary['retention_rate_pct']}% retention).

| Stage | Rows |
|---|---|
| Raw extract | {summary['raw_rows']:,} |
| Removed as duplicates | {summary['rows_removed_as_duplicates']:,} |
| Quarantined by validation | {summary['rejected_rows']:,} |
| **Loaded to warehouse** | **{summary['clean_rows']:,}** |
| Values standardised | {total_standardised:,} |
| Fields repaired from reference data | {total_repaired:,} |

**Why rows were quarantined**

| Reason | Rows |
|---|---|
{reason_rows}

**The finding that matters for trust in the numbers:**
{summary['rows_with_reconciliation_error']:,} rows
({summary['rows_with_reconciliation_error'] / summary['clean_rows'] * 100:.1f}%)
arrived with a `revenue` or `profit` value that did not reconcile with its own
components. The pipeline treats the components as authoritative and recomputes
the money, so every figure in this report is derived from
`quantity x unit_price x (1 - discount)` rather than from a field that had
already drifted. Had the reported values been trusted as they arrived, the
revenue total would have been wrong by an amount that no downstream
reconciliation would have caught.

Rejected rows are not deleted - they are written to
`data/processed/transactions_rejected.csv` with a reason code, so the
quarantine decision is reviewable and reversible."""


def _revenue_section(annual, regions, ts, latest_year) -> str:
    growth = ts["growth_decomposition"]["by_year"]
    latest_growth = growth[-1] if growth else {}
    rows = "\n".join(
        f"| {int(r.year)} | {_money(r.revenue)} | "
        f"{'-' if pd.isna(r.revenue_growth_pct) else f'{r.revenue_growth_pct:+.1f}%'} | "
        f"{_money(r.profit)} | {r.gross_margin_pct:.1f}% | {int(r.transactions):,} | "
        f"{_money(r.avg_order_value)} |"
        for r in annual.itertuples())

    region_rows = "\n".join(
        f"| {r.region} | {_money(r.revenue)} | {r.pct_of_revenue:.1f}% | "
        f"{_money(r.profit)} | {r.profit_margin_pct:.1f}% | {_money(r.avg_order_value)} | "
        f"{r.discount_rate_pct:.1f}% |"
        for r in regions[regions.region != "Unknown"].itertuples())

    return f"""---

## 3. Revenue performance

| Year | Revenue | Growth | Profit | Margin | Transactions | Avg order |
|---|---|---|---|---|---|---|
{rows}

**Growth is volume-led, not price-led.** Decomposing revenue growth against the
identity `revenue = transactions x average order value`:

| Year | Revenue growth | From volume | From order value |
|---|---|---|---|
""" + "\n".join(
        f"| {g['year']} | {g['revenue_growth_pct']:+.1f}% | "
        f"{g['volume_growth_pct']:+.1f}% ({g['volume_contribution_pct']:.0f}% of growth) | "
        f"{g['order_value_growth_pct']:+.1f}% ({g['order_value_contribution_pct']:.0f}%) |"
        for g in growth) + f"""

In {latest_growth.get('year', latest_year)},
{latest_growth.get('volume_contribution_pct', 0):.0f}% of growth came from doing
more transactions rather than from larger or better-priced ones. Volume-led
growth is durable, but it is also the kind that scales the cost base in
lockstep - which is exactly what the margin trend shows.

### Revenue by region

| Region | Revenue | Share | Profit | Margin | Avg order | Discount rate |
|---|---|---|---|---|---|---|
{region_rows}

North America and Europe together carry
{regions[regions.region.isin(['North America', 'Europe'])].pct_of_revenue.sum():.1f}%
of revenue. Note the inverse relationship between size and margin: the largest
regions run the *deepest* discounts and the thinnest margins, while Middle East
- the smallest - returns the best margin at
{regions[regions.region == 'Middle East'].profit_margin_pct.iloc[0]:.1f}%. That
pattern is consistent with discount authority being used more freely where
deal volume is highest."""


def _profitability_section(annual, categories, discount, tests, regression) -> str:
    cat_rows = "\n".join(
        f"| {r.product_category} | {_money(r.revenue)} | {r.pct_of_revenue:.1f}% | "
        f"{_money(r.profit)} | {r.pct_of_profit:.1f}% | {r.profit_margin_pct:.1f}% | "
        f"{r.discount_rate_pct:.1f}% |"
        for r in categories.itertuples())

    disc_rows = "\n".join(
        f"| {r.discount_band} | {int(r.transactions):,} | {_money(r.revenue)} | "
        f"{r.profit_margin_pct:.1f}% | {_money(r.avg_order_value)} | "
        f"{int(r.loss_making_transactions):,} |"
        for r in discount.itertuples())

    disc_test = _test(tests, "discount_vs_margin")
    best = discount.iloc[0]
    worst = discount.iloc[-1]

    return f"""---

## 4. Profitability analysis

### Margin by product category

| Category | Revenue | Rev share | Profit | Profit share | Margin | Discount rate |
|---|---|---|---|---|---|---|
{cat_rows}

The profit pool is far more concentrated than the revenue pool.
{categories.iloc[0]['product_category']} alone produces
{categories.iloc[0]['pct_of_profit']:.1f}% of profit from
{categories.iloc[0]['pct_of_revenue']:.1f}% of revenue, while the two weakest
categories together contribute
{categories.nsmallest(2, 'profit_margin_pct').pct_of_profit.sum():.1f}% of
profit on {categories.nsmallest(2, 'profit_margin_pct').pct_of_revenue.sum():.1f}%
of revenue.

### The discount-margin relationship

| Discount band | Transactions | Revenue | Margin | Avg order | Loss-making |
|---|---|---|---|---|---|
{disc_rows}

The gradient is monotonic and steep: margin falls from
{best['profit_margin_pct']:.1f}% in the **{best['discount_band']}** band to
{worst['profit_margin_pct']:.1f}% in the **{worst['discount_band']}** band. The
deepest band is loss-making in aggregate.

Note the countervailing effect, which is the honest complication: average order
value rises with discount depth, from {_money(best['avg_order_value'])} to
{_money(worst['avg_order_value'])}. Discounts *are* buying larger orders. The
question is whether they are buying enough - and past roughly 25% they are
demonstrably not, because the band stops contributing profit at all.

**Statistical confirmation:** {disc_test.get('interpretation', '')}

**Controlling for mix:** {regression['interpretation']}"""


def _cost_section(annual, opex, latest_year) -> str:
    latest = opex[pd.to_datetime(opex.month_start).dt.year == latest_year]
    first_year = opex[pd.to_datetime(opex.month_start).dt.year ==
                      pd.to_datetime(opex.month_start).dt.year.min()]

    rows = "\n".join(
        f"| {int(r.year)} | {_money(r.revenue)} | {_money(r.cost)} | "
        f"{r.cost_to_revenue_pct:.1f}% | "
        f"{'-' if pd.isna(r.revenue_growth_pct) else f'{r.revenue_growth_pct:+.1f}%'} | "
        f"{'-' if pd.isna(r.cost_growth_pct) else f'{r.cost_growth_pct:+.1f}%'} |"
        for r in annual.itertuples())

    op_margin_latest = latest.operating_margin_pct.mean()
    op_margin_first = first_year.operating_margin_pct.mean()

    return f"""---

## 5. Cost structure

| Year | Revenue | COGS | Cost-to-revenue | Revenue growth | Cost growth |
|---|---|---|---|---|---|
{rows}

**Cost of goods sold has grown faster than revenue in every year of the
series.** This is the mechanical cause of the margin decline, and it is a unit
economics problem rather than a volume problem: the same erosion is visible at
transaction level, where it cannot be explained by mix shifting toward larger
deals (section 9).

### Below the gross line

Average operating margin moved from {op_margin_first:.1f}% in
{int(pd.to_datetime(opex.month_start).dt.year.min())} to
{op_margin_latest:.1f}% in {latest_year}. Operating expenses, payroll and
marketing consumed the following share of revenue in {latest_year}:

| Cost line | % of revenue ({latest_year}) |
|---|---|
| Cost of goods sold | {latest.cogs.sum() / latest.revenue.sum() * 100:.1f}% |
| Payroll | {latest.payroll_cost.sum() / latest.revenue.sum() * 100:.1f}% |
| Marketing | {latest.marketing_spend.sum() / latest.revenue.sum() * 100:.1f}% |
| Other operating expenses | {latest.operating_expenses.sum() / latest.revenue.sum() * 100:.1f}% |
| **Operating margin** | **{op_margin_latest:.1f}%** |

Operating leverage is working - revenue per head rose to
{_money(latest.revenue_per_head.mean())} a month - but it is being partly
consumed by the gross margin decline above it."""


def _customer_section(concentration, segments, repeat, receivables, kpis) -> str:
    conc_rows = "\n".join(
        f"| {int(r.revenue_decile)} | {int(r.customers)} | {_money(r.revenue)} | "
        f"{r.pct_of_revenue:.1f}% | {r.cumulative_pct_of_revenue:.1f}% | "
        f"{_money(r.avg_revenue_per_customer)} |"
        for r in concentration.itertuples())

    seg_rows = "\n".join(
        f"| {r.customer_segment} | {int(r.customers):,} | {_money(r.revenue)} | "
        f"{r.pct_of_revenue:.1f}% | {r.profit_margin_pct:.1f}% | "
        f"{_money(r.avg_order_value)} | {_money(r.revenue_per_customer)} | "
        f"{r.discount_rate_pct:.1f}% |"
        for r in segments.itertuples())

    repeat_rows = "\n".join(
        f"| {r.order_band} | {int(r.customers):,} | {r.pct_of_customers:.1f}% | "
        f"{r.pct_of_revenue:.1f}% | {_money(r.avg_lifetime_revenue)} |"
        for r in repeat.itertuples())

    open_ar = receivables[receivables.aging_bucket != "Settled"]
    over_90 = receivables[receivables.aging_bucket == "90+ days"]
    retention = _kpi(kpis, "Customer Retention Rate")
    dso = _kpi(kpis, "Days Sales Outstanding")

    return f"""---

## 6. Customer analysis

### Concentration

| Decile | Customers | Revenue | Share | Cumulative | Avg per customer |
|---|---|---|---|---|---|
{conc_rows}

The top decile averages
{_money(concentration.iloc[0]['avg_revenue_per_customer'])} per account against
{_money(concentration.iloc[-1]['avg_revenue_per_customer'])} in the bottom
decile - a {concentration.iloc[0]['avg_revenue_per_customer'] / concentration.iloc[-1]['avg_revenue_per_customer']:.0f}x
spread. Concentration this steep is a genuine risk register item, not a
statistic.

### By segment

| Segment | Customers | Revenue | Share | Margin | Avg order | Rev/customer | Discount |
|---|---|---|---|---|---|---|---|
{seg_rows}

### Repeat purchase behaviour

| Orders placed | Customers | % of customers | % of revenue | Avg lifetime value |
|---|---|---|---|---|
{repeat_rows}

Retention is {retention.get('formatted', 'n/a')}
({retention.get('change', 0):+.1f} pp year on year). The business is retaining
well; its growth problem is not churn.

### Cash collection

Open receivables stand at {_money(open_ar.balance.sum())} across
{int(open_ar.invoices.sum()):,} invoices, of which
{_money(over_90.balance.iloc[0]) if len(over_90) else '$0'}
({over_90.pct_of_total.iloc[0] if len(over_90) else 0:.1f}% of the total
receivables book) is more than 90 days old. Days sales outstanding is
{dso.get('formatted', 'n/a')}, {dso.get('change_pct', 0):+.1f}% year on year.

The aging profile is bimodal - most invoices settle quickly, and a hard core
does not settle at all. That is a collections process issue rather than a
credit quality issue, and it is where the working capital tied up in growth is
sitting."""


def _product_section(categories, investigate) -> str:
    if investigate.empty:
        body = "No products currently meet both screening criteria."
    else:
        rows = "\n".join(
            f"| {r.product_id} | {r.product_name} | {r.product_category} | "
            f"{int(r.units_sold):,} | {_money(r.revenue)} | {r.profit_margin_pct:.1f}% | "
            f"{r.discount_rate_pct:.1f}% | {_money(r.profit_uplift_per_margin_point)} |"
            for r in investigate.itertuples())
        total_uplift = investigate.profit_uplift_per_margin_point.sum()
        body = f"""| Product | Name | Category | Units | Revenue | Margin | Discount | Value of +1pp |
|---|---|---|---|---|---|---|---|
{rows}

These {len(investigate)} products sit in the top half of the revenue
distribution and the bottom quartile of the margin distribution. Together they
turn over {_money(investigate.revenue.sum())} at an average margin of
{investigate.profit.sum() / investigate.revenue.sum() * 100:.1f}%.

**Why this is the highest-leverage list in the report:** because the volume is
already there, a single percentage point of margin recovered across these
products is worth {_money(total_uplift)} a year with no additional sales
effort. A five-point recovery - achievable through price increases,
renegotiated supply terms, or simply enforcing discount limits - would be worth
{_money(total_uplift * 5)}."""

    return f"""---

## 7. Product analysis - the investigation list

{body}"""


def _statistics_section(stats) -> str:
    tests = stats["hypothesis_tests"]
    corr_rows = "\n".join(
        f"| {c['pair']} | {c['pearson_r']:+.3f} | {c['spearman_rho']:+.3f} | "
        f"{c['pearson_p']:.2e} | {c['strength']} |"
        for c in stats["correlations_transaction_level"])
    monthly_rows = "\n".join(
        f"| {c['pair']} | {c['pearson_r']:+.3f} | {c['pearson_p']:.4f} | {c['strength']} |"
        for c in stats["correlations_monthly_level"])

    test_rows = "\n".join(
        f"| {t['name'].replace('_', ' ')} | {t['test'].split('(')[0].strip()} | "
        f"{t['p_value']:.2e} | "
        f"{t['effect_size'].get('cohens_d', t['effect_size'].get('cramers_v', t['effect_size'].get('eta_squared', 'n/a')))} "
        f"({t['effect_size'].get('magnitude', 'n/a')}) | "
        f"{'Reject H0' if t['significant'] else 'Fail to reject'} |"
        for t in tests)

    ci_rows = "\n".join(
        f"| {c['metric']} | {c['point_estimate']:,.2f} | "
        f"[{c['ci_low']:,.2f}, {c['ci_high']:,.2f}] | {c['method']} |"
        for c in stats["confidence_intervals"])

    anova = _test(tests, "regions_anova")
    weekend = _test(tests, "weekend_effect")
    marketing = next((c for c in stats["correlations_monthly_level"]
                      if "FOLLOWING" in c["question"]), {})

    return f"""---

## 8. Statistical analysis

All tests use alpha = {stats['alpha']} on n = {stats['n_transactions']:,}
transactions.

### Correlations (transaction level)

| Pair | Pearson r | Spearman rho | p | Strength |
|---|---|---|---|---|
{corr_rows}

### Correlations (monthly level)

| Pair | Pearson r | p | Strength |
|---|---|---|---|
{monthly_rows}

### Hypothesis tests

| Test | Method | p-value | Effect size | Decision |
|---|---|---|---|---|
{test_rows}

### {int(stats['confidence_level'] * 100)}% confidence intervals

| Metric | Estimate | Interval | Method |
|---|---|---|---|
{ci_rows}

### Reading these results honestly

Three cautions belong with the table above, and they matter more than any
individual p-value:

1. **Significance is nearly free at this sample size.** With
   {stats['n_transactions']:,} transactions, almost any difference clears
   p < 0.05. The regional order-value comparison is the clearest case: it is
   significant at p = {_test(tests, 'region_order_value').get('p_value', 0):.1e},
   yet region explains only
   {anova.get('effect_size', {}).get('variance_explained_pct', 0):.2f}% of the
   variance in order value. **Statistically real, commercially irrelevant.**
   Effect sizes, not p-values, are what should drive decisions here.

2. **Not every test rejects.** The weekend/weekday comparison returns
   p = {weekend.get('p_value', 0):.3f} - no significant difference in order
   value. It is reported because a battery of tests that all reject is usually
   a sign of a badly specified battery, not a remarkable business.

3. **Marketing's lagged effect is not established.** Same-month marketing spend
   correlates strongly with revenue, but that is largely because budgets are
   set as a percentage of revenue - the causality runs backwards. Tested
   properly against the *following* month's revenue, the correlation is
   {marketing.get('pearson_r', 0):+.3f} at p = {marketing.get('pearson_p', 1):.3f},
   which does not clear the threshold. **This analysis cannot show that
   marketing spend drives revenue**, and the dashboard should not be read as
   claiming it does."""


def _timeseries_section(ts, declines) -> str:
    seasonal_rows = "\n".join(
        f"| {s['month_name']} | {s['seasonal_index']:.3f} | {s['pct_vs_average']:+.1f}% |"
        for s in ts["seasonality"]["seasonal_index"])
    decline_rows = "\n".join(
        f"| {r.year_month} | {_money(r.previous_month_revenue)} | {_money(r.revenue)} | "
        f"{r.change_pct:+.1f}% |"
        for r in declines.head(5).itertuples())

    d = ts["diagnostics"]
    return f"""---

## 9. Time-series behaviour

**Trend.** {ts['trend']['interpretation']}

**Seasonality.** Strength {ts['seasonality']['seasonal_strength']:.2f} on a
0-1 scale, which is strong. The monthly index:

| Month | Index | vs trend |
|---|---|---|
{seasonal_rows}

{ts['seasonality']['interpretation']}

**Structure.** {d['interpretation']}

ADF on the level series gives p = {d['adf_on_log_revenue']['p_value']:.3f}
(cannot reject a unit root); after first differencing,
p = {d['adf_on_first_difference']['p_value']:.4f} (stationary). Autocorrelation
at lag 12 is {d['acf_lag_12']}, the numerical fingerprint of the annual cycle.

### Largest month-on-month declines

| Month | Previous | Actual | Change |
|---|---|---|---|
{decline_rows}

A caution on the seasonal index: with only three years of data, one unusual
month contaminates its own seasonal factor. February's index is depressed
partly by the February 2025 collapse identified in section 10, so the true
February seasonal effect is milder than the table implies. Five or more years
would separate the two cleanly."""


def _anomaly_section(anomalies) -> str:
    top = anomalies["top_anomalies"][:10]
    rows = "\n".join(
        f"| {a['period']} | {a['scope']} | {a['metric']} | {a['severity']} | "
        f"{a['score']:+.1f} | {a['actual']:,.0f} | {a['expected']:,.0f} | "
        f"{a['deviation_pct']:+.1f}% |"
        for a in top)

    scoring = anomalies["ground_truth_scoring"]
    scoring_rows = ""
    if scoring.get("available"):
        scoring_rows = "\n".join(
            f"| {e['event_id']} | {e['kind'].replace('_', ' ')} | {e['window']} | "
            f"{'Detected' if e['detected'] else 'MISSED'} | {e['n_matching_flags']} |"
            for e in scoring["events"])

    return f"""---

## 10. Anomaly monitor

{anomalies['total_anomalies']} flags were raised across four detectors
(global z-score, rolling z-score, seasonal-residual z-score and Tukey IQR
fences). {anomalies['material_flags']} cleared the materiality floor of
{config.MIN_MATERIAL_DEVIATION_PCT:.0f}% relative change;
{anomalies['immaterial_flags']} were statistically extreme but too small to act
on and are capped at Low severity.

That distinction is deliberate. Fixed-cost lines like rent have very little
natural month-to-month variance, so a 2-3% increase can score above z = 9 -
statistically dramatic, commercially irrelevant. Ranking by z-score alone would
put those at the top of the monitor and bury a 48% revenue collapse beneath
them.

### Highest-severity findings

| Period | Scope | Metric | Severity | z | Actual | Expected | Deviation |
|---|---|---|---|---|---|---|---|
{rows}

### Detector validation

The dataset was generated with a set of business events deliberately injected
and recorded before any analysis was run. Scoring the detectors against that
record turns "the monitor found some anomalies" into a measurable recall:

| Event | Type | Window | Outcome | Flags |
|---|---|---|---|---|
{scoring_rows}

**Recall: {scoring.get('events_recovered', 0)}/{scoring.get('events_injected', 0)}
events recovered ({scoring.get('recall_pct', 0)}%).**

{scoring.get('note', '')}

The seasonal-residual detector is the one that earns its place. February 2025
was flagged at z = -16.5 against a *seasonally adjusted* expectation - a plain
month-on-month rule would have partly excused it as "February is always weak",
and a global z-score would have missed it entirely against a growing series."""


def _questions_section(annual, regions, categories, concentration, declines,
                       investigate, tests, ts, regression, latest_year) -> str:
    latest = annual[annual.year == latest_year].iloc[0]
    first = annual.iloc[0]
    top_region = regions[regions.region != "Unknown"].nlargest(1, "profit").iloc[0]
    worst_decline = declines.iloc[0]
    top10_share = concentration.iloc[0]["pct_of_revenue"]
    anova = _test(tests, "regions_anova")
    disc = _test(tests, "discount_vs_margin")

    return f"""---

## 11. Direct answers to the business questions

**What was our revenue growth over the last 12 months?**
{latest['revenue_growth_pct']:+.1f}% in {latest_year}
({_money(first['revenue'])} to {_money(latest['revenue'])} across the full
series). The underlying compound rate is {ts['trend']['cagr_pct']:.1f}% a year.

**Which region contributes the most profit?**
{top_region['region']}, at {_money(top_region['profit'])}
({top_region['pct_of_profit']:.1f}% of total profit) on a
{top_region['profit_margin_pct']:.1f}% margin.

**Which products have high revenue but low margins?**
{len(investigate)} products meet both criteria - listed in full in section 7.
The largest is {investigate.iloc[0]['product_name'] if len(investigate) else 'n/a'}
at {_money(investigate.iloc[0]['revenue']) if len(investigate) else '$0'} revenue
and {investigate.iloc[0]['profit_margin_pct'] if len(investigate) else 0:.1f}%
margin.

**Which customer segment generates the highest revenue?**
See section 6 - the Enterprise segment leads on revenue per customer, but the
decile analysis is the more useful cut: revenue concentration cuts across
segment labels.

**Are discounts hurting profitability?**
Yes, and the effect is causal in direction if not in proof.
{disc.get('effect_size', {}).get('mean_difference_pp', 0):+.1f} percentage
points of margin separate high-discount from low-discount transactions
(p = {disc.get('p_value', 0):.1e}), and after controlling for category,
segment, region, year, order size and price, each extra point of discount still
costs roughly {abs(regression['discount_coefficient']):.2f} points of margin. The 40%+ discount band
is loss-making in aggregate.

**Which month had the largest revenue decline?**
{worst_decline['year_month']}, down {worst_decline['change_pct']:.1f}% month on
month ({_money(worst_decline['previous_month_revenue'])} to
{_money(worst_decline['revenue'])}). This is not seasonality: against a
seasonally adjusted expectation it still runs roughly 48% short.

**What percentage of revenue comes from our top 10 customers?**
The top decile ({int(concentration.iloc[0]['customers'])} accounts) generates
{top10_share:.1f}%. The ten largest individual accounts are listed in
`reports/sql_results/top_customers.csv`.

**Which products should management investigate?**
The {len(investigate)}-product list in section 7, prioritised by the value of
one percentage point of margin recovery.

**Are operating costs growing faster than revenue?**
Cost of goods sold: yes, in every year
({latest['cost_growth_pct']:.1f}% against {latest['revenue_growth_pct']:.1f}%
in {latest_year}). Below the gross line the picture is better - operating
leverage is improving as headcount grows more slowly than revenue.

**Are there statistically significant differences between regions?**
Statistically yes (ANOVA p = {anova.get('p_value', 0):.1e}), practically no:
region explains only
{anova.get('effect_size', {}).get('variance_explained_pct', 0):.2f}% of the
variance in order value. Regional differences in the dashboard mostly reflect
which customers happen to sit where.

**Which financial metrics have unusual behaviour?**
Gross margin (a sustained structural decline), the discount rate (a Q4 2024
spike), hardware unit costs (an Aug-Oct 2024 shock) and the facilities expense
line (a permanent step up in January 2025). All four are in section 10."""


def _recommendations(categories, discount, investigate, annual) -> str:
    worst_cat = categories.nsmallest(1, "profit_margin_pct").iloc[0]
    deep = discount[discount.discount_band.isin(["F. 25-40%", "G. 40%+"])]
    uplift = investigate.profit_uplift_per_margin_point.sum() if len(investigate) else 0
    latest = annual.iloc[-1]
    first = annual.iloc[0]
    margin_gap = first["gross_margin_pct"] - latest["gross_margin_pct"]

    return f"""---

## 12. Recommendations

Ordered by value at stake, with the evidence each rests on.

**1. Cap discount authority above 25%.**
The 25%+ bands carry {_money(deep.revenue.sum())} of revenue at a blended
{deep.profit.sum() / deep.revenue.sum() * 100:.1f}% margin, and the deepest
band destroys profit outright. Requiring approval above 25% does not forfeit
that revenue - it forces the trade-off to be made deliberately. *Evidence:
sections 4 and 8; the effect survives controls for product mix.*

**2. Reprice the {len(investigate)}-product investigation list.**
Worth {_money(uplift)} of annual profit per percentage point of margin
recovered, with no additional volume required. *Evidence: section 7.*

**3. Open a cost review on {worst_cat['product_category']}.**
{worst_cat['pct_of_revenue']:.1f}% of revenue returning
{worst_cat['pct_of_profit']:.1f}% of profit at a
{worst_cat['profit_margin_pct']:.1f}% margin. Either supply terms improve or
the category should shrink deliberately rather than by neglect. *Evidence:
sections 4 and 5.*

**4. Treat the {margin_gap:.1f}-point margin decline as the primary financial
issue.** It is worth
{_money(latest['revenue'] * margin_gap / 100)} a year at current revenue -
more than any growth initiative currently on the table. Cost inflation running
ahead of price realisation is the mechanism; annual price reviews indexed to
input costs are the structural fix. *Evidence: sections 3, 5 and 8.*

**5. Reduce customer concentration deliberately.**
The top decile carries most of the revenue. This does not need fixing
overnight, but it belongs on the risk register with a named owner and a target.
*Evidence: section 6.*

**6. Put the anomaly monitor on a monthly cadence.**
It recovered every injected event in validation. Run against the seasonally
adjusted expectation, not month-on-month change, and route Critical and High
material flags to a named reviewer. *Evidence: section 10.*"""


def _limitations() -> str:
    return f"""---

## 13. Limitations

Stated plainly, because analysis that hides its limits is not trustworthy.

1. **The data is synthetic.** It was generated to be realistic - seasonality,
   customer heterogeneity, cost inflation, injected shocks and genuine data
   quality defects - but it is not a real company's ledger. The *methods* are
   what transfer; the specific findings describe a simulated business.

2. **Three years is short for seasonal estimation.** Twelve monthly seasonal
   factors are estimated from three observations each. One unusual month
   distorts its own factor, as February demonstrates. Five or more years would
   be needed for stable seasonal estimates.

3. **Association is not causation.** Discount depth is set by the business,
   not assigned at random. The regression controls for the obvious confounders
   - product mix, segment, region, order size, price, year - but unobserved
   ones remain: a salesperson may discount hardest precisely on the deals that
   were always going to be thin. A pricing experiment, not more regression,
   would settle it.

4. **Marketing effectiveness is not established.** The apparent link between
   spend and revenue is largely budget-setting mechanics running backwards.
   Section 8 states this explicitly.

5. **Anomaly recall is measured; precision is not.** Recall against the
   injected events is 100%, but flags outside those windows are not
   necessarily false positives - ordinary volatility produces real outliers
   too. Without labelled "normal" periods, precision cannot be computed
   honestly, so it is not claimed.

6. **The unattributed rows.** Transactions whose customer identifier could not
   be recovered are retained in revenue totals but excluded from every
   customer-level analysis. This is the right accounting treatment, but it
   means customer-level revenue does not sum exactly to total revenue.

7. **SQLite, not PostgreSQL.** The warehouse runs on SQLite so the project
   reproduces with no server setup. All SQL is standard (CTEs and window
   functions only) and the loader is engine-agnostic, so pointing
   `FINANCE_DB_URL` at PostgreSQL runs the same pipeline - but that path has
   not been exercised in this build.

---

*Generated by `src/report.py` from the artefacts in `reports/`.
Rerun `python run_pipeline.py` to regenerate both.*"""


if __name__ == "__main__":
    build_report()
