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

CACHE = Path(__file__).resolve().parents[2] / "data" / "interim"

# Every deterministic global model Open-Meteo serves previous runs for, with the
# Chinese one included because no published comparison outside CMA has it.
MODELS = [
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
    "jma_seamless",
    "gem_global",
    "meteofrance_seamless",
    "ukmo_seamless",
    "cma_grapes_global",
]

MODEL_LABEL = {
    "ecmwf_ifs025": "ECMWF IFS",
    "gfs_seamless": "NOAA GFS",
    "icon_seamless": "DWD ICON",
    "jma_seamless": "JMA GSM",
    "gem_global": "ECCC GEM",
    "meteofrance_seamless": "Météo-France ARPEGE",
    "ukmo_seamless": "UKMO",
    "cma_grapes_global": "CMA GRAPES",
}

# The previous-runs archive begins in mid-2024.
DEFAULT_START = "2024-07-01"
DEFAULT_END = "2025-08-31"

LEADS = (1, 2, 3, 4, 5)

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
) -> pd.DataFrame:
    """Hourly 2 m temperature per model per lead, in the station's local time.

    One request per station covers every model and every lead, because the API
    returns one column per (variable, lead, model) combination.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"fc_{station.slug}_{start}_{end}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    variables = [f"temperature_2m_previous_day{lead}" for lead in leads]
    payload = json.loads(
        _get(
            PREVIOUS_RUNS,
            {
                "latitude": station.latitude,
                "longitude": station.longitude,
                "start_date": start,
                "end_date": end,
                "hourly": ",".join(variables),
                "models": ",".join(MODELS),
                "timezone": station.timezone,
            },
        ).decode("utf-8")
    )

    hourly = payload["hourly"]
    frame = pd.DataFrame(hourly)
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame.set_index("time").sort_index()

    # Columns arrive as temperature_2m_previous_day3_gfs_seamless; unpack into
    # a long frame so lead and model are data rather than column-name trivia.
    records = []
    for column in frame.columns:
        if not column.startswith("temperature_2m_previous_day"):
            continue
        remainder = column[len("temperature_2m_previous_day") :]
        lead_text, _, model = remainder.partition("_")
        if not model:
            continue
        records.append(
            pd.DataFrame(
                {
                    "time": frame.index,
                    "lead_days": int(lead_text),
                    "model": model,
                    "temp_c": frame[column].to_numpy(dtype=float),
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
    station: Station, start: str = DEFAULT_START, end: str = DEFAULT_END, refresh: bool = False
) -> pd.DataFrame:
    """Hourly METAR air temperature, converted to Celsius and local time."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"obs_{station.slug}_{start}_{end}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)

    start_date = pd.Timestamp(start)
    # Ask for a day either side so the local-day boundary is always covered.
    end_date = pd.Timestamp(end) + pd.Timedelta(days=1)
    raw = _get(
        ASOS,
        {
            "station": station.icao,
            "data": "tmpf",
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
    frame = frame.dropna(subset=["tmpf"])
    frame["valid"] = pd.to_datetime(frame["valid"], utc=True)
    frame["temp_c"] = (frame["tmpf"].astype(float) - 32.0) * 5.0 / 9.0
    # Airport thermometers occasionally report impossible values; drop rather
    # than clip, because a clipped bad reading still contaminates a daily max.
    frame = frame[frame["temp_c"].between(-60.0, 60.0)]

    out = pd.DataFrame(
        {
            "time": frame["valid"].dt.tz_convert(station.timezone).dt.tz_localize(None),
            "temp_c": frame["temp_c"].to_numpy(),
        }
    ).sort_values("time")
    out["station"] = station.slug
    out.to_parquet(path, index=False)
    return out


def daily_max(frame: pd.DataFrame, min_hours: int = 18) -> pd.DataFrame:
    """Reduce an hourly series to a daily maximum, discarding thin days.

    A day with only a handful of reports can produce a "maximum" that missed the
    afternoon entirely. Requiring most of the day present costs a few days of
    sample and removes a bias that would otherwise look like model skill.
    """
    work = frame.copy()
    work["date"] = pd.to_datetime(work["time"]).dt.normalize()
    grouped = work.groupby([c for c in ("station", "model", "lead_days", "date") if c in work.columns])
    out = grouped["temp_c"].agg(["max", "count"]).reset_index()
    out = out[out["count"] >= min_hours].drop(columns="count")
    return out.rename(columns={"max": "temp_max_c"})


def build_pairs(
    station: Station, start: str = DEFAULT_START, end: str = DEFAULT_END
) -> pd.DataFrame:
    """One row per (station, model, lead, date) with forecast and observation."""
    fc = daily_max(forecasts(station, start, end))
    obs = daily_max(observations(station, start, end))
    obs = obs.rename(columns={"temp_max_c": "observed_c"})[["station", "date", "observed_c"]]
    pairs = fc.rename(columns={"temp_max_c": "forecast_c"}).merge(
        obs, on=["station", "date"], how="inner"
    )
    pairs["error_c"] = pairs["forecast_c"] - pairs["observed_c"]
    return pairs.dropna(subset=["forecast_c", "observed_c"])
