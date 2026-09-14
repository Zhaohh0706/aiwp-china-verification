"""Fetch every station and assemble the verification set.

Runs once and caches; re-running is offline. The console output is the data
audit: how many days each station and model actually contributed, so a thin
sample is visible before anyone reads a score computed from it.
"""
from __future__ import annotations

import argparse
import warnings
from pathlib import Path

import pandas as pd

from . import fetch
from .stations import ALL, BY_SLUG

warnings.filterwarnings("ignore")

OUT = Path(__file__).resolve().parents[2] / "data" / "pairs.parquet"


def build(start: str, end: str, slugs: list[str] | None = None) -> pd.DataFrame:
    stations = [BY_SLUG[s] for s in slugs] if slugs else ALL
    frames = []
    for station in stations:
        try:
            pairs = fetch.build_pairs(station, start, end)
        except Exception as error:  # noqa: BLE001 - one bad station must not stop the run
            print(f"{station.slug:11s} FAILED: {type(error).__name__}: {error}")
            continue
        pairs["group"] = station.group
        frames.append(pairs)
        days = pairs["date"].nunique()
        models = pairs["model"].nunique()
        print(
            f"{station.slug:11s} {station.icao}  {days:4d} days x {models} models "
            f"x {pairs['lead_days'].nunique()} leads = {len(pairs):6d} pairs"
        )
    if not frames:
        raise RuntimeError("no station produced any pairs")

    out = pd.concat(frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"\nwrote {OUT}: {len(out)} pairs")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=fetch.DEFAULT_START)
    parser.add_argument("--end", default=fetch.DEFAULT_END)
    parser.add_argument("--stations", nargs="*", default=None)
    args = parser.parse_args()

    pairs = build(args.start, args.end, args.stations)

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
