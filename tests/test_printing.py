"""
Tests for printing exceptions, dry-run backend, and render pipeline.

These tests run without real printers, serial ports, or USB devices.
They verify:
  1) The render pipeline runs end-to-end on a tiny template.
  2) The printing worker can run in dry-run mode without touching hardware.
  3) Errors are mapped consistently via printing/exceptions.py.
"""
from __future__ import annotations

import os
import pytest

# Qt offscreen so these tests work in headless CI
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtWidgets

from receipt_designer.core.models import Template, Element
from receipt_designer.core.render import scene_to_image
from receipt_designer.printing.backends import (
    BaseBackend,
    DryRunBackend,
    make_backend,
)
from receipt_designer.printing.exceptions import (
    PrintError,
    PrinterConnectionError,
    PrinterConfigError,
    PrintJobError,
    map_exception,
    friendly_message,
)
from receipt_designer.printing.worker import PrinterWorker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Ensure a QApplication exists for the module (needed for QGraphicsScene)."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


@pytest.fixture()
def tiny_template():
    """A minimal 20x10mm template with one text element."""
    t = Template(width_mm=20.0, height_mm=10.0, dpi=203)
    t.elements.append(
        Element(kind="text", x=5, y=5, w=50, h=20, text="Hello")
    )
    return t


@pytest.fixture()
def tiny_scene(qapp, tiny_template):
    """QGraphicsScene sized to tiny_template."""
    scene = QtWidgets.QGraphicsScene()
    scene.setSceneRect(
        0, 0,
        tiny_template.width_px,
        tiny_template.height_px,
    )
    return scene


# ---------------------------------------------------------------------------
# 1) Render pipeline end-to-end
# ---------------------------------------------------------------------------

class TestRenderPipeline:
    def test_scene_to_image_returns_valid_qimage(self, tiny_scene):
        """scene_to_image produces a non-null QImage with correct dimensions."""
        img = scene_to_image(tiny_scene, scale=1.0)
        assert not img.isNull()
        assert img.width() == int(tiny_scene.sceneRect().width())
        assert img.height() == int(tiny_scene.sceneRect().height())

    def test_scene_to_image_with_scale(self, tiny_scene):
        """Scaled rendering produces proportionally sized output."""
        img = scene_to_image(tiny_scene, scale=2.0)
        expected_w = int(tiny_scene.sceneRect().width() * 2.0)
        expected_h = int(tiny_scene.sceneRect().height() * 2.0)
        assert img.width() == expected_w
        assert img.height() == expected_h

    def test_scene_to_image_white_background(self, tiny_scene):
        """Rendered image has a white background (pixel at 0,0)."""
        img = scene_to_image(tiny_scene, scale=1.0)
        color = QtGui.QColor(img.pixel(0, 0))
        assert color.red() == 255
        assert color.green() == 255
        assert color.blue() == 255


# ---------------------------------------------------------------------------
# 2) Dry-run backend and worker
# ---------------------------------------------------------------------------

class TestDryRunBackend:
    def test_dry_run_backend_captures_bytes(self):
        """DryRunBackend.send() accumulates data without errors."""
        backend = DryRunBackend()
        backend.send(b"\x1b\x40")
        backend.send(b"hello")
        assert len(backend.sent_chunks) == 2
        assert backend.total_bytes == 7  # 2 + 5

    def test_make_backend_dry_run(self):
        """make_backend returns DryRunBackend for interface='dry_run'."""
        backend = make_backend({"interface": "dry_run"})
        assert isinstance(backend, DryRunBackend)

    def test_worker_dry_run_feed(self, qapp):
        """PrinterWorker in dry-run mode executes 'feed' without hardware."""
        worker = PrinterWorker(
            action="feed",
            payload={"config": {"cut_mode": "partial"}},
            dry_run=True,
        )
        # Run synchronously (call run() directly instead of start())
        worker.run()
        assert worker.dry_run_backend is not None
        assert worker.dry_run_backend.total_bytes > 0

    def test_worker_dry_run_cut(self, qapp):
        """PrinterWorker in dry-run mode executes 'cut' without hardware."""
        worker = PrinterWorker(
            action="cut",
            payload={"config": {"cut_mode": "full"}},
            dry_run=True,
        )
        worker.run()
        assert worker.dry_run_backend is not None
        assert worker.dry_run_backend.total_bytes > 0

    def test_worker_dry_run_print(self, qapp):
        """PrinterWorker in dry-run mode executes 'print' without hardware."""
        worker = PrinterWorker(
            action="print",
            payload={"config": {"cut_mode": "partial"}},
            dry_run=True,
        )
        worker.run()
        assert worker.dry_run_backend is not None
        assert worker.dry_run_backend.total_bytes > 0


# ---------------------------------------------------------------------------
# 3) Exception mapping
# ---------------------------------------------------------------------------

class TestExceptionMapping:
    def test_connection_refused_maps_to_connection_error(self):
        exc = ConnectionRefusedError("refused")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConnectionError)
        assert mapped.__cause__ is exc
        assert "refused" in str(mapped).lower() or "powered on" in str(mapped).lower()

    def test_timeout_maps_to_connection_error(self):
        exc = TimeoutError("timed out")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConnectionError)
        assert "timed out" in str(mapped).lower()

    def test_connection_reset_maps_to_connection_error(self):
        exc = ConnectionResetError("reset")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConnectionError)

    def test_os_error_maps_to_connection_error(self):
        exc = OSError("network unreachable")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConnectionError)

    def test_value_error_maps_to_config_error(self):
        exc = ValueError("bad value")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConfigError)

    def test_runtime_not_installed_maps_to_config_error(self):
        exc = RuntimeError("pyserial not installed")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConfigError)

    def test_runtime_unknown_interface_maps_to_config_error(self):
        exc = RuntimeError("Unknown interface: foo")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrinterConfigError)

    def test_generic_exception_maps_to_job_error(self):
        exc = RuntimeError("something weird happened")
        mapped = map_exception(exc)
        assert isinstance(mapped, PrintJobError)

    def test_print_error_passes_through(self):
        """A PrintError subclass is returned unchanged."""
        exc = PrintJobError("already mapped")
        mapped = map_exception(exc)
        assert mapped is exc

    def test_friendly_message_returns_string(self):
        msg = friendly_message(ConnectionRefusedError("nope"))
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_make_backend_unknown_interface_raises_config_error(self):
        """make_backend raises PrinterConfigError for unknown interfaces."""
        with pytest.raises(PrinterConfigError):
            make_backend({"interface": "carrier_pigeon"})

    def test_hierarchy(self):
        """All specific errors are subclasses of PrintError."""
        assert issubclass(PrinterConnectionError, PrintError)
        assert issubclass(PrinterConfigError, PrintError)
        assert issubclass(PrintJobError, PrintError)
        assert issubclass(PrintError, Exception)
