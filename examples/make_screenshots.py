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

All of the spatial (map-view) figures are drawn over an open aerial-imagery
basemap fetched via contextily, so the screenshots show real-world context
(coastline, dune vegetation, structures, etc.) under the plotted vectors and
rasters rather than a bare set of axes. This requires two extra packages not
needed elsewhere in the project, plus outbound network access to the tile
server at runtime:

    pip install matplotlib contextily

If tiles can't be fetched (offline, or in a network-restricted sandbox/CI),
each figure still renders -- just without the imagery layer underneath -- and
a warning is printed; nothing here ever calls arcpy or any other proprietary
library.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import rasterio.plot
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
    renders beneath the data layer regardless of call order. Without this,
    two same-type artists added at the same default zorder (e.g. our own
    raster's `imshow` and contextily's basemap `imshow`) tie-break by add
    order -- so calling this *after* plotting a raster would otherwise
    paint the (opaque) basemap image right on top of it, hiding it
    entirely, even though that's never an issue for line/polygon layers
    (which already default to a higher zorder than any image)."""
    try:
        cx.add_basemap(
            ax, crs=crs, source=source or OPEN_IMAGERY_SOURCE, attribution_size=6, alpha=alpha, zorder=zorder
        )
    except Exception as exc:  # noqa: BLE001 - any failure here is non-fatal
        warnings.warn(
            f"Could not fetch open-imagery basemap tiles ({exc}); continuing without a basemap layer.",
            stacklevel=2,
        )


def fig_shorelines_with_buffers(
    shoreline_paths: dict, radii: dict, out_name: str, title: str
) -> None:
    """shoreline_paths: {label: shapefile Path}; radii: {label: buffer radius}."""
    colors = plt.cm.tab10.colors
    fig, ax = plt.subplots(figsize=(9, 4))
    crs = None
    for (label, path), color in zip(shoreline_paths.items(), colors):
        gdf = gpd.read_file(path)
        crs = gdf.crs
        line = unary_union(gdf.geometry)
        ax.plot(*line.xy, color=color, lw=1.8, label=f"{label} shoreline")
        buf = line.buffer(radii[label])
        gpd.GeoSeries([buf], crs=gdf.crs).plot(ax=ax, color=color, alpha=0.15)
    _add_basemap(ax, crs=crs)
    ax.set_title(title)
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(SHOTS / out_name, dpi=150)
    plt.close(fig)


def fig_transects(
    shoreline_paths: dict, transects_path: Path, out_name: str, title: str
) -> None:
    """All shoreline years (lines only, no buffers) plus the shore-normal
    transect grid that intersects them, over an open-imagery basemap."""
    colors = plt.cm.tab10.colors
    fig, ax = plt.subplots(figsize=(9, 4))
    crs = None
    for (label, path), color in zip(shoreline_paths.items(), colors):
        gdf = gpd.read_file(path)
        crs = gdf.crs
        ax.plot(*unary_union(gdf.geometry).xy, color=color, lw=1.5, label=f"{label} shoreline")
    transects = gpd.read_file(transects_path)
    transects.plot(ax=ax, color="gray", lw=0.6, alpha=0.7)
    _add_basemap(ax, crs=crs or transects.crs)
    ax.set_title(title)
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(SHOTS / out_name, dpi=150)
    plt.close(fig)


def fig_raster(tif_path: Path, out_name: str, title: str, cmap: str) -> None:
    """A single-band GeoTIFF (similarity index, significant change, etc.),
    semi-transparent over an open-imagery basemap so nodata/background
    pixels show the real landscape instead of an opaque empty raster."""
    with rasterio.open(tif_path) as src:
        # Mask nodata to NaN and make NaN pixels fully transparent (rather
        # than opaque) so the open-imagery basemap shows through everywhere
        # outside the analysis area, instead of being fully covered by the
        # raster's own background color.
        data = src.read(1, masked=True).astype(float).filled(np.nan)
        crs = src.crs
        extent = rasterio.plot.plotting_extent(src)
        cmap_obj = plt.get_cmap(cmap).copy()
        cmap_obj.set_bad(alpha=0)
        fig, ax = plt.subplots(figsize=(9, 3))
        im = ax.imshow(data, cmap=cmap_obj, extent=extent, alpha=0.75)
        _add_basemap(ax, crs=crs)
        fig.colorbar(im, ax=ax, shrink=0.7, label=title)
        ax.set_title(f"{title} ({tif_path.name})")
        ax.set_xlabel("Easting (m)")
        ax.set_ylabel("Northing (m)")
        fig.tight_layout()
        fig.savefig(SHOTS / out_name, dpi=150)
        plt.close(fig)


def fig_raster_tall(tif_path: Path, out_name: str, title: str, cmap: str) -> None:
    """Same as fig_raster, but sized for the prob_change surfaces, whose
    grid is padded a few sigma beyond a long, narrow shoreline (so the
    raster is much taller than it is wide) -- a 9x3 landscape figure would
    squash that shape almost flat."""
    with rasterio.open(tif_path) as src:
        data = src.read(1, masked=True).astype(float).filled(np.nan)
        crs = src.crs
        extent = rasterio.plot.plotting_extent(src)
        cmap_obj = plt.get_cmap(cmap).copy()
        cmap_obj.set_bad(alpha=0)
        fig, ax = plt.subplots(figsize=(4, 9))
        im = ax.imshow(data, cmap=cmap_obj, extent=extent, alpha=0.75)
        _add_basemap(ax, crs=crs)
        fig.colorbar(im, ax=ax, shrink=0.6, label=title)
        ax.set_title(f"{title}\n({tif_path.name})", fontsize=9)
        ax.set_xlabel("Easting (m)")
        ax.set_ylabel("Northing (m)")
        ax.set_aspect("equal")
        fig.tight_layout()
        fig.savefig(SHOTS / out_name, dpi=150)
        plt.close(fig)


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
        shoreline_paths,
        radii,
        "shorelines_with_buffers.png",
        "Synthetic shorelines with RMSE95 positional-uncertainty buffers",
    )
    fig_transects(
        shoreline_paths,
        out / "transects.shp",
        "transects.png",
        "Shore-normal transects across all shoreline years",
    )
    fig_raster(
        out / "similarity_index.tif",
        "similarity_index.png",
        "Similarity Index (buffer overlap count)",
        "viridis",
    )
    fig_raster(
        out / "significant_change.tif",
        "significant_change.png",
        "Significant Change (1 = real change)",
        "RdYlGn_r",
    )


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
        shoreline_paths,
        radii,
        "allegan_shorelines_with_buffers.png",
        "Allegan, MI shorelines (1938, 2010) with RMSE95 positional-uncertainty buffers",
    )
    fig_transects(
        shoreline_paths,
        out / "transects.shp",
        "allegan_transects.png",
        "Shore-normal transects, Allegan, MI (1938 vs. 2010)",
    )
    fig_raster(
        out / "similarity_index.tif",
        "allegan_similarity_index.png",
        "Similarity Index (buffer overlap count)",
        "viridis",
    )
    fig_raster(
        out / "significant_change.tif",
        "allegan_significant_change.png",
        "Significant Change (1 = real change)",
        "RdYlGn_r",
    )


def make_prob_change_screenshots() -> None:
    """Generate the four prob_change raster screenshots (position confidence
    for each year, position delta, and change probability) for the Allegan
    1938/2010 pair (config_prob_change.yaml)."""
    out = HERE / "output_prob_change" / "allegan"

    fig_raster_tall(
        out / "position_confidence_1938.tif",
        "allegan_position_confidence_1938.png",
        "Position confidence, 1938 (1 = on the digitized line)",
        "viridis",
    )
    fig_raster_tall(
        out / "position_confidence_2010.tif",
        "allegan_position_confidence_2010.png",
        "Position confidence, 2010 (1 = on the digitized line)",
        "viridis",
    )
    fig_raster_tall(
        out / "position_delta_1938_2010.tif",
        "allegan_position_delta_1938_2010.png",
        "Position delta, 1938->2010 (m, signed cross-shore offset)",
        "RdBu",
    )
    fig_raster_tall(
        out / "change_probability_1938_2010.tif",
        "allegan_change_probability_1938_2010.png",
        "P(real change), 1938->2010",
        "RdYlGn_r",
    )


def _fig_segment_layer(
    gdf: gpd.GeoDataFrame,
    column: str,
    cmap: str,
    vmin: float,
    vmax: float,
    legend_label: str,
    title: str,
    out_name: str,
) -> None:
    """Single full-size figure for one change-probability-segments
    GeoDataFrame, colored by *column* (PROB_CHANGE or MAGNITUDE), over the
    open-imagery basemap. Shared by fig_prob_change_segments and
    fig_change_probability_segments_magnitude so each shoreline year gets
    its own full-page figure instead of being squeezed into a side-by-side
    subplot panel."""
    fig, ax = plt.subplots(figsize=(9, 7))
    gdf.plot(
        column=column, ax=ax, cmap=cmap, vmin=vmin, vmax=vmax, lw=3, legend=True,
        legend_kwds={"label": legend_label, "shrink": 0.7},
    )
    _add_basemap(ax, crs=gdf.crs)
    ax.set_title(title)
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(SHOTS / out_name, dpi=150)
    plt.close(fig)


def fig_prob_change_segments(out: Path) -> None:
    """Each shoreline in the 1938/2010 pair, broken into
    prob_change_segment_length-long segments and colored by its
    PROB_CHANGE attribute -- a vector summary of change_probability_1938_2010.tif
    sampled along the lines themselves. One full figure per shoreline
    year (not a combined side-by-side subplot)."""
    specs = [
        ("change_probability_segments_1938_vs_2010.shp", "1938 shoreline", "allegan_change_probability_segments_1938.png"),
        ("change_probability_segments_2010_vs_1938.shp", "2010 shoreline", "allegan_change_probability_segments_2010.png"),
    ]
    for fname, label, out_name in specs:
        gdf = gpd.read_file(out / fname)
        _fig_segment_layer(
            gdf,
            "PROB_CHANG",
            "RdYlGn_r",
            0.0,
            1.0,
            "P(real change), 1938->2010",
            f"Allegan, MI -- {label} segments colored by PROB_CHANGE\n(prob_change_segment_length = 50m)",
            out_name,
        )


def fig_change_probability_segments_magnitude(out: Path) -> None:
    """Companion to fig_prob_change_segments: the same two shorelines'
    segments, this time colored by the MAGNITUDE attribute (negative =
    erosion, positive = accretion) instead of PROB_CHANGE -- a direct
    visualization of how much and in which direction each stretch of coast
    moved. One full figure per shoreline year, sharing a single symmetric
    color scale (computed across both years) so the two remain visually
    comparable even though they're separate files."""
    specs = [
        ("change_probability_segments_1938_vs_2010.shp", "1938 shoreline", "allegan_change_probability_segments_magnitude_1938.png"),
        ("change_probability_segments_2010_vs_1938.shp", "2010 shoreline", "allegan_change_probability_segments_magnitude_2010.png"),
    ]
    gdfs = [gpd.read_file(out / fname) for fname, _, _ in specs]
    vmax = max(abs(g["MAGNITUDE"]).max() for g in gdfs)
    for (fname, label, out_name), gdf in zip(specs, gdfs):
        _fig_segment_layer(
            gdf,
            "MAGNITUDE",
            "RdBu",
            -vmax,
            vmax,
            "MAGNITUDE, 1938->2010 (m, - erosion / + accretion)",
            f"Allegan, MI -- {label} segments colored by MAGNITUDE\n(prob_change_segment_length = 50m)",
            out_name,
        )


