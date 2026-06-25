"""Main plugin class: registers a toolbar/menu entry and the Processing
provider, and wires the input dialog (dialog.py) to the Processing
algorithm + map canvas (runner.py/result_loader.py) when the user accepts
the dialog.

All Qt imports go through `qgis.PyQt`, the shim QGIS itself uses so plugin
code doesn't need separate PyQt5/PyQt6 branches for QGIS 3.x vs. 4.0+.
"""
from __future__ import annotations

import os.path

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class ShorelineUncertaintyPlugin:
    """QGIS requires this object to implement `initGui()` and `unload()`;
    everything else is ours to design."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions: list[QAction] = []
        self.menu = "&Shoreline Change Uncertainty"
        self._provider = None

    def initGui(self) -> None:  # noqa: N802 -- QGIS-required method name
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        action = QAction(
            QIcon(icon_path) if os.path.exists(icon_path) else QIcon(),
            "Shoreline Change Uncertainty...",
            self.iface.mainWindow(),
        )
        action.triggered.connect(self.run)
        self.iface.addToolBarIcon(action)
        self.iface.addPluginToVectorMenu(self.menu, action)
        self.actions.append(action)

        self._register_processing_provider()

    def unload(self) -> None:  # noqa: N802 -- QGIS-required method name
        for action in self.actions:
            self.iface.removePluginVectorMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        self.actions = []

        if self._provider is not None:
            from qgis.core import QgsApplication

            QgsApplication.processingRegistry().removeProvider(self._provider)
            self._provider = None

    def _register_processing_provider(self) -> None:
        """Registers the Processing provider if one is available yet. A
        no-op for now (returns silently) until the provider module exists --
        keeps this class importable/testable at every stage of the build."""
        try:
            from qgis.core import QgsApplication

            from .processing_provider import ShorelineUncertaintyProvider
        except ImportError:
            return
        self._provider = ShorelineUncertaintyProvider()
        QgsApplication.processingRegistry().addProvider(self._provider)

    def run(self) -> None:
        """Opens the plugin's input dialog. If the user accepts it
        (dialog.run_config is set), runs the resulting configuration
        through RunAnalysisAlgorithm and loads every output vector/raster
        file it produced into the map canvas -- see runner.py's
        execute_run_config for the actual run-and-load logic, kept separate
        from this UI-wiring method so it's unit-testable without a real Qt
        event loop."""
        from qgis.PyQt.QtWidgets import QMessageBox

        try:
            from .dialog import ShorelineUncertaintyDialog
        except ImportError:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Shoreline Change Uncertainty",
                "The input dialog hasn't been built yet -- coming in a later step.",
            )
            return

        dialog = ShorelineUncertaintyDialog(self.iface.mainWindow())
        dialog.exec_()
        if dialog.run_config is None:
            return  # user canceled / closed the dialog without accepting

        from .runner import execute_run_config

        try:
            result = execute_run_config(dialog.run_config)
        except Exception as exc:  # noqa: BLE001 -- surface any run failure to the user, not a bare traceback
            QMessageBox.critical(self.iface.mainWindow(), "Run failed", str(exc))
            return

        QMessageBox.information(
            self.iface.mainWindow(),
            "Shoreline Change Uncertainty",
            f"Run complete. Loaded {len(result['layers'])} layer(s) from "
            f"'{result['output_dir']}'.",
        )
