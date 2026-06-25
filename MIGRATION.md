# Migration guide: original_program/arcgis_pro/ -> shoreline_uncertainty

This maps every script in `original_program/arcgis_pro/` (unchanged,
arcpy-dependent, kept for historical reference) to the module/function in the
new `shoreline_uncertainty` package that replaces it, plus what changed and
why. None of the original files were modified.

| Original script | New module / function | Notes |
|---|---|---|
| `add_field.py` | `uncertainty.py` -- `rmse_interpretation`, `rmse_overall`, `rmse95`, `compute_uncertainty_radius`, `resolve_uncertainty_radius`, `assign_uncertainty` | Same Eqs. 1-3 (RMSE_I, RMSE_O, RMSE95 = 1.7308 x RMSE_O). The original added an RMSE95 field directly to a feature class via arcpy `AddField`/`CalculateField`; here it's a pure function returning a `{year: radius}` dict, used as the buffer radius for `epsilon_bands.py`. A `rmse95_override` config option lets you skip the calculation entirely if you already have a value. |
| `create_fc.py` | `io_utils.py` -- `read_shoreline`, `write_vector` | The original pre-created empty ArcGIS polyline feature classes against a hardcoded Michigan State Plane `.prj` before they could be hand-populated. geopandas/Fiona create output files on demand when written, so no pre-creation step is needed; `write_vector` is a no-op for empty GeoDataFrames. |
| `intersecting_epsilon_bands.py`, `intersecting_epsilon_bands_2017_UPDATE.py` | `epsilon_bands.py` -- `overlapping_double_buffer`, `run_odb_for_site` | This is the core **published** method (Eq. 4): `Ps = Area(buffer_a ∩ buffer_b) / Area(buffer_a ∪ buffer_b)`. The two original scripts were near-duplicates (the `_2017_UPDATE` version is what the 2017 paper's analysis actually used); they're consolidated into one implementation. `significant_change = Ps < threshold`. Buffers and area/union/intersection math use shapely instead of `Buffer_analysis`/`Union_analysis`/`Intersect_analysis`. |
| `perkal_bands.py` | `epsilon_bands.py` -- `grow_buffer_to_threshold`, `run_perkal_for_site` | An **unpublished, legacy/alternative** algorithm, explicitly distinguished from the ODB method in code and docs: grows a buffer around a shoreline by fixed `step` increments until the buffer-intersected length of an adjacent shoreline reaches `confidence_level * adjacent.length`. The original's bidirectional loop (every ordered pair, `year != k`) is preserved exactly. |
| `Identify_Critical_Areas.py` | `critical_areas.py` -- `identify_critical_areas` | Reuses the same buffer-growth algorithm as `perkal_bands.py` but only tests `year < k` pairs (not `year != k`) and additionally exports the final intersected ("critical") shoreline segment per pair/confidence level. Both the asymmetric pair selection and the segment export are preserved. |
| `Cast_Transects.py` | `transects.py` -- `compute_baseline_direction`, `build_baseline`, `generate_transects` | Original used `CreateRoutes_lr` to lay out shore-normal transects at fixed spacing along a baseline. Baseline orientation here is PCA/SVD-derived if no baseline shapefile is given; transects are generated directly via shapely (perpendicular offset vectors), no linear-referencing route needed. |
| (transect orientation, via `CreateRoutes_lr`'s `coordinate_priority` arg) | `transects.py` -- `_corner_key`, `order_transect_start` | The original set `coordinate_priority` per site (e.g. `UPPER_LEFT` for alcona/sanilac, `UPPER_RIGHT` for allegan/manistee) to control which end of a transect is the linear-referencing start, which in turn controls the sign/direction of along-transect distance. `order_transect_start` reimplements this corner-priority logic directly on transect endpoints; it's now a per-site config field (`coordinate_priority`) rather than hardcoded. |
| `extract_intersected_points.py` | `transects.py` -- `intersect_transects_shorelines` | Original used `Intersect_analysis` between transects and shorelines, then read XY off the resulting points. Here it's `shapely` geometry intersection per transect/year, keeping the intersection point closest to the transect start when a transect crosses a shoreline more than once (mirroring `LocateFeaturesAlongRoutes_lr`'s default "FIRST" match). |
| `transect_analysis.py` | `transects.py` -- `intersect_transects_shorelines` (the `DISTANCE` column) | Original used `LocateFeaturesAlongRoutes_lr` to get linear-referenced ("MEAS") distance along each transect/route per year. Distance is computed directly here as `start_point.distance(intersection_point)`, using the same `coordinate_priority`-oriented start point so direction/sign stays consistent. |
| `merge_results.py` | `transects.py` -- `to_wide_table` | The original script was incomplete/broken -- it never finished pivoting per-year distances into one row per transect. `to_wide_table` implements that pivot from scratch: a long `TRANSECT_ID | YEAR | DISTANCE` table becomes one row per transect with a `TO_<year>` column per year. |
| `copy_output_table.py` | `io_utils.py` -- `write_table_csv`, `write_table_pipe_log` | Original copied in-memory arcpy tables out to standalone dbf/text tables. `write_table_csv` writes a standard CSV; `write_table_pipe_log` reproduces the original's pipe-delimited `.txt` log format for anyone relying on that exact layout. |
| `raster_buffers_analysis.py` | `raster_output.py` -- `build_similarity_surface`, `rasterize_geometry`, `write_raster` | Despite its name, the original performed **no raster cell math** -- it only unioned vector buffer polygons (`Union_analysis ... ONLY_FID`) and counted overlaps as a `Similarity_Index` attribute on the resulting *vector* polygons. This is replaced with genuine raster math via `rasterio.features.rasterize`: a `Similarity_Index` GeoTIFF (count of overlapping per-year-pair uncertainty buffers per cell) and a `Significant_Change` GeoTIFF (1 where a significant pair's footprint falls outside its own overlap region), in the spirit of the spatially-variable uncertainty concept in Wernette et al. (2020). |
| `professional_comparison.py` | `comparison.py` -- `compare_to_professionals`, `compare_professionals_pairwise`, `professional_summary` | Original used `FeatureVerticesToPoints_management` + `Near_analysis` + `Statistics_analysis` to get min/mean/max nearest-vertex distance between two shorelines, producing `_meTOprof`, `_profTOprof`, and a running `_professional_summary` table. Same three outputs are reproduced here, with the vertex-distance statistic computed via `geometry_utils.vertex_nearest_stats` (shapely). The hardcoded `professionals = ['acmoody','goodwin','lusch']` list is now a per-site `professionals` config list (any names, any count). |
| *(per-script copy-pasted)* `locations = ['alcona','allegan','manistee','sanilac']` + per-site year lists | `config.py` (`RunConfig`, `SiteConfig`, `ShorelineYear`, `ProfessionalDelineation`, `load_config`, `validate_config`) + `pipeline.py` (`run_site`, `run_pipeline`) | Every original script repeated its own copy of this hardcoded site/year list and a per-site processing block. Replaced with one YAML/JSON config and one generic, config-driven pipeline that works for any number of sites, years, and file paths -- adding a new site means editing the config, not the code. |
| *(none -- new)* | `cli.py` | A `shoreline-uncertainty run --config <path>` command-line entry point; the original toolbox only ran from within ArcGIS Pro's Python window/toolbox UI. |

## Key behavioral notes carried over deliberately

- **ODB vs. Perkal are kept distinct.** The published method (Eq. 4, ODB) and
  the unpublished legacy method (iterative buffer growth) are implemented
  side by side in `epsilon_bands.py` and documented as such everywhere they
  appear -- they are not merged or treated as equivalent.
- **Pair-selection asymmetry is preserved.** `perkal_bands.py`'s bidirectional
  `year != k` loop and `Identify_Critical_Areas.py`'s `year < k`-only loop
  were different in the original; `run_perkal_for_site` and
  `identify_critical_areas` keep that exact difference rather than
  "fixing" it to be consistent.
- **No arcpy, anywhere.** All vector I/O and geometry operations use
  geopandas/shapely/pyproj/pyogrio (wrapping GDAL/OGR); all raster output
  uses rasterio. `original_program/arcgis_pro/` is left untouched as a
  reference and is not imported by anything in `shoreline_uncertainty`.

## What's new (not a 1:1 port)

- `raster_output.py` does real per-cell raster math, which the original
  never did despite its filename.
- `transects.to_wide_table` finishes a pivot `merge_results.py` never
  completed.
- Everything is config-driven (`config.py`) instead of hardcoded per-site
  blocks copy-pasted across scripts.
- A single CLI entry point (`cli.py`) runs the whole pipeline for all
  configured sites in one command.
- `probability_surface.py` and `rate_of_change.py` have no arcpy-toolbox
  equivalent at all -- they're additions, not ports, built on the horizontal
  shoreline-position analogue of Wernette et al. (2020)'s change-probability
  math:
  - `shoreline_change_probability_segments`'s output shapefiles carry a
    `MAGNITUDE` attribute (negative = erosion, positive = accretion) per
    line segment, sourced from `transects.nearest_transect_net_distance`
    (`TO_<b> - TO_<a>` at the nearest general-purpose transect) rather than
    from the change-probability raster's own signed distance, whose sign is
    a location-dependent baseline-side indicator and not a reliable
    erosion/accretion sign on its own.
  - `rate_of_change.build_rate_change_polygons` produces
    `rate_change_polygons.shp`: one polygon per gap between two
    sequentially-adjacent rate transects, per shoreline year pair, carrying
    the averaged magnitude/direction of change (`MAGNITUDE`, `RATE`) and the
    Gaussian-overlap probability that the change is "real" (`PROB_CHANGE`,
    truncated to `PROB_CHANG` in the shapefile).
- `water_level.py` (and the `water-levels` CLI subcommand) also has no
  arcpy-toolbox equivalent: an automatic NOAA CO-OPS water-level lookup
  (Great Lakes + marine) per shoreline year, either annual or date-specific
  via the new `acquisition_date` config field. It's the one part of this
  package that makes live network calls -- deliberately kept as a separate,
  opt-in subcommand rather than wired into `run_pipeline`, so the rest of
  the pipeline (and its tests) stay offline/deterministic, and is *not*
  auto-combined with `uncertainty.py`'s RMSE_O. See the README's [Water-level
  lookup](README.md#water-level-lookup-water-levels-subcommand) section.
