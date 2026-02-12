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
├── pyproject.toml                 # Package metadata & dependency spec
├── ReceiptDesigner.spec           # PyInstaller build spec
├── receipt_designer_version.txt   # Win32 version-info resource for PyInstaller
├── requirements.txt               # Runtime dependencies (mirrors pyproject.toml)
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
│   │   ├── main_window.py         # MainWindow facade (thin re-export)
│   │   ├── main_window_impl.py    # MainWindow coordinator (~1,800 lines)
│   │   ├── host_protocols.py      # Typing-only Protocol definitions for mw coupling
│   │   ├── actions.py             # Toolbar/menu/shortcut builder
│   │   ├── persistence.py         # Save/load/autosave/recent-files/asset portability
│   │   ├── presets.py             # Layout preset definitions + fortune-cookie helper
│   │   ├── layout_ops.py          # Align/distribute/group/z-order/lock/nudge/duplicate
│   │   ├── common.py              # Shared tiny helpers (px_per_mm_factor, unpack_margins_mm)
│   │   ├── items.py               # QGraphicsItem subclasses (GItem, GLineItem, shapes)
│   │   ├── inline_editor.py       # Inline text editor
│   │   ├── layers.py              # Layer panel
│   │   ├── views.py               # RulerView and related view classes
│   │   ├── toolbox.py             # Tool palette
│   │   ├── properties.py          # Properties panel
│   │   ├── variables.py           # Variable management panel
│   │   ├── canvas/                # Scene/view creation and paper management
│   │   │   └── controller.py      # build_scene_view, setup_inline_editor, update_paper
│   │   ├── docks/                 # Dock widget builders
│   │   │   ├── __init__.py        # build_docks orchestrator + update_view_menu
│   │   │   ├── layers_dock.py     # build_layers_dock
│   │   │   ├── properties_dock.py # build_properties_dock
│   │   │   └── variables_dock.py  # build_variables_dock
│   │   └── dialogs/               # Standalone dialog functions/classes
│   │       ├── __init__.py        # Re-export hub
│   │       ├── print_preview.py   # PrintPreviewDialog
│   │       ├── keyboard_shortcuts.py # show_keyboard_shortcuts_dialog
│   │       ├── duplicate_offset.py   # show_duplicate_offset_dialog
│   │       └── printer_config.py     # show_printer_config_dialog
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
- **Barcode Generation:** python-barcode, qrcode, treepoem (optional; advanced 2D symbologies; requires Ghostscript)
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

# Optional: advanced 2D barcodes (also needs Ghostscript on PATH)
pip install treepoem
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

### UI Module Architecture

The `ui/` package follows a **coordinator + extracted-module** pattern. `MainWindow` (in `main_window_impl.py`) is the central coordinator; cohesive feature blocks are extracted into standalone modules that receive `mw` (the MainWindow instance) as their first argument.

#### Module Responsibilities

| Module | What lives here |
|---|---|
| `main_window_impl.py` | MainWindow class — wires everything together, owns Qt lifecycle (`__init__`, `closeEvent`), selection sync, and short methods that don't justify their own module. ~1,800 lines. |
| `actions.py` | `build_toolbars_and_menus(mw)` — creates all toolbars, menus, keyboard shortcuts, and connects them to `mw` slots. |
| `canvas/controller.py` | `build_scene_view(mw)`, `setup_inline_editor(mw)`, `update_paper(mw)` — QGraphicsScene/View creation, paper-size changes, inline text-editing overlay. |
| `docks/` | `build_docks(mw)`, `update_view_menu(mw)` + per-dock builders (`layers_dock`, `properties_dock`, `variables_dock`). Creates and wires all dock widgets. |
| `dialogs/` | Standalone dialog functions/classes (`PrintPreviewDialog`, `show_printer_config_dialog`, etc.). These accept **primitive data** (QWidget parent, QImage, dict) — they do *not* touch `mw` attributes. |
| `persistence.py` | Save, load, save-as, autosave, crash recovery, recent-files menu, asset portability (18 functions). |
| `presets.py` | Layout preset definitions, `apply_preset(mw, name)`, fortune-cookie API helper. |
| `layout_ops.py` | Align, distribute, group/ungroup, z-order, lock/unlock, hide/show, baseline snap, nudge, duplicate, delete (13 functions). |
| `common.py` | Tiny shared helpers (`px_per_mm_factor`, `unpack_margins_mm`) used by 2+ UI modules to avoid copy-paste. |
| `host_protocols.py` | Typing-only `Protocol` classes that document which `mw` attributes each module requires (see *Protocol Guardrails* below). |

#### The `mw` Rule

> **Extracted modules receive `mw` as a parameter — they must never `import main_window_impl`.**

This avoids circular imports and keeps the dependency arrow one-way:

```
main_window_impl  ──imports──►  persistence / presets / layout_ops / actions / …
       │                                     │
       └──── passes self as mw ─────────────►┘
```

Each extracted module can import from `core/`, `printing/`, or sibling UI modules (`items`, `layers`, `views`, etc.), but **not** from `main_window_impl` or `main_window`.

#### Where to Put New Features (Decision Guide)

| If the new code… | Put it in… |
|---|---|
| Builds toolbars, menus, or shortcuts | `actions.py` |
| Creates/configures scene, view, or paper | `canvas/controller.py` |
| Creates/wires dock widgets | `docks/` |
| Is a standalone dialog (no `mw` attribute access) | `dialogs/` |
| Handles save/load/autosave/recent-files | `persistence.py` |
| Adds or modifies layout presets | `presets.py` |
| Performs align/distribute/group/z-order/lock/nudge ops | `layout_ops.py` |
| Is a short (< 15 line) method tightly coupled to MainWindow state | Keep it in `main_window_impl.py` |
| Doesn't fit any of the above but is > ~50 lines | Create a new `ui/<name>.py` module; follow the `mw` rule |

#### Protocol Guardrails

`host_protocols.py` defines `typing.Protocol` classes that declare the `mw` attributes each module actually uses. These are **static-only** (guarded by `TYPE_CHECKING`) — they add zero runtime cost.

| Protocol | Used by |
|---|---|
| `CanvasHost` | `canvas/controller.py` |
| `DocksHost` | `docks/__init__.py`, `docks/layers_dock.py`, `docks/properties_dock.py`, `docks/variables_dock.py` |
| `ActionsHost` | `actions.py` |
| `PersistenceHost` | `persistence.py` |
| `PresetsHost` | `presets.py` |
| `LayoutHost` | `layout_ops.py` |

If you add a new attribute to MainWindow that an extracted module needs, add it to the matching Protocol first. This catches attribute-name drift at type-check time (e.g., via `mypy` or `pyright`).

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

`treepoem` (in `core/barcodes.py`) optionally adds support for advanced 2D symbologies such as PDF417, DataMatrix, and Aztec. It is not included in the default dependencies. Install it separately (`pip install treepoem`). It also requires Ghostscript to be installed and on PATH.

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
