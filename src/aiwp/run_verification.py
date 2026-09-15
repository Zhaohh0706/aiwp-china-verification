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
from .fetch import MODEL_LABEL, VARIABLES as VARIABLE_SPEC

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"

# The two variables verified so far, each against a real station observation.
VARIABLES = {
    "temperature_2m": ROOT / "data" / "pairs.parquet",
    "wind_speed_10m": ROOT / "data" / "pairs_wind_speed_10m.parquet",
}

# The AI window is a separate dataset rather than a subset, because AIFS only
# enters the archive on 2025-02-21 and the physics models must be scored on the
# same months for the comparison to mean anything.
AI_VARIABLES = {
    "temperature_2m": ROOT / "data" / "pairs_ai.parquet",
    "wind_speed_10m": ROOT / "data" / "pairs_wind_speed_10m_ai.parquet",
    "shortwave_radiation": ROOT / "data" / "pairs_shortwave_radiation_pv_ai.parquet",
}

# Which set of sites each variable is verified at.  Temperature and wind are
# scored against airport station reports; irradiance has no station instrument
# at these places, so it is scored at the eight photovoltaic sites against a
# satellite retrieval.  Reading the wrong group would silently return an empty
# frame rather than an error, so the mapping is written down.
VERIFICATION_GROUP = {
    "temperature_2m": "china",
    "wind_speed_10m": "china",
    "shortwave_radiation": "pv",
}

# Six physics models with full lead coverage, plus the one AI model archived
# for the whole window.  GraphCast covers 37 to 59 per cent of days and is
# reported separately rather than dropped or averaged over its good days.
AI_CORE_MODELS = [
    "ecmwf_ifs025", "icon_seamless", "gfs_seamless",
    "jma_seamless", "gem_global", "cma_grapes_global",
    "ecmwf_aifs025_single",
]

# JMA GSM publishes no surface radiation through this archive.  Leaving it in
# the core set would let the common-sample rule empty the irradiance table and
# make a product that does not exist look like a data fault.
AI_CORE_BY_VARIABLE = {
    "shortwave_radiation": [m for m in AI_CORE_MODELS if m != "jma_seamless"],
}

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


#: Columns once carried a ``_c`` suffix from the days when temperature was the
#: only variable.  Two of the three variables are no longer in degrees, so the
#: suffix was dropped; datasets built before that still have the old names.
LEGACY_COLUMNS = {
    "forecast_c": "forecast", "observed_c": "observed", "error_c": "error",
}


def load(variable: str = "temperature_2m", ai: bool = False) -> pd.DataFrame:
    path = (AI_VARIABLES if ai else VARIABLES)[variable]
    if not path.exists():
        raise SystemExit(
            f"run `python -m aiwp.build_dataset --variable {variable}"
            f"{' --ai' if ai else ''}` first"
        )
    return pd.read_parquet(path).rename(columns=LEGACY_COLUMNS)


def unit(variable: str) -> str:
    """The unit the numbers for this variable are in.

    Three variables, three units. A scorecard that prints 1418 without saying
    Wh/m² next to it invites the reader to carry over the degrees they saw on
    the previous table.
    """
    return VARIABLE_SPEC[variable]["unit"]


def available(ai: bool = False) -> list[str]:
    source = AI_VARIABLES if ai else VARIABLES
    return [name for name, path in source.items() if path.exists()]


def ai_sets(pairs: pd.DataFrame, variable: str = "temperature_2m") -> pd.DataFrame:
    """Common sample over the physics models plus AIFS, for one variable."""
    models = AI_CORE_BY_VARIABLE.get(variable, AI_CORE_MODELS)
    return verify.common_sample(pairs[pairs["model"].isin(models)])


