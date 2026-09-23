"""Machine-learned weather models from NOAA's archive, at a fixed lead.

The leaderboard already carries two machine-learned models, because those are
the two a point API serves. The rest - Pangu-Weather, Aurora, FourCastNet - are
not on any point API, and until now that was the end of it.

NOAA publishes them. ``noaa-oar-mlwp-data`` holds every one of those models run
twice a day from 2020, as global fields, with a kerchunk index that makes the
whole archive readable as one array without downloading a file. A chunk is one
run at one lead over the whole globe, 4.2 MB, so a station costs the same as a
country and nine stations cost the same as one.

Three choices this module makes, each of which decides what the comparison means:

* **Pangu's archive ends 2025-04-01**, and the leaderboard's AI window starts a
  month before that. So this comparison runs on its own window inside the main
  study period instead, where the physics models are already scored.
* **The archive is six-hourly**, and the leaderboard reduces hourly station
  reports to a daily mean. Four samples and twenty are not the same daily mean.
  So *both* sides are reduced here to the four synoptic hours - 00, 06, 12 and
  18 UTC - and the physics models are recomputed the same way rather than
  carried over from the leaderboard.
* **Days are UTC days here**, not the station's local day. The main study uses
  local days because that is what a load curve follows; six-hourly data has no
  useful local-day reduction, and mixing the two definitions would be the
  quieter mistake.

GraphCast is fetched too, although the point API already serves it. That is the
check on everything above: the same model from two independent sources, scored
the same way, has to agree. If it does not, the fault is in this module.

Needs ``pip install -e ".[mlwp]"``.
"""
from __future__ import annotations

import hashlib
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .stations import Station

CACHE = Path(__file__).resolve().parents[2] / "data" / "interim"
#: The assembled comparison, committed so the page can be recomputed from the
#: repository alone.  ``data/interim`` is a download cache and is not in git, so
#: a report that could only be rebuilt from it would not be reproducible - which
#: is the one thing every other page here is.
PAIRS = Path(__file__).resolve().parents[2] / "data" / "pairs_mlwp.parquet"
BUCKET = "s3://noaa-oar-mlwp-data/parquet"

#: NOAA's names, and what they are.  All initialised from GFS analyses, so the
#: initial condition is held constant across the three and only the model differs.
MODELS = {
    "pangu": ("PANG_v100_GFS", "Pangu-Weather (AI)"),
    "aurora": ("AURO_v100_GFS", "Aurora (AI)"),
    "graphcast_noaa": ("GRAP_v100_GFS", "GraphCast, NOAA 存档 (AI)"),
}

#: Every station verified here is UTC+8, and the hourly caches are stored in the
#: station's local time.  A station in another zone would be shifted by the wrong
#: number of hours and land on the wrong four synoptic times - silently, because
#: the result is still four numbers a day.
UTC_OFFSET_HOURS = 8
ALLOWED_TIMEZONES = {"Asia/Shanghai", "Asia/Hong_Kong", "Asia/Taipei"}


def _check_timezones(stations: list[Station]) -> None:
    odd = sorted({s.timezone for s in stations} - ALLOWED_TIMEZONES)
    if odd:
        raise ValueError(
            f"这里把本地时按 UTC+{UTC_OFFSET_HOURS} 折算，但传进来的站点有 {odd}。"
            f"换算错了不会报错，只会把日平均取在错误的四个时次上——所以在这里拦住。")


SYNOPTIC = (0, 6, 12, 18)
#: The archive runs at 00 and 12 UTC; a lead in whole days is taken from the 00 UTC run.
INIT_HOUR = 0


def _open(model: str):
    import xarray as xr

    warnings.filterwarnings("ignore")
    name = MODELS[model][0]
    return xr.open_dataset(
        "reference://", engine="zarr",
        backend_kwargs={"consolidated": False, "storage_options": {
            "fo": f"{BUCKET}/{name}_combined_all.parq",
            "remote_protocol": "s3", "remote_options": {"anon": True},
            "target_options": {"anon": True}}},
        chunks=None)


