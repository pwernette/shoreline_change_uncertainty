"""Sandbox-local stub of the small `qgis.core` / `qgis.PyQt` API surface
the ported plugin modules use, backed by shapely/GEOS (the same geometry
engine real QgsGeometry uses internally) and geopandas/pyproj for the
vector-layer/CRS pieces.

WHY THIS EXISTS: the development sandbox this plugin is being built in has
no real QGIS install, no PyQt5/PyQt6, no conda, and no root access to
install any of them (there is no real PyQGIS wheel on PyPI -- the bindings
only ship bundled inside a full QGIS desktop install). This stub lets the
ported module *logic* be unit-tested here anyway. It is NOT shipped with
the plugin, and passing these tests does NOT confirm the real `qgis.core`
calls are spelled/used correctly -- only that the algorithm is right. Final
validation against the real API needs a load-and-run check in actual QGIS.
See qgis_plugin/tests/README.md.

Usage: call `install()` once per test session (a conftest.py fixture does
this) before importing anything from `shoreline_uncertainty_qgis`.
"""
from __future__ import annotations

import copy
import sys
import types
from typing import List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from rasterio.transform import Affine as _Affine
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# qgis.core
# ---------------------------------------------------------------------------


class QgsPointXY:
    def __init__(self, x, y=None):
        if y is None and hasattr(x, "x"):
            y = x.y()
            x = x.x()
        self._x = float(x)
        self._y = float(y)

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y

    def __repr__(self):
        return f"QgsPointXY({self._x}, {self._y})"


class QgsRectangle:
    """Minimal stand-in for `qgis.core.QgsRectangle`, returned by
    `QgsGeometry.boundingBox()`."""

    def __init__(self, xmin: float, ymin: float, xmax: float, ymax: float):
        self._xmin, self._ymin, self._xmax, self._ymax = xmin, ymin, xmax, ymax

    def xMinimum(self) -> float:
        return self._xmin

    def yMinimum(self) -> float:
        return self._ymin

    def xMaximum(self) -> float:
        return self._xmax

    def yMaximum(self) -> float:
        return self._ymax

    def __repr__(self):
        return f"QgsRectangle({self._xmin}, {self._ymin}, {self._xmax}, {self._ymax})"


class QgsWkbTypes:
    PointGeometry = "point"
    LineGeometry = "line"
    PolygonGeometry = "polygon"
    UnknownGeometry = "unknown"
    NullGeometry = "null"

    @staticmethod
    def geometryType(wkb_tag: str) -> str:
        if wkb_tag in ("Point", "MultiPoint"):
            return QgsWkbTypes.PointGeometry
        if wkb_tag in ("LineString", "MultiLineString"):
            return QgsWkbTypes.LineGeometry
        if wkb_tag in ("Polygon", "MultiPolygon"):
            return QgsWkbTypes.PolygonGeometry
        return QgsWkbTypes.UnknownGeometry


def _wkb_tag(shapely_geom) -> str:
    return shapely_geom.geom_type