def ai_summary() -> dict:
    """How AIFS places against the physics models, and how that changes with lead.

    The headline is not the day-1 ranking. It is the growth rate: a model that
    starts behind and degrades more slowly is a different product from one that
    starts ahead and falls away, and a scorecard quoted at a single lead hides
    exactly that.
    """
    out: dict = {}
    for variable in available(ai=True):
        pairs = load(variable, ai=True)
        group = VERIFICATION_GROUP[variable]
        subset = pairs[pairs["group"] == group]
        if subset.empty:
            raise SystemExit(
                f"{variable}: no rows in group {group!r}; the dataset holds "
                f"{sorted(pairs['group'].unique())}"
            )
        scored = ai_sets(subset, variable)
        day1 = verify.scorecard(scored[scored["lead_days"] == 1]).sort_values("rmse")
        growth = (
            verify.error_growth(scored)
            .pivot(index="model", columns="lead_days", values="rmse")
        )
        growth["growth_pct"] = 100.0 * (growth[growth.columns.max()] / growth[1] - 1.0)
        out[variable] = {
            "group": group,
            "unit": unit(variable),
            "sites": int(scored["station"].nunique()),
            "days": int(scored["date"].nunique()),
            "pairs_day1": int((scored["lead_days"] == 1).sum()),
            "day1": day1.to_dict("records"),
            "growth": growth.reset_index().to_dict("records"),
            "paired_vs_ecmwf": verify.rank_table(scored, lead=1).to_dict("records"),
        }
    return out


def ranking_across_variables() -> pd.DataFrame:
    """Each model's rank on every verified variable, China, day 1.

    The single most useful table in the study, because the answer to "which
    model is best" turns out to depend entirely on which variable you asked
    about — and a buyer choosing a provider on one headline number is choosing
    wrong for every other use they have.
    """
    columns = {}
    for variable in available():
        pairs = load(variable)
        china = sets(pairs[pairs["group"] == "china"])["core"]
        board = (
            verify.scorecard(china[china["lead_days"] == 1])
            .sort_values("rmse")
            .reset_index(drop=True)
        )
        columns[variable] = pd.Series(board.index + 1, index=board["model"])
    table = pd.DataFrame(columns)
    if len(table.columns) == 2:
        first, second = table.columns
        table["rank_change"] = table[first] - table[second]
    return table.sort_values(table.columns[0])


