"""Generate illustrative PNG screenshots of pipeline outputs for the repo /
README, for all three example configs: the synthetic example_site (with
professionals), the real Allegan, MI data (without professionals), and the
prob_change probabilistic-surfaces variant of the Allegan data. Run after
all three example configs have been executed:

    python examples/generate_synthetic_data.py
    python -m shoreline_uncertainty.cli run --config examples/config_with_professionals.yaml
    python -m shoreline_uncertainty.cli run --config examples/config_without_professionals.yaml
    python -m shoreline_uncertainty.cli run --config examples/config_prob_change.yaml
    python examples/make_screenshots.py

All map-view figures use one consistent, minimalist "clean map" style: a
full-bleed open aerial-imagery basemap (fetched via contextily) under the
plotted vectors/rasters, with every bit of matplotlib chrome -- axes, ticks,
titles, legends, colorbars -- switched off, and a single bold white, halo'd,
vertically-set label in the corner standing in for a title. This mirrors a
reference figure the project owner shared and replaces the earlier style
(plain axes, titles, external colorbars/legends), which produced cluttered,
oddly-proportioned figures for some outputs (e.g. a wide colorbar dwarfing a
thin map, or scientific-notation tick labels overlapping the axis labels).

This requires three extra packages not needed elsewhere in the project, plus
outbound network access to the tile server at runtime:

    pip install matplotlib contextily pillow

If tiles can't be fetched (offline, or in a network-restricted sandbox/CI),
each figure still renders -- just without the imagery layer underneath -- and
a warning is printed; nothing here ever calls arcpy or any other proprietary
library.

In addition to the per-output screenshots, this script also builds a single
6-panel "filmstrip" composite (allegan_filmstrip.png) that walks through the
Allegan, MI analysis end to end -- 1938 shoreline, 2010 shoreline, similarity
index, critical change areas, probability-of-change line segments, and
probability-of-change polygons -- stacked vertically with thin white gaps,
directly modeled on the reference figure.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.colors as mcolors
import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import rasterio.plot
from PIL import Image
from shapely.ops import unary_union

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

# Esri World Imagery: free, no API key required, true aerial/satellite
# photography (as opposed to a cartographic/vector-styled basemap like
# standard OpenStreetMap) -- the most useful "open imagery" base layer for
# illustrating shoreline-change results over the real landscape. Swap this
# for e.g. contextily.providers.OpenStreetMap.Mapnik to use a cartographic
# basemap instead.
OPEN_IMAGERY_SOURCE = cx.providers.Esri.WorldImagery

# Allegan shoreline data is published in NAD83 / Hotine Oblique Mercator
# (1938) or already in the site's own target CRS (2010); every map-view
# figure below plots in this CRS so geometries from different years/files
# line up correctly without each caller having to reproject by hand.
ALLEGAN_CRS = "EPSG:26989"

# ---------------------------------------------------------------------------
# Clean, full-bleed map style
# ---------------------------------------------------------------------------
# Color palette loosely echoes the reference figure: a warm red (+ dark
# red/maroon glow) for the earlier shoreline, a cool purple/lavender (+ dark
# purple glow) for the later one, a pink -> maroon/purple gradient for the
# similarity index, bright red for flagged "critical" change, and a
# turbo/rainbow ramp for the two probability-of-change layers.
COLOR_EARLY = "#ff5c72"
COLOR_EARLY_HALO = "#4a0e16"
COLOR_LATE = "#c9a6ff"
COLOR_LATE_HALO = "#2a1052"
COLOR_CRITICAL = "#ff1f3d"
COLOR_TRANSECT = "#f4f4f4"

SIMILARITY_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "similarity_pink_maroon", ["#ffd1dc", "#ff6f91", "#9c2447", "#3d0e1f"]
)
PROB_CMAP = "turbo"


def _clean_fig(figsize: tuple) -> tuple:
    """A figure + axes with zero margins and every bit of matplotlib chrome
    (ticks, spines, labels) switched off, so the saved PNG is exactly the
    plotted map -- nothing else."""
    fig = plt.figure(figsize=figsize)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    return fig, ax


def _add_label(ax, text: str, *, loc: str = "left", fontsize: float = 14) -> None:
    """A single bold, white, halo'd, vertically-set label in one corner --
    the only text that appears on a clean map figure, standing in for a
    title/legend."""
    x = 0.05 if loc == "left" else 0.95
    ax.text(
        x, 0.5, text, transform=ax.transAxes, rotation=90, va="center", ha="center",
        color="white", fontsize=fontsize, fontweight="bold", family="sans-serif",
        path_effects=[patheffects.withStroke(linewidth=3, foreground="black")],
        zorder=50,
    )


def _save_clean(fig, ax, out_path: Path, *, extent=None, dpi: int = 200) -> None:
    if extent is not None:
        ax.set_xlim(extent[0], extent[2])
        ax.set_ylim(extent[1], extent[3])
    ax.set_aspect("equal")
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


def _add_basemap(ax, crs, source=None, alpha: float = 1.0, zorder: float = -10) -> None:
    """Add an open aerial-imagery basemap layer beneath whatever has already
    been plotted on *ax*. *crs* is the CRS the plotted data is in (e.g. a
    GeoDataFrame's `.crs` or a rasterio dataset's `.crs`) -- contextily
    reprojects the fetched tiles to match it on the fly, so callers never
    need to reproject their own geometries/rasters to Web Mercator just to
    add a basemap. Network failures (no connectivity, a blocked proxy, etc.)
    are caught and downgraded to a warning so screenshot generation still
    succeeds, just without the imagery layer for that figure.

    *zorder* defaults well below matplotlib's default (0-2 for images/
    lines/patches) and is passed through explicitly so the basemap always
    renders beneath the data layer regardless of call order."""
    try:
        cx.add_basemap(
            ax, crs=crs, source=source or OPEN_IMAGERY_SOURCE, attribution_size=0, alpha=alpha, zorder=zorder
        )
    except Exception as exc:  # noqa: BLE001 - any failure here is non-fatal
        warnings.warn(
            f"Could not fetch open-imagery basemap tiles ({exc}); continuing without a basemap layer.",
            stacklevel=2,
        )


def _to_crs(gdf: gpd.GeoDataFrame, crs) -> gpd.GeoDataFrame:
    return gdf.to_crs(crs) if gdf.crs is not None and gdf.crs != crs else gdf


def _plot_glow_line(ax, line, color: str, halo_color: str, *, lw: float = 2.2) -> None:
    """A synthetic 'glow' around a line: several wider, more transparent
    copies of the same line underneath a crisp one on top. Used as a
    fallback when no probability-density raster is available to drive a
    data-driven glow (see `_plot_density_glow`)."""
    for glow_lw, alpha in [(11, 0.12), (7, 0.22), (4, 0.35)]:
        ax.plot(*line.xy, color=halo_color, lw=glow_lw, alpha=alpha, solid_capstyle="round", zorder=5)
    ax.plot(*line.xy, color=color, lw=lw, solid_capstyle="round", zorder=6)


def _plot_density_glow(ax, tif_path: Path, color: str, *, max_alpha: float = 0.6) -> None:
    """Render a position-probability-density raster as a soft colored glow
    (fading from transparent to *color*) rather than a literal heatmap --
    this is the positional-uncertainty 'halo' around each shoreline in the
    reference figure, and is more faithful to what's actually being shown
    (a probability surface) than a generic glow effect would be."""
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True).astype(float).filled(0.0)
        extent = rasterio.plot.plotting_extent(src)
    positive = data[data > 0]
    vmax = float(np.percentile(positive, 99)) if positive.size else 1.0
    norm = np.clip(data / (vmax or 1.0), 0.0, 1.0)
    rgb = np.array(mcolors.to_rgb(color))
    rgba = np.zeros((*norm.shape, 4))
    rgba[..., 0:3] = rgb
    rgba[..., 3] = norm * max_alpha
    ax.imshow(rgba, extent=extent, zorder=4)


def _shoreline_line(path: Path, crs=None) -> tuple:
    gdf = gpd.read_file(path)
    if crs is not None:
        gdf = _to_crs(gdf, crs)
    return unary_union(gdf.geometry), gdf.crs


# ---------------------------------------------------------------------------
# Per-output screenshots (same clean style as the composite filmstrip below)
# ---------------------------------------------------------------------------

def fig_shorelines_with_buffers(shoreline_paths: dict, radii: dict, out_name: str, label: str) -> None:
    """shoreline_paths: {label: shapefile Path}; radii: {label: buffer radius}."""
    colors = [COLOR_EARLY, COLOR_LATE, "#7fd9c4", "#ffd166"]
    halos = [COLOR_EARLY_HALO, COLOR_LATE_HALO, "#0f3d33", "#5c3d00"]
    fig, ax = _clean_fig((4, 9))
    crs = None
    for (yr_label, path), color, halo in zip(shoreline_paths.items(), colors, halos):
        gdf = gpd.read_file(path)
        crs = gdf.crs
        line = unary_union(gdf.geometry)
        _plot_glow_line(ax, line, color, halo)
        buf = line.buffer(radii[yr_label])
        gpd.GeoSeries([buf], crs=gdf.crs).plot(ax=ax, color=color, alpha=0.18, zorder=3)
    _add_basemap(ax, crs=crs)
    _add_label(ax, label)
    _save_clean(fig, ax, SHOTS / out_name)


def fig_transects(shoreline_paths: dict, transects_path: Path, out_name: str, label: str) -> None:
    """All shoreline years (lines only, no buffers) plus the shore-normal
    transect grid that intersects them, over an open-imagery basemap."""
    colors = [COLOR_EARLY, COLOR_LATE, "#7fd9c4", "#ffd166"]
    halos = [COLOR_EARLY_HALO, COLOR_LATE_HALO, "#0f3d33", "#5c3d00"]
    fig, ax = _clean_fig((4, 9))
    crs = None
    for (yr_label, path), color, halo in zip(shoreline_paths.items(), colors, halos):
        gdf = gpd.read_file(path)
        crs = gdf.crs
        _plot_glow_line(ax, unary_union(gdf.geometry), color, halo, lw=1.8)
    transects = gpd.read_file(transects_path)
    transects.plot(ax=ax, color=COLOR_TRANSECT, lw=0.5, alpha=0.5, zorder=2)
    _add_basemap(ax, crs=crs or transects.crs)
    _add_label(ax, label)
    _save_clean(fig, ax, SHOTS / out_name)


def fig_raster(tif_path: Path, out_name: str, label: str, cmap, *, zero_as_nodata: bool = False) -> None:
    """A single-band GeoTIFF (similarity index, significant change, etc.),
    semi-transparent over an open-imagery basemap so nodata/background
    pixels show the real landscape instead of an opaque empty raster.

    *zero_as_nodata*: some rasters (similarity_index.tif in particular)
    don't set a `nodata` tag, but a value of exactly 0 still really means
    "no signal here" (e.g. zero overlapping uncertainty bands) rather than
    a meaningful low-end data value -- pass True to treat those pixels as
    transparent too, instead of painting the whole grid's empty background
    in the colormap's lowest color."""
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True).astype(float).filled(np.nan)
        crs = src.crs
        extent = rasterio.plot.plotting_extent(src)
    if zero_as_nodata:
        data = np.where(data == 0, np.nan, data)
    cmap_obj = (plt.get_cmap(cmap) if isinstance(cmap, str) else cmap).copy()
    cmap_obj.set_bad(alpha=0)
    fig, ax = _clean_fig((4, 9))
    ax.imshow(data, cmap=cmap_obj, extent=extent, alpha=0.8, zorder=3)
    _add_basemap(ax, crs=crs)
    _add_label(ax, label)
    _save_clean(fig, ax, SHOTS / out_name)