class QgsGeometry:
    """Thin shapely-backed stand-in for `qgis.core.QgsGeometry`. Implements
    only the subset of the real API actually called by the ported modules
    under test -- not a full reimplementation."""

    def __init__(self, other: Optional["QgsGeometry"] = None):
        if other is None:
            self._geom = None
        elif isinstance(other, QgsGeometry):
            self._geom = other._geom
        else:
            self._geom = other

    @staticmethod
    def fromShapely(shapely_geom) -> "QgsGeometry":
        g = QgsGeometry()
        g._geom = shapely_geom
        return g

    @staticmethod
    def fromPointXY(point: QgsPointXY) -> "QgsGeometry":
        return QgsGeometry.fromShapely(Point(point.x(), point.y()))

    @staticmethod
    def fromPolylineXY(points: List[QgsPointXY]) -> "QgsGeometry":
        return QgsGeometry.fromShapely(LineString([(p.x(), p.y()) for p in points]))

    @staticmethod
    def fromMultiPolylineXY(parts: List[List[QgsPointXY]]) -> "QgsGeometry":
        return QgsGeometry.fromShapely(
            MultiLineString([[(p.x(), p.y()) for p in part] for part in parts])
        )

    @staticmethod
    def fromPolygonXY(rings: List[List[QgsPointXY]]) -> "QgsGeometry":
        """Build a polygon from a list of rings (first = exterior, rest =
        holes), each a list of QgsPointXY -- mirrors real QgsGeometry's
        static constructor. Rings need not be explicitly closed (shapely's
        Polygon constructor closes them automatically), matching the real
        API's tolerance for an unclosed input ring."""
        shell = [(p.x(), p.y()) for p in rings[0]]
        holes = [[(p.x(), p.y()) for p in ring] for ring in rings[1:]]
        return QgsGeometry.fromShapely(Polygon(shell, holes))

    @staticmethod
    def unaryUnion(geometries: List["QgsGeometry"]) -> "QgsGeometry":
        geoms = [g._geom for g in geometries if g is not None and g._geom is not None]
        return QgsGeometry.fromShapely(unary_union(geoms)) if geoms else QgsGeometry()

    def isNull(self) -> bool:
        return self._geom is None

    def isEmpty(self) -> bool:
        return self._geom is None or self._geom.is_empty

    def isMultipart(self) -> bool:
        return self._geom is not None and self._geom.geom_type.startswith("Multi")

    def wkbType(self) -> str:
        return _wkb_tag(self._geom) if self._geom is not None else "Unknown"

    def asPoint(self) -> QgsPointXY:
        return QgsPointXY(self._geom.x, self._geom.y)

    def asPolyline(self) -> List[QgsPointXY]:
        return [QgsPointXY(*c) for c in self._geom.coords]

    def asMultiPolyline(self) -> List[List[QgsPointXY]]:
        return [[QgsPointXY(*c) for c in part.coords] for part in self._geom.geoms]

    def asPolygon(self) -> List[List[QgsPointXY]]:
        rings = [list(self._geom.exterior.coords)] + [
            list(r.coords) for r in self._geom.interiors
        ]
        return [[QgsPointXY(*c) for c in ring] for ring in rings]

    def asMultiPolygon(self) -> List[List[List[QgsPointXY]]]:
        out = []
        for poly in self._geom.geoms:
            rings = [list(poly.exterior.coords)] + [list(r.coords) for r in poly.interiors]
            out.append([[QgsPointXY(*c) for c in ring] for ring in rings])
        return out

    def distance(self, other: "QgsGeometry") -> float:
        return self._geom.distance(other._geom)

    def area(self) -> float:
        return self._geom.area

    def length(self) -> float:
        return self._geom.length

    def centroid(self) -> "QgsGeometry":
        return QgsGeometry.fromShapely(self._geom.centroid)

    def buffer(self, distance: float, segments: int = 8) -> "QgsGeometry":
        return QgsGeometry.fromShapely(self._geom.buffer(distance, quad_segs=segments))

    def intersection(self, other: "QgsGeometry") -> "QgsGeometry":
        return QgsGeometry.fromShapely(self._geom.intersection(other._geom))

    def combine(self, other: "QgsGeometry") -> "QgsGeometry":
        return QgsGeometry.fromShapely(unary_union([self._geom, other._geom]))

    def difference(self, other: "QgsGeometry") -> "QgsGeometry":
        return QgsGeometry.fromShapely(self._geom.difference(other._geom))

    def isGeosValid(self) -> bool:
        """Mirrors real QgsGeometry.isGeosValid() -- GEOS-backed validity
        check (self-intersections, etc.), same engine shapely's `is_valid`
        wraps."""
        return self._geom is not None and self._geom.is_valid

    def makeValid(self) -> "QgsGeometry":
        """Mirrors real QgsGeometry.makeValid() (available since QGIS 3.0,
        itself GEOS-backed) -- repairs an invalid geometry (e.g. a
        self-intersecting quadrilateral) into a valid one. shapely 2.0+'s
        `shapely.validation.make_valid` wraps the same GEOS
        `GEOSMakeValid`/`GEOSMakeValidWithParams` routine."""
        from shapely.validation import make_valid

        if self._geom is None:
            return QgsGeometry()
        return QgsGeometry.fromShapely(make_valid(self._geom))

    def interpolate(self, distance: float) -> "QgsGeometry":
        return QgsGeometry.fromShapely(self._geom.interpolate(distance, normalized=False))

    def mergeLines(self) -> "QgsGeometry":
        """Merge contiguous parts of a (multi)line into fewer, longer
        lines -- shapely.ops.linemerge under the hood, same engine real
        QgsGeometry.mergeLines() uses (GEOS)."""
        from shapely.ops import linemerge

        if self._geom is None or self._geom.geom_type != "MultiLineString":
            return QgsGeometry(self)
        merged = linemerge(self._geom)
        return QgsGeometry.fromShapely(merged)

    def asWkb(self) -> bytes:
        return bytes(self._geom.wkb) if self._geom is not None else b""

    def boundingBox(self) -> "QgsRectangle":
        minx, miny, maxx, maxy = self._geom.bounds
        return QgsRectangle(minx, miny, maxx, maxy)

    def asGeometryCollection(self) -> List["QgsGeometry"]:
        """Decompose into single-part pieces -- mirrors the real
        QgsGeometry.asGeometryCollection(), which works for any geometry
        type (Point/MultiPoint/LineString/MultiLineString/Polygon/
        MultiPolygon/mixed GeometryCollection), returning a one-element
        list for an already-single-part geometry."""
        if self._geom is None or self._geom.is_empty:
            return []
        if self._geom.geom_type in (
            "MultiPoint",
            "MultiLineString",
            "MultiPolygon",
            "GeometryCollection",
        ):
            return [QgsGeometry.fromShapely(g) for g in self._geom.geoms]
        return [self]

    def transform(self, transform: "QgsCoordinateTransform") -> None:
        self._geom = transform.transform_shapely(self._geom)

    def to_shapely(self):
        return self._geom


