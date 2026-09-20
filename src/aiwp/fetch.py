"""Fetch forecasts at a fixed lead, and the observations to judge them against.

The single decision that makes or breaks a verification study is **lead time**.
A forecast issued six hours before the event and one issued five days before are
different products, and mixing them produces a number that describes neither.

An earlier version of this dataset was built from Open-Meteo's historical
forecast archive, which returns the best forecast available for each hour — in
practice the most recent model run, at whatever lead that happened to be. That
is the right choice for trading and the wrong one for verification, so it is not
used here. This module uses the previous-runs archive instead, where
``temperature_2m_previous_day3`` means precisely "what the model said three days
before", for every model separately.

Truth comes from METAR, the hourly airport reports archived by Iowa State. Both
sides are reduced to a daily maximum the same way — the maximum of the hourly
values falling in the station's local calendar day — so the comparison is fair
even though hourly sampling misses the true instantaneous peak.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from .stations import Station

PREVIOUS_RUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"
ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
SATELLITE = "https://satellite-api.open-meteo.com/v1/archive"

CACHE = Path(__file__).resolve().parents[2] / "data" / "interim"

# Every deterministic global model Open-Meteo serves previous runs for, with the
# Chinese one included because no published comparison outside CMA has it, and
# two machine-learned models because placing them against the physics-based ones
# at Chinese stations is the question this repository exists to answer.
NWP_MODELS = [
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
    "jma_seamless",
    "gem_global",
    "meteofrance_seamless",
    "ukmo_seamless",
    "cma_grapes_global",
]

AI_MODELS = [
    "ecmwf_aifs025_single",  # ECMWF's own machine-learned model, operational
    "gfs_graphcast025",      # DeepMind GraphCast, initialised from GFS
]

MODELS = NWP_MODELS + AI_MODELS

MODEL_LABEL = {
    "ecmwf_ifs025": "ECMWF IFS",
    "gfs_seamless": "NOAA GFS",
    "icon_seamless": "DWD ICON",
    "jma_seamless": "JMA GSM",
    "gem_global": "ECCC GEM",
    "meteofrance_seamless": "Météo-France ARPEGE",
    "ukmo_seamless": "UKMO",
    "cma_grapes_global": "CMA GRAPES",
    "ecmwf_aifs025_single": "ECMWF AIFS (AI)",
    "gfs_graphcast025": "GraphCast (AI)",
}

IS_AI = set(AI_MODELS)

# The previous-runs archive begins in mid-2024.
DEFAULT_START = "2024-07-01"
DEFAULT_END = "2025-08-31"

# AIFS only enters the archive on 2025-02-21, so the AI comparison runs on its
# own window.  Averaging a model over the months it was present and another over
# the months it was not is the mistake the common-sample rule exists to prevent,
# and stretching the window to include months AIFS cannot cover would reintroduce
# it at the level of the study design.
AI_WINDOW_START = "2025-03-01"
AI_WINDOW_END = "2025-08-31"

LEADS = (1, 2, 3, 4, 5)

# What each verified variable is called on each side, and how a day is reduced.
# Temperature verifies against a daily maximum because that is what drives
# cooling load; wind verifies against a daily mean because a wind farm cares
# about the whole day's resource, not its gustiest hour.
VARIABLES = {
    "temperature_2m": {
        "forecast": "temperature_2m",
        "metar": "tmpf",
        "reduce": "max",
        "unit": "°C",
        "label": "日最高气温",
    },
    # Surface solar radiation has no station observation at these sites, but it
    # does have something better than a reanalysis: a satellite retrieval.
    # Himawari covers East Asia, and satellite-derived irradiance is what the
    # solar industry actually assesses resource with, so it is the truth here.
    # The daily total is what a PV yield depends on, so hourly mean irradiance
    # is summed over the local day to give Wh/m2.
    "shortwave_radiation": {
        "forecast": "shortwave_radiation",
        "truth": "satellite",
        "reduce": "sum",
        # Summing hourly mean irradiance over a day gives energy, not power.
        # Labelling the result W/m² would understate it by a factor of the
        # number of daylight hours and put the wrong unit on every chart.
        "unit": "Wh/m²",
        # The archive serves hourly mean irradiance in W/m²; the daily sum is
        # what carries Wh/m².  The unit guard has to compare against what the
        # API returns, not against what the reduction produces - it did not, and
        # only a warm cache kept that from showing.
        "forecast_unit": "W/m²",
        "label": "日辐照量",
        "min_hours": 22,
        # JMA GSM publishes no surface radiation through this archive.  It is
        # excluded by name rather than left in to be silently emptied by the
        # common-sample rule, which would look like a data problem instead of a
        # stated one.
        "models": [m for m in NWP_MODELS + AI_MODELS if m != "jma_seamless"],
    },
    "wind_speed_10m": {
        "forecast": "wind_speed_10m",
        "metar": "sknt",  # knots in the METAR archive
        "reduce": "mean",
        "unit": "m/s",
        "label": "日平均 10 m 风速",
        # Open-Meteo returns wind in km/h unless told otherwise, and METAR
        # reports it in knots.  Neither is m/s, and comparing the two as if
        # they were would inflate the forecast by a factor of 3.6 while
        # producing a scorecard that still looks like a scorecard.  Both sides
        # are converted explicitly.
        "request": {"wind_speed_unit": "ms"},
    },
}

KNOTS_TO_MS = 0.514444

USER_AGENT = "aiwp-china-verification/0.1 (research)"


def _get(url: str, params: dict, retries: int = 4, timeout: int = 180) -> bytes:
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{url}?{query}", headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
            if body.strip():
                return body
        except Exception as error:  # noqa: BLE001 - network, retried
            last = error
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"empty or failed response from {url}: {last}")


def forecasts(
    station: Station,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    leads: tuple[int, ...] = LEADS,
    refresh: bool = False,
    variable: str = "temperature_2m",
    models: list[str] | None = None,
) -> pd.DataFrame:
    """Hourly values per model per lead, in the station's local time.

    One request per station covers every model and every lead, because the API
    returns one column per (variable, lead, model) combination.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    field = VARIABLES[variable]["forecast"]
    models = models or MODELS
    tag = hashlib.sha1(",".join(sorted(models)).encode()).hexdigest()[:8]
    path = CACHE / f"fc_{variable}_{station.slug}_{start}_{end}_{tag}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    variables = [f"{field}_previous_day{lead}" for lead in leads]
    payload = json.loads(
        _get(
            PREVIOUS_RUNS,
            {
                "latitude": station.latitude,
                "longitude": station.longitude,
                "start_date": start,
                "end_date": end,
                "hourly": ",".join(variables),
                "models": ",".join(models),
                "timezone": station.timezone,
                **VARIABLES[variable].get("request", {}),
            },
        ).decode("utf-8")
    )

    expected_unit = VARIABLES[variable].get("forecast_unit", VARIABLES[variable]["unit"])
    # A model with no data for the period comes back with the unit "undefined";
    # that is an empty column, not a different unit.
    returned = {
        u for name, u in payload.get("hourly_units", {}).items()
        if name != "time" and u != "undefined"
    }
    # W/m2 comes back spelled without the superscript; compare on a normalised
    # form so the guard catches real unit swaps and not typography.
    normalise = lambda u: u.replace("²", "2").replace("³", "3").strip()
    if returned and normalise(expected_unit) not in {normalise(u) for u in returned}:
        raise RuntimeError(
            f"{station.slug}: asked for {variable} in {expected_unit}, the API "
            f"returned {sorted(returned)}. Refusing to compare across units."
        )

    hourly = payload["hourly"]
    frame = pd.DataFrame(hourly)
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame.set_index("time").sort_index()

    # Columns arrive as temperature_2m_previous_day3_gfs_seamless; unpack into
    # a long frame so lead and model are data rather than column-name trivia.
    prefix = f"{field}_previous_day"
    records = []
    for column in frame.columns:
        if not column.startswith(prefix):
            continue
        remainder = column[len(prefix) :]
        lead_text, _, model = remainder.partition("_")
        if not model:
            continue
        records.append(
            pd.DataFrame(
                {
                    "time": frame.index,
                    "lead_days": int(lead_text),
                    "model": model,
                    "value": frame[column].to_numpy(dtype=float),
                }
            )
        )
    if not records:
        raise RuntimeError(f"{station.slug}: no forecast columns returned")

    out = pd.concat(records, ignore_index=True)
    out["station"] = station.slug
    out.to_parquet(path, index=False)
    return out