def fig_raster_tall(tif_path: Path, out_name: str, label: str, cmap, *, zero_as_nodata: bool = False) -> None:
    """Alias of fig_raster -- both now use the same tall, full-bleed clean
    style, so a separate "tall" variant is no longer needed, but is kept as
    a thin wrapper so existing call sites don't need to change."""
    fig_raster(tif_path, out_name, label, cmap, zero_as_nodata=zero_as_nodata)


def make_synthetic_screenshots() -> None:
    """Generate all screenshots for the synthetic example_site
    (config_with_professionals.yaml): shorelines+buffers, transects, and the
    similarity-index/significant-change rasters."""
    data = HERE / "data" / "example_site"
    out = HERE / "output_with_professionals" / "example_site"
    years = [2000, 2010, 2020]
    radii = {2000: 2.0, 2010: 2.0, 2020: 12.0}  # matches config_with_professionals.yaml overrides
    shoreline_paths = {year: data / f"shoreline_{year}.shp" for year in years}

    fig_shorelines_with_buffers(
        shoreline_paths, radii, "shorelines_with_buffers.png",
        "Synthetic Shorelines (with Uncertainty Buffers)",
    )
    fig_transects(
        shoreline_paths, out / "transects.shp", "transects.png",
        "Shore-Normal Transects (Synthetic)",
    )
    fig_raster(out / "similarity_index.tif", "similarity_index.png", "Similarity Index", SIMILARITY_CMAP, zero_as_nodata=True)
    fig_raster(out / "significant_change.tif", "significant_change.png", "Significant Change", "RdYlGn_r")


