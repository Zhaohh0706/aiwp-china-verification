"""Scores, and the two questions a scorecard has to survive.

**Is the difference real?** Two models verified on the same 400 days are not two
independent samples; they saw the same weather. Comparing their RMSEs as if they
were independent overstates significance badly. So differences are tested
paired: the per-day difference in absolute error between two models, with a
bootstrap confidence interval over days. A model is only called better when that
interval excludes zero.

**Is the sample the same?** Models drop out — Météo-France and UKMO have gaps in
the archive — and a mean over whatever days happened to be present is not
comparable across models. Every scorecard here is computed on the intersection:
the days on which every model in the comparison produced a forecast.

Bias is reported separately from error throughout. A model that is two degrees
cold every single day has an RMSE of two and is trivially fixable with a
constant; a model that is two degrees out at random is not. Conflating them is
how a systematically-biased model gets ranked next to a noisy one.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BOOTSTRAP_SAMPLES = 2000
RANDOM_SEED = 42

# A miss of this size or more is an operational problem, not a rounding issue.
LARGE_ERROR_C = 3.0


def scores(errors: np.ndarray) -> dict:
    errors = np.asarray(errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    if errors.size == 0:
        return {"n": 0}
    return {
        "n": int(errors.size),
        "bias": float(np.mean(errors)),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
        # Error left after removing a constant offset: what a calibration step
        # could not fix.
        "debiased_rmse": float(np.std(errors)),
        "p95_abs": float(np.percentile(np.abs(errors), 95)),
        "large_error_pct": float(100.0 * np.mean(np.abs(errors) >= LARGE_ERROR_C)),
    }


def common_sample(pairs: pd.DataFrame, keys=("station", "date", "lead_days")) -> pd.DataFrame:
    """Restrict to rows where every model present has a forecast.

    Without this, a model that only ran on easy days would look good for it.
    """
    models = sorted(pairs["model"].unique())
    counts = pairs.groupby(list(keys))["model"].nunique()
    complete = counts[counts == len(models)].index
    return pairs.set_index(list(keys)).loc[complete].reset_index()


def scorecard(pairs: pd.DataFrame, by=("model", "lead_days")) -> pd.DataFrame:
    rows = []
    for key, group in pairs.groupby(list(by)):
        entry = dict(zip(by, key if isinstance(key, tuple) else (key,)))
        entry.update(scores(group["error"].to_numpy()))
        rows.append(entry)
    return pd.DataFrame(rows).sort_values(list(by)).reset_index(drop=True)


def paired_difference(
    pairs: pd.DataFrame, model_a: str, model_b: str, lead: int | None = None
) -> dict:
    """Is model_a's absolute error smaller than model_b's, on shared days?

    Returns the mean paired difference in absolute error and a bootstrap
    interval over days. Negative means model_a is closer to the observation.
    """
    frame = pairs if lead is None else pairs[pairs["lead_days"] == lead]
    wide = frame.pivot_table(
        index=["station", "date"], columns="model", values="error", aggfunc="first"
    )
    if model_a not in wide or model_b not in wide:
        return {"n": 0}
    both = wide[[model_a, model_b]].dropna()
    if both.empty:
        return {"n": 0}

    difference = both[model_a].abs().to_numpy() - both[model_b].abs().to_numpy()
    rng = np.random.default_rng(RANDOM_SEED)
    draws = rng.choice(difference, size=(BOOTSTRAP_SAMPLES, difference.size), replace=True)
    means = draws.mean(axis=1)
    low, high = np.percentile(means, [2.5, 97.5])

    return {
        "model_a": model_a,
        "model_b": model_b,
        "lead_days": lead,
        "n": int(difference.size),
        "mean_diff_abs_error": float(difference.mean()),
        "ci_low": float(low),
        "ci_high": float(high),
        "a_is_better": bool(high < 0.0),
        "b_is_better": bool(low > 0.0),
    }


def rank_table(pairs: pd.DataFrame, lead: int, reference: str = "ecmwf_ifs025") -> pd.DataFrame:
    """Every model against one reference at a given lead, paired and bootstrapped."""
    rows = []
    for model in sorted(pairs["model"].unique()):
        if model == reference:
            continue
        rows.append(paired_difference(pairs, model, reference, lead))
    frame = pd.DataFrame([r for r in rows if r.get("n")])
    return frame.sort_values("mean_diff_abs_error").reset_index(drop=True)


def error_growth(pairs: pd.DataFrame) -> pd.DataFrame:
    """RMSE by lead, the curve every verification report opens with."""
    return (
        pairs.groupby(["model", "lead_days"])["error"]
        .apply(lambda e: float(np.sqrt(np.mean(np.square(e)))))
        .rename("rmse")
        .reset_index()
    )


def lead_consistency(pairs: pd.DataFrame, tolerance: float = 0.10) -> list[dict]:
    """Model-lead combinations whose forecasts do not share a climate with day 1.

    Whatever a model gets wrong about tomorrow, its forecasts for a given date made
    one day ahead and five days ahead describe the same season at the same place,
    so their means agree to within a few per cent.  When they do not, the archive
    is not serving the same quantity at both leads - accumulated values as means,
    a coarser output interval resampled badly - and an error computed on that lead
    measures the archive.  In mid-2026 the irradiance archive has GEM running 30%
    high beyond day 3 and ARPEGE 8 to 13% high at days 2 and 3, while every other
    model is within 1%.
    """
    value = "forecast" if "forecast" in pairs else "forecast_c"
    wide = pairs.pivot_table(index=["model", "station", "date"], columns="lead_days", values=value, aggfunc="first")
    flagged = []
    for lead in [c for c in wide.columns if c != 1]:
        both = wide[[1, lead]].dropna()
        for model, group in both.groupby(level="model"):
            base = group[1].mean()
            if len(group) < 30 or not np.isfinite(base) or base == 0:
                continue
            ratio = float(group[lead].mean() / base)
            if abs(ratio - 1.0) > tolerance:
                flagged.append({"model": model, "lead_days": int(lead), "ratio_to_day1": round(ratio, 3), "n": int(len(group))})
    return flagged
