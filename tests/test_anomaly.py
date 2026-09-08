"""Anomaly detectors: planted outliers, and the severity/materiality rules.

Each detector is given a series it should be able to solve exactly - a clean
baseline with one spike deliberately inserted - so a miss is a real miss rather
than a judgement call.  The severity rules get their own tests because the
whole point of the materiality floor is to suppress statistically extreme but
commercially irrelevant flags.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src import config
from src.anomaly import (Anomaly, _is_material, _severity, iqr_detector,
                         rolling_zscore_detector, zscore_detector)


def _monthly_series(values: list[float], start: str = "2022-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="MS")
    return pd.Series(values, index=index)


# --------------------------------------------------------------------------
# Global z-score
# --------------------------------------------------------------------------
class TestZScoreDetector:
    def test_finds_a_planted_spike(self):
        values = [100.0] * 20 + [1000.0] + [100.0] * 20
        # a little noise, or the SD is zero and no z-score exists
        rng = np.random.default_rng(0)
        values = [v + rng.normal(0, 1) for v in values]
        found = zscore_detector(_monthly_series(values), "Monthly revenue")
        assert found, "the 10x spike should have been flagged"
        assert any(a.actual > 900 for a in found)

    def test_a_clean_series_produces_no_flags(self):
        rng = np.random.default_rng(1)
        values = list(rng.normal(100, 5, 40))
        assert zscore_detector(_monthly_series(values), "Monthly revenue") == []

    def test_a_constant_series_is_declined_rather_than_dividing_by_zero(self):
        assert zscore_detector(_monthly_series([100.0] * 30), "Flat") == []

    def test_too_short_a_series_is_declined(self):
        assert zscore_detector(_monthly_series([1.0, 2, 3]), "Short") == []

    def test_the_reported_expected_range_brackets_the_mean(self):
        rng = np.random.default_rng(2)
        values = [100.0 + rng.normal(0, 1) for _ in range(30)] + [500.0]
        found = zscore_detector(_monthly_series(values), "Monthly revenue")
        assert found
        flag = found[0]
        assert flag.expected_low < flag.expected < flag.expected_high
        assert not (flag.expected_low <= flag.actual <= flag.expected_high)

    def test_deviation_fields_agree_with_actual_and_expected(self):
        rng = np.random.default_rng(3)
        values = [100.0 + rng.normal(0, 1) for _ in range(30)] + [400.0]
        flag = zscore_detector(_monthly_series(values), "Monthly revenue")[0]
        # every field is stored rounded to 2dp, so recomputing from the
        # rounded values carries a little slack
        assert flag.deviation == pytest.approx(flag.actual - flag.expected, abs=0.02)
        assert flag.deviation_pct == pytest.approx(
            (flag.actual - flag.expected) / flag.expected * 100, abs=0.05)


# --------------------------------------------------------------------------
# Rolling z-score
# --------------------------------------------------------------------------
class TestRollingZScoreDetector:
    def test_catches_a_level_break_a_global_score_would_miss(self):
        """Revenue steps up permanently halfway through.  Against the whole
        series the new level is unremarkable; against the preceding six months
        the step itself is not."""
        rng = np.random.default_rng(4)
        values = ([100.0 + rng.normal(0, 1) for _ in range(18)]
                  + [180.0 + rng.normal(0, 1) for _ in range(18)])
        found = rolling_zscore_detector(_monthly_series(values), "Monthly revenue",
                                        window=6)
        assert found
        flagged_periods = [a.period for a in found]
        assert any(p.startswith("2023-07") for p in flagged_periods)

    def test_a_point_does_not_contribute_to_its_own_expectation(self):
        """The window is shifted, so a spike cannot inflate the SD it is
        judged against and hide itself."""
        rng = np.random.default_rng(5)
        values = [100.0 + rng.normal(0, 1) for _ in range(12)] + [10_000.0]
        found = rolling_zscore_detector(_monthly_series(values), "Monthly revenue",
                                        window=6)
        assert any(a.actual > 9_000 for a in found)


# --------------------------------------------------------------------------
# Tukey IQR fences
# --------------------------------------------------------------------------
class TestIqrDetector:
    def test_flags_the_extreme_tail_of_a_lognormal_population(self):
        rng = np.random.default_rng(6)
        values = pd.Series(np.exp(rng.normal(8, 0.5, 2_000)))
        values.iloc[0] = values.max() * 50          # one absurd transaction
        found, summary = iqr_detector(values, "Transaction value", "Company-wide")
        assert summary["n_flagged"] >= 1
        assert found[0].actual == pytest.approx(values.iloc[0])

    def test_fences_are_ordered_around_the_median(self):
        rng = np.random.default_rng(7)
        values = pd.Series(np.exp(rng.normal(8, 0.5, 1_000)))
        _, summary = iqr_detector(values, "Transaction value", "Company-wide")
        assert summary["lower_fence"] < summary["median"] < summary["upper_fence"]

    def test_log_scale_flags_far_fewer_rows_than_raw_scale(self):
        """Transaction values are lognormal; raw Tukey fences would condemn a
        large slice of ordinary big orders, which is why log_scale exists."""
        rng = np.random.default_rng(8)
        values = pd.Series(np.exp(rng.normal(8, 1.0, 3_000)))
        _, on_log = iqr_detector(values, "Value", "s", log_scale=True)
        _, on_raw = iqr_detector(values, "Value", "s", log_scale=False)
        assert on_log["pct_flagged"] < on_raw["pct_flagged"]

    def test_too_small_a_sample_is_declined(self):
        assert iqr_detector(pd.Series([1.0, 2, 3]), "Value", "s") == ([], {})


# --------------------------------------------------------------------------
# Severity and materiality
# --------------------------------------------------------------------------
class TestSeverityRules:
    def test_a_move_below_the_materiality_floor_cannot_rank_above_low(self):
        """A 2.7% rise in a very stable cost line scores z=9 but is not worth
        anyone's time; it must not outrank a revenue collapse."""
        tiny = config.MIN_MATERIAL_DEVIATION_PCT / 2
        assert _severity(9.0, tiny) == "Low"

    def test_a_material_and_extreme_move_is_critical(self):
        assert _severity(9.0, -48.0) == "Critical"

    @pytest.mark.parametrize("score,expected", [
        (3.1, "Medium"), (3.6, "High"), (4.6, "Critical"),
    ])
    def test_material_moves_are_graded_by_extremity(self, score, expected):
        assert _severity(score, 40.0) == expected

    def test_materiality_uses_the_configured_floor(self):
        assert _is_material(config.MIN_MATERIAL_DEVIATION_PCT + 0.1) is True
        assert _is_material(config.MIN_MATERIAL_DEVIATION_PCT - 0.1) is False

    def test_an_undefined_deviation_is_treated_as_material(self):
        """Better to surface a flag that cannot be sized than to drop it."""
        assert _is_material(None) is True
        assert _is_material(float("nan")) is True