def make_allegan_screenshots() -> None:
    """Generate all screenshots for the real Allegan, MI data
    (config_without_professionals.yaml): shorelines+buffers, transects, and
    the similarity-index/significant-change rasters."""
    data = HERE / "data" / "allegan"
    out = HERE / "output_without_professionals" / "allegan"
    radii = {1938: 13.2795, 2010: 10.3848}  # the shapefiles' own UNCERTAINT values
    shoreline_paths = {
        1938: data / "allegan_shoreline_1938.shp",
        2010: data / "allegan_shoreline_2010.shp",
    }

    fig_shorelines_with_buffers(
        shoreline_paths, radii, "allegan_shorelines_with_buffers.png",
        "1938 & 2010 Shorelines (with Uncertainty Buffers)",
    )
    fig_transects(
        shoreline_paths, out / "transects.shp", "allegan_transects.png",
        "Shore-Normal Transects (1938 vs. 2010)",
    )
    fig_raster(out / "similarity_index.tif", "allegan_similarity_index.png", "Similarity Index", SIMILARITY_CMAP, zero_as_nodata=True)
    fig_raster(out / "significant_change.tif", "allegan_significant_change.png", "Significant Change", "RdYlGn_r")


def make_prob_change_screenshots() -> None:
    """Generate the four prob_change raster screenshots (position confidence
    for each year, position delta, and change probability) for the Allegan
    1938/2010 pair (config_prob_change.yaml)."""
    out = HERE / "output_prob_change" / "allegan"

    fig_raster_tall(out / "position_confidence_1938.tif", "allegan_position_confidence_1938.png",
                     "Position Confidence, 1938", "viridis")
    fig_raster_tall(out / "position_confidence_2010.tif", "allegan_position_confidence_2010.png",
                     "Position Confidence, 2010", "viridis")
    fig_raster_tall(out / "position_delta_1938_2010.tif", "allegan_position_delta_1938_2010.png",
                     "Position Delta, 1938 -> 2010", "RdBu")
    fig_raster_tall(out / "change_probability_1938_2010.tif", "allegan_change_probability_1938_2010.png",
                     "P(Real Change), 1938 -> 2010", PROB_CMAP)