def sets(pairs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    core = pairs[pairs["model"].isin(CORE_MODELS)]
    wide = pairs[pairs["lead_days"] <= 3]
    return {
        "core": verify.common_sample(core),
        "wide": verify.common_sample(wide),
    }


def main(variable: str = "temperature_2m") -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    pairs = load(variable)
    results: dict = {"variable": variable, "dataset": {}}

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
            board.to_csv(REPORTS / f"scorecard_{variable}_{key}.csv", index=False)
            results[key]["scorecard_day1"] = (
                board[board["lead_days"] == 1].to_dict("records")
            )

    china_core = sets(pairs[pairs["group"] == "china"])["core"]
    control_core = sets(pairs[pairs["group"] == "control"])["core"]

    # Headline: every model against ECMWF at day 1, paired.
    ranking = verify.rank_table(china_core, lead=1, reference=REFERENCE)
    ranking.to_csv(REPORTS / f"paired_vs_ecmwf_china_day1_{variable}.csv", index=False)
    results["paired_vs_ecmwf_china_day1"] = ranking.to_dict("records")

    # Does bias explain the ranking?  Compare raw and debiased RMSE.
    day1 = china_core[china_core["lead_days"] == 1]
    bias_effect = verify.scorecard(day1)[["model", "bias", "rmse", "debiased_rmse"]]
    bias_effect["rank_raw"] = bias_effect["rmse"].rank().astype(int)
    bias_effect["rank_debiased"] = bias_effect["debiased_rmse"].rank().astype(int)
    bias_effect["rank_change"] = bias_effect["rank_raw"] - bias_effect["rank_debiased"]
    bias_effect = bias_effect.sort_values("rmse")
    bias_effect.to_csv(REPORTS / f"bias_vs_skill_china_day1_{variable}.csv", index=False)
    results["bias_vs_skill_china_day1"] = bias_effect.to_dict("records")

    # Is the cold bias a China effect or a global one?
    results["mean_bias_by_group_day1"] = {
        "china": float(day1["error"].mean()),
        "control": float(
            control_core[control_core["lead_days"] == 1]["error"].mean()
        ),
    }

    (REPORTS / f"results_{variable}.json").write_text(
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
        board[["model", "n", "bias", "mae", "rmse", "debiased_rmse", "large_error_pct"]]
        .round(3)
        .sort_values("rmse")
        .to_string(index=False)
    )

    print("\n=== 与 ECMWF IFS 的配对比较（负数 = 优于 ECMWF），自举 95% 区间 ===")
    ranked = ranking.copy()
    ranked["model"] = ranked["model_a"].map(lambda m: MODEL_LABEL.get(m, m))
    print(
        ranked[["model", "n", "mean_diff_abs_error", "ci_low", "ci_high", "a_is_better"]]
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


AI_MODEL = "ecmwf_aifs025_single"


def _ai_verdict(block: dict) -> str:
    """Say where the AI model placed, from the numbers rather than from memory.

    An earlier version of this function ended with a fixed sentence saying AIFS
    does not lead at day 1 but degrades most slowly. That was true of
    temperature, and it was printed under the irradiance table too, where AIFS
    is second at day 1. A conclusion that does not read its own table is not a
    conclusion.
    """
    board = pd.DataFrame(block["day1"]).reset_index(drop=True)
    if AI_MODEL not in set(board["model"]):
        return "AIFS 不在这个变量的共同样本里。"

    rank = int(board.index[board["model"] == AI_MODEL][0]) + 1
    best = float(board["rmse"].min())
    ai_rmse = float(board.loc[board["model"] == AI_MODEL, "rmse"].iloc[0])
    behind = 100.0 * (ai_rmse / best - 1.0)

    table = pd.DataFrame(block["growth"]).set_index("model")
    growth = table["growth_pct"]
    growth_rank = int(growth.rank().loc[AI_MODEL])
    unit_label = block["unit"]

    # Where it lands at the far end of the archive.  A model that ties at day 1
    # and wins at day 5 is the whole argument for AI forecasting, and a verdict
    # that reports only the day-1 rank and the growth percentage states both
    # halves of it without ever putting them together.
    leads = [c for c in table.columns if isinstance(c, (int, float))]
    last = max(leads)
    far_rank = int(table[last].rank().loc[AI_MODEL])

    place = f"提前 1 天排第 {rank}"
    if rank == 1:
        place += "（最好）"
    elif behind < 2.0:
        place += f"，与最好的只差 {behind:.1f}%（{ai_rmse - best:+.0f} {unit_label}），基本打平"
    else:
        place += f"，落后最好的 {behind:.1f}%"

    pace = (
        f"误差增长在 {len(growth)} 个模式里最慢"
        if growth_rank == 1
        else f"误差增长排第 {growth_rank}（越小越好）"
    )
    far = (
        f"提前 {last} 天升到第 1（全场最好）"
        if far_rank == 1
        else f"提前 {last} 天排第 {far_rank}"
    )
    return f"AIFS {place}；{far}；{pace}。"


def run_ai() -> None:
    summary = ai_summary()
    if not summary:
        return
    (REPORTS / "results_ai_window.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=float), encoding="utf-8"
    )
    for variable, block in summary.items():
        unit_label = block["unit"]
        print(
            f"\n{'=' * 78}\nAI 窗口 — {variable}"
            f"（{block['days']} 天，{block['sites']} 个站点，单位 {unit_label}）\n{'=' * 78}"
        )
        board = pd.DataFrame(block["day1"]).reset_index(drop=True)
        board.insert(0, "rank", board.index + 1)
        board["model"] = board["model"].map(lambda m: MODEL_LABEL.get(m, m))
        # Irradiance numbers run to four figures; degrees need the decimals.
        digits = 0 if board["rmse"].max() > 100 else 3
        print(
            board[["rank", "model", "bias", "mae", "rmse", "debiased_rmse"]]
            .round(digits).to_string(index=False)
        )
        growth = pd.DataFrame(block["growth"]).set_index("model")
        growth.index = [MODEL_LABEL.get(m, m) for m in growth.index]
        print(f"\n误差增长 RMSE（提前 1 天 -> 5 天，{unit_label}）:")
        print(growth.round(2).sort_values("growth_pct").to_string())
        print(f"\n{_ai_verdict(block)}")

    print(
        "\n同一个 AI 模式在不同变量上的位置并不一样，"
        "只报单一时效、单一变量的记分牌会把这件事整个盖掉。"
    )


def run_all() -> None:
    for variable in available():
        print(f"\n{'=' * 78}\n{variable}\n{'=' * 78}")
        main(variable)

    run_ai()

    table = ranking_across_variables()
    if len(table.columns) > 1:
        table.to_csv(REPORTS / "rank_across_variables.csv")
        shown = table.copy()
        shown.index = [MODEL_LABEL.get(m, m) for m in shown.index]
        print(f"\n{'=' * 78}\n同一批模式在两个变量上的名次\n{'=' * 78}")
        print(shown.to_string())
        print(
            "\n名次随变量而变，且变化很大。用单一总分挑供应商，"
            "对另一半用途就是挑错了。"
        )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in VARIABLES:
        main(sys.argv[1])
    else:
        run_all()
