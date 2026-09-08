"""Statistical layer: estimators checked against closed-form answers.

The hypothesis tests in this project drive business recommendations, so the
machinery underneath them is verified against textbook results and against
scipy, rather than against whatever the code happened to produce first.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from scipy import stats

from src import config
from src import stats_analysis as sa
from src.stats_analysis import (bootstrap_ci, cohens_d, correlation_analysis,
                                describe_effect, eta_squared, t_interval,
                                wilson_interval)

# The hypothesis-test functions are reached through the module rather than
# imported by name: pytest collects any module-level callable called test_*,
# and would try to run them as tests.


# --------------------------------------------------------------------------
# Effect sizes
# --------------------------------------------------------------------------
class TestCohensD:
    def test_identical_groups_have_no_effect(self):
        a = np.array([1.0, 2, 3, 4, 5])
        assert cohens_d(a, a.copy()) == pytest.approx(0.0, abs=1e-12)

    def test_one_pooled_sd_of_separation_gives_d_of_one(self):
        """Same spread, means one SD apart -> d = 1 by construction."""
        rng = np.random.default_rng(0)
        a = rng.normal(0, 1, 20_000)
        b = rng.normal(1, 1, 20_000)
        assert cohens_d(b, a) == pytest.approx(1.0, abs=0.05)

    def test_sign_follows_the_argument_order(self):
        a, b = np.array([1.0, 2, 3]), np.array([4.0, 5, 6])
        assert cohens_d(a, b) < 0 < cohens_d(b, a)

    @pytest.mark.parametrize("d,expected", [
        (0.05, "negligible"), (0.3, "small"), (0.6, "medium"), (1.2, "large"),
    ])
    def test_conventional_thresholds_are_labelled(self, d, expected):
        assert describe_effect(d).lower().startswith(expected[:5])


def test_eta_squared_is_one_when_groups_do_not_overlap_at_all():
    """Zero within-group variance means every bit of variance is between
    groups, so eta-squared must be exactly 1."""
    groups = [np.array([1.0, 1, 1]), np.array([5.0, 5, 5]), np.array([9.0, 9, 9])]
    assert eta_squared(groups) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Interval estimates
# --------------------------------------------------------------------------
class TestConfidenceIntervals:
    def test_t_interval_matches_the_closed_form(self):
        x = np.array([2.0, 4, 4, 4, 5, 5, 7, 9])
        lo, hi = t_interval(x, confidence=0.95)
        half = stats.sem(x) * stats.t.ppf(0.975, len(x) - 1)
        assert (lo, hi) == pytest.approx((x.mean() - half, x.mean() + half))

    def test_t_interval_brackets_the_sample_mean(self):
        x = np.array([2.0, 4, 4, 4, 5, 5, 7, 9])
        lo, hi = t_interval(x)
        assert lo < x.mean() < hi

    def test_wider_confidence_gives_a_wider_interval(self):
        x = np.random.default_rng(1).normal(100, 15, 200)
        narrow = t_interval(x, 0.90)
        wide = t_interval(x, 0.99)
        assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])

    def test_bootstrap_agrees_with_the_t_interval_on_normal_data(self):
        """They answer the same question by different routes; on well-behaved
        data they should land in nearly the same place."""
        x = np.random.default_rng(2).normal(50, 10, 800)
        boot = bootstrap_ci(x, n_iterations=2_000)
        para = t_interval(x)
        assert boot[0] == pytest.approx(para[0], abs=0.6)
        assert boot[1] == pytest.approx(para[1], abs=0.6)

    def test_bootstrap_is_reproducible_for_a_fixed_seed(self):
        x = np.random.default_rng(3).normal(0, 1, 300)
        assert bootstrap_ci(x, n_iterations=1_000, seed=7) == \
               bootstrap_ci(x, n_iterations=1_000, seed=7)

    def test_wilson_interval_stays_inside_zero_and_one_at_the_boundary(self):
        """The normal approximation escapes [0, 1] for p near 0; Wilson must
        not - this is the whole reason it is used here."""
        lo, hi = wilson_interval(0, 30)
        assert 0.0 <= lo < hi <= 1.0

    def test_wilson_interval_brackets_the_observed_proportion(self):
        lo, hi = wilson_interval(45, 100)
        assert lo < 0.45 < hi


# --------------------------------------------------------------------------
# Correlation and hypothesis tests on the real data
# --------------------------------------------------------------------------
class TestCorrelation:
    def test_every_pair_reports_r_p_and_n(self, clean_df):
        results = correlation_analysis(clean_df)
        assert results
        for row in results:
            assert -1.0 <= row["pearson_r"] <= 1.0
            assert -1.0 <= row["spearman_rho"] <= 1.0
            assert 0.0 <= row["pearson_p"] <= 1.0
            assert row["r_squared"] == pytest.approx(row["pearson_r"] ** 2, abs=1e-3)
            assert row["n"] > 0

    def test_quantity_and_revenue_are_positively_related(self, clean_df):
        """Revenue is quantity x price x (1-discount); the correlation must
        come out positive or something upstream has broken."""
        row = next(r for r in correlation_analysis(clean_df)
                   if r["pair"] == "quantity vs revenue")
        assert row["pearson_r"] > 0


class TestHypothesisTests:
    def test_discount_vs_margin_returns_a_complete_result(self, clean_df):
        result = sa.test_discount_vs_margin(clean_df)
        assert result.null_hypothesis and result.alternative_hypothesis
        assert 0.0 <= result.p_value <= 1.0
        assert result.effect_size
        assert result.significant == (result.p_value < config.ALPHA)

    def test_two_region_comparison_names_both_groups(self, clean_df):
        result = sa.test_region_order_value(clean_df, "North America", "Europe")
        assert len(result.groups) == 2
        assert 0.0 <= result.p_value <= 1.0

    def test_anova_across_regions_reports_an_f_statistic(self, clean_df):
        result = sa.test_regions_anova(clean_df)
        assert result.statistic >= 0
        assert 0.0 <= result.p_value <= 1.0

    def test_significance_is_decided_at_the_configured_alpha(self, clean_df):
        """No test may quietly use its own threshold."""
        for result in (sa.test_discount_vs_margin(clean_df),
                       sa.test_regions_anova(clean_df)):
            assert result.alpha == config.ALPHA


class TestPublishedStatistics:
    def test_saved_results_are_internally_consistent(self):
        path = config.REPORTS_DIR / "statistical_analysis.json"
        if not path.exists():
            pytest.skip("run: python run_pipeline.py --stage stats")
        payload = json.loads(path.read_text())
        for test in payload.get("hypothesis_tests", []):
            assert test["significant"] == (test["p_value"] < test["alpha"])