def _fig_segment_layer(gdf: gpd.GeoDataFrame, column: str, cmap, vmin: float, vmax: float, label: str, out_name: str) -> None:
    """Single full-bleed figure for one change-probability-segments
    GeoDataFrame, colored by *column* (PROB_CHANG or MAGNITUDE), over the
    open-imagery basemap. Shared by fig_prob_change_segments and
    fig_change_probability_segments_magnitude so each shoreline year gets
    its own figure instead of being squeezed into a side-by-side subplot."""
    fig, ax = _clean_fig((4, 9))
    gdf.plot(column=column, ax=ax, cmap=cmap, vmin=vmin, vmax=vmax, lw=4, legend=False, zorder=4)
    _add_basemap(ax, crs=gdf.crs)
    _add_label(ax, label)
    _save_clean(fig, ax, SHOTS / out_name)


def fig_prob_change_segments(out: Path) -> None:
    """Each shoreline in the 1938/2010 pair, broken into
    prob_change_segment_length-long segments and colored by its
    PROB_CHANGE attribute -- a vector summary of change_probability_1938_2010.tif
    sampled along the lines themselves. One full figure per shoreline year."""
    specs = [
        ("change_probability_segments_1938_vs_2010.shp", "Probability of Change -- 1938 Segments", "allegan_change_probability_segments_1938.png"),
        ("change_probability_segments_2010_vs_1938.shp", "Probability of Change -- 2010 Segments", "allegan_change_probability_segments_2010.png"),
    ]
    for fname, label, out_name in specs:
        gdf = gpd.read_file(out / fname)
        _fig_segment_layer(gdf, "PROB_CHANG", PROB_CMAP, 0.0, 1.0, label, out_name)


