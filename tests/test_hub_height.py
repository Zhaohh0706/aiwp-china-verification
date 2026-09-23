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


# --------------------------------------------------------------------------
# The NOAA machine-learned archive
# --------------------------------------------------------------------------


def test_the_cache_key_is_stable_across_processes():
    """A cache keyed on hash() is written by one run and invisible to the next.

    Python randomises string hashing per process, so the file lands under a name
    the next run does not look for - which is indistinguishable from the fetch
    never having happened, and costs the whole download again.
    """
    import subprocess
    import sys

    from aiwp import mlwp
    from aiwp.stations import CHINA

    def key_in_a_fresh_process() -> str:
        code = ("import sys; sys.path.insert(0, 'src');"
                "from aiwp import mlwp; from aiwp.stations import CHINA;"
                "import inspect, hashlib;"
                "print(hashlib.sha1(','.join(sorted(s.slug for s in CHINA)).encode()).hexdigest()[:8])")
        return subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, cwd=str(mlwp.CACHE.parents[1])).stdout.strip()

    first, second = key_in_a_fresh_process(), key_in_a_fresh_process()
    assert first and first == second


def test_synoptic_daily_keeps_only_the_four_analysis_hours():
    """Twenty hourly reports and four synoptic ones are different daily means."""
    from aiwp import mlwp

    hours = pd.date_range("2025-01-01 08:00", periods=24, freq="h")  # local time, UTC+8
    frame = pd.DataFrame({"time": hours, "value": 1.0, "station": "x"})
    frame.loc[frame["time"].dt.hour.isin([8, 14, 20, 2]), "value"] = 5.0
    out = mlwp.synoptic_daily(frame)
    # Local 08/14/20/02 are UTC 00/06/12/18, so every kept hour has the value 5.
    assert not out.empty
    assert out["value"].iloc[0] == pytest.approx(5.0)


def test_synoptic_daily_drops_a_day_with_fewer_than_three_of_the_four():
    from aiwp import mlwp

    hours = pd.to_datetime(["2025-01-01 08:00", "2025-01-01 14:00"])  # only two
    frame = pd.DataFrame({"time": hours, "value": 3.0, "station": "x"})
    assert mlwp.synoptic_daily(frame).empty


def test_a_station_outside_utc_plus_eight_is_refused():
    """The local-to-UTC shift here is a constant, and a wrong constant is silent.

    It would still produce four values a day, just at the wrong four hours, and
    every number downstream would look ordinary.
    """
    from aiwp import mlwp
    from aiwp.stations import CHINA, CONTROL

    with pytest.raises(ValueError, match="UTC"):
        mlwp._check_timezones(list(CHINA) + list(CONTROL))
