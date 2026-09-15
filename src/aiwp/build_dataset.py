"""Fetch every station and assemble the verification set.

Runs once and caches; re-running is offline. The console output is the data
audit: how many days each station and model actually contributed, so a thin
sample is visible before anyone reads a score computed from it.
"""
from __future__ import annotations

import argparse
import os
import traceback
import warnings
from pathlib import Path

import pandas as pd

from . import fetch
from .stations import ALL, BY_SLUG, PV_SITES

warnings.filterwarnings("ignore")

DATA = Path(__file__).resolve().parents[2] / "data"


def out_path(variable: str, tag: str = "") -> Path:
    stem = "pairs" if variable == "temperature_2m" else f"pairs_{variable}"
    return DATA / f"{stem}{tag}.parquet"


def build(
    start: str,
    end: str,
    slugs: list[str] | None = None,
    variable: str = "temperature_2m",
    models: list[str] | None = None,
    tag: str = "",
    station_set: list | None = None,
) -> pd.DataFrame:
    stations = [BY_SLUG[s] for s in slugs] if slugs else (station_set or ALL)
    frames = []
    for station in stations:
        try:
            pairs = fetch.build_pairs(station, start, end, variable=variable, models=models)
        except Exception as error:  # noqa: BLE001 - one bad station must not stop the run
            print(f"{station.slug:11s} FAILED: {type(error).__name__}: {error}")
            if os.environ.get("AIWP_TRACEBACK"):
                traceback.print_exc()
            continue
        pairs["group"] = station.group
        frames.append(pairs)
        # Local names here must not collide with the `models` parameter: it is
        # reused on every iteration, and shadowing it made the first station
        # succeed and every later one fail.
        day_count = pairs["date"].nunique()
        model_count = pairs["model"].nunique()
        print(
            f"{station.slug:11s} {station.icao}  {day_count:4d} days x {model_count} models "
            f"x {pairs['lead_days'].nunique()} leads = {len(pairs):6d} pairs"
        )
    if not frames:
        raise RuntimeError("no station produced any pairs")

    out = pd.concat(frames, ignore_index=True)
    target = out_path(variable, tag)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(target, index=False)
    print(f"\nwrote {target}: {len(out)} pairs")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=fetch.DEFAULT_START)
    parser.add_argument("--end", default=fetch.DEFAULT_END)
    parser.add_argument("--stations", nargs="*", default=None)
    parser.add_argument(
        "--variable", default="temperature_2m", choices=sorted(fetch.VARIABLES)
    )
    parser.add_argument(
        "--pv",
        action="store_true",
        help="run on the eight PV sites from the power-forecasting study "
        "instead of the airport stations",
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="AI window: adds AIFS and GraphCast, and shortens the period to the "
        "months AIFS is archived for",
    )
    args = parser.parse_args()

    start, end, models, tag = args.start, args.end, None, ""
    station_set = PV_SITES if args.pv else None
    if args.pv:
        tag = "_pv"
        print(f"PV sites: {len(PV_SITES)} locations from the power-forecasting study")
    declared = fetch.VARIABLES[args.variable].get("models")
    if declared:
        models = declared
        print(f"variable declares its own model list: {len(models)} models "
              f"(excludes {', '.join(sorted(set(fetch.MODELS) - set(models)))})")
    if args.ai:
        start = fetch.AI_WINDOW_START if args.start == fetch.DEFAULT_START else args.start
        end = fetch.AI_WINDOW_END if args.end == fetch.DEFAULT_END else args.end
        models = declared or fetch.MODELS
        tag = f"{tag}_ai"
        print(f"AI window {start} to {end}: {len(models)} models including "
              f"{', '.join(fetch.AI_MODELS)}")

    print(f"variable: {args.variable} ({fetch.VARIABLES[args.variable]['label']})\n")
    pairs = build(start, end, args.stations, args.variable, models, tag, station_set)

    print("\ndays contributed per model (all stations):")
    counts = pairs[pairs["lead_days"] == 1].groupby("model")["date"].count()
    print(counts.to_string())

    print("\nmodels with a shorter record than ECMWF:")
    reference = counts.get("ecmwf_ifs025", 0)
    for model, count in counts.items():
        if count < 0.95 * reference:
            print(f"  {model:22s} {count} of {reference} ({100 * count / reference:.0f}%)")


if __name__ == "__main__":
    main()