def fig_change_probability_segments_magnitude(out: Path) -> None:
    """Companion to fig_prob_change_segments: the same two shorelines'
    segments, this time colored by the MAGNITUDE attribute (negative =
    erosion, positive = accretion) instead of PROB_CHANGE. One full figure
    per shoreline year, sharing a single symmetric color scale (computed
    across both years) so the two remain visually comparable even though
    they're separate files."""
    specs = [
        ("change_probability_segments_1938_vs_2010.shp", "Magnitude of Change -- 1938 Segments", "allegan_change_probability_segments_magnitude_1938.png"),
        ("change_probability_segments_2010_vs_1938.shp", "Magnitude of Change -- 2010 Segments", "allegan_change_probability_segments_magnitude_2010.png"),
    ]
    gdfs = [gpd.read_file(out / fname) for fname, _, _ in specs]
    vmax = max(abs(g["MAGNITUDE"]).max() for g in gdfs)
    for (fname, label, out_name), gdf in zip(specs, gdfs):
        _fig_segment_layer(gdf, "MAGNITUDE", "RdBu", -vmax, vmax, label, out_name)


def fig_rate_change_polygons(out: Path) -> None:
    """rate_change_polygons.shp for the 1938->2010 pair: one polygon per gap
    between two adjacent rate transects, colored by PROB_CHANG -- a
    polygon-area analogue of the per-transect probability-of-change line
    segments, useful for seeing which stretches of coast changed the most
    without reading individual transect values one at a time."""
    gdf = gpd.read_file(out / "rate_change_polygons.shp")
    pair = gdf[(gdf["YEAR_A"] == 1938) & (gdf["YEAR_B"] == 2010)]
    fig, ax = _clean_fig((4, 9))
    pair.plot(column="PROB_CHANG", ax=ax, cmap=PROB_CMAP, vmin=0.0, vmax=1.0, alpha=0.85, legend=False, zorder=4)
    _add_basemap(ax, crs=gdf.crs)
    _add_label(ax, "Probability of Change Polygons")
    _save_clean(fig, ax, SHOTS / "allegan_rate_change_polygons.png")


def fig_rate_of_change(out: Path) -> None:
    """EPR_RATE and LRR_RATE (m/yr) along the dense rate_transect_spacing
    transect grid, ordered by TRANSECT_ID -- with only 2 shoreline years
    (1938, 2010) at this site, LRR and EPR are mathematically identical
    (LRR_R2 == 1.0 everywhere), so the two lines should overlap exactly;
    this is itself a useful sanity-check visualization of that property.
    Unlike the map-view figures above, this is a real x/y chart, so it
    keeps normal matplotlib axes/labels rather than the clean map style."""
    df = pd.read_csv(out / "transect_rate_of_change.csv").sort_values("TRANSECT_ID")
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(df["TRANSECT_ID"], df["EPR_RATE"], color="tab:blue", lw=2, label="EPR_RATE (end point)")
    ax.plot(df["TRANSECT_ID"], df["LRR_RATE"], color="tab:orange", lw=1, ls="--", label="LRR_RATE (regression)")
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_title("Allegan, MI -- EPR / LRR shoreline change rate, 1938->2010")
    ax.set_xlabel("Transect ID (along baseline)")
    ax.set_ylabel("Rate of change (m/yr, + = accretion / - = erosion)")
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(SHOTS / "allegan_rate_of_change.png", dpi=150)
    plt.close(fig)


def make_rate_and_segments_screenshots() -> None:
    """Generate the change-probability-segments, magnitude-segments,
    rate-of-change, and rate-change-polygons screenshots for the Allegan
    1938/2010 pair (config_prob_change.yaml)."""
    out = HERE / "output_prob_change" / "allegan"
    fig_prob_change_segments(out)
    fig_change_probability_segments_magnitude(out)
    fig_rate_of_change(out)
    fig_rate_change_polygons(out)