def _nearest(ds, latitude: float, longitude: float) -> tuple[int, int, float]:
    lat = ds.latitude.values
    lon = ds.longitude.values % 360.0
    iy = int(np.abs(lat - latitude).argmin())
    ix = int(np.abs(lon - (longitude % 360.0)).argmin())
    # Great-circle distance to the cell actually used, so it can be reported
    # rather than assumed small.
    dy = np.radians(lat[iy] - latitude)
    dx = np.radians(((lon[ix] - longitude % 360.0 + 180) % 360) - 180)
    a = np.sin(dy / 2) ** 2 + np.cos(np.radians(latitude)) ** 2 * np.sin(dx / 2) ** 2
    return iy, ix, float(6371.0 * 2 * np.arcsin(np.sqrt(a)))


def wind(model: str, stations: list[Station], start: str, end: str,
         lead_days: int, refresh: bool = False, cached_only: bool = False) -> pd.DataFrame:
    """Daily mean 10 m wind speed at each station, from one model at one lead.

    One row per station and UTC day. The four synoptic hours of that day are
    taken from the run initialised ``lead_days`` days earlier at 00 UTC, which
    is what makes the lead exact rather than "whatever was latest".
    """
    # hashlib, not hash().  Python randomises string hashing per process, so a
    # cache keyed on hash() is written by one run and invisible to the next -
    # which looks exactly like the fetch never happened.
    tag = hashlib.sha1(",".join(sorted(s.slug for s in stations)).encode()).hexdigest()[:8]
    path = CACHE / f"mlwp_{model}_ws10_{start}_{end}_d{lead_days}_{tag}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    if cached_only:
        # The report must never start a download.  A half-finished fetch running
        # in another process would otherwise be duplicated here, and the two
        # would race on the same cache file.
        raise FileNotFoundError(path)

    ds = _open(model)
    inits = pd.DatetimeIndex(ds.init_time.values)
    steps = pd.TimedeltaIndex(pd.DatetimeIndex(ds.time.values) - pd.DatetimeIndex(ds.time.values)[0])
    points = {s.slug: _nearest(ds, s.latitude, s.longitude) for s in stations}

    days = pd.date_range(start, end, freq="D")
    rows = []
    for day in days:
        init = day - pd.Timedelta(days=lead_days) + pd.Timedelta(hours=INIT_HOUR)
        where = inits.get_indexer([init])
        if where[0] < 0:
            continue
        wanted = [pd.Timedelta(hours=lead_days * 24 + h) for h in SYNOPTIC]
        indices = [int(np.abs(steps - w).argmin()) for w in wanted]
        if any(abs(steps[i] - w) > pd.Timedelta(hours=1) for i, w in zip(indices, wanted)):
            continue
        try:
            u = ds["u10"].isel(init_time=int(where[0]), time=indices).values
            v = ds["v10"].isel(init_time=int(where[0]), time=indices).values
        except Exception as error:  # noqa: BLE001 - a missing run must not stop the run
            print(f"  {model} {day.date()} +{lead_days}d 取不到：{type(error).__name__}")
            continue
        speed = np.hypot(u, v)
        for slug, (iy, ix, distance) in points.items():
            rows.append({"station": slug, "date": day, "lead_days": lead_days,
                         "model": model, "forecast": float(speed[:, iy, ix].mean()),
                         "grid_km": round(distance, 1), "n_hours": len(indices)})
        if len(rows) % 200 == 0:
            print(f"  {model} +{lead_days}d {day.date()} 已取 {len(rows)} 行", flush=True)

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError(f"{model}: 这个窗口一条都没取到")
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def synoptic_daily(hourly: pd.DataFrame, offset_hours: int = UTC_OFFSET_HOURS) -> pd.DataFrame:
    """Reduce an hourly series in station-local time to a UTC-day synoptic mean.

    The archive gives four values a day; a mean over twenty hourly reports is a
    different statistic, and the difference is not noise - it is the diurnal
    cycle sampled two ways. So the station side is cut down to the same four
    hours rather than the model side being stretched.
    """
    work = hourly.copy()
    work["utc"] = pd.to_datetime(work["time"]) - pd.Timedelta(hours=offset_hours)
    work = work[work["utc"].dt.hour.isin(SYNOPTIC)]
    work["date"] = work["utc"].dt.normalize()
    keys = [c for c in ("station", "model", "lead_days", "date") if c in work.columns]
    out = work.groupby(keys)["value"].agg(["mean", "count"]).reset_index()
    # Fewer than three of the four synoptic hours is not a day's mean.
    return out[out["count"] >= 3].drop(columns="count").rename(columns={"mean": "value"})


