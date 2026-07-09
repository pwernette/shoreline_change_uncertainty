"""Command-line entry point.

Usage
-----
    # Run the full pipeline (--config defaults to config.yaml in the cwd)
    surf run
    surf run --config path/to/config.yaml

    # Look up NOAA water levels for every shoreline year
    surf water-levels
    surf water-levels --config path/to/config.yaml

    # Launch the tkinter GUI
    surf gui

    # Show help
    surf
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

from .config import load_config
from .io_utils import read_shoreline, write_table_csv
from .pipeline import run_pipeline
from .water_level import WaterLevelError, get_annual_water_level, get_water_level, site_lat_lon

# Candidate filenames to look for when --config is omitted.
_CONFIG_DEFAULTS = ("config.yaml", "config.yml")


def _find_default_config() -> Path | None:
    """Return the first of config.yaml / config.yml found in the cwd, or None."""
    for name in _CONFIG_DEFAULTS:
        p = Path.cwd() / name
        if p.is_file():
            return p
    return None


def _resolve_config(config_arg: str | None, parser: argparse.ArgumentParser) -> str:
    """Return a config path string: either the explicit --config value, or the
    auto-detected default. Exits with a friendly error if neither is available."""
    if config_arg:
        return config_arg
    default = _find_default_config()
    if default:
        print(f"No --config given; using {default}")
        return str(default)
    parser.error(
        "no --config argument given and no config.yaml / config.yml found in "
        f"the current directory ({Path.cwd()}).\n"
        "  Usage: surf run --config path/to/config.yaml"
    )


def main(argv=None):
    """Parse CLI arguments and dispatch to a subcommand.

    Subcommands
    -----------
    run
        Load a config file via :func:`config.load_config` and run the full
        pipeline via :func:`pipeline.run_pipeline`. ``--config`` defaults to
        ``config.yaml`` (or ``config.yml``) in the current working directory.

    water-levels
        Walk every shoreline year in the config, look up the nearest NOAA
        CO-OPS water-level station, and write one row per year to a CSV.
        Makes live network calls; individual failures are recorded in an
        ``error`` column rather than aborting the run.

    gui
        Launch the tkinter graphical interface (``gui_app``). Requires
        ``python3-tk`` on Linux; bundled on Windows and macOS.
    """
    parser = argparse.ArgumentParser(
        prog="surf",
        description="SURF: Shoreline Uncertainty and Rate Framework — shoreline change analysis with positional uncertainty.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  surf run                          # uses config.yaml in cwd\n"
            "  surf run --config my.yaml\n"
            "  surf water-levels --config my.yaml\n"
            "  surf gui\n"
        ),
    )
    # Not required=True — no subcommand prints help instead of erroring.
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run the full pipeline.")
    run_p.add_argument(
        "--config", default=None,
        help="Path to a YAML or JSON run config. Defaults to config.yaml in the cwd.",
    )
    run_p.add_argument("--verbose", action="store_true")
    run_p.add_argument(
        "--no-progress", action="store_true",
        help="Disable tqdm progress bars (e.g. for CI / non-interactive logs).",
    )

    wl_p = sub.add_parser(
        "water-levels",
        help="Look up NOAA CO-OPS water level for every shoreline year in a config.",
    )
    wl_p.add_argument(
        "--config", default=None,
        help="Path to a YAML or JSON run config. Defaults to config.yaml in the cwd.",
    )
    wl_p.add_argument(
        "--out", default=None,
        help="Output CSV path. Defaults to '<output_dir>/water_levels.csv'.",
    )
    wl_p.add_argument(
        "--datum", default=None,
        help="Override the datum (default: auto — IGLD for Great Lakes, MSL for marine).",
    )
    wl_p.add_argument(
        "--window-days", type=int, default=0,
        help="±window (days) around acquisition_date for date-specific lookups (default 0).",
    )
    wl_p.add_argument(
        "--sleep", type=float, default=0.25,
        help="Seconds between CO-OPS API calls (default 0.25).",
    )
    wl_p.add_argument("--verbose", action="store_true")

    sub.add_parser("gui", help="Launch the tkinter graphical interface.")

    args = parser.parse_args(argv)

    # No subcommand → print help and exit cleanly.
    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "run":
        logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
        config_path = _resolve_config(args.config, run_p)
        config = load_config(config_path)
        results = run_pipeline(config, progress=not args.no_progress)
        for site_name, site_results in results.items():
            print(f"{site_name}: {list(site_results.keys())}")

    elif args.command == "water-levels":
        logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
        args.config = _resolve_config(args.config, wl_p)
        _run_water_levels(args)

    elif args.command == "gui":
        _launch_gui()


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


def _launch_gui() -> None:
    """Launch the tkinter GUI (gui_app package)."""
    try:
        from gui_app.app import SURFApp
    except ModuleNotFoundError as exc:
        sys.exit(
            f"Cannot import gui_app: {exc}\n"
            "Make sure you are running from the repository root and the "
            "gui_app/ folder is present.\n"
            "On Linux you may also need:  sudo apt install python3-tk"
        )
    app = SURFApp()
    app.mainloop()


if __name__ == "__main__":
    main()