# --------------------------------------------------------------------------
# The published report
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def report() -> dict:
    path = config.REPORTS_DIR / "anomaly_report.json"
    if not path.exists():
        pytest.skip("run: python run_pipeline.py --stage anomaly")
    return json.loads(path.read_text())


class TestPublishedAnomalies:
    def test_every_flag_carries_the_fields_an_analyst_needs(self, report):
        flags = report["top_anomalies"]
        assert flags
        required = {"period", "metric", "actual", "expected", "expected_low",
                    "expected_high", "deviation", "severity", "interpretation"}
        for flag in flags:
            assert required <= set(flag)

    def test_severity_labels_come_from_the_known_set(self, report):
        allowed = {"Low", "Medium", "High", "Critical"}
        assert {f["severity"] for f in report["top_anomalies"]} <= allowed
        assert set(report["by_severity"]) <= allowed

    def test_no_immaterial_flag_was_promoted_above_low(self, report):
        for flag in report["top_anomalies"]:
            if flag.get("material") is False:
                assert flag["severity"] == "Low"

    def test_actual_always_falls_outside_the_expected_range(self, report):
        for flag in report["top_anomalies"]:
            assert (flag["actual"] < flag["expected_low"]
                    or flag["actual"] > flag["expected_high"]), flag["period"]

    def test_the_detectors_found_the_events_planted_in_the_raw_data(self, report):
        """generate_data.py records what it injected; the monitor is scored
        against that ground truth rather than against its own output."""
        scoring = report["ground_truth_scoring"]
        if not scoring.get("available"):
            pytest.skip("ground-truth file not present")
        assert scoring["events_injected"] > 0
        assert scoring["recall_pct"] > 50
        assert scoring["events_recovered"] <= scoring["events_injected"]

    def test_the_severity_counts_add_up_to_the_headline_total(self, report):
        assert sum(report["by_severity"].values()) == report["total_anomalies"]
        assert (report["material_flags"] + report["immaterial_flags"]
                == report["total_anomalies"])
