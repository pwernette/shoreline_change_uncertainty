"""Processing provider that registers this plugin's QgsProcessingAlgorithm
subclasses (processing_algorithm.py) with QGIS's Processing framework, so
they show up in the Toolbox / batch processing / model designer / Python
console (e.g. `processing.run("surf:run_analysis", ...)`)
the same way any built-in QGIS algorithm does. Registered/unregistered by
plugin.py's `_register_processing_provider`/`unload` via
`QgsApplication.processingRegistry().add/removeProvider`.
"""
from __future__ import annotations

from qgis.core import QgsProcessingProvider

from .processing_algorithm import RunAnalysisAlgorithm, WaterLevelLookupAlgorithm


class SURFProvider(QgsProcessingProvider):
    """One provider exposing both algorithms under a single
    "Shoreline Change Uncertainty" group in the Processing Toolbox."""

    def id(self) -> str:  # noqa: A003 -- matches QgsProcessingProvider's real method name
        return "surf"

    def name(self) -> str:
        return "Shoreline Change Uncertainty"

    def loadAlgorithms(self) -> None:
        self.addAlgorithm(RunAnalysisAlgorithm())
        self.addAlgorithm(WaterLevelLookupAlgorithm())
