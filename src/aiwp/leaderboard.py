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
SCORED_LEADS = (1, 3, 5)


def label(model: str) -> str:
    return MODEL_LABEL.get(model, model)


def eligible(pairs: pd.DataFrame, leads: tuple[int, ...]) -> tuple[pd.DataFrame, dict]:
    """Keep models with enough coverage at every lead asked for, then the common sample.

    Two sets come out of this, as in the main study.  The day-1 ranking takes every
    model that covers day 1.  The table across leads takes only models that cover
    day 5 as well: one archived to day 3 is complete at day 1 and absent at day 5,
    and would otherwise empty the common sample at the leads it never ran.
    """
    coverage = {}
    pairs = pairs[pairs["lead_days"].isin(leads)]
    for model in sorted(pairs["model"].unique()):
        shares = []
        for lead in leads:
            at_lead = pairs[pairs["lead_days"] == lead]
            total = at_lead.groupby("station")["date"].nunique().sum()
            shares.append(float((at_lead["model"] == model).sum() / total) if total else 0.0)
        coverage[model] = round(min(shares), 3)
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
            "p": float(test.get("p_boot", float("nan"))),
            "rmse": float(card.iloc[0]["rmse"]), "n": int(card.iloc[0]["n"])}


def hold_up_together(winners: dict) -> dict:
    """Mark the winners in one table that survive a correction for the whole table.

    Each winner here was judged on its own interval.  A reader does not read one
    row, they read the table, so the family to correct over is the table.
    """
    keys = [k for k, w in winners.items() if w and np.isfinite(w.get("p", np.nan))]
    kept = verify.holm_reject([winners[k]["p"] for k in keys])
    for key, keep in zip(keys, kept):
        winners[key]["holm"] = bool(keep)
    return winners


def fmt(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}"


