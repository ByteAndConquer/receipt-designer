# Receipt Designer - Claude Code Guidelines

## Project Overview

Receipt Designer (Receipt Lab) is a PySide6-based GUI application for designing and printing thermal receipt templates. It supports various element types (text, images, barcodes, QR codes, shapes) and multiple printer backends (network, serial, USB).

**Version:** 0.9.5
**Organization:** ByteSized Labs
**License:** MIT

## Project Structure

```
receipt-designer/                  # repo root
├── run_receipt_designer.py        # Standalone launcher script
├── ReceiptDesigner.spec           # PyInstaller build spec
├── receipt_designer_version.txt   # Win32 version-info resource for PyInstaller
├── requirements.txt               # Runtime dependencies
├── requirements-dev.txt           # Dev/test dependencies (pytest)
├── pytest.ini                     # Pytest configuration
├── .gitignore
├── README.md
├── CLAUDE.md
├── LICENSE.md
│
├── receipt_designer/              # Main package
│   ├── __init__.py                # __version__ = "0.9.5"
│   ├── __main__.py                # python -m receipt_designer entrypoint
│   ├── app.py                     # QApplication setup, main(), resource_path()
│   ├── core/                      # Core business logic (no UI dependencies)
│   │   ├── models.py              # Data models: Element, Template, VariableManager, GuideLine, GuideGrid
│   │   ├── commands.py            # QUndoCommand classes for undo/redo support
│   │   ├── render.py              # Scene-to-image rendering
│   │   ├── barcodes.py            # Barcode generation utilities
│   │   └── utils.py               # Path normalization and portable-asset helpers
│   ├── printing/                  # Printer communication
│   │   ├── backends.py            # NetworkBackend, SerialBackend, USBBackend
│   │   ├── worker.py              # Background print worker (ESC/POS + raw socket)
│   │   └── profiles.py            # Printer profiles
│   ├── ui/                        # UI components
│   │   ├── main_window.py         # MainWindow facade
│   │   ├── main_window_impl.py    # Full MainWindow implementation
│   │   ├── items.py               # QGraphicsItem subclasses (GItem, GLineItem, shapes)
│   │   ├── inline_editor.py       # Inline text editor
│   │   ├── layers.py              # Layer panel
│   │   ├── views.py               # RulerView and related view classes
│   │   ├── toolbox.py             # Tool palette
│   │   ├── properties.py          # Properties panel
│   │   └── variables.py           # Variable management panel
│   └── assets/                    # Static assets
│       └── icons/                 # App icons (PNG + ICO in multiple sizes)
│
└── tests/                         # Test suite (pytest, at repo root)
    ├── conftest.py                # Fixtures
    ├── test_variables.py
    ├── test_path_utils.py
    ├── test_template.py
    └── test_ui_autosave_recovery.py  # Qt integration tests (opt-in)
```

## Tech Stack

- **UI Framework:** PySide6 (Qt6 for Python)
- **Barcode Generation:** python-barcode, qrcode, treepoem (advanced 2D symbologies; requires Ghostscript)
- **Image Processing:** Pillow
- **Printer Communication:**
  - Network: raw sockets (port 9100)
  - Serial: pyserial
  - USB: pyusb
  - ESC/POS protocol: python-escpos

## Install

```bash
# Runtime dependencies
pip install -r requirements.txt

# Dev/test dependencies (adds pytest)
pip install -r requirements-dev.txt
```

## Run

From the repo root:

```bash
# Module entrypoint (preferred)
python -m receipt_designer

# Or via the launcher script
python run_receipt_designer.py
```

## Tests

```bash
# Run all unit tests
pytest -v

# Include Qt/GUI integration tests (requires a display or offscreen Qt platform)
# Linux / Git Bash:
RUN_QT_TESTS=1 pytest -v
# PowerShell:
$env:RUN_QT_TESTS="1"; pytest -v
# CMD:
set RUN_QT_TESTS=1 && pytest -v
```

Qt integration tests in `tests/test_ui_autosave_recovery.py` are skipped by default. Set `RUN_QT_TESTS=1` to enable them. The test module sets `QT_QPA_PLATFORM=offscreen` via `os.environ.setdefault` so headless runs work without a display (an existing `QT_QPA_PLATFORM` value takes precedence).