def fig_rate_change_polygons(out: Path) -> None:
    """rate_change_polygons.shp for the 1938->2010 pair: one polygon per gap
    between two adjacent rate transects, colored by MAGNITUDE (negative =
    erosion, positive = accretion) -- a polygon-area analogue of the
    per-transect EPR_RATE line plot in fig_rate_of_change, useful for seeing
    which stretches of coast changed the most without reading individual
    transect values one at a time."""
    gdf = gpd.read_file(out / "rate_change_polygons.shp")
    pair = gdf[(gdf["YEAR_A"] == 1938) & (gdf["YEAR_B"] == 2010)]
    vmax = abs(pair["MAGNITUDE"]).max()
    fig, ax = plt.subplots(figsize=(9, 4))
    pair.plot(column="MAGNITUDE", ax=ax, cmap="RdBu", vmin=-vmax, vmax=vmax, alpha=0.7, legend=True,
              legend_kwds={"label": "MAGNITUDE (m, - erosion / + accretion)", "shrink": 0.7})
    _add_basemap(ax, crs=gdf.crs)
    ax.set_title("Allegan, MI -- rate_change_polygons, 1938->2010 (rate_transect_spacing = 10m)")
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(SHOTS / "allegan_rate_change_polygons.png", dpi=150)
    plt.close(fig)


