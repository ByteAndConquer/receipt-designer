# Contributing to Receipt Designer

Thanks for your interest in contributing! This guide covers getting a development
environment running, making changes, and submitting them.

## Prerequisites

- Python 3.10 or newer
- Git
- (Optional) [Ghostscript](https://ghostscript.com/) on PATH — only needed for
  advanced 2D barcode symbologies via treepoem

## Getting the code

1. Fork the repository on GitHub.
2. Clone your fork:

   ```bash
   git clone git@github.com:<your-username>/receipt-designer.git
   cd receipt-designer
   ```

3. (Optional) Add the upstream remote so you can pull future changes:

   ```bash
   git remote add upstream git@github.com:<upstream-owner>/receipt-designer.git
   ```

## Setting up a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (CMD):**

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
```

## Installing dependencies

```bash
python -m pip install -r requirements.txt        # runtime
python -m pip install -r requirements-dev.txt    # adds pytest
```

There is no `pyproject.toml` or `setup.py`; the project is run directly from
source, not installed as an editable package.

## Running the app

From the repo root:

```bash
python -m receipt_designer             # preferred
# or
python run_receipt_designer.py
```

## Running tests

```bash
python -m pytest -v
```

### Qt integration tests

The tests in `tests/test_ui_autosave_recovery.py` are **skipped by default**
because they require PySide6 and a Qt platform. Enable them by setting
`RUN_QT_TESTS=1`:

**Linux / Git Bash:**

```bash
RUN_QT_TESTS=1 python -m pytest -v
```

**PowerShell:**

```powershell
$env:RUN_QT_TESTS="1"; python -m pytest -v
```

**CMD:**

```cmd
set RUN_QT_TESTS=1 && python -m pytest -v
```

When enabled, the test module automatically sets `QT_QPA_PLATFORM=offscreen`
(unless you have already set it), so a physical display is not required.

## Building the executable

```bash
pyinstaller ReceiptDesigner.spec
```

This produces a single-file executable at `dist/ReceiptDesigner.exe`.
Build artifacts land in `build/` and `dist/`.

## Linting / formatting

There are no project-wide linter or formatter requirements at this time. If you
use one locally (e.g., ruff, black), that's fine — just avoid including unrelated
reformatting in your PR.

## Submitting changes

1. Create a feature branch from `main`.
2. Make your changes. Include or update tests where appropriate.
3. Run `python -m pytest -v` and confirm all tests pass.
4. Push to your fork and open a pull request with a clear description of the change.

## Code style notes

- All state mutations go through `QUndoCommand` subclasses (see `core/commands.py`).
- Imports of optional third-party libraries (Pillow, python-barcode, pyserial, etc.)
  are wrapped in `try/except` so the app can still launch when they are missing.
- See `CLAUDE.md` for architecture details, element kinds, and the full project
  structure.
