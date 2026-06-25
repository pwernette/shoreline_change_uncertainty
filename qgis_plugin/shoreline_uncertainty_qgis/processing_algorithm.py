"""QgsProcessingAlgorithm wrappers exposing this plugin's config-file-driven
pipeline and water-level lookup through QGIS's Processing framework (the
Toolbox, batch processing, model designer, and `processing.run(...)` from
the Python console) -- the same two operations the standalone package's CLI
exposes as its `run` and `water-levels` subcommands (see
shoreline_uncertainty/cli.py), but as Processing algorithms instead of CLI
subcommands.

Both algorithms are deliberately config-file driven rather than exposing
every SiteConfig/ShorelineYear field as an individual Processing parameter:
a run config can describe any number of sites, each with any number of
shoreline years, baselines, and professionals, which doesn't map onto
Processing's fixed per-algorithm parameter list. The hybrid custom dialog
(dialog.py) is what builds/edits a config file interactively; these
algorithms are what actually executes one, either standalone (Toolbox/
batch/model) or driven by that dialog (task #76).
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from .config_qgis import load_config
from .io_utils_qgis import read_shoreline, write_table_csv
from .pipeline_qgis import run_pipeline
from .water_level_qgis import (
    WaterLevelError,
    get_annual_water_level,
    get_water_level,
    site_lat_lon,
)


class RunAnalysisAlgorithm(QgsProcessingAlgorithm):
    """Runs the full pipeline (`pipeline_qgis.run_pipeline`) for every site
    in a run configuration file -- the Processing-framework equivalent of
    the standalone CLI's `run` subcommand."""

    CONFIG = "CONFIG"
    OUTPUT_DIR = "OUTPUT_DIR"

    def name(self) -> str:
        return "run_analysis"

    def displayName(self) -> str:
        return self.tr("Run Shoreline Change Uncertainty Analysis")

    def group(self) -> str:
        return self.tr("Shoreline Change Uncertainty")

    def groupId(self) -> str:
        return "shoreline_uncertainty"

    def shortHelpString(self) -> str:
        return self.tr(
            "Runs the full shoreline-change-uncertainty pipeline (epsilon "
            "bands, transects, rate-of-change, probability surfaces, etc., "
            "as configured) for every site in a YAML/JSON run configuration "
            "file, writing all outputs under the config's output_dir (or an "
            "optional override directory)."
        )

    def createInstance(self) -> "RunAnalysisAlgorithm":
        return RunAnalysisAlgorithm()

    def initAlgorithm(self, config=None) -> None:
        self.addParameter(
            QgsProcessingParameterFile(self.CONFIG, self.tr("Run configuration file (YAML/JSON)"))
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr("Output directory (optional -- overrides the config's output_dir)"),
                optional=True,
            )
        )

    def processAlgorithm(self, parameters: dict, context, feedback) -> dict:
        config_path = self.parameterAsFile(parameters, self.CONFIG, context)
        if not config_path:
            raise QgsProcessingException(self.tr("A run configuration file is required."))

        try:
            run = load_config(config_path)
        except (ValueError, OSError) as exc:
            raise QgsProcessingException(str(exc)) from exc

        output_override = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        if output_override:
            run.output_dir = output_override

        feedback.pushInfo(
            f"Loaded '{config_path}': {len(run.sites)} site(s), output_dir='{run.output_dir}'."
        )

        try:
            results = run_pipeline(run, progress=False)
        except Exception as exc:  # noqa: BLE001 -- surface any pipeline failure through Processing, not a bare traceback
            raise QgsProcessingException(str(exc)) from exc

        for site_name, site_results in results.items():
            feedback.pushInfo(f"{site_name}: {list(site_results.keys())}")

        return {self.OUTPUT_DIR: run.output_dir}


