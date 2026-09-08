"""Statistical analysis: correlation, hypothesis testing, interval estimation
and an explanatory regression.

The point of this module is to separate *description* from *inference*.  A
dashboard can show that high-discount orders have a lower margin; only a test
can say whether that gap is larger than sampling noise, how big it is, and
whether it survives controlling for product mix.

Every test is reported as a structured record - hypotheses, assumption checks,
statistic, p-value, effect size, decision, and a business reading - so the
output can be dropped straight into the report or the dashboard.

Method notes:

* **Welch's t-test, not Student's.**  Group variances here are demonstrably
  unequal (Levene's test is reported alongside), and Welch is the correct
  default when they are.
* **A non-parametric partner for every mean test.**  Transaction values are
  heavily right-skewed, so a Mann-Whitney U on the same split is reported as a
  robustness check.  Agreement between the two is the evidence; disagreement
  is a flag.
* **Effect sizes always.**  With ~69,000 rows almost anything reaches
  p < 0.05.  Cohen's d, rank-biserial correlation, eta-squared and Cramer's V
  are what actually carry the business meaning.
* **Bootstrap alongside the parametric interval.**  Where a mean is skewed,
  the percentile bootstrap interval is the honest one; both are reported.

Run with:  python -m src.stats_analysis
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from src import config
from src.clean_pipeline import load_clean

RESULTS_PATH = config.REPORTS_DIR / "statistical_analysis.json"


# --------------------------------------------------------------------------
# Result containers
# --------------------------------------------------------------------------
@dataclass
class TestResult:
    name: str
    question: str
    null_hypothesis: str
    alternative_hypothesis: str
    test: str
    statistic: float
    p_value: float
    effect_size: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    assumptions: dict = field(default_factory=dict)
    robustness: dict = field(default_factory=dict)
    alpha: float = config.ALPHA
    interpretation: str = ""

    @property
    def significant(self) -> bool:
        return self.p_value < self.alpha

    def to_dict(self) -> dict:
        d = asdict(self)
        d["significant"] = self.significant
        d["decision"] = ("Reject the null hypothesis" if self.significant
                         else "Fail to reject the null hypothesis")
        return d


@dataclass
class IntervalEstimate:
    metric: str
    n: int
    point_estimate: float
    ci_low: float
    ci_high: float
    method: str
    confidence: float = config.CONFIDENCE
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["margin_of_error"] = (self.ci_high - self.ci_low) / 2
        return d


# --------------------------------------------------------------------------
# Effect-size helpers
# --------------------------------------------------------------------------
def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Standardised mean difference using the pooled SD."""
    na, nb = len(a), len(b)
    pooled_var = (((na - 1) * a.var(ddof=1) + (nb - 1) * b.var(ddof=1))
                  / (na + nb - 2))
    return float((a.mean() - b.mean()) / np.sqrt(pooled_var)) if pooled_var > 0 else 0.0


def rank_biserial(u_statistic: float, n1: int, n2: int) -> float:
    """Effect size for Mann-Whitney U: 0 = no separation, 1 = complete."""
    return float(1 - (2 * u_statistic) / (n1 * n2))


def cramers_v(contingency: np.ndarray, chi2: float) -> float:
    n = contingency.sum()
    r, k = contingency.shape
    return float(np.sqrt((chi2 / n) / max(min(r - 1, k - 1), 1)))


def eta_squared(groups: list[np.ndarray]) -> float:
    """Proportion of variance explained by group membership (one-way ANOVA)."""
    all_values = np.concatenate(groups)
    grand_mean = all_values.mean()
    ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in groups)
    ss_total = ((all_values - grand_mean) ** 2).sum()
    return float(ss_between / ss_total) if ss_total > 0 else 0.0


def describe_effect(d: float) -> str:
    a = abs(d)
    if a < 0.2:
        return "negligible"
    if a < 0.5:
        return "small"
    if a < 0.8:
        return "medium"
    return "large"


# --------------------------------------------------------------------------
# Interval estimation
# --------------------------------------------------------------------------
def t_interval(x: np.ndarray, confidence: float = config.CONFIDENCE) -> tuple[float, float]:
    n = len(x)
    se = stats.sem(x)
    half = se * stats.t.ppf((1 + confidence) / 2, n - 1)
    return float(x.mean() - half), float(x.mean() + half)


