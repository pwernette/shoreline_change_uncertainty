"""QGIS plugin entry point.

QGIS imports this package and calls `classFactory(iface)` to get the plugin
object -- this is the one function QGIS's plugin loader requires to exist
here. Everything else lives in plugin.py so that module can be imported and
unit-tested (against the qgis_plugin/tests stub) without going through the
plugin-loading machinery itself.
"""
from __future__ import annotations


def classFactory(iface):  # noqa: N802 -- name required by QGIS's plugin loader
    from .plugin import ShorelineUncertaintyPlugin

    return ShorelineUncertaintyPlugin(iface)