# --------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------

WINDOW = ("2025-01-01", "2025-03-31")
#: The window the point archive caches the physics models over.
MAIN_CACHE = ("2024-07-01", "2025-08-31")
#: The AI-window cache, which is the only one carrying Open-Meteo's GraphCast.
AI_CACHE = ("2025-03-01", "2025-08-31", "c29b5fb3")
LEADS = (1, 3)


def _cached_hourly(station: Station, window: tuple) -> pd.DataFrame:
    tag = f"_{window[2]}" if len(window) > 2 else ""
    path = CACHE / f"fc_wind_speed_10m_{station.slug}_{window[0]}_{window[1]}{tag}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def physics_daily(stations: list[Station], window: tuple = MAIN_CACHE) -> pd.DataFrame:
    """The point archive's models, reduced the same way the six-hourly ones are."""
    _check_timezones(stations)
    frames = [_cached_hourly(s, window) for s in stations]
    frames = [f for f in frames if len(f)]
    if not frames:
        raise SystemExit("找不到逐小时预报缓存，先跑 make data")
    daily = synoptic_daily(pd.concat(frames, ignore_index=True))
    return daily.rename(columns={"value": "forecast"})


def observed_daily(stations: list[Station], window: tuple = MAIN_CACHE) -> pd.DataFrame:
    _check_timezones(stations)
    frames = []
    for s in stations:
        path = CACHE / f"obs_wind_speed_10m_{s.slug}_{window[0]}_{window[1]}.parquet"
        if path.exists():
            frames.append(pd.read_parquet(path))
    daily = synoptic_daily(pd.concat(frames, ignore_index=True))
    return daily.rename(columns={"value": "observed"})


def assemble(stations: list[Station], start: str = WINDOW[0], end: str = WINDOW[1],
             leads: tuple[int, ...] = LEADS, rebuild: bool = False) -> pd.DataFrame:
    """One frame in the shape every scoring function here already takes.

    Written to ``data/pairs_mlwp.parquet`` and read from there afterwards, the
    way the rest of this repository stores what its pages are computed from.
    """
    if PAIRS.exists() and not rebuild:
        frame = pd.read_parquet(PAIRS)
        frame["date"] = pd.to_datetime(frame["date"])
        return frame
    parts = [physics_daily(stations)]
    for model in MODELS:
        for lead in leads:
            try:
                parts.append(wind(model, stations, start, end, lead, cached_only=True)[
                    ["station", "date", "lead_days", "model", "forecast"]])
            except FileNotFoundError:
                print(f"  {model} 提前 {lead} 天还没取，跳过")
    pairs = pd.concat(parts, ignore_index=True)
    pairs["date"] = pd.to_datetime(pairs["date"])
    pairs = pairs[(pairs["date"] >= start) & (pairs["date"] <= end) & pairs["lead_days"].isin(leads)]
    observed = observed_daily(stations)
    observed["date"] = pd.to_datetime(observed["date"])
    pairs = pairs.merge(observed, on=["station", "date"], how="inner")
    pairs["error"] = pairs["forecast"] - pairs["observed"]
    pairs = pairs.dropna(subset=["forecast", "observed"])
    PAIRS.parent.mkdir(parents=True, exist_ok=True)
    pairs.to_parquet(PAIRS, index=False)
    return pairs