def fig_rate_of_change(out: Path) -> None:
    """EPR_RATE and LRR_RATE (m/yr) along the dense rate_transect_spacing
    transect grid, ordered by TRANSECT_ID -- with only 2 shoreline years
    (1938, 2010) at this site, LRR and EPR are mathematically identical
    (LRR_R2 == 1.0 everywhere), so the two lines should overlap exactly;
    this is itself a useful sanity-check visualization of that property."""
    import pandas as pd

    df = pd.read_csv(out / "transect_rate_of_change.csv").sort_values("TRANSECT_ID")
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(df["TRANSECT_ID"], df["EPR_RATE"], color="tab:blue", lw=2, label="EPR_RATE (end point)")
    ax.plot(df["TRANSECT_ID"], df["LRR_RATE"], color="tab:orange", lw=1, ls="--", label="LRR_RATE (regression)")
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_title("Allegan, MI -- EPR / LRR shoreline change rate, 1938->2010 (rate_transect_spacing = 10m)")
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


def main():
    """Regenerate every screenshot in examples/screenshots/, for all three
    example configs."""
    make_synthetic_screenshots()
    make_allegan_screenshots()
    make_prob_change_screenshots()
    make_rate_and_segments_screenshots()
    print(f"Wrote screenshots to {SHOTS}")


if __name__ == "__main__":
    main()
