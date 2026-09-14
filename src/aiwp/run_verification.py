"""Produce the scorecards, the significance tests and the figures.

Two comparison sets, because the archive does not give every model the same
coverage and averaging over whatever happened to be present is how scorecards
mislead:

* **core** — the six models that publish all five lead days. This is the set the
  lead-growth curves and the headline ranking use.
* **wide** — all eight, restricted to leads 1 to 3, because Météo-France ARPEGE
  is only archived out to day 3. UKMO is in this set despite a 60 per cent
  record, on the common sample only.

Every ranking is paired: the per-day difference in absolute error against a
reference model, with a bootstrap interval over days. Two models verified on the
same days are not independent samples, and treating them as such turns a
0.05-degree difference into a discovery.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import verify
from .fetch import MODEL_LABEL

ROOT = Path(__file__).resolve().parents[2]
PAIRS = ROOT / "data" / "pairs.parquet"
REPORTS = ROOT / "reports"

# Six models with the full five-day archive.
CORE_MODELS = [
    "ecmwf_ifs025",
    "icon_seamless",
    "gfs_seamless",
    "jma_seamless",
    "gem_global",
    "cma_grapes_global",
]
REFERENCE = "ecmwf_ifs025"


def label(frame: pd.DataFrame, column: str = "model") -> pd.DataFrame:
    out = frame.copy()
    out[column] = out[column].map(lambda m: MODEL_LABEL.get(m, m))
    return out


def load() -> pd.DataFrame:
    if not PAIRS.exists():
        raise SystemExit("run `python -m aiwp.build_dataset` first")
    return pd.read_parquet(PAIRS)


def sets(pairs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    core = pairs[pairs["model"].isin(CORE_MODELS)]
    wide = pairs[pairs["lead_days"] <= 3]
    return {
        "core": verify.common_sample(core),
        "wide": verify.common_sample(wide),
    }


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    pairs = load()
    results: dict = {"dataset": {}}

    results["dataset"] = {
        "pairs": int(len(pairs)),
        "stations": int(pairs["station"].nunique()),
        "days": int(pairs["date"].nunique()),
        "first_date": str(pairs["date"].min())[:10],
        "last_date": str(pairs["date"].max())[:10],
        "models": sorted(pairs["model"].unique()),
        "leads": sorted(int(x) for x in pairs["lead_days"].unique()),
    }

    for group in ("china", "control"):
        subset = pairs[pairs["group"] == group]
        for name, frame in sets(subset).items():
            key = f"{group}_{name}"
            results[key] = {
                "pairs": int(len(frame)),
                "days": int(frame["date"].nunique()),
                "stations": int(frame["station"].nunique()),
            }
            board = verify.scorecard(frame)
            board.to_csv(REPORTS / f"scorecard_{key}.csv", index=False)
            results[key]["scorecard_day1"] = (
                board[board["lead_days"] == 1].to_dict("records")
            )

    china_core = sets(pairs[pairs["group"] == "china"])["core"]
    control_core = sets(pairs[pairs["group"] == "control"])["core"]

    # Headline: every model against ECMWF at day 1, paired.
    ranking = verify.rank_table(china_core, lead=1, reference=REFERENCE)
    ranking.to_csv(REPORTS / "paired_vs_ecmwf_china_day1.csv", index=False)
    results["paired_vs_ecmwf_china_day1"] = ranking.to_dict("records")

    # Does bias explain the ranking?  Compare raw and debiased RMSE.
    day1 = china_core[china_core["lead_days"] == 1]
    bias_effect = verify.scorecard(day1)[["model", "bias_c", "rmse_c", "debiased_rmse_c"]]
    bias_effect["rank_raw"] = bias_effect["rmse_c"].rank().astype(int)
    bias_effect["rank_debiased"] = bias_effect["debiased_rmse_c"].rank().astype(int)
    bias_effect["rank_change"] = bias_effect["rank_raw"] - bias_effect["rank_debiased"]
    bias_effect = bias_effect.sort_values("rmse_c")
    bias_effect.to_csv(REPORTS / "bias_vs_skill_china_day1.csv", index=False)
    results["bias_vs_skill_china_day1"] = bias_effect.to_dict("records")

    # Is the cold bias a China effect or a global one?
    results["mean_bias_by_group_day1"] = {
        "china": float(day1["error_c"].mean()),
        "control": float(
            control_core[control_core["lead_days"] == 1]["error_c"].mean()
        ),
    }

    (REPORTS / "results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=float), encoding="utf-8"
    )

    _print(results, china_core, control_core, bias_effect, ranking)


def _print(results, china_core, control_core, bias_effect, ranking) -> None:
    pd.set_option("display.width", 200)
    d = results["dataset"]
    print(
        f"{d['pairs']:,} pairs | {d['stations']} stations | {d['days']} days "
        f"({d['first_date']} to {d['last_date']}) | leads {d['leads']}\n"
    )

    print("=== 中国站点，提前 1 天，六模式共同样本 ===")
    board = label(verify.scorecard(china_core[china_core["lead_days"] == 1]))
    print(
        board[["model", "n", "bias_c", "mae_c", "rmse_c", "debiased_rmse_c", "large_error_pct"]]
        .round(3)
        .sort_values("rmse_c")
        .to_string(index=False)
    )

    print("\n=== 与 ECMWF IFS 的配对比较（负数 = 优于 ECMWF），自举 95% 区间 ===")
    ranked = ranking.copy()
    ranked["model"] = ranked["model_a"].map(lambda m: MODEL_LABEL.get(m, m))
    print(
        ranked[["model", "n", "mean_diff_abs_error_c", "ci_low", "ci_high", "a_is_better"]]
        .round(3)
        .to_string(index=False)
    )

    print("\n=== 去掉固定偏差之后，排名怎么变 ===")
    shown = label(bias_effect)
    print(shown.round(3).to_string(index=False))

    bias = results["mean_bias_by_group_day1"]
    print(
        f"\n所有模式的平均偏差：中国站点 {bias['china']:+.2f} °C，"
        f"对照站点 {bias['control']:+.2f} °C"
    )
    print(f"\n结果写入 {REPORTS}")


if __name__ == "__main__":
    main()
