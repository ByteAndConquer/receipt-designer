# Receipt Designer

A visual template editor for thermal receipts and labels. Built with PySide6, it lets you design layouts with text, images, barcodes, and shapes, then print to ESC/POS-compatible printers over network, USB, or serial connections.

## Key Capabilities

### Template Variables
- Insert dynamic content using `{{var:variable_name}}` syntax for user-defined variables
- Manage variables in the **Variables panel**—values are saved with the template
- Built-in system variables: `{{date}}`, `{{time}}`, `{{datetime}}`, `{{year}}`, `{{month}}`, `{{month_name}}`, `{{day}}`, `{{weekday}}`, `{{hour}}`, `{{minute}}`, `{{second}}`

### Images
- Drag images into your template from anywhere on disk
- **Portable paths**: Images inside the template folder are stored as relative paths, so you can move the folder and images still load
- Images outside the template folder remain absolute
- Missing images display a placeholder instead of causing errors

### Autosave & Crash Recovery
- Unsaved work is periodically auto-saved to a temporary file
- Writes are atomic (`.tmp` file first, then replace) to avoid corruption
- On next launch after a crash, you're prompted to restore your work

### Printer Profiles
- Save multiple printer configurations (network, USB, serial)
- Switch between profiles from the toolbar
- The active profile is remembered by name across sessions

### Recent Files
- Tracks recently opened templates
- Normalizes paths to avoid duplicates from casing or slash differences
- Prompts to remove entries when the file no longer exists

## Quick Start

**Requirements**: Python 3.10+

```bash
# Install all runtime dependencies
pip install -r requirements.txt

# Run the application
python -m receipt_designer
# or
python run_receipt_designer.py
```

For development (adds pytest):

```bash
pip install -r requirements-dev.txt
```

## Tests

```bash
# Unit tests
pytest -v

# Include Qt/GUI integration tests
# PowerShell:
$env:RUN_QT_TESTS="1"; pytest -v
# CMD:
set RUN_QT_TESTS=1 && pytest -v
```

## Build

```bash
pyinstaller ReceiptDesigner.spec
```

Produces a single-file executable at `dist/ReceiptDesigner.exe`.

## How It Works

Templates are JSON files containing page dimensions, element definitions (text, image, barcode, QR, shapes), and variable bindings. When you print, the template is rendered to a bitmap and sent to the configured printer backend.

Supported backends:
- **Network** — raw socket to port 9100
- **USB** — direct via pyusb
- **Serial** — RS-232 via pyserial
- **ESC/POS** — high-level thermal printer protocol via python-escpos

Barcode generation uses python-barcode (1D) and qrcode (QR). Advanced 2D symbologies (PDF417, DataMatrix, Aztec) use treepoem, which requires [Ghostscript](https://ghostscript.com/) installed and on PATH.

## Data & Persistence

| Data | Location |
|------|----------|
| Templates | User-chosen `.json` files |
| Autosave | OS temp directory: `receipt_designer_autosave.json` |
| Printer profiles | QSettings key: `printer/profiles_json` |
| Active profile | QSettings key: `printer/active_profile_name` |
| Recent files | QSettings key: `recent_files` |

> **Note**: The autosave file may include a `_autosave_original_path` key for internal recovery purposes. This key is never written to normal saved templates.

## Quick Smoke Tests

1. **Portable images** — Save a template in a folder with an `assets/` subfolder containing an image. Move the entire folder elsewhere. Reopen the template; the image should still display.

2. **Autosave recovery** — Make changes, wait for "Auto-saved" in the status bar, force-close the app, then relaunch. You should be prompted to restore.

3. **Profile persistence** — Select a printer profile, close the app, reopen. The same profile should still be selected.

4. **Recent files deduplication** — Open the same template using different path casings (e.g., `C:\Foo\template.json` vs `c:\foo\TEMPLATE.json`). Only one entry should appear in the Recent Files menu.

## License

MIT — see [LICENSE.md](./LICENSE.md) for details.