def validate(stations: list[Station], month: str = "2025-03") -> dict:
    """The same GraphCast from two independent sources, scored the same way.

    Everything else on this page rests on the six-hourly reduction, the lead
    arithmetic and the nearest-grid-point lookup being right. None of those
    raises when it is wrong. This is the check that would catch them: NOAA's
    GraphCast and the point archive's GraphCast are the same model run from the
    same initial conditions, so on the days both cover they have to agree to
    within interpolation. A gap here is a fault in this module, not a finding.
    """
    theirs = _cached_hourly(stations[0], AI_CACHE)
    if theirs.empty:
        return {}
    frames = [_cached_hourly(s, AI_CACHE) for s in stations]
    point = pd.concat([f for f in frames if len(f)], ignore_index=True)
    point = point[point["model"] == "gfs_graphcast025"]
    point = synoptic_daily(point).rename(columns={"value": "point_api"})

    try:
        noaa = wind("graphcast_noaa", stations, WINDOW[0], WINDOW[1], 1, cached_only=True)
    except FileNotFoundError:
        return {}
    noaa = noaa.rename(columns={"forecast": "noaa"})[["station", "date", "lead_days", "noaa"]]
    point["date"] = pd.to_datetime(point["date"])
    noaa["date"] = pd.to_datetime(noaa["date"])
    both = noaa.merge(point, on=["station", "date", "lead_days"], how="inner")
    both = both[both["date"].dt.strftime("%Y-%m") == month]
    if both.empty:
        return {}
    gap = (both["noaa"] - both["point_api"]).abs()
    both = both.assign(gap=both["noaa"] - both["point_api"])
    per_station = both.groupby("station")["gap"].agg(["mean", "std", "count"])
    residual = float((both["gap"] - both.groupby("station")["gap"].transform("mean")).std())
    return {"n": int(len(both)), "month": month,
            "mean_abs_gap": float(gap.mean()), "max_abs_gap": float(gap.max()),
            "correlation": float(both["noaa"].corr(both["point_api"])),
            "mean_level": float(both["point_api"].mean()),
            "signed_gap": float(both["gap"].mean()),
            "between_stations": float(per_station["mean"].std()),
            "within_station": residual,
            "per_station": {k: round(float(v), 3) for k, v in per_station["mean"].items()}}


#: A station whose two sources disagree by more than this carries a spatial
#: offset that has nothing to do with the models, so it is left out of the
#: table that compares the two sources' models against each other.
AGREEMENT_LIMIT = 0.25


def agreeing_stations(check: dict, stations: list[Station]) -> list[Station]:
    """The stations where the nearest grid point and the point API mean the same place.

    A 0.25-degree nearest neighbour at a coastal airport can land on water, and
    sea is smooth, so 10 m wind there is systematically stronger. That offset is
    a property of the lookup, not of any model - but it moves the archive's
    models and not the point API's, which is exactly the comparison this page
    makes. Where the two sources agree, the comparison is about the models.
    """
    if not check:
        return stations
    ok = {s for s, gap in check.get("per_station", {}).items() if abs(gap) <= AGREEMENT_LIMIT}
    return [s for s in stations if s.slug in ok]


VALIDATION = Path(__file__).resolve().parents[2] / "data" / "mlwp_validation.json"


