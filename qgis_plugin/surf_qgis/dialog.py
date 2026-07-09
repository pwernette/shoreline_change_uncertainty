"""Hybrid input dialog for the Shoreline Change Uncertainty plugin.

Two ways to configure a run, in one dialog:
  - "Site" / "Analysis options" / "Professional comparison" tabs: build a
    RunConfig for a single site interactively through plain widgets (file
    pickers, spin boxes, a table for shoreline years) -- no YAML/JSON
    authoring needed for the common one-site-at-a-time case.
  - "Load/save config file" tab: load an existing YAML/JSON RunConfig (e.g.
    a multi-site config already used with the CLI) via
    config_qgis.load_config to populate the single-site tabs from its first
    site, or save the dialog's current state out to a config file -- so the
    same config files work interchangeably between the CLI
    (surf package) and this plugin.

This dialog only *builds* a validated RunConfig (self.run_config, set when
the user accepts the dialog); it does not execute the pipeline or touch the
map canvas itself -- running it through the registered
QgsProcessingAlgorithm and loading outputs into the canvas is wired in by
plugin.py once that algorithm exists (see processing_provider.py /
processing_algorithm.py, and the "Wire dialog to algorithm" task).

All widget-value extraction is funneled through `build_run_config()`, a
pure function with no Qt dependency, so the RunConfig-assembly/validation
logic is fully unit-testable without a real Qt event loop -- the
qgis_stub.py qgis.PyQt stand-ins used in this sandbox's tests are
deliberately bare/inert (see that module's docstring), so only
`build_run_config()` and "does the dialog construct without raising" are
exercised by qgis_plugin/tests/test_dialog_qgis.py today. Full widget
round-trip behavior (populate_from_run_config / get_run_config actually
reading real widget state) needs a real Qt event loop and is exercised once
this dialog is wired to the Processing algorithm.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config_qgis import (
    ProfessionalDelineation,
    RunConfig,
    ShorelineYear,
    SiteConfig,
    UncertaintyComponents,
    load_config,
    validate_config,
)

_COORDINATE_PRIORITIES = ["UPPER_LEFT", "UPPER_RIGHT", "LOWER_LEFT", "LOWER_RIGHT"]
_EPSILON_BAND_METHODS = ["odb", "perkal", "both", "prob_change"]

# Shoreline-year table columns.
_COL_YEAR, _COL_PATH, _COL_RMSE95, _COL_RMSE_BASE, _COL_RMSE_GEOREF, _COL_RMSE_INTERP, _COL_ACQ_DATE = range(7)
_SHORELINE_HEADERS = [
    "Year", "Shapefile", "RMSE95 override", "RMSE base", "RMSE georef",
    "RMSE interp", "Acquisition date (YYYY-MM-DD)",
]

# Professional-comparison table columns.
_COL_PRO_NAME, _COL_PRO_YEAR, _COL_PRO_PATH = range(3)
_PROFESSIONAL_HEADERS = ["Name", "Year", "Shapefile"]


def build_run_config(
    *,
    site_name: str,
    shorelines: list,
    baseline: Optional[str],
    transect_spacing: float,
    transect_length: float,
    coordinate_priority: str,
    rate_transect_spacing: float,
    professionals: list,
    output_dir: str,
    target_crs: Optional[str],
    confidence_levels: list,
    significance_threshold: float,
    epsilon_band_method: str,
    compute_prob_change: bool,
    prob_change_segment_length: float,
    compute_rate_of_change: bool,
    export_intersect_geometries: bool,
    raster_cell_size: float,
) -> RunConfig:
    """Pure assembly + validation of a single-site RunConfig from plain
    Python values (no Qt) -- the part of dialog construction that's
    unit-testable without a real Qt event loop.

    `shorelines` is a list of dicts with keys year/path/rmse95_override/
    rmse_base/rmse_georef/rmse_interp/acquisition_date (any value besides
    year/path may be None or an empty string to mean "unset"). `professionals`
    is a list of dicts with keys name/year/path.

    If a shoreline's rmse95_override is set (non-empty), it takes priority
    and no UncertaintyComponents block is attached for that year -- mirrors
    rmse95_override's documented meaning of "skip the RMSE calc, use this
    buffer radius directly" (config_qgis.ShorelineYear). Otherwise an
    UncertaintyComponents is built from rmse_base/rmse_georef/rmse_interp
    (defaulting missing rmse_base/rmse_georef to 0.0, consistent with
    UncertaintyComponents' own dataclass defaults) -- but only if at least
    one rmse_* field was actually supplied; if none were (and there's no
    rmse95_override either), `uncertainty` is left None so validate_config
    raises its "needs rmse95_override or uncertainty" error, rather than
    silently treating a blank row as 0.0/0.0/None uncertainty.

    Raises ValueError (via validate_config) on any structural problem --
    the same errors load_config raises for an equivalent YAML/JSON config.
    """
    shoreline_years = []
    for s in shorelines:
        rmse95_override = s.get("rmse95_override")
        rmse95_override = float(rmse95_override) if rmse95_override not in (None, "") else None

        uncertainty = None
        has_any_rmse_field = any(
            s.get(key) not in (None, "") for key in ("rmse_base", "rmse_georef", "rmse_interp")
        )
        if rmse95_override is None and has_any_rmse_field:
            rmse_interp = s.get("rmse_interp")
            uncertainty = UncertaintyComponents(
                rmse_base=float(s.get("rmse_base") or 0.0),
                rmse_georef=float(s.get("rmse_georef") or 0.0),
                rmse_interp=float(rmse_interp) if rmse_interp not in (None, "") else None,
            )

        shoreline_years.append(
            ShorelineYear(
                year=int(s["year"]),
                path=s["path"],
                uncertainty=uncertainty,
                rmse95_override=rmse95_override,
                acquisition_date=s.get("acquisition_date") or None,
            )
        )

    site = SiteConfig(
        name=site_name,
        shorelines=shoreline_years,
        baseline=baseline or None,
        transect_spacing=float(transect_spacing),
        transect_length=float(transect_length),
        coordinate_priority=coordinate_priority,
        professionals=[
            ProfessionalDelineation(name=p["name"], year=int(p["year"]), path=p["path"])
            for p in professionals
        ],
        rate_transect_spacing=float(rate_transect_spacing),
    )

    run = RunConfig(
        sites=[site],
        output_dir=output_dir,
        target_crs=target_crs or None,
        confidence_levels=list(confidence_levels),
        significance_threshold=float(significance_threshold),
        epsilon_band_method=epsilon_band_method,
        compute_prob_change=bool(compute_prob_change),
        prob_change_segment_length=float(prob_change_segment_length),
        compute_rate_of_change=bool(compute_rate_of_change),
        export_intersect_geometries=bool(export_intersect_geometries),
        raster_cell_size=float(raster_cell_size),
    )
    validate_config(run)
    return run


def write_run_config(run: RunConfig, path: str | Path) -> None:
    """Serialize a RunConfig back out to a YAML/JSON file, mirroring
    config_qgis.load_config's expected structure exactly so the written
    file round-trips through load_config (and therefore through the CLI's
    surf.config.load_config too, since both are the same
    schema). Used by the dialog's "Save config file..." button, and usable
    standalone."""
    import json

    import yaml

    def shoreline_dict(sy: ShorelineYear) -> dict:
        d: dict = {"year": sy.year, "path": sy.path}
        if sy.rmse95_override is not None:
            d["rmse95_override"] = sy.rmse95_override
        if sy.uncertainty is not None:
            u = sy.uncertainty
            u_dict = {"rmse_base": u.rmse_base, "rmse_georef": u.rmse_georef}
            if u.rmse_interp is not None:
                u_dict["rmse_interp"] = u.rmse_interp
            if u.interp_distances is not None:
                u_dict["interp_distances"] = u.interp_distances
            d["uncertainty"] = u_dict
        if sy.acquisition_date is not None:
            d["acquisition_date"] = sy.acquisition_date
        return d

    def site_dict(site: SiteConfig) -> dict:
        d: dict = {
            "name": site.name,
            "shorelines": [shoreline_dict(sy) for sy in site.shorelines],
            "transect_spacing": site.transect_spacing,
            "transect_length": site.transect_length,
            "coordinate_priority": site.coordinate_priority,
            "rate_transect_spacing": site.rate_transect_spacing,
        }
        if site.baseline is not None:
            d["baseline"] = site.baseline
        if site.professionals:
            d["professionals"] = [
                {"name": p.name, "year": p.year, "path": p.path} for p in site.professionals
            ]
        return d

    raw: dict = {
        "sites": [site_dict(s) for s in run.sites],
        "output_dir": run.output_dir,
        "confidence_levels": run.confidence_levels,
        "significance_threshold": run.significance_threshold,
        "epsilon_band_method": run.epsilon_band_method,
        "compute_prob_change": run.compute_prob_change,
        "prob_change_segment_length": run.prob_change_segment_length,
        "compute_rate_of_change": run.compute_rate_of_change,
        "export_intersect_geometries": run.export_intersect_geometries,
        "raster_cell_size": run.raster_cell_size,
    }
    if run.target_crs is not None:
        raw["target_crs"] = run.target_crs

    path = Path(path)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(raw, indent=2))
    else:
        path.write_text(yaml.safe_dump(raw, sort_keys=False))


class SURFDialog(QDialog):
    """The plugin's main input dialog. See module docstring for the
    quick-setup-tabs vs. load/save-config-file split."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shoreline Change Uncertainty")
        self.run_config: Optional[RunConfig] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_site_tab(), "Site")
        self.tabs.addTab(self._build_options_tab(), "Analysis options")
        self.tabs.addTab(self._build_professionals_tab(), "Professional comparison")
        self.tabs.addTab(self._build_config_file_tab(), "Load/save config file")

        button_row = QHBoxLayout()
        ok_button = QPushButton("Run")
        ok_button.clicked.connect(self._on_accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def _build_site_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        self.site_name_edit = QLineEdit("site_1")
        form.addRow("Site name", self.site_name_edit)

        baseline_row = QHBoxLayout()
        self.baseline_edit = QLineEdit()
        baseline_browse = QPushButton("Browse...")
        baseline_browse.clicked.connect(self._browse_baseline)
        baseline_row.addWidget(self.baseline_edit)
        baseline_row.addWidget(baseline_browse)
        form.addRow("Baseline (optional; auto-detected if blank)", baseline_row)

        self.transect_spacing_spin = QDoubleSpinBox()
        self.transect_spacing_spin.setRange(0.01, 1e9)
        self.transect_spacing_spin.setValue(50.0)
        form.addRow("Transect spacing", self.transect_spacing_spin)

        self.transect_length_spin = QDoubleSpinBox()
        self.transect_length_spin.setRange(0.01, 1e9)
        self.transect_length_spin.setValue(1000.0)
        form.addRow("Transect length", self.transect_length_spin)

        self.coordinate_priority_combo = QComboBox()
        self.coordinate_priority_combo.addItems(_COORDINATE_PRIORITIES)
        form.addRow("Coordinate priority", self.coordinate_priority_combo)

        self.rate_transect_spacing_spin = QDoubleSpinBox()
        self.rate_transect_spacing_spin.setRange(0.01, 1e9)
        self.rate_transect_spacing_spin.setValue(1.0)
        form.addRow("Rate-of-change transect spacing", self.rate_transect_spacing_spin)

        self.shoreline_table = QTableWidget(0, len(_SHORELINE_HEADERS))
        self.shoreline_table.setHorizontalHeaderLabels(_SHORELINE_HEADERS)
        form.addRow(self.shoreline_table)

        row_buttons = QHBoxLayout()
        add_btn = QPushButton("Add shoreline year")
        add_btn.clicked.connect(lambda: self._add_shoreline_row())
        remove_btn = QPushButton("Remove selected row")
        remove_btn.clicked.connect(self._remove_selected_shoreline_row)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(remove_btn)
        form.addRow(row_buttons)

        return widget

    def _build_options_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)

        output_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit("output")
        output_browse = QPushButton("Browse...")
        output_browse.clicked.connect(self._browse_output_dir)
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(output_browse)
        form.addRow("Output directory", output_row)

        self.target_crs_edit = QLineEdit()
        self.target_crs_edit.setPlaceholderText("e.g. EPSG:32616 (auto-UTM if blank)")
        form.addRow("Target CRS (optional)", self.target_crs_edit)

        self.epsilon_band_method_combo = QComboBox()
        self.epsilon_band_method_combo.addItems(_EPSILON_BAND_METHODS)
        form.addRow("Epsilon-band method", self.epsilon_band_method_combo)

        self.significance_threshold_spin = QDoubleSpinBox()
        self.significance_threshold_spin.setRange(0.0, 1.0)
        self.significance_threshold_spin.setDecimals(3)
        self.significance_threshold_spin.setValue(0.05)
        form.addRow("Significance threshold", self.significance_threshold_spin)

        self.confidence_levels_edit = QLineEdit("0.05, 0.50, 0.90, 0.95")
        form.addRow("Confidence levels (comma-separated)", self.confidence_levels_edit)

        self.raster_cell_size_spin = QDoubleSpinBox()
        self.raster_cell_size_spin.setRange(0.001, 1e6)
        self.raster_cell_size_spin.setValue(0.5)
        form.addRow("Raster cell size", self.raster_cell_size_spin)

        self.compute_prob_change_check = QCheckBox("Compute change-probability surfaces")
        form.addRow(self.compute_prob_change_check)

        self.prob_change_segment_length_spin = QDoubleSpinBox()
        self.prob_change_segment_length_spin.setRange(0.01, 1e9)
        self.prob_change_segment_length_spin.setValue(50.0)
        form.addRow("Probability-change segment length", self.prob_change_segment_length_spin)

        self.compute_rate_of_change_check = QCheckBox("Compute EPR/LRR rate of change")
        form.addRow(self.compute_rate_of_change_check)

        self.export_intersect_geometries_check = QCheckBox("Export intersect geometries")
        form.addRow(self.export_intersect_geometries_check)

        return widget

    def _build_professionals_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.professionals_table = QTableWidget(0, len(_PROFESSIONAL_HEADERS))
        self.professionals_table.setHorizontalHeaderLabels(_PROFESSIONAL_HEADERS)
        layout.addWidget(self.professionals_table)

        row_buttons = QHBoxLayout()
        add_btn = QPushButton("Add professional shoreline")
        add_btn.clicked.connect(lambda: self._add_professional_row())
        remove_btn = QPushButton("Remove selected row")
        remove_btn.clicked.connect(self._remove_selected_professional_row)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(remove_btn)
        layout.addLayout(row_buttons)

        return widget

    def _build_config_file_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(
            "Load an existing YAML/JSON run configuration (as used by the "
            "surf CLI) to populate the tabs above from that "
            "config's first site, or save the current dialog state out to a "
            "config file. Loading a multi-site config only populates this "
            "dialog's single-site fields -- use the CLI directly for true "
            "multi-site batch runs."
        ))
        button_row = QHBoxLayout()
        load_btn = QPushButton("Load config file...")
        load_btn.clicked.connect(self._load_config_file)
        save_btn = QPushButton("Save config file...")
        save_btn.clicked.connect(self._save_config_file)
        button_row.addWidget(load_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)
        return widget

    # ------------------------------------------------------------------
    # Row add/remove
    # ------------------------------------------------------------------

    def _add_shoreline_row(
        self, year="", path="", rmse95_override="", rmse_base="", rmse_georef="",
        rmse_interp="", acquisition_date="",
    ) -> None:
        row = self.shoreline_table.rowCount()
        self.shoreline_table.insertRow(row)
        values = [year, path, rmse95_override, rmse_base, rmse_georef, rmse_interp, acquisition_date]
        for col, value in enumerate(values):
            self.shoreline_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _remove_selected_shoreline_row(self) -> None:
        row = self.shoreline_table.currentRow()
        if row >= 0:
            self.shoreline_table.removeRow(row)

    def _add_professional_row(self, name="", year="", path="") -> None:
        row = self.professionals_table.rowCount()
        self.professionals_table.insertRow(row)
        for col, value in enumerate([name, year, path]):
            self.professionals_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _remove_selected_professional_row(self) -> None:
        row = self.professionals_table.currentRow()
        if row >= 0:
            self.professionals_table.removeRow(row)

    # ------------------------------------------------------------------
    # File browsing
    # ------------------------------------------------------------------

    def _browse_baseline(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select baseline shapefile", "", "Shapefiles (*.shp)")
        if path:
            self.baseline_edit.setText(path)

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output directory")
        if path:
            self.output_dir_edit.setText(path)

    # ------------------------------------------------------------------
    # Config-file load/save
    # ------------------------------------------------------------------

    def _load_config_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load run configuration", "", "Config files (*.yaml *.yml *.json)"
        )
        if not path:
            return
        try:
            run = load_config(path)
            self.populate_from_run_config(run)
        except Exception as exc:  # noqa: BLE001 -- surface any load/validation error to the user
            QMessageBox.critical(self, "Failed to load config", str(exc))

    def _save_config_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save run configuration", "", "YAML files (*.yaml *.yml);;JSON files (*.json)"
        )
        if not path:
            return
        try:
            run = self.get_run_config()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Cannot save -- dialog has invalid values", str(exc))
            return
        write_run_config(run, path)

    # ------------------------------------------------------------------
    # Widgets <-> RunConfig
    # ------------------------------------------------------------------

    def populate_from_run_config(self, run: RunConfig) -> None:
        """Fill every widget from `run` (its first site, for the
        single-site quick-setup tabs)."""
        site = run.sites[0]
        self.site_name_edit.setText(site.name)
        self.baseline_edit.setText(site.baseline or "")
        self.transect_spacing_spin.setValue(site.transect_spacing)
        self.transect_length_spin.setValue(site.transect_length)
        idx = self.coordinate_priority_combo.findText(site.coordinate_priority)
        if idx >= 0:
            self.coordinate_priority_combo.setCurrentIndex(idx)
        self.rate_transect_spacing_spin.setValue(site.rate_transect_spacing)

        self.shoreline_table.setRowCount(0)
        for sy in site.shorelines:
            u = sy.uncertainty
            self._add_shoreline_row(
                year=sy.year,
                path=sy.path,
                rmse95_override=sy.rmse95_override if sy.rmse95_override is not None else "",
                rmse_base=u.rmse_base if u else "",
                rmse_georef=u.rmse_georef if u else "",
                rmse_interp=u.rmse_interp if u and u.rmse_interp is not None else "",
                acquisition_date=sy.acquisition_date or "",
            )

        self.professionals_table.setRowCount(0)
        for p in site.professionals:
            self._add_professional_row(name=p.name, year=p.year, path=p.path)

        self.output_dir_edit.setText(run.output_dir)
        self.target_crs_edit.setText(run.target_crs or "")
        idx = self.epsilon_band_method_combo.findText(run.epsilon_band_method)
        if idx >= 0:
            self.epsilon_band_method_combo.setCurrentIndex(idx)
        self.significance_threshold_spin.setValue(run.significance_threshold)
        self.confidence_levels_edit.setText(", ".join(str(c) for c in run.confidence_levels))
        self.raster_cell_size_spin.setValue(run.raster_cell_size)
        self.compute_prob_change_check.setChecked(run.compute_prob_change)
        self.prob_change_segment_length_spin.setValue(run.prob_change_segment_length)
        self.compute_rate_of_change_check.setChecked(run.compute_rate_of_change)
        self.export_intersect_geometries_check.setChecked(run.export_intersect_geometries)

    def get_run_config(self) -> RunConfig:
        """Read every widget and build+validate a single-site RunConfig.
        Raises ValueError on any structural problem (the same errors
        validate_config raises for an equivalent YAML/JSON config)."""

        def table_cell(table: QTableWidget, row: int, col: int) -> str:
            item = table.item(row, col)
            return item.text() if item is not None else ""

        shorelines = []
        for row in range(self.shoreline_table.rowCount()):
            shorelines.append({
                "year": table_cell(self.shoreline_table, row, _COL_YEAR),
                "path": table_cell(self.shoreline_table, row, _COL_PATH),
                "rmse95_override": table_cell(self.shoreline_table, row, _COL_RMSE95) or None,
                "rmse_base": table_cell(self.shoreline_table, row, _COL_RMSE_BASE) or None,
                "rmse_georef": table_cell(self.shoreline_table, row, _COL_RMSE_GEOREF) or None,
                "rmse_interp": table_cell(self.shoreline_table, row, _COL_RMSE_INTERP) or None,
                "acquisition_date": table_cell(self.shoreline_table, row, _COL_ACQ_DATE) or None,
            })

        professionals = []
        for row in range(self.professionals_table.rowCount()):
            professionals.append({
                "name": table_cell(self.professionals_table, row, _COL_PRO_NAME),
                "year": table_cell(self.professionals_table, row, _COL_PRO_YEAR),
                "path": table_cell(self.professionals_table, row, _COL_PRO_PATH),
            })

        confidence_levels = [
            float(v.strip()) for v in self.confidence_levels_edit.text().split(",") if v.strip()
        ]

        return build_run_config(
            site_name=self.site_name_edit.text() or "site_1",
            shorelines=shorelines,
            baseline=self.baseline_edit.text() or None,
            transect_spacing=self.transect_spacing_spin.value(),
            transect_length=self.transect_length_spin.value(),
            coordinate_priority=self.coordinate_priority_combo.currentText(),
            rate_transect_spacing=self.rate_transect_spacing_spin.value(),
            professionals=professionals,
            output_dir=self.output_dir_edit.text() or "output",
            target_crs=self.target_crs_edit.text() or None,
            confidence_levels=confidence_levels or [0.05, 0.50, 0.90, 0.95],
            significance_threshold=self.significance_threshold_spin.value(),
            epsilon_band_method=self.epsilon_band_method_combo.currentText(),
            compute_prob_change=self.compute_prob_change_check.isChecked(),
            prob_change_segment_length=self.prob_change_segment_length_spin.value(),
            compute_rate_of_change=self.compute_rate_of_change_check.isChecked(),
            export_intersect_geometries=self.export_intersect_geometries_check.isChecked(),
            raster_cell_size=self.raster_cell_size_spin.value(),
        )

    # ------------------------------------------------------------------
    # Accept/cancel
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        try:
            self.run_config = self.get_run_config()
        except Exception as exc:  # noqa: BLE001 -- surface any validation error, keep dialog open
            QMessageBox.critical(self, "Invalid configuration", str(exc))
            return
        self.accept()