## Build (PyInstaller)

```bash
# From repo root
pyinstaller ReceiptDesigner.spec
```

- Produces a single-file executable at `dist/ReceiptDesigner.exe`.
- Build artifacts go to `build/` and `dist/`.
- The spec bundles `receipt_designer/assets/` into `{_MEIPASS}/assets/` inside the frozen app, matching the path that `app.resource_path()` expects at runtime.
- `receipt_designer_version.txt` is embedded as Win32 version-info metadata.

## Asset Bundling

`app.py` provides `resource_path(rel)` which resolves asset paths in both modes:

| Mode | Base path | Example: `resource_path("assets/icons")` |
|---|---|---|
| Source | `receipt_designer/` (`Path(__file__).parent`) | `receipt_designer/assets/icons/` |
| Frozen | `sys._MEIPASS` | `{_MEIPASS}/assets/icons/` |

The PyInstaller spec maps `receipt_designer/assets/` → `assets/` in the bundle, preserving this structure.

## Architecture Patterns

### Undo/Redo System
All modifications use `QUndoCommand` subclasses from `core/commands.py`:
- `AddItemCmd`, `DeleteItemCmd` - item lifecycle
- `MoveResizeCmd`, `MoveLineCmd`, `ResizeLineCmd` - geometry changes
- `PropertyChangeCmd` - element property modifications
- `GroupItemsCmd`, `UngroupItemsCmd` - grouping operations

### Element Model
`core/models.Element` is the data class representing design elements:
- **Kinds:** `text`, `image`, `qr`, `barcode`, `rect`, `ellipse`, `line`
- **Barcode types:** CODE128, CODE39, EAN13, UPCA, ITF14, PDF417, DATAMATRIX, AZTEC
- **Lock modes:** `none`, `position`, `style`, `full`

### Variable System
Template variables use `{{var:variable_name}}` syntax, resolved by `VariableManager`.
System variables (date, time) are handled separately in `GItem._resolve_text()`.

### Graphics Items
UI items inherit from Qt graphics classes with `ContextMenuMixin`:
- `GItem` - main element rendering (text, images, barcodes)
- `GLineItem`, `GRectItem`, `GEllipseItem`, `GStarItem`, `GDiamondItem`, `GArrowItem` - shapes
- `GuideLineItem`, `GuideGridItem` - design guides

## Key Conventions

### Measurements
- Template dimensions: millimeters (`width_mm`, `height_mm`)
- Element positions: pixels
- Conversion: `px_per_mm = dpi / 25.4`
- Default DPI: 203 (common thermal printer resolution)

### Serialization
Templates serialize to JSON via `to_dict()` / `from_dict()` methods on model classes.

### File Extension
Receipt templates use `.receipt` file extension.

## Printing Backends

| Backend | Dependency | Module | Notes |
|---|---|---|---|
| Network (raw socket) | *(none — stdlib `socket`)* | `printing/backends.py` | Sends raw bytes to port 9100 |
| Serial | `pyserial` | `printing/backends.py` | RS-232 / COM port printers |
| USB | `pyusb` | `printing/backends.py` | Direct USB device communication |
| ESC/POS | `python-escpos` | `printing/worker.py` | High-level thermal printer protocol; wraps Network/Serial/USB |

`treepoem` (in `core/barcodes.py`) adds support for advanced 2D symbologies such as PDF417, DataMatrix, and Aztec. It requires Ghostscript to be installed and on PATH.

## Common Tasks

### Adding a New Element Type
1. Add kind to `Element.kind` in `core/models.py`
2. Implement rendering in `GItem` class (`ui/items.py`)
3. Add toolbox button in `ui/toolbox.py`
4. Add property controls in `ui/properties.py`

### Adding a New Printer Backend
1. Create backend class inheriting `BaseBackend` in `printing/backends.py`
2. Implement `send(data: bytes)` method
3. Add case to `make_backend()` factory function

### Working with Undo/Redo
Always wrap modifications in a `QUndoCommand`:
```python
from receipt_designer.core.commands import PropertyChangeCmd
cmd = PropertyChangeCmd(elem, "font_size", old_value, new_value, "Change font size", item)
undo_stack.push(cmd)
```