class QgsCoordinateReferenceSystem:
    def __init__(self, definition: str = ""):
        self._definition = definition
        try:
            self._crs = pyproj.CRS.from_user_input(definition) if definition else None
        except Exception:
            self._crs = None

    def isValid(self) -> bool:
        return self._crs is not None

    def isGeographic(self) -> bool:
        return self._crs is not None and self._crs.is_geographic

    def authid(self) -> str:
        if self._crs is None:
            return ""
        epsg = self._crs.to_epsg()
        return f"EPSG:{epsg}" if epsg else self._definition

    def __eq__(self, other):
        return isinstance(other, QgsCoordinateReferenceSystem) and self.authid() == other.authid()

    def __repr__(self):
        return f"QgsCoordinateReferenceSystem({self.authid()!r})"


class QgsProject:
    _instance = None

    def __init__(self):
        self._layers: List[object] = []

    @staticmethod
    def instance() -> "QgsProject":
        if QgsProject._instance is None:
            QgsProject._instance = QgsProject()
        return QgsProject._instance

    def addMapLayer(self, layer) -> object:
        """Mirrors real QgsProject.addMapLayer -- records the layer so
        result_loader.py's "load into the map canvas" step has somewhere
        real to add to under test, without a real QGIS map canvas."""
        self._layers.append(layer)
        return layer

    def mapLayers(self):
        return list(self._layers)


class QgsCoordinateTransform:
    def __init__(self, src, dst, project=None):
        self._transformer = pyproj.Transformer.from_crs(src._crs, dst._crs, always_xy=True)

    def transform_shapely(self, geom):
        return shapely_transform(lambda x, y, z=None: self._transformer.transform(x, y), geom)


class QgsField:
    def __init__(self, name: str, type_=None):
        self._name = name
        self.type_ = type_

    def name(self) -> str:
        return self._name


class QgsFields:
    def __init__(self):
        self._fields: List[QgsField] = []

    def append(self, field: QgsField):
        self._fields.append(field)

    def names(self):
        return [f.name() for f in self._fields]

    def __iter__(self):
        return iter(self._fields)

    def __len__(self):
        return len(self._fields)