def section(variable: str, spec: dict) -> tuple[list[str], dict]:
    pairs = pd.read_parquet(spec["pairs"])
    pairs["date"] = pd.to_datetime(pairs["date"])
    inconsistent = verify.lead_consistency(pairs)
    for item in inconsistent:
        pairs = pairs[~((pairs["model"] == item["model"]) & (pairs["lead_days"] == item["lead_days"]))]
    # The rolling offset is fitted per model, station and lead on the whole record,
    # before the common sample narrows it: the days a user would have had are the
    # days that happened, not the days every model happens to cover.
    # The observation series is taken before anything narrows the frame: the day
    # a persistence baseline copies from is a day that happened, not a day that
    # survived the common-sample rule.
    truth = verify.observation_series(pairs)
    pairs = verify.out_of_sample_debias(pairs)
    sample, coverage = eligible(pairs, (1,))
    core, core_coverage = eligible(pairs, SCORED_LEADS)
    digits = spec["digits"]
    stations = sorted(sample["station"].unique())
    start, end = sample["date"].min().date(), sample["date"].max().date()
    mean_obs = float(sample.drop_duplicates(["station", "date"])["observed"].mean())

    out = [f"## {spec['title']}", "",
           f"{len(stations)} 个点位，{start} 至 {end}，"
           f"提前 1 天的共同样本 {sample.groupby(['station', 'date']).ngroups:,} 个站日。"
           f"观测均值 {fmt(mean_obs, digits)} {spec['unit']}。", ""]
    if inconsistent:
        out += ["存档里下列模式在这些时效上的预报与它自己提前 1 天的预报气候态对不上（均值相差超过 10%），"
                "说明存档给出的不是同一个量，已整段剔除："
                + "；".join(f"{label(i['model'])} 提前 {i['lead_days']} 天（是提前 1 天的 {i['ratio_to_day1']:.2f} 倍）" for i in inconsistent) + "。", ""]
    dropped = {label(m): f"{c:.0%}" for m, c in coverage.items() if c < MIN_COVERAGE}
    if dropped:
        out += ["提前 1 天覆盖不足 80%、未参与排名的模式：" + "，".join(f"{k}（{v}）" for k, v in dropped.items()) + "。", ""]

    # 0. the question before any ranking: is any of this better than doing nothing
    skill = verify.skill_over_persistence(core, truth)
    out += ["**先回答一个问题：比什么都不做强多少**", "",
            "持续法是照抄 N 天前的实测——提前 1 天的预报拿前一天的值，提前 5 天的拿 5 天前的值。"
            "时效对齐是这件事的全部意义：一个永远用昨天的基准会在提前 5 天上赢过所有模式，那个数没有意义。", "",
            "| 时效 | 持续法 | 当期最好的模式 | 技巧评分 | 站日 |", "|---|---|---|---|---|"]
    for lead in SCORED_LEADS:
        at_lead = skill[skill["lead_days"] == lead].sort_values("skill", ascending=False)
        if at_lead.empty:
            continue
        best = at_lead.iloc[0]
        out.append(f"| 提前 {lead} 天 | {fmt(best['persistence_rmse'], digits)} | {label(best['model'])} "
                   f"{fmt(best['rmse'], digits)} | {best['skill']:.2f} | {best['n']:,} |")
    out += ["", "技巧评分是 1 − 模式均方误差 ÷ 持续法均方误差：0 分等于什么都不做，1 分等于完美。"
            "越往后看这个数越不该当真——持续法在提前 5 天时本身已经差到接近气候态，"
            "衬得每个模式都好看。真正要看的是提前 1 天那一行。"
            "持续法只能用数据集里有的实测，所以头几天和实测被小时数规则丢掉的日子没有基准，站日数比模式少一些。"
            "这张表和下面那张“误差随时效的增长”用同一组模式（存档到提前 5 天的那些）的共同样本，"
            "参评模式比提前 1 天评分表少一个，共同样本因此更大，站日数和评分表对不上是这个原因。"]
    # The line worth writing down, when it holds: a five-day forecast beating
    # yesterday's weather is the plain-language version of the whole table.
    day1_base = skill[skill["lead_days"] == 1]
    day5_best = skill[skill["lead_days"] == SCORED_LEADS[-1]].sort_values("rmse")
    if not day1_base.empty and not day5_best.empty:
        base1 = float(day1_base["persistence_rmse"].iloc[0])
        best5 = day5_best.iloc[0]
        if float(best5["rmse"]) < base1:
            out += ["", f"换一句话说：{label(best5['model'])} 提前 {SCORED_LEADS[-1]} 天的预报"
                    f"（{fmt(float(best5['rmse']), digits)}），仍然比照抄昨天"
                    f"（{fmt(base1, digits)}）准。"]
    out += [""]

    # 1. day-1 scorecard, every model that covers day 1
    out += ["**提前 1 天评分表**（越小越好）", "",
            "| 模式 | 均方根误差 | 滚动去偏后 | 偏差 | 平均绝对误差 |", "|---|---|---|---|---|"]
    day1 = verify.scorecard(verify.common_debiased(sample), by=("model",)).set_index("model").sort_values("rmse")
    for model, row in day1.iterrows():
        out.append(f"| {label(model)} | {fmt(row['rmse'], digits)} | {fmt(row['debiased_rmse'], digits)} | "
                   f"{row['bias']:+,.{digits}f} | {fmt(row['mae'], digits)} |")
    out += ["", f"“滚动去偏后”是每天用该模式在这个点位之前 {verify.DEBIAS_WINDOW} 天的平均误差估一个偏移量、"
                f"再减掉它之后剩下的误差。偏移量只用当天以前的数据，历史不足 {verify.DEBIAS_MIN_HISTORY} 天、"
                f"或者有模式还没攒够历史的日子整天不计入，这一列的共同样本是 {int(day1['n_debiased'].max()):,} 个站日。"
                "改用当期样本自己的平均偏差去减，会得到一个更小、但任何校准都拿不到的数。"
                "本来就几乎没有偏差的模式，这一列可能比原来还高，那是估计偏移量本身带来的噪声。"]
    winner = first_place(sample, 1)
    verdict = "与第二名在统计上分不开" if winner["tie"] else "对第二名的领先是显著的"
    out += ["", f"第一名是 {label(winner['model'])}，{verdict}（第二名 {label(winner['runner_up'])}，按天配对自举）。", ""]

    # 1b. error growth, only models archived out to day 5
    cards = {lead: verify.scorecard(core[core["lead_days"] == lead], by=("model",)).set_index("model") for lead in SCORED_LEADS}
    out += ["**误差随时效的增长**（均方根误差；只含存档到提前 5 天的模式，三个时效各用自己的共同样本）", "",
            "| 模式 | 提前 1 天 | 提前 3 天 | 提前 5 天 | 增长 |", "|---|---|---|---|---|"]
    for model in cards[1].sort_values("rmse").index:
        a, b, c = (cards[l].loc[model, "rmse"] for l in SCORED_LEADS)
        out.append(f"| {label(model)} | {fmt(a, digits)} | {fmt(b, digits)} | {fmt(c, digits)} | {100 * (c / a - 1):+.0f}% |")
    base = verify.scorecard(verify.persistence(core, truth), by=("model", "lead_days")).set_index("lead_days")
    if all(lead in base.index for lead in SCORED_LEADS):
        a, b, c = (float(base.loc[lead, "rmse"]) for lead in SCORED_LEADS)
        out.append(f"| {label(verify.PERSISTENCE)} | {fmt(a, digits)} | {fmt(b, digits)} | {fmt(c, digits)} | {100 * (c / a - 1):+.0f}% |")
    short = {label(m): f"{v:.0%}" for m, v in core_coverage.items() if v < MIN_COVERAGE and coverage.get(m, 0) >= MIN_COVERAGE}
    if short:
        out += ["", "提前 1 天有数据、但没有存档到提前 5 天的模式不在这张表里：" + "，".join(short) + "。"]
    out += [""]

    # 2. month by month
    monthly = {}
    for month, group in sample.groupby(sample["date"].dt.to_period("M")):
        w = first_place(group, 1)
        if w:
            monthly[str(month)] = w
    hold_up_together(monthly)
    out += ["**逐月第一名**（提前 1 天）", "",
            "| 月份 | 第一名 | 均方根误差 | 第二名 | 单独看是否显著 | 放进整张表看 |", "|---|---|---|---|---|---|"]
    for month, w in monthly.items():
        out.append(f"| {month} | {label(w['model'])} | {fmt(w['rmse'], digits)} | {label(w.get('runner_up', ''))} | "
                   f"{'否，算并列' if w['tie'] else '是'} | {'是' if w.get('holm') else '不成立'} |")
    wins = pd.Series([w["model"] for w in monthly.values()]).value_counts()
    out += ["", f"{len(monthly)} 个月里，" + "，".join(f"{label(m)} {n} 次" for m, n in wins.items()) + "拿到第一；"
            f"其中单独看显著的 {sum(not w['tie'] for w in monthly.values())} 个月，"
            f"按整张表校正后还成立的 {sum(bool(w.get('holm')) for w in monthly.values())} 个月。", ""]

    # 3. station by station
    by_station = {}
    for slug in stations:
        by_station[slug] = first_place(sample[sample["station"] == slug], 1)
    hold_up_together(by_station)
    out += ["**逐站第一名**（提前 1 天）", "",
            "| 点位 | 第一名 | 均方根误差 | 第二名 | 单独看是否显著 | 放进整张表看 |", "|---|---|---|---|---|---|"]
    for slug in stations:
        w = by_station[slug]
        name = BY_SLUG[slug].name_zh if slug in BY_SLUG else slug
        out.append(f"| {name} | {label(w['model'])} | {fmt(w['rmse'], digits)} | {label(w.get('runner_up', ''))} | "
                   f"{'否，算并列' if w['tie'] else '是'} | {'是' if w.get('holm') else '不成立'} |")
    station_wins = pd.Series([w["model"] for w in by_station.values()]).value_counts()
    solid = sum(bool(w.get("holm")) for w in by_station.values())
    out += ["", f"{len(stations)} 个点位里，" + "，".join(f"{label(m)} {n} 个" for m, n in station_wins.items()) + "。"
            f"但这些第一名里，单独看能和第二名分开的有 {sum(not w['tie'] for w in by_station.values())} 个，"
            f"把十几个点位当成一张表一起校正之后只剩 {solid} 个。"
            "也就是说，多数点位上“哪个模式最好”这件事，现有样本量还答不了；"
            "各站第一名各不相同，本身不足以证明必须按站选模式。", ""]

    summary = {"window": [str(start), str(end)], "stations": stations, "coverage": coverage,
               "overall_day1": winner, "inconsistent_leads": inconsistent, "monthly": monthly, "by_station": by_station,
               "scorecard_day1": day1.round(6).reset_index().to_dict("records"),
               "skill_over_persistence": skill.round(6).to_dict("records"),
               "growth": {str(l): cards[l]["rmse"].round(6).to_dict() for l in SCORED_LEADS}}
    return out, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None, help="page name, default the last month in the data")
    parser.add_argument("--out", default=None,
                        help="write somewhere else than reports/leaderboard; used by the "
                             "reproducibility check, which must not touch the committed pages")
    args = parser.parse_args()
    out_dir = Path(args.out) if args.out else OUT

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
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{tag}.md").write_text("\n".join(head + body) + "\n", encoding="utf-8")
    (out_dir / f"{tag}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"wrote {out_dir}/{tag}.md")


if __name__ == "__main__":
    main()
