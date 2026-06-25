"""Tests for processing_provider.py's ShorelineUncertaintyProvider, and for
plugin.py's registration/unregistration of it via QgsApplication's stub
processing registry (see qgis_stub.py's _ProcessingRegistry/QgsApplication
stand-ins -- addProvider calls loadAlgorithms() immediately, mirroring real
QGIS's registration-time behavior).
"""
from __future__ import annotations

from qgis.core import QgsApplication

from shoreline_uncertainty_qgis.processing_algorithm import RunAnalysisAlgorithm, WaterLevelLookupAlgorithm
from shoreline_uncertainty_qgis.processing_provider import ShorelineUncertaintyProvider


def test_provider_id_and_name():
    provider = ShorelineUncertaintyProvider()
    assert provider.id() == "shoreline_uncertainty"
    assert provider.name() == "Shoreline Change Uncertainty"


def test_provider_load_algorithms_registers_both_algorithms():
    provider = ShorelineUncertaintyProvider()
    provider.loadAlgorithms()
    algs = provider.algorithms()
    assert len(algs) == 2
    assert any(isinstance(a, RunAnalysisAlgorithm) for a in algs)
    assert any(isinstance(a, WaterLevelLookupAlgorithm) for a in algs)


def test_plugin_registers_provider_with_processing_registry():
    from shoreline_uncertainty_qgis.plugin import ShorelineUncertaintyPlugin

    plugin = ShorelineUncertaintyPlugin(iface=None)
    plugin._register_processing_provider()

    registry = QgsApplication.processingRegistry()
    assert plugin._provider in registry.providers()
    assert len(plugin._provider.algorithms()) == 2

    plugin.unload()
    assert plugin._provider not in registry.providers()