class QgsFeature:
    def __init__(self, source=None):
        if isinstance(source, QgsFeature):
            self._fields = source._fields
            self._geometry = source._geometry
            self._attributes = dict(source._attributes)
        elif isinstance(source, (QgsFields, list)):
            self._fields = source
            self._geometry = None
            self._attributes = {}
        else:
            self._fields = QgsFields()
            self._geometry = None
            self._attributes = {}

    def setGeometry(self, geom: QgsGeometry):
        self._geometry = geom

    def geometry(self) -> QgsGeometry:
        return self._geometry

    def setAttributes(self, values: list):
        names = (
            self._fields.names()
            if isinstance(self._fields, QgsFields)
            else [f.name() for f in self._fields]
        )
        self._attributes = dict(zip(names, values))

    def attributes(self):
        return list(self._attributes.values())

    def __getitem__(self, key):
        return self._attributes[key]


class _MemoryProvider:
    def __init__(self, layer: "QgsVectorLayer"):
        self._layer = layer

    def addAttributes(self, fields):
        for f in fields:
            self._layer._fields.append(f)

    def addFeatures(self, feats: List[QgsFeature]):
        self._layer._features.extend(feats)


class QgsVectorLayer:
    """Backed by geopandas when reading a real file (so `read_shoreline`
    can be tested against actual shapefiles/GeoJSON in this sandbox);
    backed by a plain in-memory feature list for the 'memory' provider used
    to build output layers."""

    def __init__(self, source: str, name: str, provider: str):
        self._name = name
        self._provider_type = provider
        self._fields = QgsFields()
        self._features: List[QgsFeature] = []
        self._crs = QgsCoordinateReferenceSystem()
        self._valid = True

        if provider == "ogr":
            try:
                gdf = gpd.read_file(source)
            except Exception:
                self._valid = False
                return
            if gdf.crs is not None:
                self._crs = QgsCoordinateReferenceSystem(gdf.crs.to_string())
            cols = [c for c in gdf.columns if c != "geometry"]
            for col in cols:
                self._fields.append(QgsField(col))
            for _, row in gdf.iterrows():
                feat = QgsFeature(self._fields)
                feat.setGeometry(QgsGeometry.fromShapely(row.geometry))
                feat.setAttributes([row[c] for c in cols])
                self._features.append(feat)
        elif provider == "memory":
            if "crs=" in source:
                self._crs = QgsCoordinateReferenceSystem(source.split("crs=", 1)[1])

    def isValid(self) -> bool:
        return self._valid

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs

    def name(self) -> str:
        return self._name

    def wkbType(self):
        return self._features[0].geometry().wkbType() if self._features else "Unknown"

    def getFeatures(self):
        return list(self._features)

    def featureCount(self) -> int:
        return len(self._features)

    def fields(self) -> QgsFields:
        return self._fields

    def dataProvider(self) -> _MemoryProvider:
        return _MemoryProvider(self)

    def updateFields(self):
        pass

    def updateExtents(self):
        pass

    def transformContext(self):
        return None

    def clone(self) -> "QgsVectorLayer":
        return copy.deepcopy(self)


class QgsVectorFileWriter:
    NoError = 0

    class SaveVectorOptions:
        def __init__(self):
            self.driverName = None

    @staticmethod
    def driverForExtension(ext: str) -> str:
        return {".shp": "ESRI Shapefile", ".geojson": "GeoJSON", ".gpkg": "GPKG"}.get(
            ext.lower(), "ESRI Shapefile"
        )

    @staticmethod
    def writeAsVectorFormatV3(layer: QgsVectorLayer, path: str, transform_context, options) -> Tuple:
        records = []
        for feat in layer.getFeatures():
            record = dict(feat._attributes)
            record["geometry"] = feat.geometry().to_shapely()
            records.append(record)
        if not records:
            return (QgsVectorFileWriter.NoError, "")
        gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=layer.crs().authid() or None)
        driver = options.driverName or "ESRI Shapefile"
        gdf.to_file(path, driver=driver)
        return (QgsVectorFileWriter.NoError, "")


class QgsRasterLayer:
    """Backed by rasterio when reading a real GeoTIFF -- every raster output
    this plugin writes (similarity_index.tif, significant_change.tif, the
    position_*/change_probability_* rasters) is a GeoTIFF. Just enough to
    let result_loader.py's discovery/loading step be unit-tested here: an
    invalid/unreadable source makes isValid() false, mirroring real QGIS's
    behavior when a raster provider can't open its source."""

    def __init__(self, source: str, name: str = "", provider: str = "gdal"):
        self._name = name
        self._source = source
        self._valid = True
        self._crs = QgsCoordinateReferenceSystem()
        self.width = 0
        self.height = 0
        try:
            with rasterio.open(source) as ds:
                if ds.crs:
                    self._crs = QgsCoordinateReferenceSystem(ds.crs.to_string())
                self.width = ds.width
                self.height = ds.height
        except Exception:
            self._valid = False

    def isValid(self) -> bool:
        return self._valid

    def name(self) -> str:
        return self._name

    def source(self) -> str:
        return self._source

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs


class QgsProcessingException(Exception):
    """Mirrors qgis.core.QgsProcessingException -- raised by
    QgsProcessingAlgorithm.processAlgorithm to report a fatal, user-facing
    error (e.g. a bad config file) back through the Processing framework."""


class QgsProcessingContext:
    """Opaque placeholder -- real QgsProcessingContext carries project/
    transform-context state that none of the ported algorithms' own logic
    needs directly; it's only threaded through parameterAs* calls."""


class QgsProcessingFeedback:
    """No-op stand-in for qgis.core.QgsProcessingFeedback. Real QGIS wires
    this to the Processing dialog's progress bar/log; here it just swallows
    every call so processAlgorithm can be exercised without a UI."""

    def pushInfo(self, msg: str) -> None:
        pass

    def pushWarning(self, msg: str) -> None:
        pass

    def reportError(self, msg: str, fatalError: bool = False) -> None:
        pass

    def setProgress(self, progress: float) -> None:
        pass

    def isCanceled(self) -> bool:
        return False


class _ProcessingParameter:
    """Common base for the QgsProcessingParameter* stand-ins below -- real
    QGIS parameter classes carry far more (validation, widget metadata,
    default-value coercion); here they're just inert records of a
    parameter's name, since `addParameter` in this stub only needs to
    remember names for introspection, not validate anything (tests call
    processAlgorithm directly with a plain `parameters` dict, bypassing the
    real Processing framework's own parameter resolution)."""

    def __init__(self, name: str, description: str = "", *args, **kwargs):
        self._name = name
        self._description = description

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._description


class QgsProcessingParameterFile(_ProcessingParameter):
    pass


class QgsProcessingParameterFileDestination(_ProcessingParameter):
    pass


class QgsProcessingParameterFolderDestination(_ProcessingParameter):
    pass


class QgsProcessingParameterString(_ProcessingParameter):
    pass


class QgsProcessingParameterNumber(_ProcessingParameter):
    Integer = 0
    Double = 1

    def __init__(self, name, description="", type=Double, defaultValue=None, minValue=None, **kwargs):
        super().__init__(name, description)
        self.type = type
        self.defaultValue = defaultValue
        self.minValue = minValue


class QgsProcessingParameterBoolean(_ProcessingParameter):
    def __init__(self, name, description="", defaultValue=False, **kwargs):
        super().__init__(name, description)
        self.defaultValue = defaultValue


class QgsProcessingAlgorithm:
    """Bare stand-in for qgis.core.QgsProcessingAlgorithm. Real QGIS
    resolves `parameters` (a dict of widget values from the Processing
    dialog/script call) against each registered QgsProcessingParameter*'s
    own type/validation rules before handing them to processAlgorithm; this
    stub's parameterAs*() helpers skip that resolution and just read
    straight out of the `parameters` dict, coercing to the requested type.
    That's enough to unit-test a subclass's processAlgorithm logic directly
    (passing a plain dict in tests) without a real Processing context --
    the same scope boundary as qgis_stub.py's other stand-ins (see module
    docstring)."""

    def __init__(self):
        self._parameters = []

    def addParameter(self, parameter) -> None:
        self._parameters.append(parameter)

    def parameterDefinitions(self):
        return list(self._parameters)

    def parameterAsFile(self, parameters: dict, name: str, context) -> str:
        return str(parameters.get(name) or "")

    def parameterAsFileOutput(self, parameters: dict, name: str, context) -> str:
        return str(parameters.get(name) or "")

    def parameterAsString(self, parameters: dict, name: str, context) -> str:
        value = parameters.get(name)
        return "" if value in (None, "") else str(value)

    def parameterAsDouble(self, parameters: dict, name: str, context) -> float:
        value = parameters.get(name)
        return float(value) if value not in (None, "") else 0.0

    def parameterAsInt(self, parameters: dict, name: str, context) -> int:
        value = parameters.get(name)
        return int(value) if value not in (None, "") else 0

    def parameterAsBool(self, parameters: dict, name: str, context) -> bool:
        return bool(parameters.get(name, False))

    def tr(self, text: str) -> str:
        return text

    def createInstance(self) -> "QgsProcessingAlgorithm":
        return type(self)()


