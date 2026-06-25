"""End-to-end orchestration: load a config, run every analysis stage for
every site, and write all outputs.

Replaces the per-site copy-pasted ALCONA/ALLEGAN/MANISTEE/SANILAC blocks
found in nearly every original_program/arcgis_pro/*.py script with one
generic, config-driven pipeline that works for any number of sites.
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union
from tqdm import tqdm

from . import io_utils
from .comparison import compare_professionals_pairwise, compare_to_professionals, professional_summary
from .config import RunConfig, SiteConfig
from .critical_areas import identify_critical_areas
from .epsilon_bands import overlapping_double_buffer, run_odb_for_site, run_perkal_for_site
from .probability_surface import (
    change_probability_raster,
    change_probability_table,
    position_probability_surfaces,
    rmse95_to_sigma,
    segment_line,
    shoreline_change_probability_segments,
)
from .raster_output import build_grid_transform, build_similarity_surface, write_raster
from .rate_of_change import build_rate_change_polygons, compute_rate_of_change
from .transects import (
    baseline_center_direction,
    build_baseline,
    compute_baseline_direction,
    generate_transects,
    intersect_transects_shorelines,
    nearest_transect_net_distance,
    to_wide_table,
    transects_to_gdf,
)
from .uncertainty import assign_uncertainty

log = logging.getLogger(__name__)


def _load_site_shorelines(site: SiteConfig, target_crs, *, progress: bool = True):
    """Read every shoreline year for a site, reproject, and dissolve each to
    a single geometry for buffer/area/length math.

    Returns (gdf_by_year, dissolved_geom_by_year, crs).
    """
    gdf_by_year = {}
    crs = None
    for sy in tqdm(site.shorelines, desc=f"{site.name}: loading shorelines", disable=not progress, leave=False):
        gdf = io_utils.read_shoreline(sy.path)
        gdf = io_utils.ensure_projected(gdf, target_crs)
        gdf_by_year[sy.year] = gdf
        crs = gdf.crs
    dissolved = {year: unary_union(gdf.geometry) for year, gdf in gdf_by_year.items()}
    return gdf_by_year, dissolved, crs


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

    gdf_by_year, dissolved_by_year, crs = _load_site_shorelines(site, run.target_crs, progress=progress)
    radii_by_year = assign_uncertainty(site)
    # Hoisted out of the compute_prob_change-only block below: also needed,
    # unconditionally, by the rate_of_change polygon-probability stage and
    # by the change_probability_segments MAGNITUDE lookup, neither of which
    # require compute_prob_change to be set.
    sigma_by_year = {year: rmse95_to_sigma(radii_by_year[year]) for year in radii_by_year}

    # --- Baseline (shared by transects and the probabilistic surfaces) ---
    if site.baseline:
        baseline_gdf = io_utils.ensure_projected(io_utils.read_shoreline(site.baseline), run.target_crs)
        baseline = unary_union(baseline_gdf.geometry)
    else:
        any_year_gdf = next(iter(gdf_by_year.values()))
        center, direction = compute_baseline_direction(any_year_gdf)
        total_len = max(g.length for g in dissolved_by_year.values()) * 1.5
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
            overlap_rows = [{
                "YEAR_A": r.year_a, "YEAR_B": r.year_b,
                "PROP_AB_OVERLAP": r.prop_ab_overlap, "geometry": r.intersection,
            } for r in odb_objects if not r.intersection.is_empty]
            if overlap_rows:
                overlap_gdf = gpd.GeoDataFrame(overlap_rows, geometry="geometry", crs=crs)
                io_utils.write_vector(overlap_gdf, site_dir / "odb_overlap_geometries.shp")

    if run.epsilon_band_method in ("perkal", "both"):
        perkal_df = run_perkal_for_site(site.name, dissolved_by_year, run.confidence_levels, progress=progress)
        io_utils.write_table_csv(perkal_df, site_dir / "perkal_shoreline_buffer_table.csv")
        results["perkal"] = perkal_df

        critical_summary, critical_gdf = identify_critical_areas(
            site.name, dissolved_by_year, run.confidence_levels, crs=crs, export_table=True, progress=progress,
        )
        io_utils.write_table_csv(critical_summary, site_dir / "critical_areas_summary.csv")
        io_utils.write_vector(critical_gdf, site_dir / "critical_areas.shp")
        results["critical_areas"] = critical_summary

    # --- Transects (direction/magnitude of change) ---
    transects = generate_transects(
        baseline, site.transect_spacing, site.transect_length, site.coordinate_priority, progress=progress
    )
    io_utils.write_vector(transects_to_gdf(transects, crs), site_dir / "transects.shp")

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
        io_utils.write_vector(transects_to_gdf(rate_transects, crs), site_dir / "rate_transects.shp")

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
            # being "real" (see rate_of_change.build_rate_change_polygons).
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
            gdf = io_utils.ensure_projected(io_utils.read_shoreline(prof.path), run.target_crs)
            prof_by_year.setdefault(prof.year, {})[prof.name] = unary_union(gdf.geometry)

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
    # DEM change-probability approach -- see probability_surface.py.
    if run.compute_prob_change or run.epsilon_band_method == "prob_change":
        # Pad the raster grid a few sigma beyond the shorelines themselves
        # so each Gaussian's meaningful extent is fully captured.
        pad = 3.0 * max(sigma_by_year.values())
        grid_bounds = unary_union(
            [geom.buffer(pad) for geom in dissolved_by_year.values()]
        ).bounds
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
            # (transects.nearest_transect_net_distance), not derived from
            # `delta`/`p_real` above -- signed_distance_raster's sign is
            # location-dependent (it flips depending on which of the two
            # shorelines a point sits near) and isn't a reliable stand-in
            # for which way the coast actually moved, whereas TO_<year>
            # carries the same fixed, transect-global sign already used for
            # EPR_NET_DISTANCE/EPR_RATE.
            general_wide_table = results.get("transects")
            if general_wide_table is not None:
                magnitudes_a = [
                    nearest_transect_net_distance(
                        seg.interpolate(0.5, normalized=True), transects, general_wide_table, year_a, year_b,
                    )
                    for seg in segment_line(dissolved_by_year[year_a], run.prob_change_segment_length)
                ]
                magnitudes_b = [
                    nearest_transect_net_distance(
                        seg.interpolate(0.5, normalized=True), transects, general_wide_table, year_a, year_b,
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
    results dict into one outer dict keyed by site name. This is what
    `cli.py` and `load_config(...)`-based scripts call after building/
    validating a RunConfig.
    """
    output_dir = Path(run.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_results = {}
    for site in tqdm(run.sites, desc="Processing sites", disable=not progress, leave=True):
        all_results[site.name] = run_site(site, run, output_dir, progress=progress)
    return all_results
