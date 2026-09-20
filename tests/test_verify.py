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
        rows, columns=["station", "date", "model", "lead_days", "error"]
    )


# --------------------------------------------------------------------------
# Scores
# --------------------------------------------------------------------------


def test_scores_match_hand_calculation():
    # errors 1, -1, 2, -2: bias 0, MAE 1.5, RMSE sqrt(10/4) = 1.5811
    out = verify.scores(np.array([1.0, -1.0, 2.0, -2.0]))
    assert out["n"] == 4
    assert out["bias"] == pytest.approx(0.0)
    assert out["mae"] == pytest.approx(1.5)
    assert out["rmse"] == pytest.approx(1.5811, abs=1e-4)


def test_error_sd_removes_this_sample_s_own_offset():
    # A model that is exactly 2 degrees cold every day: RMSE 2, nothing left
    # once this sample's own mean is taken out.
    errors = np.full(50, -2.0)
    out = verify.scores(errors)
    assert out["rmse"] == pytest.approx(2.0)
    assert out["error_sd"] == pytest.approx(0.0, abs=1e-9)


def test_rmse_squared_splits_into_bias_squared_plus_spread_squared():
    rng = np.random.default_rng(0)
    errors = rng.normal(-1.2, 1.7, size=500)
    out = verify.scores(errors)
    assert out["rmse"] ** 2 == pytest.approx(out["bias"] ** 2 + out["error_sd"] ** 2, rel=1e-9)


def test_debiased_rmse_is_reported_only_when_the_debiased_column_is_supplied():
    errors = np.array([1.0, -1.0, 2.0, -2.0])
    assert "debiased_rmse" not in verify.scores(errors)
    out = verify.scores(errors, np.array([0.5, -0.5, np.nan, -1.0]))
    assert out["n_debiased"] == 3
    assert out["debiased_rmse"] == pytest.approx(np.sqrt((0.25 + 0.25 + 1.0) / 3))


# --------------------------------------------------------------------------
# Out-of-sample debiasing
# --------------------------------------------------------------------------


def _series(errors, model="m", station="s", lead=1):
    days = pd.date_range("2026-01-01", periods=len(errors), freq="D")
    return pd.DataFrame({"model": model, "station": station, "lead_days": lead,
                         "date": days, "error": errors})


def test_the_offset_uses_only_earlier_days():
    # Twenty days at -2, then one day at -2 as well. The offset for the last day
    # is fitted on the twenty before it, so nothing should be left of it.
    frame = verify.out_of_sample_debias(_series(np.full(21, -2.0)))
    assert frame["debiased_error"].iloc[-1] == pytest.approx(0.0, abs=1e-12)
    # A day that arrives before there is enough history has no estimate at all,
    # rather than an estimate made from two days.
    assert frame["debiased_error"].iloc[: verify.DEBIAS_MIN_HISTORY].isna().all()


def test_a_shift_confined_to_the_future_is_not_removed_from_the_present():
    # The bias appears only on the final day; an honest estimate cannot know it.
    errors = np.concatenate([np.zeros(20), [5.0]])
    frame = verify.out_of_sample_debias(_series(errors))
    assert frame["debiased_error"].iloc[-1] == pytest.approx(5.0)


def test_out_of_sample_debiasing_leaves_more_error_than_the_sample_s_own_mean():
    rng = np.random.default_rng(7)
    errors = rng.normal(-1.5, 1.0, size=200)
    frame = verify.out_of_sample_debias(_series(errors))
    left = frame["debiased_error"].dropna().to_numpy()
    scored = frame.loc[frame["debiased_error"].notna(), "error"].to_numpy()
    assert np.sqrt(np.mean(left**2)) > np.std(scored)


def test_each_station_and_lead_gets_its_own_offset():
    warm = _series(np.full(40, 3.0), station="a")
    cold = _series(np.full(40, -3.0), station="b")
    frame = verify.out_of_sample_debias(pd.concat([warm, cold], ignore_index=True))
    left = frame.dropna(subset=["debiased_error"])
    assert left["debiased_error"].abs().max() == pytest.approx(0.0, abs=1e-12)
    assert set(left["station"]) == {"a", "b"}


# --------------------------------------------------------------------------
# Multiplicity
# --------------------------------------------------------------------------


def test_holm_is_stricter_than_looking_at_each_test_alone():
    p = [0.001, 0.04, 0.2, 0.5]
    assert sum(x <= 0.05 for x in p) == 2
    assert verify.holm_reject(p) == [True, False, False, False]


def test_holm_stops_at_the_first_failure_even_if_a_later_p_is_small():
    # 0.03 would clear its own 0.05/2 step, but the step above it failed.
    assert verify.holm_reject([0.049, 0.03]) == [False, False]


def test_holm_keeps_the_order_of_the_input():
    assert verify.holm_reject([0.9, 0.0001, 0.8]) == [False, True, False]


def test_a_single_test_is_its_own_family():
    assert verify.holm_reject([0.04]) == [True]


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
    assert verify.scores(raw[raw.model == "cherry"]["error"])["rmse"] < 0.2

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


def test_daily_reduction_discards_days_with_too_few_reports():
    hours = pd.date_range("2025-06-01", periods=30, freq="h")
    frame = pd.DataFrame({"time": hours, "value": np.arange(30.0), "station": "bj"})
    out = fetch.daily(frame, "max", min_hours=18)
    # The first day has 24 hours and survives; the second has 6 and does not.
    assert len(out) == 1
    assert out["daily_value"].iloc[0] == pytest.approx(23.0)


def test_daily_reduction_keeps_model_and_lead_apart():
    hours = pd.date_range("2025-06-01", periods=24, freq="h")
    frame = pd.concat(
        [
            pd.DataFrame(
                {"time": hours, "value": 10.0, "station": "bj", "model": "a", "lead_days": 1}
            ),
            pd.DataFrame(
                {"time": hours, "value": 20.0, "station": "bj", "model": "a", "lead_days": 2}
            ),
        ]
    )
    out = fetch.daily(frame, "max")
    assert len(out) == 2
    assert sorted(out["daily_value"]) == [10.0, 20.0]


def test_temperature_reduces_by_maximum_and_wind_by_mean():
    """The reduction is a modelling choice, not a detail: cooling load follows
    the peak, a wind resource follows the whole day."""
    assert fetch.VARIABLES["temperature_2m"]["reduce"] == "max"
    assert fetch.VARIABLES["wind_speed_10m"]["reduce"] == "mean"


def test_knots_convert_to_metres_per_second():
    # 10 kt is 5.14 m/s; getting this backwards doubles a wind resource.
    assert 10 * fetch.KNOTS_TO_MS == pytest.approx(5.14444, abs=1e-4)


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
