"""The checks that keep an archive fault from turning into a ranking."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aiwp import verify


def _pairs(scale_by_lead: dict[int, float], model: str = "m", days: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2026-05-01", periods=days)
    rng = np.random.default_rng(1)
    base = 6000 + 1500 * rng.standard_normal(days)
    rows = []
    for lead, scale in scale_by_lead.items():
        rows.append(pd.DataFrame({"model": model, "station": "s", "date": dates, "lead_days": lead,
                                  "forecast": base * scale, "observed": base, "error": base * scale - base}))
    return pd.concat(rows, ignore_index=True)


def test_a_lead_whose_climate_differs_from_day_one_is_flagged():
    pairs = pd.concat([_pairs({1: 1.0, 3: 1.01, 5: 1.30}, "gem"), _pairs({1: 1.0, 3: 0.99, 5: 1.0}, "ifs")])
    flagged = verify.lead_consistency(pairs)
    assert [(f["model"], f["lead_days"]) for f in flagged] == [("gem", 5)]
    assert flagged[0]["ratio_to_day1"] == 1.3


def test_a_model_that_is_merely_wrong_is_not_flagged():
    # a 6% bias that is the same at every lead is a model property, not an archive fault
    pairs = _pairs({1: 1.06, 3: 1.06, 5: 1.06})
    assert verify.lead_consistency(pairs) == []


def test_short_records_are_not_judged():
    assert verify.lead_consistency(_pairs({1: 1.0, 5: 1.5}, days=10)) == []