# ---------------------------------------------------------------------------
# 6-panel "filmstrip" composite
# ---------------------------------------------------------------------------
# Walks through the Allegan, MI analysis end to end, one clean full-bleed
# panel per stage, all sharing the same cropped map extent so they read as a
# single continuous strip once stacked: 1938 shoreline, 2010 shoreline,
# similarity index, critical change areas (+ transects), probability of
# change (line segments), probability of change (polygons).

_FILMSTRIP_FIGSIZE = (4, 9)


def _filmstrip_extent() -> tuple:
    """A common, tightly-cropped map window (in ALLEGAN_CRS) shared by every
    filmstrip panel, so all six line up as one continuous strip of coast
    rather than six independently-framed maps. Centered on the middle of the
    dense rate-transect grid and sized to roughly the same tall, narrow
    aspect ratio as the reference figure."""
    transects = gpd.read_file(HERE / "output_without_professionals" / "allegan" / "transects.shp")
    xmin, ymin, xmax, ymax = transects.total_bounds
    cx_, cy_ = (xmin + xmax) / 2, (ymin + ymax) / 2
    half_w, half_h = 165.0, 460.0
    return (cx_ - half_w, cy_ - half_h, cx_ + half_w, cy_ + half_h)


def _filmstrip_panel_shoreline(year: int, shoreline_path: Path, density_tif: Path, color: str, halo_color: str,
                                label: str, extent: tuple, out_path: Path) -> None:
    fig, ax = _clean_fig(_FILMSTRIP_FIGSIZE)
    line, _ = _shoreline_line(shoreline_path, crs=ALLEGAN_CRS)
    if density_tif.exists():
        _plot_density_glow(ax, density_tif, halo_color)
    ax.plot(*line.xy, color=color, lw=2.2, solid_capstyle="round", zorder=6)
    _add_basemap(ax, crs=ALLEGAN_CRS)
    _add_label(ax, label)
    _save_clean(fig, ax, out_path, extent=extent)


def _filmstrip_panel_similarity(tif_path: Path, label: str, extent: tuple, out_path: Path) -> None:
    fig, ax = _clean_fig(_FILMSTRIP_FIGSIZE)
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True).astype(float).filled(np.nan)
        raster_extent = rasterio.plot.plotting_extent(src)
    # similarity_index.tif has no nodata tag, but 0 (zero overlapping
    # uncertainty bands) really means "no signal here" -- treat it as
    # transparent too, rather than painting the whole grid's empty
    # background in the colormap's lowest (pink) color.
    data = np.where(data == 0, np.nan, data)
    cmap_obj = SIMILARITY_CMAP.copy()
    cmap_obj.set_bad(alpha=0)
    ax.imshow(data, cmap=cmap_obj, extent=raster_extent, alpha=0.85, zorder=3)
    _add_basemap(ax, crs=ALLEGAN_CRS)
    _add_label(ax, label)
    _save_clean(fig, ax, out_path, extent=extent)


def _filmstrip_panel_critical_areas(transects_path: Path, critical_path: Path, label: str, extent: tuple, out_path: Path) -> None:
    fig, ax = _clean_fig(_FILMSTRIP_FIGSIZE)
    transects = gpd.read_file(transects_path)
    transects.plot(ax=ax, color=COLOR_TRANSECT, lw=0.45, alpha=0.5, zorder=2)
    critical = _to_crs(gpd.read_file(critical_path), transects.crs)
    if not critical.empty:
        critical.plot(ax=ax, color=COLOR_CRITICAL, lw=3.5, zorder=6)
    _add_basemap(ax, crs=transects.crs)
    _add_label(ax, label)
    _save_clean(fig, ax, out_path, extent=extent)


def _filmstrip_panel_segments(shp_path: Path, label: str, extent: tuple, out_path: Path) -> None:
    fig, ax = _clean_fig(_FILMSTRIP_FIGSIZE)
    gdf = gpd.read_file(shp_path)
    gdf.plot(column="PROB_CHANG", ax=ax, cmap=PROB_CMAP, vmin=0.0, vmax=1.0, lw=5, legend=False, zorder=4)
    _add_basemap(ax, crs=gdf.crs)
    _add_label(ax, label)
    _save_clean(fig, ax, out_path, extent=extent)


