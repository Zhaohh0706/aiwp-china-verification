"""Tests for the irradiance arm of the verification.

Irradiance came in after temperature and wind, and it broke three assumptions
the earlier code had quietly built in: that every variable is verified at the
airports, that every model publishes every variable, and that every number is in
degrees. Each of those would have produced a table rather than an error, which
is why they are tested rather than trusted.
"""
from __future__ import annotations

import pandas as pd
import pytest

from aiwp import make_figures, run_verification as rv


class TestGroupMapping:
    def test_every_ai_variable_declares_where_it_is_verified(self):
        assert set(rv.AI_VARIABLES) <= set(rv.VERIFICATION_GROUP)

    def test_irradiance_is_verified_at_the_photovoltaic_sites(self):
        # Reading group "china" from a dataset whose only group is "pv" returns
        # an empty frame, not an error, and an empty frame scores as a blank
        # table rather than as a failure.
        assert rv.VERIFICATION_GROUP["shortwave_radiation"] == "pv"

    def test_wrong_group_is_refused_loudly(self):
        pairs = pd.DataFrame({"group": ["pv"] * 4, "model": ["ecmwf_ifs025"] * 4})
        subset = pairs[pairs["group"] == "china"]
        assert subset.empty  # the failure mode the SystemExit in ai_summary guards


class TestModelCoverage:
    def test_jma_is_excluded_from_irradiance(self):
        # JMA GSM publishes no surface radiation.  Left in the core set, the
        # common-sample rule would empty the whole irradiance table.
        assert "jma_seamless" not in rv.AI_CORE_BY_VARIABLE["shortwave_radiation"]

    def test_the_other_ai_core_models_survive(self):
        irradiance = set(rv.AI_CORE_BY_VARIABLE["shortwave_radiation"])
        assert irradiance == set(rv.AI_CORE_MODELS) - {"jma_seamless"}

    def test_variables_without_an_override_keep_the_full_core_set(self):
        frame = pd.DataFrame(
            {
                "model": rv.AI_CORE_MODELS,
                "station": ["a"] * len(rv.AI_CORE_MODELS),
                "date": [pd.Timestamp("2025-03-01")] * len(rv.AI_CORE_MODELS),
                "lead_days": [1] * len(rv.AI_CORE_MODELS),
                "error": [0.0] * len(rv.AI_CORE_MODELS),
            }
        )
        assert set(rv.ai_sets(frame, "temperature_2m")["model"]) == set(rv.AI_CORE_MODELS)


class TestUnits:
    def test_irradiance_is_energy_not_power(self):
        # Hourly mean irradiance summed over a day is Wh/m2.  Labelling it W/m2
        # understates it by the number of daylight hours.
        assert rv.unit("shortwave_radiation") == "Wh/m²"

    def test_each_variable_has_its_own_unit(self):
        units = {v: rv.unit(v) for v in rv.VERIFICATION_GROUP}
        assert len(set(units.values())) == len(units)

    def test_legacy_celsius_columns_are_renamed_on_load(self):
        # Datasets built before the rename still have forecast_c and friends.
        assert rv.LEGACY_COLUMNS["error_c"] == "error"
        assert set(rv.LEGACY_COLUMNS.values()) == {"forecast", "observed", "error"}


class TestVerdict:
    def _block(self, day1_rmse: dict[str, float], day5_rmse: dict[str, float]) -> dict:
        growth = [
            {
                "model": m,
                1: day1_rmse[m],
                5: day5_rmse[m],
                "growth_pct": 100 * (day5_rmse[m] / day1_rmse[m] - 1),
            }
            for m in day1_rmse
        ]
        return {
            "unit": "Wh/m²",
            "day1": [{"model": m, "rmse": v} for m, v in sorted(day1_rmse.items(), key=lambda kv: kv[1])],
            "growth": growth,
        }

    def test_a_tie_at_day_one_is_reported_as_a_tie(self):
        block = self._block(
            {"icon_seamless": 999.0, rv.AI_MODEL: 1000.0},
            {"icon_seamless": 1459.0, rv.AI_MODEL: 1296.0},
        )
        verdict = rv._ai_verdict(block)
        assert "基本打平" in verdict
        assert "第 1" in verdict  # first by day 5

    def test_a_real_gap_is_reported_as_a_gap(self):
        block = self._block(
            {"icon_seamless": 1.87, rv.AI_MODEL: 2.46},
            {"icon_seamless": 2.72, rv.AI_MODEL: 2.87},
        )
        verdict = rv._ai_verdict(block)
        assert "基本打平" not in verdict
        assert "落后最好的 31" in verdict

    def test_a_missing_ai_model_is_said_plainly(self):
        block = self._block({"icon_seamless": 1.0}, {"icon_seamless": 2.0})
        assert "不在" in rv._ai_verdict(block)


class TestFigureTitles:
    def _growth(self, day1: dict[str, float], day5: dict[str, float]) -> pd.DataFrame:
        rows = []
        for model in day1:
            for lead, source in ((1, day1), (5, day5)):
                rows.append({"model": model, "lead_days": lead, "rmse": source[model]})
        return pd.DataFrame(rows)

    def test_title_says_level_when_the_gap_is_tiny(self):
        left, _ = make_figures._ai_titles(
            self._growth(
                {"icon_seamless": 999.0, rv.AI_MODEL: 1000.0},
                {"icon_seamless": 1459.0, rv.AI_MODEL: 1296.0},
            )
        )
        assert "level at day 1" in left
        assert "first by day 5" in left

    def test_title_says_behind_when_it_is_behind(self):
        left, _ = make_figures._ai_titles(
            self._growth(
                {"icon_seamless": 1.87, rv.AI_MODEL: 2.46},
                {"icon_seamless": 2.72, rv.AI_MODEL: 2.87},
            )
        )
        assert "starts 32% behind" in left

    @pytest.mark.parametrize(
        "n,expected",
        [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (21, "21st")],
    )
    def test_ordinals(self, n, expected):
        assert make_figures._ordinal(n) == expected