class QgsProcessingProvider:
    """Bare stand-in for qgis.core.QgsProcessingProvider. Real QGIS calls
    loadAlgorithms() once, during which a subclass is expected to call
    self.addAlgorithm(...) for each algorithm it provides; that part of the
    real contract is preserved here so a subclass's own loadAlgorithms()
    override can be tested directly."""

    def __init__(self):
        self._algorithms = []

    def addAlgorithm(self, algorithm) -> None:
        self._algorithms.append(algorithm)

    def algorithms(self):
        return list(self._algorithms)


class _ProcessingRegistry:
    def __init__(self):
        self._providers = []

    def addProvider(self, provider) -> None:
        self._providers.append(provider)
        provider.loadAlgorithms()

    def removeProvider(self, provider) -> None:
        if provider in self._providers:
            self._providers.remove(provider)

    def providers(self):
        return list(self._providers)


class QgsApplication:
    """Bare stand-in for qgis.core.QgsApplication -- only the one static
    accessor plugin.py actually calls (`processingRegistry()`) is
    implemented, backed by a single process-wide registry instance so
    repeated calls return the same object, matching real QGIS's
    singleton-per-application behavior."""

    _registry = None

    @staticmethod
    def processingRegistry() -> "_ProcessingRegistry":
        if QgsApplication._registry is None:
            QgsApplication._registry = _ProcessingRegistry()
        return QgsApplication._registry


_CORE_EXPORTS = {
    name: obj
    for name, obj in list(globals().items())
    if name.startswith("Qgs")
}


# ---------------------------------------------------------------------------
# osgeo.gdal / osgeo.ogr / osgeo.osr -- fake GDAL bindings for
# raster_output_qgis.py, backed by rasterio (real GeoTIFF I/O) and shapely
# (vector geometry). QGIS bundles its own GDAL Python bindings; there is no
# real `osgeo` wheel installable in this sandbox either, for the same reason
# there's no real `qgis` wheel (it only ships inside a full GDAL/QGIS
# install). This fake only exercises raster_output_qgis.py's *logic* -- it
# does NOT confirm the real osgeo.gdal/ogr/osr API is being called
# correctly; that needs a load-and-run check in actual QGIS.
# ---------------------------------------------------------------------------

_GDAL_DTYPE_TO_NUMPY = {
    1: np.uint8,
    2: np.uint16,
    3: np.int16,
    4: np.uint32,
    5: np.int32,
    6: np.float32,
    7: np.float64,
}


class _GdalBand:
    def __init__(self, dataset: "_GdalDataset", index: int):
        self._dataset = dataset
        self._index = index
        self._nodata = None

    def Fill(self, value):
        self._dataset._arrays[self._index][:] = value

    def ReadAsArray(self):
        return self._dataset._arrays[self._index].copy()

    def WriteArray(self, array):
        self._dataset._arrays[self._index][:] = array

    def SetNoDataValue(self, value):
        self._nodata = value

    def GetNoDataValue(self):
        return self._nodata

    def FlushCache(self):
        self._dataset.FlushCache()


