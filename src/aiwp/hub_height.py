"""Hub height, and the price of having no instrument there.

The leaderboard's own caveat is that 10 m is not where a rotor turns. Fixing it
runs into two facts that cannot be argued with:

* Of the ten models, **only four publish 100 m wind** through this archive -
  ECMWF IFS, NOAA GFS, DWD ICON and ECMWF AIFS. The other six return nothing.
* **Nothing at these airports measures 100 m wind.** The only available truth is
  ERA5, a reanalysis - and ERA5 is produced by ECMWF, two of whose models are in
  the four being judged.

The second is usually written as a caveat and then forgotten. It does not have
to be. The same four models also forecast 10 m wind, where an anemometer exists,
so the same ranking can be computed twice on the same days: once against the
instrument, once against ERA5. Whatever changes between those two tables is what
the reanalysis contributes, in m/s, and that is the correction to carry into
reading the 100 m table.

What it is not: a measurement of hub-height wind at a wind farm. These are
airports, the heights are model levels, and ERA5 is a 31 km reanalysis. What it
can answer is narrower and still worth knowing - whether the ranking a buyer
would make at 10 m is the ranking they should make at hub height.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import verify
from .fetch import MODEL_LABEL

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
DATA = ROOT / "data"

# The four models that publish both heights.  The 10 m tables are cut down to
# these four so that all three tables rank the same competitors.
MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "ecmwf_aifs025_single"]
ECMWF = {"ecmwf_ifs025", "ecmwf_aifs025_single"}

SOURCES = {
    "10m_metar": (DATA / "pairs_wind_speed_10m_energy_ai.parquet", "10 m，对机场 METAR 实测"),
    "10m_era5": (DATA / "pairs_wind_speed_10m_era5_energy_ai.parquet", "10 m，对 ERA5 再分析"),
    "100m_era5": (DATA / "pairs_wind_speed_100m_energy_ai.parquet", "100 m，对 ERA5 再分析"),
}


def load(name: str, days: pd.MultiIndex | None = None) -> pd.DataFrame:
    path, _ = SOURCES[name]
    if not path.exists():
        raise SystemExit(f"缺 {path.name}，先跑 make hub-data")
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame[frame["model"].isin(MODELS)]
    frame = verify.common_sample(frame)
    if days is not None:
        frame = frame.set_index(["station", "date", "lead_days"]).loc[
            frame.set_index(["station", "date", "lead_days"]).index.intersection(days)
        ].reset_index()
    return frame


def shared_days(*frames: pd.DataFrame) -> pd.MultiIndex:
    """The station-days every frame has, so two rankings compare the same weather."""
    index = None
    for frame in frames:
        here = pd.MultiIndex.from_frame(frame[["station", "date", "lead_days"]].drop_duplicates())
        index = here if index is None else index.intersection(here)
    return index


def card(frame: pd.DataFrame, lead: int = 1) -> pd.DataFrame:
    at_lead = frame[frame["lead_days"] == lead]
    return (verify.scorecard(at_lead, by=("model",))
            .set_index("model").sort_values("rmse")[["rmse", "bias", "mae", "n"]])


def report(lead: int = 1) -> tuple[list[str], dict]:
    metar_all, era5_all, hub_all = (load(k) for k in ("10m_metar", "10m_era5", "100m_era5"))
    # The kinship measurement has to be on identical days, or a difference in
    # sample would be read as a difference in truth.
    days = shared_days(metar_all, era5_all)
    metar, era5 = load("10m_metar", days), load("10m_era5", days)

    cards = {"10m_metar": card(metar, lead), "10m_era5": card(era5, lead),
             "100m_era5": card(hub_all, lead)}
    n_shared = int(cards["10m_metar"]["n"].max())

    out = ["# 轮毂高度：100 m 风速，以及没有仪器的代价", "",
           f"四个模式（{'、'.join(MODEL_LABEL[m] for m in MODELS)}）在 12 个能源大省机场，"
           f"提前 {lead} 天。另外六个模式在这个存档里不发 100 m 风，整段缺席。", "",
           "## 一、先量偏袒有多大",
           "",
           "同样四个模式、同样的 10 米风速、同样的日子，换一个真值：左边是机场风速计，"
           f"右边是 ERA5 再分析。共同样本 {n_shared:,} 个站日。", "",
           "| 模式 | 对实测 RMSE | 对 ERA5 RMSE | 差 | 对实测名次 | 对 ERA5 名次 |",
           "|---|---|---|---|---|---|"]

    left, right = cards["10m_metar"], cards["10m_era5"]
    left_rank = {m: i + 1 for i, m in enumerate(left.index)}
    right_rank = {m: i + 1 for i, m in enumerate(right.index)}
    for model in left.index:
        a, b = float(left.loc[model, "rmse"]), float(right.loc[model, "rmse"])
        out.append(f"| {MODEL_LABEL[model]} | {a:.2f} | {b:.2f} | {b - a:+.2f} | "
                   f"{left_rank[model]} | {right_rank[model]} |")

    aifs = f'{float(left.loc["ecmwf_aifs025_single", "rmse"]) - float(right.loc["ecmwf_aifs025_single", "rmse"]):.2f}'
    ecmwf_gain = sum(float(left.loc[m, "rmse"]) - float(right.loc[m, "rmse"]) for m in MODELS if m in ECMWF) / 2
    other_gain = sum(float(left.loc[m, "rmse"]) - float(right.loc[m, "rmse"]) for m in MODELS if m not in ECMWF) / 2
    moved = [MODEL_LABEL[m] for m in MODELS if left_rank[m] != right_rank[m]]
    out += ["",
            f"换成 ERA5 之后，两个 ECMWF 模式的误差平均降了 {ecmwf_gain:.2f} m/s，"
            f"另外两个降了 {other_gain:.2f} m/s，差 {ecmwf_gain - other_gain:+.2f} m/s。"
            + (f"名次变了的：{'、'.join(moved)}。" if moved else "名次没有变。"),
            "",
            "这个差值就是下面那张表要打的折扣。它有两个来源，混在一起分不开："
            "再分析比单点仪器平滑，本来就更像模式的格点值；以及 ERA5 由 ECMWF 制作。"
            f"降得最多的是 AIFS（{aifs} m/s），而 AIFS 是拿 ERA5 训练出来的机器学习模式——"
            "**用 ERA5 去考 AIFS，接近于用它自己的训练目标去考它**。", "",
            "## 二、100 m 风速", "",
            f"真值是 ERA5，不是仪器。共同样本 {int(cards['100m_era5']['n'].max()):,} 个站日。", "",
            "| 模式 | RMSE | 偏差 | MAE | 10 m 对实测的名次 |", "|---|---|---|---|---|"]
    hub = cards["100m_era5"]
    for model in hub.index:
        out.append(f"| {MODEL_LABEL[model]} | {float(hub.loc[model,'rmse']):.2f} | "
                   f"{float(hub.loc[model,'bias']):+.2f} | {float(hub.loc[model,'mae']):.2f} | "
                   f"{left_rank[model]} |")

    same = list(hub.index) == list(left.index)
    hub_spread = float(hub["rmse"].max() - hub["rmse"].min())
    kinship = ecmwf_gain - other_gain
    verdict = (
        f"整张表第一名和最后一名只差 {hub_spread:.2f} m/s，而上一节量出来的"
        f"“换个真值就白得”的幅度是 {kinship:.2f} m/s。**前者小于后者，"
        f"所以这张表不能当名次读**——它排出来的顺序，一个尺子自己的偏向就足以解释。"
        if hub_spread < kinship else
        f"整张表第一名和最后一名差 {hub_spread:.2f} m/s，大于上一节量出来的 {kinship:.2f} m/s，"
        f"所以超出那个幅度的那部分差距还站得住。"
    )
    out += ["",
            ("100 m 的名次和 10 m 对实测的名次一致。" if same else
             "**100 m 的名次和 10 m 对实测的名次不一样。**") + verdict, "",
            "## 三、这一页不能回答什么", "",
            "- 真值是再分析不是仪器。ERA5 是一次模式积分的产物，它看不到风速计看得到的阵风，"
            "而且由被考的其中两家做出来。第一节量的就是这件事，但量出来不等于消掉。",
            "- 机场不是风电场，模式层不是轮毂。这里只回答“在 10 米上排出来的名次，到了高空还成不成立”。",
            "- 只有四个模式。在 10 米上排第一的 NOAA GFS 在这里还在，"
            "但 CMA GRAPES、UKMO、JMA、GEM、ARPEGE、GraphCast 都不发 100 m 风，不在这张表上。"]

    summary = {"lead": lead, "models": MODELS, "shared_station_days": n_shared,
               "era5_gain_ecmwf": ecmwf_gain, "era5_gain_others": other_gain,
               "cards": {k: v.round(6).reset_index().to_dict("records") for k, v in cards.items()}}
    return out, summary


def main() -> None:
    body, summary = report()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "hub_height.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    (REPORTS / "hub_height.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n".join(body))


if __name__ == "__main__":
    main()