def _filmstrip_panel_polygons(shp_path: Path, label: str, extent: tuple, out_path: Path) -> None:
    fig, ax = _clean_fig(_FILMSTRIP_FIGSIZE)
    gdf = gpd.read_file(shp_path)
    pair = gdf[(gdf["YEAR_A"] == 1938) & (gdf["YEAR_B"] == 2010)]
    pair.plot(column="PROB_CHANG", ax=ax, cmap=PROB_CMAP, vmin=0.0, vmax=1.0, alpha=0.85, legend=False, zorder=4)
    _add_basemap(ax, crs=gdf.crs)
    _add_label(ax, label)
    _save_clean(fig, ax, out_path, extent=extent)


def _stitch_filmstrip(panel_paths: list, out_path: Path, gap_px: int = 6) -> None:
    """Stack pre-rendered panel PNGs vertically with a thin white gap
    between each, matching the reference figure's filmstrip layout. All
    panels share the same figsize/dpi, so widths already match; this just
    concatenates them rather than re-rendering anything."""
    imgs = [Image.open(p).convert("RGB") for p in panel_paths]
    width = imgs[0].width
    imgs = [im if im.width == width else im.resize((width, round(im.height * width / im.width))) for im in imgs]
    total_height = sum(im.height for im in imgs) + gap_px * (len(imgs) - 1)
    canvas = Image.new("RGB", (width, total_height), "white")
    y = 0
    for im in imgs:
        canvas.paste(im, (0, y))
        y += im.height + gap_px
    canvas.save(out_path)


def make_filmstrip() -> None:
    """Build the 6-panel Allegan, MI filmstrip composite, modeled on the
    reference figure: 1938 shoreline, 2010 shoreline, similarity index,
    critical change areas, probability-of-change line segments, and
    probability-of-change polygons -- all sharing one cropped map window so
    they read as a single continuous strip of coast."""
    extent = _filmstrip_extent()
    data = HERE / "data" / "allegan"
    odb_out = HERE / "output_without_professionals" / "allegan"
    prob_out = HERE / "output_prob_change" / "allegan"

    panels = [
        (
            "_filmstrip_1938.png",
            lambda p: _filmstrip_panel_shoreline(
                1938, data / "allegan_shoreline_1938.shp", prob_out / "position_probability_density_1938.tif",
                COLOR_EARLY, COLOR_EARLY_HALO, "1938 Shoreline (with Probability Distribution)", extent, p,
            ),
        ),
        (
            "_filmstrip_2010.png",
            lambda p: _filmstrip_panel_shoreline(
                2010, data / "allegan_shoreline_2010.shp", prob_out / "position_probability_density_2010.tif",
                COLOR_LATE, COLOR_LATE_HALO, "2010 Shoreline (with Probability Distribution)", extent, p,
            ),
        ),
        (
            "_filmstrip_similarity.png",
            lambda p: _filmstrip_panel_similarity(
                odb_out / "similarity_index.tif", "Similarity Index (from Overlapping Bands)", extent, p,
            ),
        ),
        (
            "_filmstrip_critical.png",
            lambda p: _filmstrip_panel_critical_areas(
                odb_out / "transects.shp", odb_out / "critical_areas.shp",
                "Critical Change Areas (& Transects)", extent, p,
            ),
        ),
        (
            "_filmstrip_segments.png",
            lambda p: _filmstrip_panel_segments(
                prob_out / "change_probability_segments_1938_vs_2010.shp",
                "Probability of Change (Line Segments)", extent, p,
            ),
        ),
        (
            "_filmstrip_polygons.png",
            lambda p: _filmstrip_panel_polygons(
                prob_out / "rate_change_polygons.shp", "Probability of Change (Polygons)", extent, p,
            ),
        ),
    ]

    panel_paths = []
    for fname, render in panels:
        path = SHOTS / fname
        render(path)
        panel_paths.append(path)

    _stitch_filmstrip(panel_paths, SHOTS / "allegan_filmstrip.png")
    for path in panel_paths:
        path.unlink()


def main():
    """Regenerate every screenshot in examples/screenshots/, for all three
    example configs, plus the composite filmstrip."""
    make_synthetic_screenshots()
    make_allegan_screenshots()
    make_prob_change_screenshots()
    make_rate_and_segments_screenshots()
    make_filmstrip()
    print(f"Wrote screenshots to {SHOTS}")


if __name__ == "__main__":
    main()
