"""Ties the dialog's validated RunConfig to the registered
RunAnalysisAlgorithm and to result_loader.load_output_layers -- this is the
"wire dialog to algorithm, load results into map canvas" task. Split out
from plugin.py (which only handles UI wiring: opening the dialog, showing
message boxes on success/failure) so the actual run-and-load logic is
unit-testable without a real Qt event loop, the same carve-out pattern as
dialog.py's build_run_config and result_loader.py's discover_output_files.

Runs through RunAnalysisAlgorithm (rather than calling pipeline_qgis.run_
pipeline directly) so a dialog-driven run and a Processing-Toolbox-driven
run go through the exact same code path -- the dialog is just an
alternative way of producing the run-configuration file the algorithm's
own CONFIG parameter expects.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from qgis.core import QgsProcessingFeedback, QgsProject

from .config_qgis import RunConfig
from .dialog import write_run_config
from .processing_algorithm import RunAnalysisAlgorithm
from .result_loader import load_output_layers


def execute_run_config(
    run: RunConfig,
    *,
    project: Optional["QgsProject"] = None,
    feedback: Optional["QgsProcessingFeedback"] = None,
) -> dict:
    """Write `run` out to a temporary config file, execute it through
    RunAnalysisAlgorithm (the same Processing algorithm exposed in the
    Toolbox/batch/model designer), then load every produced vector/raster
    output file into `project` (defaults to QgsProject.instance()) as map
    layers.

    Any failure raised by the algorithm (bad config, pipeline error) -- a
    QgsProcessingException -- propagates to the caller; plugin.py is
    responsible for catching it and showing the user a message box rather
    than letting it escape into QGIS's UI thread unhandled.

    Returns {"output_dir": str, "layers": [...]} -- `layers` is the list of
    QgsVectorLayer/QgsRasterLayer objects actually built and added to the
    project, which the caller can e.g. zoom the canvas to.
    """
    if project is None:
        project = QgsProject.instance()
    if feedback is None:
        feedback = QgsProcessingFeedback()

    tmp_dir = Path(tempfile.mkdtemp(prefix="shoreline_uncertainty_"))
    config_path = tmp_dir / "run_config.yaml"
    write_run_config(run, config_path)

    alg = RunAnalysisAlgorithm()
    alg.initAlgorithm()
    result = alg.processAlgorithm({"CONFIG": str(config_path)}, None, feedback)

    output_dir = result["OUTPUT_DIR"]
    layers = load_output_layers(output_dir, project=project)
    return {"output_dir": output_dir, "layers": layers}