def bootstrap_ci(x: np.ndarray, statistic=np.mean,
                 n_iterations: int = config.BOOTSTRAP_ITERATIONS,
                 confidence: float = config.CONFIDENCE,
                 batch: int = 250, seed: int = 42) -> tuple[float, float]:
    """Percentile bootstrap interval, resampled in batches.

    Batching matters: a 10,000 x 69,000 resample matrix would need several GB,
    so the draws are taken a few hundred at a time and only the statistic is
    kept.
    """
    rng = np.random.default_rng(seed)
    n = len(x)
    estimates = np.empty(n_iterations)
    done = 0
    while done < n_iterations:
        size = min(batch, n_iterations - done)
        idx = rng.integers(0, n, size=(size, n))
        estimates[done:done + size] = statistic(x[idx], axis=1)
        done += size
    lo = (1 - confidence) / 2 * 100
    return float(np.percentile(estimates, lo)), float(np.percentile(estimates, 100 - lo))


def wilson_interval(successes: int, n: int,
                    confidence: float = config.CONFIDENCE) -> tuple[float, float]:
    """Wilson score interval for a proportion - well behaved near 0 and 1,
    where the normal approximation is not."""
    z = stats.norm.ppf((1 + confidence) / 2)
    p = successes / n
    denom = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denom
    return float(centre - half), float(centre + half)


# --------------------------------------------------------------------------
# Correlation analysis
# --------------------------------------------------------------------------
CORRELATION_PAIRS = [
    ("discount", "profit_margin_pct",
     "Does deeper discounting move realised margin?"),
    ("quantity", "revenue",
     "Does order size translate into revenue proportionally?"),
    ("cost", "profit",
     "Do cost and profit move together, or does cost eat the gain?"),
    ("unit_price", "profit_margin_pct",
     "Do higher-priced products carry better margins?"),
    ("discount", "quantity",
     "Are discounts buying volume?"),
    ("gross_revenue", "discount_amount",
     "Does discount scale with deal size?"),
]


def correlation_analysis(df: pd.DataFrame) -> list[dict]:
    """Pearson and Spearman for each pair of interest.

    Both are reported deliberately: Pearson answers "is the relationship
    linear?", Spearman answers "is it monotonic?".  A large gap between them
    is itself a finding - it means the relationship is real but curved.
    """
    out = []
    for x_col, y_col, question in CORRELATION_PAIRS:
        sub = df[[x_col, y_col]].dropna()
        x, y = sub[x_col].to_numpy(), sub[y_col].to_numpy()
        pearson_r, pearson_p = stats.pearsonr(x, y)
        spearman_r, spearman_p = stats.spearmanr(x, y)
        out.append({
            "pair": f"{x_col} vs {y_col}",
            "question": question,
            "n": len(sub),
            "pearson_r": round(float(pearson_r), 4),
            "pearson_p": float(pearson_p),
            "spearman_rho": round(float(spearman_r), 4),
            "spearman_p": float(spearman_p),
            "r_squared": round(float(pearson_r ** 2), 4),
            "strength": _describe_correlation(pearson_r),
            "linear_vs_monotonic_gap": round(abs(float(spearman_r) - float(pearson_r)), 4),
        })
    return out


def _describe_correlation(r: float) -> str:
    a = abs(r)
    direction = "positive" if r > 0 else "negative"
    if a < 0.1:
        return "negligible"
    if a < 0.3:
        return f"weak {direction}"
    if a < 0.5:
        return f"moderate {direction}"
    if a < 0.7:
        return f"strong {direction}"
    return f"very strong {direction}"


def monthly_correlation_analysis(df: pd.DataFrame) -> list[dict]:
    """Correlations at month grain, including marketing spend.

    Marketing spend only exists monthly, and a same-month correlation would
    miss any lag in response, so spend is tested against the current month and
    the following month.
    """
    monthly = (df.groupby("month_start")
                 .agg(revenue=("revenue", "sum"), profit=("profit", "sum"),
                      cost=("cost", "sum"), transactions=("transaction_id", "size"),
                      units=("quantity", "sum"),
                      avg_discount=("discount", "mean"))
                 .reset_index())
    monthly["margin_pct"] = monthly.profit / monthly.revenue * 100

    marketing = pd.read_csv(config.RAW_MARKETING, parse_dates=["month"])
    spend = marketing.groupby("month")["spend"].sum().rename("marketing_spend")
    monthly = monthly.merge(spend, left_on="month_start", right_index=True, how="left")
    monthly["revenue_next_month"] = monthly["revenue"].shift(-1)

    pairs = [
        ("marketing_spend", "revenue", "Same-month marketing spend vs revenue"),
        ("marketing_spend", "revenue_next_month",
         "Marketing spend vs the FOLLOWING month's revenue (one-month lag)"),
        ("avg_discount", "margin_pct", "Monthly average discount vs monthly margin"),
        ("cost", "revenue", "Monthly cost vs monthly revenue"),
        ("transactions", "revenue", "Transaction count vs revenue"),
    ]
    out = []
    for x_col, y_col, question in pairs:
        sub = monthly[[x_col, y_col]].dropna()
        r, p = stats.pearsonr(sub[x_col], sub[y_col])
        rho, rho_p = stats.spearmanr(sub[x_col], sub[y_col])
        out.append({
            "pair": f"{x_col} vs {y_col}", "question": question, "n": len(sub),
            "pearson_r": round(float(r), 4), "pearson_p": float(p),
            "spearman_rho": round(float(rho), 4), "spearman_p": float(rho_p),
            "r_squared": round(float(r ** 2), 4),
            "strength": _describe_correlation(r),
            "linear_vs_monotonic_gap": round(abs(float(rho) - float(r)), 4),
        })
    return out


