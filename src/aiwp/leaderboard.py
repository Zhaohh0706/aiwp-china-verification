"""A leaderboard for the provinces that carry China's wind and solar fleets.

The main study ranks models at nine airports chosen for coverage of the country.
A plant operator needs the ranking where the plants are.  This module scores the
same models on two energy-province sets - twelve airports across the north, the
north-east and the north-west for 10 m wind speed against METAR, and ten points
inside PV-base counties for daily irradiation against satellite retrieval - and
writes the result as one dated page, so that it can be regenerated each month and
the pages compared.

Three tables per variable, each answering a different question:

*   the scorecard at one, three and five days, on the days every model ran;
*   month by month, who was first at day 1 - whether a ranking is stable enough
    to act on, or an average over a year of changing places;
*   station by station, who was first - whether one model can be bought for a
    whole fleet or has to be chosen per site.

Every "first" carries a paired bootstrap against the runner-up, and a lead that
the interval does not support is printed as a tie.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import verify
from .fetch import MODEL_LABEL, VARIABLES
from .stations import BY_SLUG

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "leaderboard"

SETS = {
    "wind_speed_10m": {
        "pairs": ROOT / "data" / "pairs_wind_speed_10m_energy_ai.parquet",
        "title": "10 m 风速（对机场 METAR 实测）",
        "unit": "m/s",
        "digits": 2,
    },
    "shortwave_radiation": {
        "pairs": ROOT / "data" / "pairs_shortwave_radiation_energy_ai.parquet",
        "title": "日辐照量（对葵花卫星反演）",
        "unit": "Wh/m²",
        "digits": 0,
    },
}

# A model has to cover most of the window to be ranked on the common sample;
# one that ran on a quarter of the days would shrink everyone's sample to its own.
MIN_COVERAGE = 0.80


def label(model: str) -> str:
    return MODEL_LABEL.get(model, model)


def eligible(pairs: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Keep models with enough coverage, then restrict to days all of them ran."""
    day1 = pairs[pairs["lead_days"] == 1]
    total = day1.groupby("station")["date"].nunique().sum()
    coverage = (day1.groupby("model").size() / total).round(3).to_dict()
    keep = [m for m, c in coverage.items() if c >= MIN_COVERAGE]
    return verify.common_sample(pairs[pairs["model"].isin(keep)]), coverage


def first_place(pairs: pd.DataFrame, lead: int) -> dict:
    """The lowest RMSE at this lead, and whether the runner-up is distinguishable."""
    card = verify.scorecard(pairs[pairs["lead_days"] == lead], by=("model",)).sort_values("rmse")
    if len(card) < 2:
        return {"model": card.iloc[0]["model"], "tie": False} if len(card) else {}
    best, second = card.iloc[0]["model"], card.iloc[1]["model"]
    test = verify.paired_difference(pairs, best, second, lead)
    return {"model": best, "runner_up": second, "tie": not test.get("a_is_better", False),
            "rmse": float(card.iloc[0]["rmse"]), "n": int(card.iloc[0]["n"])}


def fmt(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}"


