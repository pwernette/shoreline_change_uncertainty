"""Tests for plugin.py's run() method: the UI-wiring half of task #76
("wire dialog to algorithm, load results into map canvas"). The actual
run-and-load logic (runner.execute_run_config) is tested directly in
test_runner_qgis.py; here we only exercise run()'s own control flow --
open the dialog, bail out if it wasn't accepted, call execute_run_config if
it was, and show a message box on success/failure -- using a fake dialog
and a fake QMessageBox (qgis_stub.py's real QMessageBox is an inert _Stub
that swallows every call, so it can't be asserted against directly; this
fake one records calls instead).

A real Qt event loop can't be driven headlessly in this sandbox (see
test_dialog_qgis.py's own module docstring), so dialog.exec_()/the dialog
class itself are monkeypatched rather than driven for real.
"""
from __future__ import annotations

import pytest

import surf_qgis.dialog as dialog_module
from surf_qgis.plugin import SURFPlugin


class _FakeIface:
    def mainWindow(self):
        return None


class _FakeMessageBox:
    """Records information()/critical() calls instead of swallowing them,
    so tests can assert on what plugin.py's run() actually reported to the
    user."""

    info_calls: list = []
    critical_calls: list = []

    @classmethod
    def reset(cls):
        cls.info_calls = []
        cls.critical_calls = []

    @staticmethod
    def information(parent, title, text):
        _FakeMessageBox.info_calls.append((title, text))

    @staticmethod
    def critical(parent, title, text):
        _FakeMessageBox.critical_calls.append((title, text))


def _make_fake_dialog(run_config):
    class _FakeDialog:
        def __init__(self, parent=None):
            self.parent = parent
            self.run_config = run_config

        def exec_(self):
            pass

    return _FakeDialog


@pytest.fixture(autouse=True)
def _patch_message_box(monkeypatch):
    _FakeMessageBox.reset()
    monkeypatch.setattr("qgis.PyQt.QtWidgets.QMessageBox", _FakeMessageBox)
    yield
    _FakeMessageBox.reset()


def test_run_does_nothing_when_dialog_not_accepted(monkeypatch):
    monkeypatch.setattr(dialog_module, "SURFDialog", _make_fake_dialog(None))

    def _fail_if_called(*a, **k):
        raise AssertionError("execute_run_config should not be called when the dialog was canceled")

    monkeypatch.setattr("surf_qgis.runner.execute_run_config", _fail_if_called)

    plugin = SURFPlugin(iface=_FakeIface())
    plugin.run()

    assert _FakeMessageBox.info_calls == []
    assert _FakeMessageBox.critical_calls == []


def test_run_executes_and_reports_success_when_dialog_accepted(monkeypatch):
    sentinel_run_config = object()
    monkeypatch.setattr(dialog_module, "SURFDialog", _make_fake_dialog(sentinel_run_config))

    captured = {}

    def _fake_execute_run_config(run_config):
        captured["run_config"] = run_config
        return {"output_dir": "/tmp/out", "layers": [object(), object()]}

    monkeypatch.setattr(
        "surf_qgis.runner.execute_run_config", _fake_execute_run_config
    )

    plugin = SURFPlugin(iface=_FakeIface())
    plugin.run()

    assert captured["run_config"] is sentinel_run_config
    assert len(_FakeMessageBox.info_calls) == 1
    title, text = _FakeMessageBox.info_calls[0]
    assert "2 layer" in text
    assert "/tmp/out" in text
    assert _FakeMessageBox.critical_calls == []


def test_run_reports_failure_when_execute_run_config_raises(monkeypatch):
    monkeypatch.setattr(dialog_module, "SURFDialog", _make_fake_dialog(object()))

    def _raise(*a, **k):
        raise RuntimeError("pipeline blew up")

    monkeypatch.setattr("surf_qgis.runner.execute_run_config", _raise)

    plugin = SURFPlugin(iface=_FakeIface())
    plugin.run()  # must not raise -- the failure is reported via QMessageBox, not propagated

    assert _FakeMessageBox.info_calls == []
    assert len(_FakeMessageBox.critical_calls) == 1
    title, text = _FakeMessageBox.critical_calls[0]
    assert "pipeline blew up" in text


def test_run_shows_placeholder_message_when_dialog_module_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        # `from .dialog import X` inside plugin.py resolves to __import__("dialog", ..., level=1),
        # not the fully-dotted module name -- match on the bare name actually passed.
        if name in ("dialog", "surf_qgis.dialog"):
            raise ImportError("dialog not built yet")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    plugin = SURFPlugin(iface=_FakeIface())
    plugin.run()

    assert len(_FakeMessageBox.info_calls) == 1
    assert "hasn't been built yet" in _FakeMessageBox.info_calls[0][1]
