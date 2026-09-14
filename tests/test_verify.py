"""Metrics and the sampling rules are pinned by hand-worked cases.

The two that matter are the ones a verification study gets wrong quietly: the
common-sample restriction, which stops a model being scored on days it happened
to run, and the paired test, which stops a difference between two models
verified on the same weather being read as if they were independent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aiwp import fetch, verify
from aiwp.stations import ALL, CHINA, BY_SLUG


def _pairs(rows) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["station", "date", "model", "lead_days", "error_c"]
    )


# --------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------


def test_scores_match_hand_calculation():
    # errors 1, -1, 2, -2: bias 0, MAE 1.5, RMSE sqrt(10/4) = 1.5811
    out = verify.scores(np.array([1.0, -1.0, 2.0, -2.0]))
    assert out["n"] == 4
    assert out["bias_c"] == pytest.approx(0.0)
    assert out["mae_c"] == pytest.approx(1.5)
    assert out["rmse_c"] == pytest.approx(1.5811, abs=1e-4)


def test_debiased_rmse_removes_a_constant_offset():
    # A model that is exactly 2 degrees cold every day: RMSE 2, nothing left
    # once the offset is removed.
    errors = np.full(50, -2.0)
    out = verify.scores(errors)
    assert out["rmse_c"] == pytest.approx(2.0)
    assert out["debiased_rmse_c"] == pytest.approx(0.0, abs=1e-9)


def test_rmse_squared_splits_into_bias_squared_plus_debiased_squared():
    rng = np.random.default_rng(0)
    errors = rng.normal(-1.2, 1.7, size=500)
    out = verify.scores(errors)
    assert out["rmse_c"] ** 2 == pytest.approx(
        out["bias_c"] ** 2 + out["debiased_rmse_c"] ** 2, rel=1e-9
    )


def test_large_error_rate_counts_three_degree_misses():
    errors = np.array([0.5, -3.0, 3.5, 1.0])
    assert verify.scores(errors)["large_error_pct"] == pytest.approx(50.0)


def test_empty_input_reports_nothing_rather_than_zero():
    assert verify.scores(np.array([])) == {"n": 0}


# --------------------------------------------------------------------------
# Common sample
# --------------------------------------------------------------------------


def test_common_sample_drops_days_a_model_is_missing():
    rows = [
        ("bj", "2025-01-01", "a", 1, 1.0),
        ("bj", "2025-01-01", "b", 1, 2.0),
        ("bj", "2025-01-02", "a", 1, 1.0),  # b missing on the 2nd
    ]
    out = verify.common_sample(_pairs(rows))
    assert len(out) == 2
    assert set(out["date"]) == {"2025-01-01"}


def test_common_sample_keeps_leads_separate():
    rows = [
        ("bj", "2025-01-01", "a", 1, 1.0),
        ("bj", "2025-01-01", "b", 1, 1.0),
        ("bj", "2025-01-01", "a", 2, 1.0),  # b has no day-2 forecast
    ]
    out = verify.common_sample(_pairs(rows))
    assert set(out["lead_days"]) == {1}


def test_a_model_that_only_runs_on_easy_days_cannot_flatter_itself():
    """The failure the common sample exists to prevent."""
    rows = [("bj", f"2025-01-{d:02d}", "everyday", 1, 3.0) for d in range(1, 11)]
    # A second model that only produced forecasts on the two days it nailed.
    rows += [("bj", f"2025-01-{d:02d}", "cherry", 1, 0.1) for d in (1, 2)]
    raw = _pairs(rows)
    assert verify.scores(raw[raw.model == "cherry"]["error_c"])["rmse_c"] < 0.2

    shared = verify.common_sample(raw)
    assert shared["date"].nunique() == 2
    # On the shared days both are scored, and the comparison is now fair.
    assert set(shared["model"]) == {"everyday", "cherry"}
    assert len(shared) == 4


# --------------------------------------------------------------------------
# Paired comparison
# --------------------------------------------------------------------------


def test_paired_difference_detects_a_real_improvement():
    rng = np.random.default_rng(7)
    days = pd.date_range("2025-01-01", periods=300)
    weather = rng.normal(0, 3, size=days.size)  # the shared signal
    rows = []
    for day, shared in zip(days, weather):
        rows.append(("bj", day, "good", 1, 0.5 * shared))
        rows.append(("bj", day, "bad", 1, 1.5 * shared))
    out = verify.paired_difference(_pairs(rows), "good", "bad", lead=1)
    assert out["a_is_better"] is True
    assert out["ci_high"] < 0


def test_paired_difference_does_not_invent_a_winner():
    rng = np.random.default_rng(11)
    days = pd.date_range("2025-01-01", periods=300)
    rows = []
    for day in days:
        shared = rng.normal(0, 2)
        rows.append(("bj", day, "a", 1, shared + rng.normal(0, 0.01)))
        rows.append(("bj", day, "b", 1, shared + rng.normal(0, 0.01)))
    out = verify.paired_difference(_pairs(rows), "a", "b", lead=1)
    assert out["a_is_better"] is False
    assert out["b_is_better"] is False
    assert out["ci_low"] < 0 < out["ci_high"]


def test_paired_difference_needs_both_models():
    rows = [("bj", "2025-01-01", "a", 1, 1.0)]
    assert verify.paired_difference(_pairs(rows), "a", "missing", lead=1) == {"n": 0}


# --------------------------------------------------------------------------
# Daily reduction and stations
# --------------------------------------------------------------------------


def test_daily_max_discards_days_with_too_few_reports():
    hours = pd.date_range("2025-06-01", periods=30, freq="h")
    frame = pd.DataFrame({"time": hours, "temp_c": np.arange(30.0), "station": "bj"})
    out = fetch.daily_max(frame, min_hours=18)
    # The first day has 24 hours and survives; the second has 6 and does not.
    assert len(out) == 1
    assert out["temp_max_c"].iloc[0] == pytest.approx(23.0)


def test_daily_max_keeps_model_and_lead_apart():
    hours = pd.date_range("2025-06-01", periods=24, freq="h")
    frame = pd.concat(
        [
            pd.DataFrame(
                {"time": hours, "temp_c": 10.0, "station": "bj", "model": "a", "lead_days": 1}
            ),
            pd.DataFrame(
                {"time": hours, "temp_c": 20.0, "station": "bj", "model": "a", "lead_days": 2}
            ),
        ]
    )
    out = fetch.daily_max(frame)
    assert len(out) == 2
    assert sorted(out["temp_max_c"]) == [10.0, 20.0]


def test_station_list_is_coherent():
    assert len(CHINA) == 9
    assert all(s.is_china for s in CHINA)
    assert len({s.icao for s in ALL}) == len(ALL)
    assert BY_SLUG["shenzhen"].icao == "ZGSZ"
    # Every station's timezone is a real one pandas can localise to.
    for station in ALL:
        pd.Timestamp("2025-01-01").tz_localize(station.timezone)


def test_every_model_has_a_display_name():
    for model in fetch.MODELS:
        assert model in fetch.MODEL_LABEL