def report(stations: list[Station] | None = None) -> tuple[list[str], dict]:
    from . import verify
    from .fetch import MODEL_LABEL
    from .stations import BY_SLUG, CHINA

    stations = stations or CHINA
    label = lambda m: MODELS[m][1] if m in MODELS else MODEL_LABEL.get(m, m)
    pairs = assemble(stations)
    summary = {"window": list(WINDOW), "stations": [s.slug for s in stations]}

    out = ["# 机器学习天气模式：盘古、Aurora，在中国站点上按固定时效检验", "",
           f"取数覆盖 {len(stations)} 个中国机场站，{WINDOW[0]} 至 {WINDOW[1]}，10 米风速；"
           f"评分只用其中两个来源落点一致的那几个（第一节说明为什么）。", "",
           "榜单上只有两个机器学习模式，因为点接口只发这两个。其余的——盘古、Aurora、"
           "FourCastNet——不在任何点接口上，到此为止。NOAA 把它们全都存了下来，"
           "每天两次、全球场、2020 年起，带一个 kerchunk 索引，于是整个存档可以当成一个数组读，"
           "一个站点的代价和一个国家一样。", "",
           "**两边都按 UTC 日的四个天气时次（00、06、12、18）取平均。**存档是六小时一次的，"
           "而榜单是把逐小时台站报告归到当地日。四个样本和二十个样本不是同一个日平均，"
           "差的是被两种方式采样的日变化。所以这里把台站那边也切到同样四个时次，"
           "而不是把模式那边拉长。", ""]

    import json as _json

    if VALIDATION.exists():
        check = _json.loads(VALIDATION.read_text(encoding="utf-8"))
    else:
        check = validate(stations)
        if check:
            VALIDATION.write_text(_json.dumps(check, ensure_ascii=False, indent=1), encoding="utf-8")
    keep = stations
    if check:
        keep = agreeing_stations(check, stations)
        moved = {s: g for s, g in check["per_station"].items() if abs(g) > AGREEMENT_LIMIT}
        out += ["## 一、先验证这条管线本身，结果查出一个必须处理的问题", "",
                "这一页所有数字都压在三件事上：六小时的归并、时效的算术、最近格点的取法。"
                "三件事做错了都不会报错。所以先做一个能抓到它们的检查——"
                "NOAA 存档里的 GraphCast 和点接口里的 GraphCast 是同一个模式、同一批初始场，"
                "在双方都覆盖的日子上必须对得上。", "",
                f"共同站日 {check['n']:,}（{check['month']}），相关系数 {check['correlation']:.3f}，"
                f"但平均绝对差 **{check['mean_abs_gap']:.3f} m/s**，"
                f"是同期风速均值（{check['mean_level']:.2f} m/s）的 "
                f"{100 * check['mean_abs_gap'] / check['mean_level']:.0f}%。同一个模式不该差这么多。", "",
                "拆到站上，答案很干净：", "",
                "| 点位 | 两个来源的平均差 |", "|---|---|"]
        for slug, gap in sorted(check["per_station"].items(), key=lambda kv: -abs(kv[1])):
            name = BY_SLUG[slug].name_zh if slug in BY_SLUG else slug
            out.append(f"| {name} | {gap:+.2f} |")
        out += ["", f"站间偏移的散布是 {check['between_stations']:.3f}，"
                    f"去掉各站固定偏移之后只剩 {check['within_station']:.3f}——"
                    "**差异几乎全是每个站一个固定量，而且大的全在沿海和岛上。**"
                    "0.25 度的最近格点在海岸机场很容易落到海面，海面粗糙度低、10 米风系统性偏大；"
                    "点接口做了插值和陆海处理，落点不一样。", "",
                "所以时效算术和时次归并是对的（去掉偏移后的剩余散布只有均值的 "
                f"{100 * check['within_station'] / check['mean_level']:.0f}%），"
                "但**最近格点这个取法在沿海站不够用**。它同等地移动存档里的三个模式、"
                "不移动点接口里的模式——而那正是下面这张表要比的东西。", ""]
        if moved:
            names = "、".join(f"{BY_SLUG[s].name_zh if s in BY_SLUG else s}（{g:+.2f}）"
                             for s, g in sorted(moved.items(), key=lambda kv: -abs(kv[1])))
            out += [f"所以评分表只用两个来源对得上的点位，剔除 {names}。"
                    f"剩下 {len(keep)} 个点位。", ""]
        summary["validation"] = check
        summary["stations_kept"] = [s.slug for s in keep]

    kept = pairs[pairs["station"].isin({s.slug for s in keep})]
    have = {(m, int(l)) for m, l in pairs[["model", "lead_days"]].drop_duplicates().to_numpy()}
    missing = [(m, l) for m in MODELS for l in LEADS if (m, l) not in have]
    out += ["## 二、评分表", ""]
    if missing:
        out += ["存档这一侧还没取全的组合，所以下面对应的表里没有它："
                + "、".join(f"{MODELS[m][1]} 提前 {l} 天" for m, l in missing)
                + "。一个模式在某个时效上缺席，表里就少一行——写在这里，"
                  "免得读表的人以为它参加了比较而输了。", ""]
        summary["missing"] = [{"model": m, "lead_days": l} for m, l in missing]
    for lead in LEADS:
        at_lead = verify.common_sample(kept[kept["lead_days"] == lead])
        if at_lead.empty:
            continue
        card = verify.scorecard(at_lead, by=("model",)).set_index("model").sort_values("rmse")
        days = at_lead.groupby(["station", "date"]).ngroups
        best = card.index[0]
        out += [f"**提前 {lead} 天**（共同样本 {days:,} 个站日，{card.index.size} 个模式）", "",
                "| 模式 | 均方根误差 | 偏差 | 平均绝对误差 | 与第一名是否分得开 |", "|---|---|---|---|---|"]
        for model, row in card.iterrows():
            mark = " ★" if model in MODELS else ""
            if model == best:
                verdict = "—"
            else:
                test = verify.paired_difference(at_lead, best, model, lead)
                verdict = "是" if test.get("a_is_better") else "否，算并列"
            out.append(f"| {label(model)}{mark} | {row['rmse']:.2f} | {row['bias']:+.2f} | "
                       f"{row['mae']:.2f} | {verdict} |")
        ties = sum(1 for m in card.index if m != best
                   and not verify.paired_difference(at_lead, best, m, lead).get("a_is_better"))
        out += ["", "★ 是从 NOAA 存档读出来的机器学习模式。"
                f"{days:,} 个站日分不开第一名和其中 {ties} 个模式（按天配对自举）——"
                "这个样本量下，名次表读的是量级，不是顺序。", ""]
        summary[f"lead_{lead}"] = card.round(6).reset_index().to_dict("records")

    out += ["## 三、这一页不能回答什么", "",
            f"- **样本很小。**窗口三个月，扣掉落点对不上的沿海站之后剩 {len(keep)} 个点位，"
            "每个时效一百个站日上下。上面那一栏「与第一名是否分得开」就是为此而设：多数名次分不开。"
            "盘古这份存档到 2025-04-01 为止，而榜单的 AI 窗口从 2025-03 才开始，两者只重叠一个月，"
            "所以这里改用主研究的窗口、取其中的冬春三个月——季节也是单一的。",
            "- **沿海站被剔除，不是因为它们不重要，而是因为这个取法在那里量的不是同一个地方。**"
            "要把它们拿回来，得给存档这一侧做陆海掩膜下的插值，而不是取最近格点。",
            "- **只有 10 米风速。**日最高气温用六小时采样会系统性偏低——四个时次很容易错过"
            "当天的峰值——那是采样方式的差，不是模式的差，所以温度不在这里。",
            "- **三个机器学习模式都由 GFS 分析场起步。**初始场因此是一样的，差异归于模式本身；"
            "但这也意味着它们共享 GFS 分析的误差，和从自家分析场起步的 IFS 不完全可比。",
            "- 机场不是风电场，10 米不是轮毂高度。这一页只回答"
            "「这些模式在中国这几个点上的近地面风速准不准」。"]
    return out, summary


def main() -> None:
    import json

    body, summary = report()
    reports = Path(__file__).resolve().parents[2] / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "mlwp.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    (reports / "mlwp.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n".join(body))


if __name__ == "__main__":
    main()