class _GdalDataset:
    def __init__(self, driver_name, path, width, height, bands, dtype):
        self._driver_name = driver_name
        self._path = path
        self.RasterXSize = width
        self.RasterYSize = height
        self._arrays = [np.zeros((height, width), dtype=dtype) for _ in range(bands)]
        self._geotransform = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
        self._projection_wkt = ""
        self._bands = [_GdalBand(self, i) for i in range(bands)]

    def SetGeoTransform(self, gt):
        self._geotransform = tuple(gt)

    def GetGeoTransform(self):
        return self._geotransform

    def SetProjection(self, wkt):
        self._projection_wkt = wkt

    def GetProjection(self):
        return self._projection_wkt

    def GetRasterBand(self, index_1_based):
        return self._bands[index_1_based - 1]

    def FlushCache(self):
        # Only the "GTiff" driver with a real path actually persists to
        # disk (mirroring real GDAL); the in-memory "MEM" driver used by
        # rasterize_geometry has no file to flush.
        if self._driver_name != "GTiff" or not self._path:
            return
        origin_x, pixel_w, rot_x, origin_y, rot_y, pixel_h = self._geotransform
        transform = _Affine(pixel_w, rot_x, origin_x, rot_y, pixel_h, origin_y)
        with rasterio.open(
            self._path,
            "w",
            driver="GTiff",
            height=self.RasterYSize,
            width=self.RasterXSize,
            count=len(self._arrays),
            dtype=self._arrays[0].dtype,
            crs=self._projection_wkt or None,
            transform=transform,
            nodata=self._bands[0]._nodata,
        ) as dst:
            for i, arr in enumerate(self._arrays, start=1):
                dst.write(arr, i)


class _GdalDriver:
    def __init__(self, name):
        self._name = name

    def Create(self, path, width, height, bands=1, eType=1):
        dtype = _GDAL_DTYPE_TO_NUMPY.get(eType, np.float64)
        return _GdalDataset(self._name, path or None, width, height, bands, dtype)


class _GdalModule:
    GDT_Byte = 1
    GDT_UInt16 = 2
    GDT_Int16 = 3
    GDT_UInt32 = 4
    GDT_Int32 = 5
    GDT_Float32 = 6
    GDT_Float64 = 7

    @staticmethod
    def UseExceptions():
        pass

    @staticmethod
    def GetDriverByName(name):
        return _GdalDriver(name)

    @staticmethod
    def RasterizeLayer(dataset, band_list, layer, burn_values=None, **kwargs):
        from rasterio.features import rasterize as _rasterize

        burn_value = (burn_values or [1])[0]
        width, height = dataset.RasterXSize, dataset.RasterYSize
        origin_x, pixel_w, rot_x, origin_y, rot_y, pixel_h = dataset.GetGeoTransform()
        transform = _Affine(pixel_w, rot_x, origin_x, rot_y, pixel_h, origin_y)
        geoms = [f._geom.shapely_geom for f in layer._features if f._geom is not None]
        if geoms:
            mask = _rasterize(
                [(g, 1) for g in geoms],
                out_shape=(height, width),
                transform=transform,
                fill=0,
                dtype="uint8",
            )
        else:
            mask = np.zeros((height, width), dtype=np.uint8)
        for b in band_list:
            band = dataset.GetRasterBand(b)
            arr = band.ReadAsArray()
            arr[mask.astype(bool)] = burn_value
            band.WriteArray(arr)


gdal = _GdalModule()


class _OgrGeometry:
    def __init__(self, shapely_geom):
        self.shapely_geom = shapely_geom


class _OgrFeature:
    def __init__(self, defn=None):
        self._defn = defn
        self._geom: Optional[_OgrGeometry] = None

    def SetGeometry(self, geom):
        self._geom = geom

    def GetGeometryRef(self):
        return self._geom


class _OgrLayer:
    def __init__(self, name, geom_type=None):
        self.name = name
        self._features: List[_OgrFeature] = []

    def GetLayerDefn(self):
        return None

    def CreateFeature(self, feat):
        self._features.append(feat)


class _OgrDataSource:
    def __init__(self, name):
        self.name = name

    def CreateLayer(self, name, geom_type=None, srs=None):
        return _OgrLayer(name, geom_type)


class _OgrDriver:
    def CreateDataSource(self, name):
        return _OgrDataSource(name)


class _OgrModule:
    wkbUnknown = 0
    Feature = _OgrFeature

    @staticmethod
    def GetDriverByName(name):
        return _OgrDriver()

    @staticmethod
    def CreateGeometryFromWkb(wkb_bytes):
        from shapely import wkb as _wkb

        return _OgrGeometry(_wkb.loads(bytes(wkb_bytes)))


ogr = _OgrModule()


class _SpatialReference:
    def __init__(self):
        self._user_input = ""

    def SetFromUserInput(self, value):
        self._user_input = value
        return 0

    def ExportToWkt(self):
        return self._user_input