def observations(
    station: Station,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    refresh: bool = False,
    variable: str = "temperature_2m",
) -> pd.DataFrame:
    """Hourly observation of one variable, in SI units and local time.

    Dispatches on the truth source the variable declares: METAR station reports
    for what a station measures, satellite retrieval for irradiance, which no
    station here measures.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    if VARIABLES[variable].get("truth") == "satellite":
        return _satellite_observations(station, start, end, variable, refresh)
    field = VARIABLES[variable]["metar"]
    path = CACHE / f"obs_{variable}_{station.slug}_{start}_{end}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    start_date = pd.Timestamp(start)
    # Ask for a day either side so the local-day boundary is always covered.
    end_date = pd.Timestamp(end) + pd.Timedelta(days=1)
    raw = _get(
        ASOS,
        {
            "station": station.icao,
            "data": field,
            "year1": start_date.year, "month1": start_date.month, "day1": start_date.day,
            "year2": end_date.year, "month2": end_date.month, "day2": end_date.day,
            "tz": "Etc/UTC",
            "format": "onlycomma",
            "latlon": "no",
            "missing": "empty",
            "trace": "empty",
            "direct": "no",
            "report_type": 3,  # routine hourly reports only, no specials
        },
        timeout=300,
    )

    frame = pd.read_csv(io.StringIO(raw.decode("utf-8")))
    frame = frame.rename(columns={c: c.strip() for c in frame.columns})
    frame = frame.dropna(subset=[field])
    frame["valid"] = pd.to_datetime(frame["valid"], utc=True)

    if field == "tmpf":
        values = (frame[field].astype(float) - 32.0) * 5.0 / 9.0
        plausible = values.between(-60.0, 60.0)
    elif field == "sknt":
        values = frame[field].astype(float) * KNOTS_TO_MS
        plausible = values.between(0.0, 60.0)
    else:
        raise NotImplementedError(f"no conversion defined for METAR field {field!r}")
    # Airport sensors occasionally report impossible values; drop rather than
    # clip, because a clipped bad reading still contaminates a daily statistic.
    frame = frame[plausible.to_numpy()]
    values = values[plausible]

    out = pd.DataFrame(
        {
            "time": frame["valid"].dt.tz_convert(station.timezone).dt.tz_localize(None),
            "value": values.to_numpy(),
        }
    ).sort_values("time")
    out["station"] = station.slug
    out.to_parquet(path, index=False)
    return out


def _satellite_observations(
    station: Station, start: str, end: str, variable: str, refresh: bool
) -> pd.DataFrame:
    """Satellite-retrieved irradiance at a point, hourly, in local time."""
    path = CACHE / f"obs_{variable}_{station.slug}_{start}_{end}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    field = VARIABLES[variable]["forecast"]
    payload = json.loads(
        _get(
            SATELLITE,
            {
                "latitude": station.latitude,
                "longitude": station.longitude,
                "start_date": start,
                "end_date": end,
                "hourly": field,
                "models": "satellite_radiation_seamless",
                "timezone": station.timezone,
            },
        ).decode("utf-8")
    )
    hourly = payload["hourly"]
    frame = pd.DataFrame({"time": pd.to_datetime(hourly["time"]), "value": hourly[field]})
    frame = frame.dropna(subset=["value"])
    frame["station"] = station.slug
    frame = frame.sort_values("time")
    frame.to_parquet(path, index=False)
    return frame


def daily(frame: pd.DataFrame, how: str = "max", min_hours: int = 18) -> pd.DataFrame:
    """Reduce an hourly series to one value per day, discarding thin days.

    A day with only a handful of reports can produce a "maximum" that missed the
    afternoon entirely, or a "mean" weighted towards whichever hours happened to
    report. Requiring most of the day present costs a few days of sample and
    removes a bias that would otherwise look like model skill.
    """
    work = frame.copy()
    work["date"] = pd.to_datetime(work["time"]).dt.normalize()
    keys = [c for c in ("station", "model", "lead_days", "date") if c in work.columns]
    out = work.groupby(keys)["value"].agg([how, "count"]).reset_index()
    out = out[out["count"] >= min_hours].drop(columns="count")
    return out.rename(columns={how: "daily_value"})


def daily_max(frame: pd.DataFrame, min_hours: int = 18) -> pd.DataFrame:
    """Backwards-compatible alias used by the temperature path and its tests."""
    return daily(frame, "max", min_hours).rename(columns={"daily_value": "temp_max"})


def build_pairs(
    station: Station,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    variable: str = "temperature_2m",
    models: list[str] | None = None,
) -> pd.DataFrame:
    """One row per (station, model, lead, date) with forecast and observation."""
    how = VARIABLES[variable]["reduce"]
    min_hours = VARIABLES[variable].get("min_hours", 18)
    fc = daily(
        forecasts(station, start, end, variable=variable, models=models), how, min_hours
    )
    obs = daily(observations(station, start, end, variable=variable), how, min_hours)
    obs = obs.rename(columns={"daily_value": "observed"})[["station", "date", "observed"]]
    pairs = fc.rename(columns={"daily_value": "forecast"}).merge(
        obs, on=["station", "date"], how="inner"
    )
    pairs["error"] = pairs["forecast"] - pairs["observed"]
    pairs["variable"] = variable
    return pairs.dropna(subset=["forecast", "observed"])
