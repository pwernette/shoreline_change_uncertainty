"""Automatic water-level lookup via the NOAA CO-OPS Tides & Currents API.

A single free, no-API-key REST service (https://api.tidesandcurrents.noaa.gov)
covers both marine/coastal tide-gauge stations and Great Lakes water-level
stations, which is what makes one module workable for both: given a site's
location, find the nearest station (via the companion Metadata API), then
pull either a date-specific water level (the level at the moment a shoreline
was actually digitized from imagery/LiDAR -- a known source of horizontal
position error, since the water line on the source shifts with lake/tide
stage) or a year-level mean (a climate-normalization figure -- "was this an
unusually high or low water year").

This module is intentionally decoupled from pipeline.run_pipeline: it makes
live HTTP calls, which the rest of this package deliberately never does (see
io_utils.py and the synthetic/Allegan test fixtures) so the core positional-
uncertainty analysis stays deterministic, offline, and fast to test. Use it
standalone, or via `python -m surf.cli water-levels
--config ...` (cli.py), which writes one CSV row per shoreline year. Nothing
here feeds back into uncertainty.py's RMSE_O automatically -- the three
Wernette et al. (2017) components (base image, georeferencing, interpretation)
don't include a water-level/tidal-datum term today, and folding a *measured*
quantity into that *modeled* equation is a deliberate call left to the
caller, not something this module should decide silently.

Great Lakes vs. marine differences that drive the product/datum choices
below (see the CO-OPS Data API and Metadata API docs):
    - Datums: Great Lakes stations commonly use IGLD (International Great
      Lakes Datum) or LWD (Low Water Datum); marine stations commonly use
      MSL, MLLW, NAVD, etc. There is no single datum valid everywhere, so
      the default here is picked per-station from its `greatlakes` flag.
    - Products: `daily_mean` is Great-Lakes-only and requires
      `time_zone=lst`; `hourly_height` (verified, historical-depth) is the
      marine equivalent at a similar granularity. `monthly_mean` is the one
      product published for both regions and is used here for year-level
      lookups.
    - Coverage: digital CO-OPS records generally start in the 1970s-90s even
      where a station has operated much longer; very old shoreline dates
      (e.g. 1938 imagery) may simply have no station data available. Callers
      should be ready for WaterLevelError on old dates rather than assuming
      coverage.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import geopandas as gpd
import requests

MDAPI_STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
DATAGETTER_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
APPLICATION_NAME = "surf"
DEFAULT_STATION_CACHE = Path.home() / ".cache" / "surf" / "coops_stations.json"

_EARTH_RADIUS_NM = 3440.065  # mean Earth radius in nautical miles


class WaterLevelError(RuntimeError):
    """Raised when a station, or water-level data for a requested period,
    cannot be found/retrieved -- including after this module's own fallback
    window-widening has been exhausted. Callers should expect this for very
    old shoreline dates or remote sites with no nearby gauge."""


@dataclass
class WaterLevelStation:
    """One CO-OPS water-level station, as returned by the Metadata API's
    `stations.json?type=waterlevels` resource. `distance_nm` is left unset
    (None) on records fetched/cached via fetch_station_list, and filled in
    by find_nearest_station for the one station it selects."""

    id: str
    name: str
    lat: float
    lng: float
    greatlakes: bool
    distance_nm: Optional[float] = None


@dataclass
class WaterLevelResult:
    """One resolved water-level lookup: which station was used, what it
    reported, and -- if the originally requested window had no data --
    what fallback was applied to get an answer at all."""

    station: WaterLevelStation
    datum: str
    units: str
    value: float
    value_type: str  # "hourly_height" | "daily_mean" | "monthly_mean"
    period_start: str
    period_end: str
    n_observations: int
    fallback_used: Optional[str] = None


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in nautical miles
    (matching the unit CO-OPS itself uses for its `radius` parameter)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def site_lat_lon(gdf: gpd.GeoDataFrame) -> tuple[float, float]:
    """Representative (lat, lon) for a site, derived from the centroid of a
    GeoDataFrame's geometry (e.g. a shoreline or baseline) -- so callers
    never need to hand-enter a site's coordinates just to look up the
    nearest water-level station. Reprojects to EPSG:4326 first regardless of
    the input CRS."""
    centroid = gdf.to_crs(epsg=4326).unary_union.centroid
    return centroid.y, centroid.x  # (lat, lon)


def fetch_station_list(
    cache_path: Optional[Path] = DEFAULT_STATION_CACHE,
    max_age_days: float = 30,
    session=None,
) -> list[WaterLevelStation]:
    """Fetch the full list of active water-level stations (Great Lakes +
    marine) from the CO-OPS Metadata API, caching it to disk -- the list
    rarely changes, so repeated full-list pulls just add unnecessary load.
    Pass cache_path=None to disable caching entirely. A cache older than
    max_age_days (or unreadable/corrupt) is refetched."""
    cache_path = Path(cache_path) if cache_path else None
    if cache_path and cache_path.exists():
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400
        if age_days <= max_age_days:
            try:
                raw = json.loads(cache_path.read_text())
                return [WaterLevelStation(**s) for s in raw]
            except (json.JSONDecodeError, TypeError, KeyError):
                pass  # corrupt cache -- fall through and refetch

    client = session or requests
    resp = client.get(MDAPI_STATIONS_URL, params={"type": "waterlevels"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    stations = [
        WaterLevelStation(
            id=str(s["id"]),
            name=s["name"],
            lat=float(s["lat"]),
            lng=float(s["lng"]),
            greatlakes=bool(s.get("greatlakes", False)),
        )
        for s in payload.get("stations", [])
    ]
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps([asdict(s) for s in stations]))
    return stations


def find_nearest_station(
    lat: float,
    lon: float,
    stations: Optional[list] = None,
    prefer_greatlakes: Optional[bool] = None,
    max_distance_nm: Optional[float] = None,
) -> WaterLevelStation:
    """Find the nearest CO-OPS water-level station to (lat, lon).

    Deliberately searches the full station list (fetched/cached via
    fetch_station_list if `stations` isn't passed in) rather than using the
    Metadata API's "Nearby" resource -- that resource finds stations near
    *another station*, which requires already knowing a station ID, not an
    arbitrary site lat/lon.

    If `prefer_greatlakes` is True or False, only stations whose
    `greatlakes` flag matches are considered, so a coastal site near a lake
    can't accidentally match a marine station (or vice versa). Raises
    WaterLevelError if the filtered candidate list is empty, or if the
    nearest match is farther than `max_distance_nm` (when given).
    """
    stations = stations if stations is not None else fetch_station_list()
    candidates = stations
    if prefer_greatlakes is not None:
        candidates = [s for s in candidates if s.greatlakes == prefer_greatlakes]
    if not candidates:
        raise WaterLevelError("No candidate water-level stations after filtering by prefer_greatlakes.")

    best, best_dist = None, math.inf
    for s in candidates:
        d = _haversine_nm(lat, lon, s.lat, s.lng)
        if d < best_dist:
            best, best_dist = s, d

    if max_distance_nm is not None and best_dist > max_distance_nm:
        raise WaterLevelError(
            f"Nearest station {best.id} ({best.name}) is {best_dist:.1f} nm away, "
            f"beyond max_distance_nm={max_distance_nm}."
        )
    return WaterLevelStation(
        id=best.id, name=best.name, lat=best.lat, lng=best.lng,
        greatlakes=best.greatlakes, distance_nm=round(best_dist, 2),
    )


def _default_datum(station: WaterLevelStation) -> str:
    """IGLD for Great Lakes stations, MSL for marine -- reasonable defaults
    that callers can always override via the `datum` parameter."""
    return "IGLD" if station.greatlakes else "MSL"


def _request_datagetter(params: dict, session=None) -> dict:
    client = session or requests
    full_params = {"format": "json", "application": APPLICATION_NAME, **params}
    resp = client.get(DATAGETTER_URL, params=full_params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and "error" in payload:
        raise WaterLevelError(str(payload["error"].get("message", payload["error"])))
    return payload


def _mean_value(payload: dict) -> tuple[float, int]:
    """Average the 'v' field across whatever rows datagetter returned
    (under 'data' for water_level/hourly_height/daily_mean, or under
    'predictions' for the predictions product, included for completeness
    even though this module doesn't call that product itself)."""
    rows = payload.get("data") or payload.get("predictions") or []
    values = []
    for row in rows:
        v = row.get("v")
        if v in (None, ""):
            continue
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue
    if not values:
        raise WaterLevelError("CO-OPS response contained no usable water-level observations.")
    return sum(values) / len(values), len(values)


def get_water_level(
    lat: float,
    lon: float,
    when: "date | str",
    *,
    window_days: int = 0,
    max_window_days: int = 7,
    datum: Optional[str] = None,
    units: str = "metric",
    stations: Optional[list] = None,
    session=None,
) -> WaterLevelResult:
    """Date-specific water level: the mean observed level at the nearest
    CO-OPS station within +/- window_days of `when` (a date or a
    'YYYY-MM-DD' string) -- the value relevant to correcting for the
    water/tide stage at the moment a shoreline was actually digitized.

    Uses `hourly_height` (verified, historical-depth) for marine stations
    and `daily_mean` (verified, Great-Lakes-only, forced time_zone='lst' per
    CO-OPS' requirement for that product) for Great Lakes stations.

    If the requested window has no data -- common for older imagery dates,
    or a sensor outage -- the window is widened by doubling (capped at
    max_window_days) until data is found or the cap is hit, in which case
    WaterLevelError is raised. Any widening actually used is recorded in the
    returned result's `fallback_used`, so a result is never silently mixed
    from a meaningfully different time period without saying so.
    """
    if isinstance(when, str):
        when = datetime.strptime(when, "%Y-%m-%d").date()

    nearest = find_nearest_station(lat, lon, stations=stations)
    resolved_datum = datum or _default_datum(nearest)
    fallback_used = None
    w = max(window_days, 0)

    while True:
        begin = when - timedelta(days=w)
        end = when + timedelta(days=w)
        params = {
            "station": nearest.id,
            "begin_date": begin.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "datum": resolved_datum,
            "units": units,
            "time_zone": "lst",
            "product": "daily_mean" if nearest.greatlakes else "hourly_height",
        }
        try:
            payload = _request_datagetter(params, session=session)
            value, n = _mean_value(payload)
            break
        except WaterLevelError:
            if w >= max_window_days:
                raise WaterLevelError(
                    f"No water-level data for station {nearest.id} within "
                    f"+/-{w}d of {when} (datum={resolved_datum})."
                ) from None
            new_w = min(max(w * 2, 1), max_window_days)
            fallback_used = f"no data within +/-{w}d of {when}; widened to +/-{new_w}d"
            w = new_w

    return WaterLevelResult(
        station=nearest,
        datum=resolved_datum,
        units=units,
        value=value,
        value_type="daily_mean" if nearest.greatlakes else "hourly_height",
        period_start=begin.isoformat(),
        period_end=end.isoformat(),
        n_observations=n,
        fallback_used=fallback_used,
    )


def get_annual_water_level(
    lat: float,
    lon: float,
    year: int,
    *,
    datum: Optional[str] = None,
    units: str = "metric",
    stations: Optional[list] = None,
    session=None,
) -> WaterLevelResult:
    """Year-level water level: the mean of the verified `monthly_mean`
    values at the nearest CO-OPS station across `year` -- the right
    granularity for "what was the typical lake/sea level that year" rather
    than the level at one specific moment. `monthly_mean` is the one
    product CO-OPS publishes for both Great Lakes and marine stations
    (with up to 200 years of history where available), which is why it's
    used here regardless of station type."""
    nearest = find_nearest_station(lat, lon, stations=stations)
    resolved_datum = datum or _default_datum(nearest)
    params = {
        "station": nearest.id,
        "begin_date": f"{year}0101",
        "end_date": f"{year}1231",
        "product": "monthly_mean",
        "datum": resolved_datum,
        "units": units,
    }
    payload = _request_datagetter(params, session=session)
    value, n = _mean_value(payload)
    return WaterLevelResult(
        station=nearest,
        datum=resolved_datum,
        units=units,
        value=value,
        value_type="monthly_mean",
        period_start=f"{year}-01-01",
        period_end=f"{year}-12-31",
        n_observations=n,
        fallback_used=None,
    )