class WaterLevelLookupAlgorithm(QgsProcessingAlgorithm):
    """Looks up the nearest NOAA CO-OPS water-level station and water level
    for every shoreline year in a run configuration file -- the Processing-
    framework equivalent of the standalone CLI's `water-levels` subcommand.
    Entirely decoupled from RunAnalysisAlgorithm/run_pipeline: this makes
    live network calls (see water_level_qgis.py's module docstring), which
    the core pipeline deliberately never does."""

    CONFIG = "CONFIG"
    OUT = "OUT"
    DATUM = "DATUM"
    WINDOW_DAYS = "WINDOW_DAYS"
    SLEEP = "SLEEP"

    def name(self) -> str:
        return "water_level_lookup"

    def displayName(self) -> str:
        return self.tr("Look Up NOAA Water Levels for Shoreline Years")

    def group(self) -> str:
        return self.tr("Shoreline Change Uncertainty")

    def groupId(self) -> str:
        return "shoreline_uncertainty"

    def shortHelpString(self) -> str:
        return self.tr(
            "Looks up the nearest NOAA CO-OPS water-level station (Great "
            "Lakes or marine) and the water level there for every shoreline "
            "year in a run configuration file -- date-specific if that "
            "shoreline year has an acquisition_date set, otherwise an annual "
            "mean -- and writes one row per shoreline year to a CSV. Makes "
            "live network calls; a lookup failure for an individual "
            "shoreline year is recorded in that row's 'error' column rather "
            "than aborting the whole run."
        )

    def createInstance(self) -> "WaterLevelLookupAlgorithm":
        return WaterLevelLookupAlgorithm()

    def initAlgorithm(self, config=None) -> None:
        self.addParameter(
            QgsProcessingParameterFile(self.CONFIG, self.tr("Run configuration file (YAML/JSON)"))
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUT, self.tr("Output CSV"), self.tr("CSV files (*.csv)"), optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.DATUM, self.tr("Datum override (blank = auto)"), optional=True, defaultValue=""
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.WINDOW_DAYS,
                self.tr("Window (+/- days) for date-specific lookups"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SLEEP,
                self.tr("Seconds to sleep between API calls"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.25,
                minValue=0.0,
            )
        )

    def processAlgorithm(self, parameters: dict, context, feedback) -> dict:
        config_path = self.parameterAsFile(parameters, self.CONFIG, context)
        if not config_path:
            raise QgsProcessingException(self.tr("A run configuration file is required."))
        try:
            run = load_config(config_path)
        except (ValueError, OSError) as exc:
            raise QgsProcessingException(str(exc)) from exc

        out_path_str = self.parameterAsFileOutput(parameters, self.OUT, context)
        out_path = Path(out_path_str) if out_path_str else Path(run.output_dir) / "water_levels.csv"
        datum = self.parameterAsString(parameters, self.DATUM, context) or None
        window_days = self.parameterAsInt(parameters, self.WINDOW_DAYS, context)
        sleep_s = self.parameterAsDouble(parameters, self.SLEEP, context)

        rows = []
        for site in run.sites:
            for sy in site.shorelines:
                if feedback.isCanceled():
                    break
                row = {"site": site.name, "year": sy.year, "acquisition_date": sy.acquisition_date}
                try:
                    layer = read_shoreline(sy.path)
                    lat, lon = site_lat_lon(layer)
                    if sy.acquisition_date:
                        result = get_water_level(
                            lat, lon, sy.acquisition_date, window_days=window_days, datum=datum
                        )
                    else:
                        result = get_annual_water_level(lat, lon, sy.year, datum=datum)
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
                    feedback.pushWarning(f"{site.name} {sy.year}: {exc}")
                rows.append(row)
                time.sleep(max(sleep_s, 0.0))

        df = pd.DataFrame(rows)
        write_table_csv(df, out_path)
        n_ok = int(df["error"].isna().sum()) if "error" in df.columns and len(df) else 0
        feedback.pushInfo(f"Wrote {len(df)} row(s) ({n_ok} successful) to {out_path}")
        return {self.OUT: str(out_path)}
