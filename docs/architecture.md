# Architecture

Receipt Designer is a modular PySide6 desktop application for designing and printing ESC/POS receipts. The codebase is structured to keep **UI**, **business logic**, and **printing backends** separated so contributors can extend or replace parts without touching the whole system.

> **Transport status:** Network printing is tested and working. USB and Serial transports are present but require verification and adjustments (timeouts, device paths, write/flush behavior).

---

## Goals

- **Separation of concerns:** UI code should not contain printing/transport specifics.
- **Extensibility:** Add new receipt items, render behaviors, or transports without rewriting the app.
- **Workflow friendliness:** Support repeatable layouts via JSON templates and reusable assets.
- **Safe migration path:** Keep legacy fallback until the modular implementation is complete.

---

## Repository layout

High-level structure (simplified):

```
receipt_designer/
  app.py
  __main__.py
  core/
  printing/
  ui/
  legacy/
  assets/
packaging/
  pyinstaller/
```

### `receipt_designer/app.py`
Application entry point and bootstrapping logic. This is where the Qt app is started and the main window is created.

### `receipt_designer/__main__.py`
Allows launching via:

```bash
python -m receipt_designer
```

---

## Modules

### 1) `receipt_designer/core/`
**What it is:** The “business logic” layer.  
**What it should contain:** models, layout primitives, rendering, and data transformations that do **not** depend on Qt widgets or transport I/O.

Typical responsibilities:
- Receipt model representation (items, layout, style)
- Render pipeline / layout calculation
- Barcode/QR generation helpers
- ESC/POS command generation (when it’s pure/serializable)

Key files (may evolve):
- `models.py` — core data structures
- `render.py` — layout/render logic
- `barcodes.py` — barcode & QR helpers

**Rule of thumb:** If it can be unit tested without launching a UI, it belongs here.

---

### 2) `receipt_designer/ui/`
**What it is:** The PySide6 interface layer.  
**What it should contain:** windows, widgets, scene/canvas rendering, property panels, and event handling.

Typical responsibilities:
- Main window composition (menus, panels, canvas view)
- Layer list UI and item manipulation
- Property editing panels
- Drag/drop, selection, snapping, etc.

Notes:
- `main_window.py` is often used as a façade so the app can evolve the implementation without breaking imports.
- UI should call into `core` for logic, not reimplement it.

---

### 3) `receipt_designer/printing/`
**What it is:** Output/transport layer.  
**What it should contain:** printer profiles, spool/worker execution, and transport implementations (network, USB, serial).

Typical responsibilities:
- Converting a rendered receipt into printer-ready bytes/commands
- Managing print jobs (queueing, cancellation, progress updates)
- Talking to printers through different transports

Files you’ll likely touch:
- `backends.py` — transport/backends (network/usb/serial)
- `profiles.py` — printer profile config & defaults
- `worker.py` — print job execution, threading, status callbacks

**Transport notes**
- **Network:** validated and expected to work.
- **USB/Serial:** present but needs testing + tuning (timeouts, device discovery, write/flush).

---

### 4) `receipt_designer/legacy/`
**What it is:** The original monolithic implementation kept for reference and fallback during refactor.  
**What it should contain:** Minimal additions. Ideally, no new features should be implemented here.

Plan:
- Incrementally migrate logic from `legacy/receipt_designer_v4.py` into `core`, `ui`, and `printing`.
- Remove fallback imports once parity is reached.
- Delete legacy module as part of a later milestone (e.g., `v1.0.0`).

---

### 5) `receipt_designer/assets/`
Static resources:
- Templates (JSON)
- Icons
- Sample assets

Guidelines:
- Keep templates small and readable.
- Prefer versioned template examples (e.g., `templates/bills/monthly_bill_v1.json`).

---

## Runtime flow (conceptual)

1. **Launch**
   - `receipt_designer/app.py` initializes Qt application and main window.

2. **Design session**
   - UI loads a template or starts blank.
   - UI events mutate receipt structures.
   - `core` is used for model updates and rendering logic.

3. **Print**
   - UI initiates a print job with a selected printer profile.
   - `printing/worker.py` creates and executes the job.
   - A backend in `printing/backends.py` sends bytes to the printer via the chosen transport.
   - Status updates are surfaced back to the UI.

---

## Adding new functionality

### Add a new receipt item type
- Define a model representation in `core/models.py` (or a dedicated module).
- Update render logic in `core/render.py`.
- Add UI controls in `ui/` (toolbox, properties panel, layer list integration).
- Add/adjust template serialization fields as needed.

### Add a new transport (e.g., Bluetooth)
- Add backend implementation in `printing/backends.py` (or a new module if it grows).
- Extend `printing/profiles.py` to support configuration for the transport.
- Ensure `printing/worker.py` can route to it.
- Document platform prerequisites (drivers, permissions, pairing, etc.).

---

## Testing strategy (suggested)

- **Unit tests (core):**
  - Rendering output for known layouts
  - Barcode/QR generation helpers
  - ESC/POS command generation for common cases
- **Integration tests (printing):**
  - Mock backends to validate bytes emitted
  - Optional “golden file” command output comparisons
- **Manual testing (UI):**
  - Template load/save
  - Item editing workflows
  - Print job cancellation and errors

---

## Packaging & releases

- **PyInstaller** configuration lives in:
  - `packaging/pyinstaller/ReceiptDesigner.spec`
- Recommended: distribute binaries via **GitHub Releases** (not committed into git).
- Include SHA-256 hashes in release notes for verification.

---

## Conventions & guidelines

- Prefer small, testable functions in `core/`.
- Avoid printing I/O in UI code.
- Keep legacy file changes to a minimum.
- When adding features, update:
  - README (user-facing)
  - `docs/architecture.md` (developer-facing) if structure changes
  - Changelog/release notes when publishing builds