class _OsrModule:
    SpatialReference = _SpatialReference


osr = _OsrModule()


# ---------------------------------------------------------------------------
# qgis.PyQt -- bare-minimum stand-ins, just enough for plugin.py/dialog.py
# to import cleanly; this stub is for testing pure logic, not UI behavior.
# ---------------------------------------------------------------------------


class _Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, item):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()

    def connect(self, *args, **kwargs):
        pass


_QT_WIDGET_NAMES = (
    "QAction",
    "QIcon",
    "QMessageBox",
    "QDialog",
    "QWidget",
    "QVBoxLayout",
    "QHBoxLayout",
    "QFormLayout",
    "QTableWidget",
    "QTableWidgetItem",
    "QTabWidget",
    "QPushButton",
    "QLabel",
    "QLineEdit",
    "QComboBox",
    "QCheckBox",
    "QProgressBar",
    "QFileDialog",
    "QDialogButtonBox",
    "QDoubleSpinBox",
    "QSpinBox",
    "QGroupBox",
)


def install() -> None:
    """Install the fake `qgis` package tree into `sys.modules` so that
    `from qgis.core import ...` / `from qgis.PyQt import ...` resolve here
    instead of raising ModuleNotFoundError. Idempotent."""
    if isinstance(sys.modules.get("qgis"), types.ModuleType) and getattr(
        sys.modules["qgis"], "_is_shoreline_uncertainty_stub", False
    ):
        return

    qgis_pkg = types.ModuleType("qgis")
    qgis_pkg._is_shoreline_uncertainty_stub = True

    core_mod = types.ModuleType("qgis.core")
    for name, obj in _CORE_EXPORTS.items():
        setattr(core_mod, name, obj)

    pyqt_mod = types.ModuleType("qgis.PyQt")
    qtcore_mod = types.ModuleType("qgis.PyQt.QtCore")
    qtgui_mod = types.ModuleType("qgis.PyQt.QtGui")
    qtwidgets_mod = types.ModuleType("qgis.PyQt.QtWidgets")

    for cls_name in _QT_WIDGET_NAMES:
        setattr(qtwidgets_mod, cls_name, _Stub)
        setattr(qtgui_mod, cls_name, _Stub)
    setattr(qtcore_mod, "Qt", _Stub)
    setattr(qtcore_mod, "pyqtSignal", lambda *a, **k: _Stub())

    qgis_pkg.core = core_mod
    qgis_pkg.PyQt = pyqt_mod
    pyqt_mod.QtCore = qtcore_mod
    pyqt_mod.QtGui = qtgui_mod
    pyqt_mod.QtWidgets = qtwidgets_mod

    sys.modules["qgis"] = qgis_pkg
    sys.modules["qgis.core"] = core_mod
    sys.modules["qgis.PyQt"] = pyqt_mod
    sys.modules["qgis.PyQt.QtCore"] = qtcore_mod
    sys.modules["qgis.PyQt.QtGui"] = qtgui_mod
    sys.modules["qgis.PyQt.QtWidgets"] = qtwidgets_mod

    osgeo_pkg = types.ModuleType("osgeo")
    osgeo_pkg._is_shoreline_uncertainty_stub = True
    gdal_mod = types.ModuleType("osgeo.gdal")
    ogr_mod = types.ModuleType("osgeo.ogr")
    osr_mod = types.ModuleType("osgeo.osr")
    for name in dir(gdal):
        if not name.startswith("_"):
            setattr(gdal_mod, name, getattr(gdal, name))
    for name in dir(ogr):
        if not name.startswith("_"):
            setattr(ogr_mod, name, getattr(ogr, name))
    for name in dir(osr):
        if not name.startswith("_"):
            setattr(osr_mod, name, getattr(osr, name))
    osgeo_pkg.gdal = gdal_mod
    osgeo_pkg.ogr = ogr_mod
    osgeo_pkg.osr = osr_mod

    sys.modules["osgeo"] = osgeo_pkg
    sys.modules["osgeo.gdal"] = gdal_mod
    sys.modules["osgeo.ogr"] = ogr_mod
    sys.modules["osgeo.osr"] = osr_mod
