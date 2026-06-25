"""QGIS-native port of shoreline_uncertainty/pipeline.py.

End-to-end orchestration: load a config, run every analysis stage for every
site, and write all outputs -- same per-site stage structure as the
standalone package's pipeline.py (see its docstrings for the full
replaces-original-arcpy-scripts rationale), just built on `qgis.core`
QgsVectorLayer/QgsGeometry + QGIS-bundled-GDAL instead of geopandas/shapely/
rasterio:

  - `io_utils_qgis.read_shoreline`/`ensure_projected` replace
    `io_utils.read_shoreline`/`ensure_projected`, returning a QgsVectorLayer
    instead of a GeoDataFrame.
  - `geometry_utils_qgis.dissolve(layer_geometries(layer))` replaces
    `shapely.ops.unary_union(gdf.geometry)`.
  - `QgsGeometry.length()` (a method) replaces shapely's `.length`
    (a property).
  - `transects_qgis.transects_to_layer` replaces `transects.transects_to_gdf`.
  - `compute_baseline_direction` takes a QgsVectorLayer directly (it already
    iterates `layer_geometries` internally), not a bare geometry list.
  - The ODB overlap-geometries export and every raster/vector output is
    assembled via `io_utils_qgis.build_memory_layer`/`write_vector`/
    `write_raster` instead of building a GeoDataFrame and calling
    `gdf.to_file`/`rasterio`.
  - `config_qgis`/`uncertainty_qgis` are this package's own self-contained
    copies of config.py/uncertainty.py (pure dataclasses/math, zero qgis
    dependency) -- see their module docstrings.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from qgis.core import QgsField
from tqdm import tqdm

from . import io_utils_qgis as io_utils
from .comparison_qgis import compare_professionals_pairwise, compare_to_professionals, professional_summary
from .config_qgis import RunConfig, SiteConfig
from .critical_areas_qgis import identify_critical_areas
from .epsilon_bands_qgis import overlapping_double_buffer, run_odb_for_site, run_perkal_for_site
from .geometry_utils_qgis import dissolve
from .probability_surface_qgis import (
    change_probability_raster,
    change_probability_table,
    position_probability_surfaces,
    rmse95_to_sigma,
    segment_line,
    shoreline_change_probability_segments,
)
from .raster_output_qgis import build_grid_transform, build_similarity_surface, write_raster
from .rate_of_change_qgis import build_rate_change_polygons, compute_rate_of_change
from .transects_qgis import (
    baseline_center_direction,
    build_baseline,
    compute_baseline_direction,
    generate_transects,
    intersect_transects_shorelines,
    nearest_transect_net_distance,
    to_wide_table,
    transects_to_layer,
)
from .uncertainty_qgis import assign_uncertainty

log = logging.getLogger(__name__)


def _load_site_shorelines(site: SiteConfig, target_crs, *, progress: bool = True):
    """Read every shoreline year for a site, reproject, and dissolve each to
    a single geometry for buffer/area/length math.

    Returns (layer_by_year, dissolved_geom_by_year, crs).
    """
    layer_by_year = {}
    crs = None
    for sy in tqdm(site.shorelines, desc=f"{site.name}: loading shorelines", disable=not progress, leave=False):
        layer = io_utils.read_shoreline(sy.path)
        layer = io_utils.ensure_projected(layer, target_crs)
        layer_by_year[sy.year] = layer
        crs = layer.crs()
    dissolved = {year: dissolve(io_utils.layer_geometries(layer)) for year, layer in layer_by_year.items()}
    return layer_by_year, dissolved, crs


def run_site(site: SiteConfig, run: RunConfig, output_dir: Path, *, progress: bool = True) -> dict:
    """Run every analysis stage configured by `run` for a single `site` and
    write all resulting tables/shapefiles/rasters under
    `output_dir/<site.name>/`.

    Stages are independent and each gated by its own RunConfig/SiteConfig
    flag, so a given call may execute any subset of: ODB and/or Perkal
    epsilon-band significance testing (+ the similarity-index/significant-
    change rasters derived from ODB), shore-normal transects and their
    per-year distance table, EPR/LRR rate-of-change along a separate denser
    transect grid, professional-delineation comparison, and the Gaussian
    position-probability / change-probability surfaces (plus their
    per-segment vector summaries). See the inline `# --- stage --- ` comments
    below for the boundary between each stage.

    Returns a dict of in-memory results keyed by stage name (e.g. "odb",
    "transects", "rate_of_change", "rate_change_polygons", "prob_change",
    "prob_change_segments", "professional_comparison", "raster") -- the
    same data that gets written to disk, useful for tests and for chaining
    results without re-reading files back in.
    """
    log.info("Processing site: %s", site.name)
    site_dir = output_dir / site.name
    site_dir.mkdir(parents=True, exist_ok=True)

    layer_by_year, dissolved_by_year, crs = _load_site_shorelines(site, run.target_crs, progress=progress)
    radii_by_year = assign_uncertainty(site)
    # Hoisted out of the compute_prob_change-only block below: also needed,
    # unconditionally, by the rate_of_change polygon-probability stage and
    # by the change_probability_segments MAGNITUDE lookup, neither of which
    # require compute_prob_change to be set.
    sigma_by_year = {year: rmse95_to_sigma(radii_by_year[year]) for year in radii_by_year}

    # --- Baseline (shared by transects and the probabilistic surfaces) ---
    if site.baseline:
        baseline_layer = io_utils.ensure_projected(io_utils.read_shoreline(site.baseline), run.target_crs)
        baseline = dissolve(io_utils.layer_geometries(baseline_layer))
    else:
        any_year_layer = next(iter(layer_by_year.values()))
        center, direction = compute_baseline_direction(any_year_layer)
        total_len = max(g.length() for g in dissolved_by_year.values()) * 1.5
        baseline = build_baseline(center, direction, total_len)
    baseline_center, baseline_direction = baseline_center_direction(baseline)

    results: dict = {}
    odb_objects = []

    # --- Epsilon bands (significance testing) ---
    if run.epsilon_band_method in ("odb", "both"):
        years = sorted(dissolved_by_year)
        year_pairs = [(year_a, year_b) for i, year_a in enumerate(years) for year_b in years[i + 1:]]
        for year_a, year_b in tqdm(
            year_pairs, desc=f"{site.name}: building ODB buffer pairs", disable=not progress, leave=False
        ):
            odb_objects.append(overlapping_double_buffer(
                dissolved_by_year[year_a], radii_by_year[year_a],
                dissolved_by_year[year_b], radii_by_year[year_b],
                site=site.name, year_a=year_a, year_b=year_b,
                threshold=run.significance_threshold,
            ))

        odb_df = run_odb_for_site(
            site.name, dissolved_by_year, radii_by_year, threshold=run.significance_threshold, progress=progress
        )
        io_utils.write_table_csv(odb_df, site_dir / "odb_overlapping_buffer_table.csv")
        io_utils.write_table_pipe_log(
            odb_df, site_dir / f"{site.name}_OVERLAPPING_BANDS.txt",
            header_lines=[f"Site: {site.name}"],
        )
        results["odb"] = odb_df

        if run.export_intersect_geometries and odb_objects:
            overlap_geoms = [r.intersection for r in odb_objects if not r.intersection.isEmpty()]
            overlap_attrs = [
                (r.year_a, r.year_b, r.prop_ab_overlap)
                for r in odb_objects if not r.intersection.isEmpty()
            ]
            if overlap_geoms:
                overlap_layer = io_utils.build_memory_layer(
                    geometries=overlap_geoms,
                    fields=[QgsField("YEAR_A"), QgsField("YEAR_B"), QgsField("PROP_AB_OVERLAP")],
                    attributes=overlap_attrs,
                    geometry_kind="Polygon",
                    crs=crs,
                    name="odb_overlap_geometries",
                )
                io_utils.write_vector(overlap_layer, site_dir / "odb_overlap_geometries.shp")

    if run.epsilon_band_method in ("perkal", "both"):
        perkal_df = run_perkal_for_site(site.name, dissolved_by_year, run.confidence_levels, progress=progress)
        io_utils.write_table_csv(perkal_df, site_dir / "perkal_shoreline_buffer_table.csv")
        results["perkal"] = perkal_df

        critical_summary, critical_layer = identify_critical_areas(
            site.name, dissolved_by_year, run.confidence_levels, crs=crs, export_table=True, progress=progress,
        )
        io_utils.write_table_csv(critical_summary, site_dir / "critical_areas_summary.csv")
        io_utils.write_vector(critical_layer, site_dir / "critical_areas.shp")
        results["critical_areas"] = critical_summary

    # --- Transects (direction/magnitude of change) ---
    transects = generate_transects(
        baseline, site.transect_spacing, site.transect_length, site.coordinate_priority, progress=progress
    )
    io_utils.write_vector(transects_to_layer(transects, crs), site_dir / "transects.shp")

    long_table = intersect_transects_shorelines(transects, dissolved_by_year, progress=progress)
    io_utils.write_table_csv(long_table, site_dir / "transect_intersections.csv")
    if not long_table.empty:
        wide_table = to_wide_table(long_table)
        io_utils.write_table_csv(wide_table, site_dir / "transect_distances_wide.csv")
        results["transects"] = wide_table

    # --- EPR / LRR rate-of-change along a separate, denser transect grid ---
    if run.compute_rate_of_change:
        rate_transects = generate_transects(
            baseline, site.rate_transect_spacing, site.transect_length, site.coordinate_priority, progress=progress,
        )
        io_utils.write_vector(transects_to_layer(rate_transects, crs), site_dir / "rate_transects.shp")

        rate_long_table = intersect_transects_shorelines(rate_transects, dissolved_by_year, progress=progress)
        io_utils.write_table_csv(rate_long_table, site_dir / "rate_transect_intersections.csv")
        if not rate_long_table.empty:
            rate_wide_table = to_wide_table(rate_long_table)
            rate_of_change_df = compute_rate_of_change(rate_wide_table)
            io_utils.write_table_csv(rate_of_change_df, site_dir / "transect_rate_of_change.csv")
            results["rate_of_change"] = rate_of_change_df

            # Polygon-area analogue of the per-transect EPR statistics: the
            # area between each pair of adjacent rate transects, with the
            # magnitude/direction of change and probability of that change
            # being "real" (see rate_of_change_qgis.build_rate_change_polygons).
            rate_change_polygons = build_rate_change_polygons(
                rate_transects, rate_wide_table, sigma_by_year, crs=crs,
            )
            io_utils.write_vector(rate_change_polygons, site_dir / "rate_change_polygons.shp")
            results["rate_change_polygons"] = rate_change_polygons

    # --- Professional comparison ---
    if site.professionals:
        prof_by_year: dict = {}
        for prof in tqdm(
            site.professionals, desc=f"{site.name}: loading professional shorelines", disable=not progress, leave=False
        ):
            prof_layer = io_utils.ensure_projected(io_utils.read_shoreline(prof.path), run.target_crs)
            prof_by_year.setdefault(prof.year, {})[prof.name] = dissolve(io_utils.layer_geometries(prof_layer))

        me_rows, pair_rows = [], []
        for year, prof_geoms in tqdm(
            prof_by_year.items(), desc=f"{site.name}: professional comparison", disable=not progress, leave=False,
            total=len(prof_by_year),
        ):
            if year in dissolved_by_year:
                me_rows.append(compare_to_professionals(
                    site.name, year, dissolved_by_year[year], prof_geoms, progress=progress
                ))
            pair_rows.append(compare_professionals_pairwise(site.name, year, prof_geoms, progress=progress))

        me_df = pd.concat(me_rows, ignore_index=True) if me_rows else pd.DataFrame()
        pair_df = pd.concat(pair_rows, ignore_index=True) if pair_rows else pd.DataFrame()
        io_utils.write_table_csv(me_df, site_dir / "professional_comparison_me_to_prof.csv")
        io_utils.write_table_csv(pair_df, site_dir / "professional_comparison_prof_to_prof.csv")
        io_utils.write_table_csv(professional_summary(pair_df), site_dir / "professional_comparison_summary.csv")
        results["professional_comparison"] = {"me_to_prof": me_df, "prof_to_prof": pair_df}

    # --- Raster similarity-index surface ---
    if odb_objects:
        similarity, significant, transform = build_similarity_surface(
            odb_objects, run.raster_cell_size, progress=progress
        )
        write_raster(similarity, transform, crs, site_dir / "similarity_index.tif")
        write_raster(significant, transform, crs, site_dir / "significant_change.tif", dtype="uint8")
        results["raster"] = {
            "similarity_index": site_dir / "similarity_index.tif",
            "significant_change": site_dir / "significant_change.tif",
        }

    # --- Probabilistic position / change-probability surfaces ---
    # Horizontal-direction analogue of Wernette et al. (2020)'s vertical
    # DEM change-probability approach -- see probability_surface_qgis.py.
    if run.compute_prob_change or run.epsilon_band_method == "prob_change":
        # Pad the raster grid a few sigma beyond the shorelines themselves
        # so each Gaussian's meaningful extent is fully captured.
        pad = 3.0 * max(sigma_by_year.values())
        padded = [geom.buffer(pad, 8) for geom in dissolved_by_year.values()]
        bbox = dissolve(padded).boundingBox()
        grid_bounds = (bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum())
        transform, width, height = build_grid_transform(grid_bounds, run.raster_cell_size)

        for year, geom in tqdm(
            dissolved_by_year.items(), desc=f"{site.name}: position probability surfaces",
            disable=not progress, leave=False, total=len(dissolved_by_year),
        ):
            pdf, confidence = position_probability_surfaces(geom, sigma_by_year[year], transform, width, height)
            write_raster(
                pdf, transform, crs, site_dir / f"position_probability_density_{year}.tif", dtype="float32"
            )
            write_raster(
                confidence, transform, crs, site_dir / f"position_confidence_{year}.tif", dtype="float32"
            )

        years = sorted(dissolved_by_year)
        year_pairs = [(year_a, year_b) for i, year_a in enumerate(years) for year_b in years[i + 1:]]
        for year_a, year_b in tqdm(
            year_pairs, desc=f"{site.name}: change-probability surfaces", disable=not progress, leave=False,
        ):
            delta, p_real = change_probability_raster(
                dissolved_by_year[year_a], sigma_by_year[year_a],
                dissolved_by_year[year_b], sigma_by_year[year_b],
                baseline_center, baseline_direction, transform, width, height,
            )
            write_raster(
                delta, transform, crs, site_dir / f"position_delta_{year_a}_{year_b}.tif", dtype="float32"
            )
            write_raster(
                p_real, transform, crs, site_dir / f"change_probability_{year_a}_{year_b}.tif", dtype="float32"
            )

            # Per-segment mean change_probability along each of the pair's
            # two shorelines -- a vector summary of the same raster, one
            # PROB_CHANGE attribute per `prob_change_segment_length`-long
            # piece of line rather than a continuous pixel surface.
            #
            # MAGNITUDE (negative = erosion, positive = accretion) is looked
            # up per segment from the *general* transects' TO_<year> values
            # (transects_qgis.nearest_transect_net_distance), not derived
            # from `delta`/`p_real` above -- signed_distance_raster's sign is
            # location-dependent (it flips depending on which of the two
            # shorelines a point sits near) and isn't a reliable stand-in
            # for which way the coast actually moved, whereas TO_<year>
            # carries the same fixed, transect-global sign already used for
            # EPR_NET_DISTANCE/EPR_RATE.
            general_wide_table = results.get("transects")
            if general_wide_table is not None:
                magnitudes_a = [
                    nearest_transect_net_distance(
                        seg.interpolate(0.5 * seg.length()), transects, general_wide_table, year_a, year_b,
                    )
                    for seg in segment_line(dissolved_by_year[year_a], run.prob_change_segment_length)
                ]
                magnitudes_b = [
                    nearest_transect_net_distance(
                        seg.interpolate(0.5 * seg.length()), transects, general_wide_table, year_a, year_b,
                    )
                    for seg in segment_line(dissolved_by_year[year_b], run.prob_change_segment_length)
                ]
            else:
                magnitudes_a = magnitudes_b = None

            seg_a = shoreline_change_probability_segments(
                dissolved_by_year[year_a], run.prob_change_segment_length, p_real, transform, width, height, crs=crs,
                magnitudes=magnitudes_a,
            )
            seg_b = shoreline_change_probability_segments(
                dissolved_by_year[year_b], run.prob_change_segment_length, p_real, transform, width, height, crs=crs,
                magnitudes=magnitudes_b,
            )
            io_utils.write_vector(seg_a, site_dir / f"change_probability_segments_{year_a}_vs_{year_b}.shp")
            io_utils.write_vector(seg_b, site_dir / f"change_probability_segments_{year_b}_vs_{year_a}.shp")
            results.setdefault("prob_change_segments", {})[(year_a, year_b)] = {
                year_a: seg_a, year_b: seg_b,
            }

        if "transects" in results:
            prob_table = change_probability_table(results["transects"], sigma_by_year)
            io_utils.write_table_csv(prob_table, site_dir / "transect_change_probability.csv")
            results["prob_change"] = prob_table

    return results


def run_pipeline(run: RunConfig, *, progress: bool = True) -> dict:
    """Top-level entry point: create `run.output_dir` if needed, then call
    `run_site` once per configured site, collecting each site's in-memory
    results dict into one outer dict keyed by site name.
    """
    output_dir = Path(run.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_results = {}
    for site in tqdm(run.sites, desc="Processing sites", disable=not progress, leave=True):
        all_results[site.name] = run_site(site, run, output_dir, progress=progress)
    return all_results
