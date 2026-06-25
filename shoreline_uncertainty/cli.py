"""Command-line entry point.

Usage:
    python -m shoreline_uncertainty.cli run --config path/to/config.yaml
    python -m shoreline_uncertainty.cli water-levels --config path/to/config.yaml
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from .config import load_config
from .io_utils import read_shoreline, write_table_csv
from .pipeline import run_pipeline
from .water_level import WaterLevelError, get_annual_water_level, get_water_level, site_lat_lon


def main(argv=None):
    """Parse CLI arguments and dispatch to the `run` or `water-levels`
    subcommand. `argv` defaults to `sys.argv` (via argparse) when None, but
    can be passed explicitly for testing.

    `run` loads a config file via `config.load_config` (which also
    validates it) and runs the full pipeline via `pipeline.run_pipeline`,
    printing, per site, the list of result keys produced (e.g. ["odb",
    "transects", "rate_of_change"]) as a quick console summary.

    `water-levels` is unrelated to the pipeline above and never touches it:
    it walks every shoreline year in the config, looks up the nearest
    NOAA CO-OPS water-level station to that shoreline (see water_level.py)
    and the water level there -- date-specific if `acquisition_date` is set
    on that shoreline year, otherwise an annual mean -- and writes one row
    per shoreline year to a CSV. This subcommand makes live network calls
    (the `run` pipeline never does), so failures for an individual
    shoreline (no nearby station, no data for that period, etc.) are caught
    and recorded in the output CSV's `error` column rather than aborting
    the whole run.
    """
    parser = argparse.ArgumentParser(prog="shoreline-uncertainty")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the full pipeline for a config file.")
    run_p.add_argument("--config", required=True, help="Path to a YAML or JSON run config.")
    run_p.add_argument("--verbose", action="store_true")
    run_p.add_argument(
        "--no-progress", action="store_true", help="Disable tqdm progress bars (e.g. for CI / non-interactive logs)."
    )

    wl_p = sub.add_parser(
        "water-levels",
        help="Look up NOAA CO-OPS water level (Great Lakes + marine) for every shoreline year in a config.",
    )
    wl_p.add_argument("--config", required=True, help="Path to a YAML or JSON run config.")
    wl_p.add_argument(
        "--out", default=None, help="Output CSV path. Defaults to '<output_dir>/water_levels.csv'."
    )
    wl_p.add_argument(
        "--datum", default=None, help="Override the datum for every lookup (default: auto -- IGLD for Great Lakes, MSL for marine)."
    )
    wl_p.add_argument(
        "--window-days",
        type=int,
        default=0,
        help="For date-specific lookups, the +/- window (days) around acquisition_date to average (default 0).",
    )
    wl_p.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Seconds to sleep between CO-OPS API calls, to stay polite to the (free, no-key) service (default 0.25).",
    )
    wl_p.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    if args.command == "run":
        config = load_config(args.config)
        results = run_pipeline(config, progress=not args.no_progress)
        for site_name, site_results in results.items():
            print(f"{site_name}: {list(site_results.keys())}")
    elif args.command == "water-levels":
        _run_water_levels(args)


def _run_water_levels(args) -> pd.DataFrame:
    """Implementation of the `water-levels` subcommand, split out from
    `main` so it's directly callable/testable without going through
    argparse. Returns the DataFrame it also writes to `args.out`."""
    config = load_config(args.config)
    out_path = Path(args.out) if args.out else Path(config.output_dir) / "water_levels.csv"

    rows = []
    for site in config.sites:
        for sy in site.shorelines:
            row = {
                "site": site.name,
                "year": sy.year,
                "acquisition_date": sy.acquisition_date,
            }
            try:
                gdf = read_shoreline(sy.path)
                lat, lon = site_lat_lon(gdf)
                if sy.acquisition_date:
                    result = get_water_level(
                        lat, lon, sy.acquisition_date, window_days=args.window_days, datum=args.datum
                    )
                else:
                    result = get_annual_water_level(lat, lon, sy.year, datum=args.datum)
                row.update(
                    {
                        "lat": lat,
                        "lon": lon,
                        "station_id": result.station.id,
                        "station_name": result.station.name,
                        "station_distance_nm": result.station.distance_nm,
                        "greatlakes": result.station.greatlakes,
                        "datum": result.datum,
                        "units": result.units,
                        "water_level": result.value,
                        "value_type": result.value_type,
                        "period_start": result.period_start,
                        "period_end": result.period_end,
                        "n_observations": result.n_observations,
                        "fallback_used": result.fallback_used,
                        "error": None,
                    }
                )
            except (WaterLevelError, OSError, ValueError) as exc:
                row["error"] = str(exc)
            rows.append(row)
            time.sleep(max(args.sleep, 0.0))

    df = pd.DataFrame(rows)
    write_table_csv(df, out_path)
    n_ok = df["error"].isna().sum() if "error" in df.columns and len(df) else 0
    print(f"Wrote {len(df)} row(s) ({n_ok} successful) to {out_path}")
    return df


if __name__ == "__main__":
    main()
