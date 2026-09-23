"""The hub-height page's one real claim is a difference between two tables, so
what has to be pinned is that the two tables are built on the same days.
"""
from __future__ import annotations

import pandas as pd
import pytest

from aiwp import hub_height


def _frame(rows) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["station", "date", "lead_days", "model", "error"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def test_shared_days_is_the_intersection_not_the_union():
    a = _frame([["s", "2025-01-01", 1, "m", 0.0], ["s", "2025-01-02", 1, "m", 0.0]])
    b = _frame([["s", "2025-01-02", 1, "m", 0.0], ["s", "2025-01-03", 1, "m", 0.0]])
    shared = hub_height.shared_days(a, b)
    assert len(shared) == 1
    assert shared[0][1] == pd.Timestamp("2025-01-02")


def test_shared_days_keeps_lead_apart():
    # The same day at two leads is two different comparisons; collapsing them
    # would let a model archived to day 1 borrow another model's day 5.
    a = _frame([["s", "2025-01-01", 1, "m", 0.0]])
    b = _frame([["s", "2025-01-01", 5, "m", 0.0]])
    assert len(hub_height.shared_days(a, b)) == 0


def test_card_ranks_by_rmse_and_reports_its_own_count():
    rows = []
    for day in pd.date_range("2025-01-01", periods=10, freq="D"):
        rows.append(["s", day, 1, "good", 0.1])
        rows.append(["s", day, 1, "bad", 2.0])
    card = hub_height.card(_frame(rows))
    assert list(card.index) == ["good", "bad"]
    assert int(card.loc["good", "n"]) == 10


def test_the_four_models_are_the_ones_that_publish_both_heights():
    # A model added to this list without checking the archive would be scored on
    # an empty column, which the common-sample rule turns into an empty table.
    from aiwp.fetch import VARIABLES
    assert hub_height.MODELS == VARIABLES["wind_speed_100m"]["models"]
    assert hub_height.MODELS == VARIABLES["wind_speed_10m_era5"]["models"]
    assert hub_height.ECMWF < set(hub_height.MODELS)