def section(variable: str, spec: dict) -> tuple[list[str], dict]:
    pairs = pd.read_parquet(spec["pairs"])
    pairs["date"] = pd.to_datetime(pairs["date"])
    sample, coverage = eligible(pairs)
    digits = spec["digits"]
    stations = sorted(sample["station"].unique())
    start, end = sample["date"].min().date(), sample["date"].max().date()
    mean_obs = float(sample[sample["lead_days"] == 1].drop_duplicates(["station", "date"])["observed"].mean())

    out = [f"## {spec['title']}", "",
           f"{len(stations)} 个点位，{start} 至 {end}，"
           f"共同样本 {sample[sample['lead_days'] == 1].groupby(['station', 'date']).ngroups:,} 个站日。"
           f"观测均值 {fmt(mean_obs, digits)} {spec['unit']}。", ""]
    dropped = {label(m): f"{c:.0%}" for m, c in coverage.items() if c < MIN_COVERAGE}
    if dropped:
        out += ["覆盖不足 80%、未参与排名的模式：" + "，".join(f"{k}（{v}）" for k, v in dropped.items()) + "。", ""]

    # 1. scorecard at three leads
    out += ["**评分表**（均方根误差，越小越好；括号里是去掉常数偏差之后的值）", "",
            "| 模式 | 提前 1 天 | 提前 3 天 | 提前 5 天 | 偏差（提前 1 天） |", "|---|---|---|---|---|"]
    cards = {lead: verify.scorecard(sample[sample["lead_days"] == lead], by=("model",)).set_index("model") for lead in (1, 3, 5)}
    for model in cards[1].sort_values("rmse").index:
        cells = [f"{fmt(cards[l].loc[model, 'rmse'], digits)}（{fmt(cards[l].loc[model, 'debiased_rmse'], digits)}）" for l in (1, 3, 5)]
        out.append(f"| {label(model)} | " + " | ".join(cells) + f" | {cards[1].loc[model, 'bias']:+,.{digits}f} |")
    winner = first_place(sample, 1)
    verdict = "与第二名在统计上分不开" if winner["tie"] else "对第二名的领先是显著的"
    out += ["", f"提前 1 天第一名是 {label(winner['model'])}，{verdict}（第二名 {label(winner['runner_up'])}，按天配对自举）。", ""]

    # 2. month by month
    out += ["**逐月第一名**（提前 1 天）", "", "| 月份 | 第一名 | 均方根误差 | 第二名 | 领先是否显著 |", "|---|---|---|---|---|"]
    monthly = {}
    for month, group in sample.groupby(sample["date"].dt.to_period("M")):
        w = first_place(group, 1)
        if not w:
            continue
        monthly[str(month)] = w
        out.append(f"| {month} | {label(w['model'])} | {fmt(w['rmse'], digits)} | {label(w.get('runner_up', ''))} | {'否，算并列' if w['tie'] else '是'} |")
    wins = pd.Series([w["model"] for w in monthly.values()]).value_counts()
    out += ["", f"{len(monthly)} 个月里，" + "，".join(f"{label(m)} {n} 次" for m, n in wins.items()) + "拿到第一。", ""]

    # 3. station by station
    out += ["**逐站第一名**（提前 1 天）", "", "| 点位 | 第一名 | 均方根误差 | 第二名 | 领先是否显著 |", "|---|---|---|---|---|"]
    by_station = {}
    for slug in stations:
        w = first_place(sample[sample["station"] == slug], 1)
        by_station[slug] = w
        name = BY_SLUG[slug].name_zh if slug in BY_SLUG else slug
        out.append(f"| {name} | {label(w['model'])} | {fmt(w['rmse'], digits)} | {label(w.get('runner_up', ''))} | {'否，算并列' if w['tie'] else '是'} |")
    station_wins = pd.Series([w["model"] for w in by_station.values()]).value_counts()
    out += ["", f"{len(stations)} 个点位里，" + "，".join(f"{label(m)} {n} 个" for m, n in station_wins.items()) + "。", ""]

    summary = {"window": [str(start), str(end)], "stations": stations, "coverage": coverage,
               "overall_day1": winner, "monthly": monthly, "by_station": by_station,
               "scorecard_day1": cards[1].round(4).reset_index().to_dict("records")}
    return out, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None, help="page name, default the last month in the data")
    args = parser.parse_args()

    body, summary = [], {}
    for variable, spec in SETS.items():
        if not spec["pairs"].exists():
            body += [f"## {spec['title']}", "", "这一期没有数据。", ""]
            continue
        lines, summary[variable] = section(variable, spec)
        body += lines

    tag = args.tag or max(s["window"][1] for s in summary.values())[:7]
    head = [f"# 能源大省预报检验榜 {tag}", "",
            "风电看北方、东北和西北 12 个机场的 10 米风速，光伏看 10 个光伏基地所在县的日辐照量。"
            "所有比较只用每个参评模式都有预报的日子，名次差异用按天配对的自举检验，检验不出差别的写成并列。", "",
            "要注意的三点：机场离风电场有几十到几百公里，10 米也不是轮毂高度，这里量的是各模式在这些省份的近地面风速，不是风电场的风；"
            "辐照的“实测”是卫星反演，本身有几个百分点的误差，各模式对的是同一份反演，名次不受影响，绝对误差偏大；"
            "光伏点位是在光伏基地所在县里取的整数坐标点，不是任何一个电站的位置。", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{tag}.md").write_text("\n".join(head + body) + "\n", encoding="utf-8")
    (OUT / f"{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"wrote reports/leaderboard/{tag}.md")


if __name__ == "__main__":
    main()