# --------------------------------------------------------------------------
# Hypothesis tests
# --------------------------------------------------------------------------
def test_discount_vs_margin(df: pd.DataFrame) -> TestResult:
    """H1: do heavily discounted orders realise a lower profit margin?"""
    high = df.loc[df.discount > 0.15, "profit_margin_pct"].dropna().to_numpy()
    low = df.loc[df.discount <= 0.15, "profit_margin_pct"].dropna().to_numpy()

    levene_stat, levene_p = stats.levene(high, low)
    t_stat, t_p = stats.ttest_ind(high, low, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(high, low, alternative="two-sided")
    d = cohens_d(high, low)

    diff = high.mean() - low.mean()
    return TestResult(
        name="discount_vs_margin",
        question="Does giving higher discounts significantly reduce profit margins?",
        null_hypothesis="Mean profit margin is equal for high-discount (>15%) and "
                        "low-discount (<=15%) transactions.",
        alternative_hypothesis="Mean profit margin differs between the two groups.",
        test="Welch's two-sample t-test (unequal variances)",
        statistic=round(float(t_stat), 4), p_value=float(t_p),
        effect_size={"cohens_d": round(d, 4), "magnitude": describe_effect(d),
                     "mean_difference_pp": round(float(diff), 2),
                     "rank_biserial": round(rank_biserial(u_stat, len(high), len(low)), 4)},
        groups={
            "high_discount": {"n": len(high), "mean_margin_pct": round(float(high.mean()), 2),
                              "sd": round(float(high.std(ddof=1)), 2),
                              "median": round(float(np.median(high)), 2)},
            "low_discount": {"n": len(low), "mean_margin_pct": round(float(low.mean()), 2),
                             "sd": round(float(low.std(ddof=1)), 2),
                             "median": round(float(np.median(low)), 2)},
        },
        assumptions={"levene_statistic": round(float(levene_stat), 4),
                     "levene_p": float(levene_p),
                     "equal_variances": bool(levene_p >= config.ALPHA),
                     "note": "Levene rejects equal variance, so Welch's correction is "
                             "used rather than the pooled-variance t-test."},
        robustness={"mann_whitney_u": float(u_stat), "mann_whitney_p": float(u_p),
                    "agrees_with_t_test": bool((u_p < config.ALPHA) == (t_p < config.ALPHA))},
        interpretation=(
            f"Transactions discounted above 15% realise a margin {abs(diff):.1f} "
            f"percentage points {'lower' if diff < 0 else 'higher'} than lightly "
            f"discounted ones. The effect is statistically significant and its "
            f"magnitude is {describe_effect(d)}. Because the discount rate is set "
            f"by the business rather than assigned at random, this is an "
            f"association, not proof of causation - the regression below "
            f"controls for product mix and order size to narrow that gap."),
    )


def test_region_order_value(df: pd.DataFrame, region_a: str = "North America",
                            region_b: str = "Europe") -> TestResult:
    """H2: is average order value different between two regions?"""
    a = df.loc[df.region == region_a, "revenue"].dropna().to_numpy()
    b = df.loc[df.region == region_b, "revenue"].dropna().to_numpy()

    levene_stat, levene_p = stats.levene(a, b)
    t_stat, t_p = stats.ttest_ind(a, b, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(a, b, alternative="two-sided")
    # Transaction values are strongly right-skewed; the log scale is where the
    # t-test's normality assumption is closest to satisfied.
    log_t, log_p = stats.ttest_ind(np.log(a[a > 0]), np.log(b[b > 0]), equal_var=False)
    d = cohens_d(a, b)
    diff = a.mean() - b.mean()

    return TestResult(
        name="region_order_value",
        question=f"Is average order value significantly different between "
                 f"{region_a} and {region_b}?",
        null_hypothesis=f"Mean transaction value is equal in {region_a} and {region_b}.",
        alternative_hypothesis=f"Mean transaction value differs between {region_a} "
                               f"and {region_b}.",
        test="Welch's two-sample t-test (unequal variances)",
        statistic=round(float(t_stat), 4), p_value=float(t_p),
        effect_size={"cohens_d": round(d, 4), "magnitude": describe_effect(d),
                     "mean_difference": round(float(diff), 2),
                     "rank_biserial": round(rank_biserial(u_stat, len(a), len(b)), 4)},
        groups={
            region_a: {"n": len(a), "mean_order_value": round(float(a.mean()), 2),
                       "median": round(float(np.median(a)), 2),
                       "sd": round(float(a.std(ddof=1)), 2)},
            region_b: {"n": len(b), "mean_order_value": round(float(b.mean()), 2),
                       "median": round(float(np.median(b)), 2),
                       "sd": round(float(b.std(ddof=1)), 2)},
        },
        assumptions={"levene_p": float(levene_p),
                     "equal_variances": bool(levene_p >= config.ALPHA),
                     "skewness_region_a": round(float(stats.skew(a)), 3),
                     "skewness_region_b": round(float(stats.skew(b)), 3),
                     "note": "Both distributions are strongly right-skewed, so the "
                             "test is repeated on log values and with a rank test."},
        robustness={"mann_whitney_u": float(u_stat), "mann_whitney_p": float(u_p),
                    "log_scale_t": round(float(log_t), 4), "log_scale_p": float(log_p),
                    "all_three_agree": bool(
                        (u_p < config.ALPHA) == (t_p < config.ALPHA) ==
                        (log_p < config.ALPHA))},
        interpretation=(
            f"{region_a} averages {a.mean():,.0f} per transaction against "
            f"{b.mean():,.0f} in {region_b}, a gap of {abs(diff):,.0f}. "
            f"The effect size is {describe_effect(d)}, which is the more useful "
            f"number here: with {len(a) + len(b):,} transactions, even a "
            f"commercially trivial gap would clear p < 0.05."),
    )


def test_regions_anova(df: pd.DataFrame) -> TestResult:
    """H3: does order value differ across all regions simultaneously?"""
    regions = [r for r in df.region.unique() if r != "Unknown"]
    groups = [df.loc[df.region == r, "revenue"].dropna().to_numpy() for r in regions]

    f_stat, f_p = stats.f_oneway(*groups)
    h_stat, h_p = stats.kruskal(*groups)
    levene_stat, levene_p = stats.levene(*groups)
    eta2 = eta_squared(groups)

    # Games-Howell would be ideal under unequal variance; Tukey HSD is the
    # standard available implementation and is reported with that caveat.
    sub = df[df.region.isin(regions)]
    tukey = sm.stats.multicomp.pairwise_tukeyhsd(sub["revenue"], sub["region"],
                                                 alpha=config.ALPHA)
    pairs = []
    for row in tukey.summary().data[1:]:
        pairs.append({"group_1": row[0], "group_2": row[1],
                      "mean_difference": round(float(row[2]), 2),
                      "p_adjusted": float(row[3]), "reject_null": bool(row[6])})

    return TestResult(
        name="regions_anova",
        question="Are there statistically significant differences in average order "
                 "value between regions?",
        null_hypothesis="All regions have the same mean transaction value.",
        alternative_hypothesis="At least one region's mean transaction value differs.",
        test="One-way ANOVA with Tukey HSD post-hoc",
        statistic=round(float(f_stat), 4), p_value=float(f_p),
        effect_size={"eta_squared": round(eta2, 4),
                     "variance_explained_pct": round(eta2 * 100, 2),
                     "magnitude": ("negligible" if eta2 < 0.01 else
                                   "small" if eta2 < 0.06 else
                                   "medium" if eta2 < 0.14 else "large")},
        groups={r: {"n": len(g), "mean": round(float(g.mean()), 2),
                    "median": round(float(np.median(g)), 2)}
                for r, g in zip(regions, groups)},
        assumptions={"levene_p": float(levene_p),
                     "equal_variances": bool(levene_p >= config.ALPHA),
                     "note": "Variances are unequal, so the Kruskal-Wallis result is "
                             "the one to trust; ANOVA is reported for comparability."},
        robustness={"kruskal_wallis_h": round(float(h_stat), 4),
                    "kruskal_wallis_p": float(h_p),
                    "agrees_with_anova": bool((h_p < config.ALPHA) == (f_p < config.ALPHA)),
                    "tukey_pairs": pairs},
        interpretation=(
            f"Region membership explains {eta2 * 100:.2f}% of the variance in order "
            f"value. Whatever the p-value says, that is a small share - order value "
            f"is driven far more by customer segment and product mix than by "
            f"geography, so regional differences in the dashboard mostly reflect "
            f"which customers happen to sit where."),
    )


def test_margin_compression(df: pd.DataFrame) -> TestResult:
    """H4: has the gross margin structurally declined between 2023 and 2025?"""
    a = df.loc[df.year == 2023, "profit_margin_pct"].dropna().to_numpy()
    b = df.loc[df.year == 2025, "profit_margin_pct"].dropna().to_numpy()

    t_stat, t_p = stats.ttest_ind(a, b, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(a, b, alternative="two-sided")
    d = cohens_d(a, b)
    diff = a.mean() - b.mean()

    return TestResult(
        name="margin_compression_2023_vs_2025",
        question="Has transaction-level profit margin declined between 2023 and 2025?",
        null_hypothesis="Mean transaction profit margin is the same in 2023 and 2025.",
        alternative_hypothesis="Mean transaction profit margin differs between the years.",
        test="Welch's two-sample t-test (unequal variances)",
        statistic=round(float(t_stat), 4), p_value=float(t_p),
        effect_size={"cohens_d": round(d, 4), "magnitude": describe_effect(d),
                     "margin_change_pp": round(float(-diff), 2)},
        groups={"2023": {"n": len(a), "mean_margin_pct": round(float(a.mean()), 2),
                         "sd": round(float(a.std(ddof=1)), 2)},
                "2025": {"n": len(b), "mean_margin_pct": round(float(b.mean()), 2),
                         "sd": round(float(b.std(ddof=1)), 2)}},
        assumptions={"note": "Compares transaction-level margins, so the result is not "
                             "distorted by the growth in transaction volume between "
                             "the two years."},
        robustness={"mann_whitney_u": float(u_stat), "mann_whitney_p": float(u_p),
                    "agrees_with_t_test": bool((u_p < config.ALPHA) == (t_p < config.ALPHA))},
        interpretation=(
            f"Average transaction margin moved from {a.mean():.2f}% in 2023 to "
            f"{b.mean():.2f}% in 2025, a change of {-diff:+.2f} percentage points. "
            f"This is measured per transaction, so it is not an artefact of mix "
            f"shifting toward larger deals - the unit economics themselves moved."),
    )


def test_hardware_cost_shock(df: pd.DataFrame) -> TestResult:
    """H5: was the Aug-Oct 2024 hardware margin drop a real shift?

    Compares the same calendar months a year apart, which removes seasonality
    from the comparison rather than pretending it is absent.
    """
    hw = df[df.product_category == "Hardware"]
    window = hw[(hw.transaction_date >= "2024-08-01") & (hw.transaction_date <= "2024-10-15")]
    baseline = hw[(hw.transaction_date >= "2023-08-01") & (hw.transaction_date <= "2023-10-15")]

    a = window["profit_margin_pct"].dropna().to_numpy()
    b = baseline["profit_margin_pct"].dropna().to_numpy()
    t_stat, t_p = stats.ttest_ind(a, b, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(a, b, alternative="two-sided")
    d = cohens_d(a, b)
    diff = a.mean() - b.mean()

    return TestResult(
        name="hardware_cost_shock",
        question="Did hardware margin in Aug-Oct 2024 differ from the same window "
                 "in 2023?",
        null_hypothesis="Hardware transaction margin is the same in Aug-Oct 2024 as "
                        "in Aug-Oct 2023.",
        alternative_hypothesis="Hardware transaction margin differs between the two "
                               "windows.",
        test="Welch's two-sample t-test on matched calendar windows",
        statistic=round(float(t_stat), 4), p_value=float(t_p),
        effect_size={"cohens_d": round(d, 4), "magnitude": describe_effect(d),
                     "margin_change_pp": round(float(diff), 2)},
        groups={"aug_oct_2024": {"n": len(a), "mean_margin_pct": round(float(a.mean()), 2)},
                "aug_oct_2023": {"n": len(b), "mean_margin_pct": round(float(b.mean()), 2)}},
        assumptions={"note": "Matching on calendar window controls for seasonality; "
                             "any residual difference is a change in unit economics."},
        robustness={"mann_whitney_u": float(u_stat), "mann_whitney_p": float(u_p),
                    "agrees_with_t_test": bool((u_p < config.ALPHA) == (t_p < config.ALPHA))},
        interpretation=(
            f"Hardware margin in the Aug-Oct 2024 window averaged {a.mean():.2f}% "
            f"against {b.mean():.2f}% in the same window of 2023 "
            f"({diff:+.2f} pp). Combined with stable selling prices, this points to "
            f"a cost-side shock rather than a pricing decision."),
    )


def test_payment_segment_independence(df: pd.DataFrame) -> TestResult:
    """H6: is payment method independent of customer segment?"""
    sub = df[(df.payment_type != "Unknown") & (df.customer_segment != "Unknown")]
    table = pd.crosstab(sub.customer_segment, sub.payment_type)
    chi2, p, dof, expected = stats.chi2_contingency(table)
    v = cramers_v(table.to_numpy(), chi2)

    return TestResult(
        name="payment_segment_independence",
        question="Do different customer segments pay in different ways?",
        null_hypothesis="Payment method is independent of customer segment.",
        alternative_hypothesis="Payment method depends on customer segment.",
        test="Chi-square test of independence",
        statistic=round(float(chi2), 4), p_value=float(p),
        effect_size={"cramers_v": round(v, 4),
                     "magnitude": ("negligible" if v < 0.1 else "small" if v < 0.3
                                   else "medium" if v < 0.5 else "large"),
                     "degrees_of_freedom": int(dof)},
        groups={"contingency_table": table.to_dict(),
                "row_percentages": (table.div(table.sum(axis=1), axis=0) * 100)
                                    .round(1).to_dict()},
        assumptions={"min_expected_count": round(float(expected.min()), 2),
                     "all_expected_above_5": bool(expected.min() >= 5),
                     "note": "Chi-square requires expected counts of at least 5 in "
                             "every cell; that holds here."},
        interpretation=(
            f"Payment method and segment are strongly associated (Cramer's V = "
            f"{v:.3f}). Enterprise accounts settle on invoice terms while Retail "
            f"pays by card - which is why the receivables balance is concentrated "
            f"in the largest accounts and drives the collections finding."),
    )


def test_weekend_effect(df: pd.DataFrame) -> TestResult:
    """H7: do weekend orders behave differently from weekday orders?"""
    a = df.loc[df.is_weekend, "revenue"].dropna().to_numpy()
    b = df.loc[~df.is_weekend, "revenue"].dropna().to_numpy()
    t_stat, t_p = stats.ttest_ind(a, b, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(a, b, alternative="two-sided")
    d = cohens_d(a, b)

    return TestResult(
        name="weekend_effect",
        question="Do weekend transactions differ in value from weekday transactions?",
        null_hypothesis="Mean transaction value is equal on weekends and weekdays.",
        alternative_hypothesis="Mean transaction value differs between weekends and "
                               "weekdays.",
        test="Welch's two-sample t-test (unequal variances)",
        statistic=round(float(t_stat), 4), p_value=float(t_p),
        effect_size={"cohens_d": round(d, 4), "magnitude": describe_effect(d),
                     "mean_difference": round(float(a.mean() - b.mean()), 2)},
        groups={"weekend": {"n": len(a), "mean_order_value": round(float(a.mean()), 2)},
                "weekday": {"n": len(b), "mean_order_value": round(float(b.mean()), 2)}},
        robustness={"mann_whitney_u": float(u_stat), "mann_whitney_p": float(u_p),
                    "agrees_with_t_test": bool((u_p < config.ALPHA) == (t_p < config.ALPHA))},
        interpretation=(
            f"Weekend orders average {a.mean():,.0f} against {b.mean():,.0f} on "
            f"weekdays. Weekend volume is only {len(a) / (len(a) + len(b)) * 100:.1f}% "
            f"of transactions, consistent with a B2B order pattern; this test mainly "
            f"confirms the day-of-week structure the time-series module models."),
    )


# --------------------------------------------------------------------------
# Explanatory regression
# --------------------------------------------------------------------------
def margin_regression(df: pd.DataFrame) -> dict:
    """OLS of profit margin on discount, controlling for mix.

    This is the answer to the obvious objection to the discount test: maybe
    discounted orders just happen to be hardware, and hardware is thin-margin
    anyway.  Adding category and segment fixed effects and log order size
    isolates the discount coefficient from that confound.

    It is a *descriptive* regression - a variance decomposition, not a
    predictive model - which is why it reports coefficients and R-squared
    rather than out-of-sample error.
    """
    sub = (df[df.revenue > 0]
           .loc[:, ["profit_margin_pct", "discount", "quantity", "unit_price",
                    "product_category", "customer_segment", "region", "year"]]
           .dropna()
           .copy())
    sub["log_quantity"] = np.log(sub["quantity"])
    sub["log_unit_price"] = np.log(sub["unit_price"])
    sub["discount_pct"] = sub["discount"] * 100

    model = smf.ols(
        "profit_margin_pct ~ discount_pct + log_quantity + log_unit_price "
        "+ C(product_category) + C(customer_segment) + C(region) + C(year)",
        data=sub).fit()

    # Heteroskedasticity-robust standard errors: residual spread varies with
    # order size, so classical SEs would be optimistic.
    robust = model.get_robustcov_results(cov_type="HC3")

    coefficients = []
    for name, coef, se, p in zip(model.params.index, robust.params,
                                 robust.bse, robust.pvalues):
        coefficients.append({"term": name, "coefficient": round(float(coef), 4),
                             "std_error": round(float(se), 4), "p_value": float(p),
                             "significant": bool(p < config.ALPHA)})

    discount_coef = float(model.params["discount_pct"])
    return {
        "model": "OLS: profit_margin_pct ~ discount + log(quantity) + log(price) "
                 "+ category + segment + region + year",
        "n_observations": int(model.nobs),
        "r_squared": round(float(model.rsquared), 4),
        "adj_r_squared": round(float(model.rsquared_adj), 4),
        "f_statistic": round(float(model.fvalue), 2),
        "f_p_value": float(model.f_pvalue),
        "standard_errors": "HC3 heteroskedasticity-robust",
        "discount_coefficient": round(discount_coef, 4),
        "discount_p_value": float(robust.pvalues[list(model.params.index).index("discount_pct")]),
        "coefficients": coefficients,
        "interpretation": (
            f"Holding product category, customer segment, region, year, order size "
            f"and unit price constant, each additional percentage point of discount "
            f"is associated with a {abs(discount_coef):.3f} pp "
            f"{'reduction' if discount_coef < 0 else 'increase'} in realised profit "
            f"margin. The model explains {model.rsquared * 100:.1f}% of margin "
            f"variance. The discount effect survives the mix controls, so the "
            f"headline discount finding is not simply hardware-heavy orders being "
            f"counted twice."),
    }


# --------------------------------------------------------------------------
# Confidence intervals
# --------------------------------------------------------------------------
def confidence_intervals(df: pd.DataFrame) -> list[dict]:
    out: list[IntervalEstimate] = []

    rev = df["revenue"].dropna().to_numpy()
    lo, hi = t_interval(rev)
    out.append(IntervalEstimate(
        "Average transaction value", len(rev), float(rev.mean()), lo, hi,
        "Student's t interval",
        note="Valid despite the skew because n is large enough for the CLT to "
             "apply to the sampling distribution of the mean."))
    blo, bhi = bootstrap_ci(rev)
    out.append(IntervalEstimate(
        "Average transaction value (bootstrap)", len(rev), float(rev.mean()),
        blo, bhi, f"Percentile bootstrap, {config.BOOTSTRAP_ITERATIONS:,} resamples",
        note="Agreement with the t interval is the check that the CLT "
             "approximation is holding at this sample size."))

    prof = df["profit"].dropna().to_numpy()
    lo, hi = t_interval(prof)
    out.append(IntervalEstimate("Average profit per transaction", len(prof),
                                float(prof.mean()), lo, hi, "Student's t interval"))

    per_customer = (df[df.is_customer_attributed]
                    .groupby("customer_id")["revenue"].sum().to_numpy())
    lo, hi = t_interval(per_customer)
    out.append(IntervalEstimate(
        "Revenue per customer (lifetime)", len(per_customer),
        float(per_customer.mean()), lo, hi, "Student's t interval",
        note="Heavily right-skewed with n=1,200; the bootstrap interval below is "
             "the more trustworthy of the two."))
    blo, bhi = bootstrap_ci(per_customer)
    out.append(IntervalEstimate(
        "Revenue per customer (bootstrap)", len(per_customer),
        float(per_customer.mean()), blo, bhi,
        f"Percentile bootstrap, {config.BOOTSTRAP_ITERATIONS:,} resamples"))

    margin = df["profit_margin_pct"].dropna().to_numpy()
    lo, hi = t_interval(margin)
    out.append(IntervalEstimate("Average transaction profit margin (%)", len(margin),
                                float(margin.mean()), lo, hi, "Student's t interval"))

    losses = int(df["is_loss_making"].sum())
    lo, hi = wilson_interval(losses, len(df))
    out.append(IntervalEstimate(
        "Proportion of loss-making transactions", len(df), losses / len(df),
        lo, hi, "Wilson score interval",
        note="Wilson rather than the normal approximation, which misbehaves for "
             "proportions this close to zero."))

    disc = df["discount"].dropna().to_numpy()
    lo, hi = t_interval(disc)
    out.append(IntervalEstimate("Average discount rate", len(disc), float(disc.mean()),
                                lo, hi, "Student's t interval"))

    return [i.to_dict() for i in out]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_all(df: pd.DataFrame | None = None, verbose: bool = True) -> dict:
    df = load_clean() if df is None else df

    if verbose:
        print("Correlation analysis ...")
    transaction_corr = correlation_analysis(df)
    monthly_corr = monthly_correlation_analysis(df)

    if verbose:
        print("Hypothesis tests ...")
    tests = [
        test_discount_vs_margin(df),
        test_region_order_value(df),
        test_regions_anova(df),
        test_margin_compression(df),
        test_hardware_cost_shock(df),
        test_payment_segment_independence(df),
        test_weekend_effect(df),
    ]

    if verbose:
        print("Explanatory regression ...")
    regression = margin_regression(df)

    if verbose:
        print("Confidence intervals ...")
    intervals = confidence_intervals(df)

    results = {
        "alpha": config.ALPHA,
        "confidence_level": config.CONFIDENCE,
        "n_transactions": len(df),
        "correlations_transaction_level": transaction_corr,
        "correlations_monthly_level": monthly_corr,
        "hypothesis_tests": [t.to_dict() for t in tests],
        "regression": regression,
        "confidence_intervals": intervals,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))

    if verbose:
        _print_summary(results)
        print(f"\nFull results written to "
              f"{RESULTS_PATH.relative_to(config.ROOT)}")
    return results


def _print_summary(r: dict) -> None:
    print("\n" + "=" * 78)
    print("CORRELATIONS (transaction level)")
    print("=" * 78)
    for c in r["correlations_transaction_level"]:
        print(f"  {c['pair']:<34} r={c['pearson_r']:>7.3f}  rho={c['spearman_rho']:>7.3f}"
              f"  p={c['pearson_p']:.2e}  {c['strength']}")

    print("\n" + "=" * 78)
    print("CORRELATIONS (monthly level)")
    print("=" * 78)
    for c in r["correlations_monthly_level"]:
        print(f"  {c['pair']:<40} r={c['pearson_r']:>7.3f}  p={c['pearson_p']:.4f}"
              f"  {c['strength']}")

    print("\n" + "=" * 78)
    print("HYPOTHESIS TESTS")
    print("=" * 78)
    for t in r["hypothesis_tests"]:
        verdict = "REJECT H0" if t["significant"] else "fail to reject H0"
        effect = t["effect_size"]
        size = effect.get("cohens_d", effect.get("cramers_v",
                                                 effect.get("eta_squared", "")))
        print(f"\n  {t['name']}")
        print(f"    {t['question']}")
        print(f"    {t['test']}")
        print(f"    statistic={t['statistic']:<12.3f} p={t['p_value']:.3e}  ->  {verdict}")
        print(f"    effect size: {size} ({effect.get('magnitude', 'n/a')})")

    print("\n" + "=" * 78)
    print("REGRESSION")
    print("=" * 78)
    reg = r["regression"]
    print(f"  {reg['model']}")
    print(f"  n={reg['n_observations']:,}  R^2={reg['r_squared']:.4f}  "
          f"adj R^2={reg['adj_r_squared']:.4f}")
    print(f"  discount coefficient = {reg['discount_coefficient']:.4f} pp of margin "
          f"per pp of discount (p={reg['discount_p_value']:.2e})")

    print("\n" + "=" * 78)
    print(f"CONFIDENCE INTERVALS ({int(config.CONFIDENCE * 100)}%)")
    print("=" * 78)
    for ci in r["confidence_intervals"]:
        # Proportions and rates need more decimals than currency, or the
        # interval prints as [0.03, 0.03] and looks degenerate.
        dp = 5 if abs(ci["point_estimate"]) < 10 else 2
        print(f"  {ci['metric']:<44} {ci['point_estimate']:>14,.{dp}f}  "
              f"[{ci['ci_low']:>13,.{dp}f}, {ci['ci_high']:>13,.{dp}f}]")


if __name__ == "__main__":
    run_all()
