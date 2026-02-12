# Architecture — Receipt Designer UI

This document describes the structure and rules of the `receipt_designer/ui/` package. It is intended for contributors adding features or refactoring code.

## UI Module Responsibilities

| Module | Responsibility |
|---|---|
| `main_window_impl.py` | Central coordinator. Owns `__init__`, `closeEvent`, selection sync, and short methods that don't justify their own module (~1,800 lines). |
| `actions.py` | `build_toolbars_and_menus(mw)` — creates all toolbars, menus, keyboard shortcuts, and connects them to `mw` slots. |
| `canvas/controller.py` | `build_scene_view(mw)`, `setup_inline_editor(mw)`, `update_paper(mw)` — QGraphicsScene/View creation, paper-size changes, inline text-editing overlay. |
| `docks/__init__.py` | `build_docks(mw)`, `update_view_menu(mw)` — orchestrates per-dock builders and wires cross-dock signals (selection sync, variable updates). |
| `docks/layers_dock.py` | Builds the Layers dock widget. |
| `docks/properties_dock.py` | Builds the Properties dock widget. |
| `docks/variables_dock.py` | Builds the Variables dock widget. |
| `dialogs/` | Standalone dialog functions/classes (`PrintPreviewDialog`, `show_printer_config_dialog`, etc.). These accept **primitive data** (QWidget parent, QImage, dict) and do *not* access `mw` attributes. |
| `persistence.py` | Save, load, save-as, autosave, crash recovery, recent-files menu, asset-path portability (18 functions). |
| `presets.py` | Layout preset definitions, `apply_preset(mw, name)`, fortune-cookie API helper. |
| `layout_ops.py` | Align, distribute, group/ungroup, z-order, lock/unlock, hide/show, baseline snap, nudge, duplicate, delete (13 functions). |
| `common.py` | Tiny shared helpers (`px_per_mm_factor`, `unpack_margins_mm`) used by 2+ UI modules. |

## Dependency Rule

Extracted modules receive `mw` (the MainWindow instance) as a parameter — **they must never import `main_window_impl`**.

```
main_window_impl  ──imports──►  persistence / presets / layout_ops / actions / …
       │                                     │
       └──── passes self as mw ─────────────►┘
```

- `main_window_impl` may import any extracted module.
- Extracted modules may import from `core/`, `printing/`, or sibling UI modules (`items`, `layers`, `views`, etc.).
- Extracted modules must **not** import from `main_window_impl` or `main_window`.

This one-way dependency avoids circular imports and keeps the modules testable in isolation.

## Guardrails

### Typing Protocols (`host_protocols.py`)

`host_protocols.py` defines `typing.Protocol` classes that declare the `mw` attributes each module actually uses. They are **static-only** (guarded by `TYPE_CHECKING`) and add zero runtime cost.

| Protocol | Used by |
|---|---|
| `CanvasHost` | `canvas/controller.py` |
| `DocksHost` | `docks/__init__.py`, `docks/layers_dock.py`, `docks/properties_dock.py`, `docks/variables_dock.py` |
| `ActionsHost` | `actions.py` |
| `PersistenceHost` | `persistence.py` |
| `PresetsHost` | `presets.py` |
| `LayoutHost` | `layout_ops.py` |

If you add a new attribute to MainWindow that an extracted module needs, add it to the matching Protocol first. This catches attribute-name drift at type-check time (e.g., via `mypy` or `pyright`).

### UI Smoke Tests (`tests/test_ui_smoke.py`)

Smoke tests verify import health, MainWindow construction, menu/toolbar wiring, and dock widget placement. They run headless (`QT_QPA_PLATFORM=offscreen`) and are gated behind `RUN_QT_TESTS=1`:

```bash
RUN_QT_TESTS=1 pytest tests/test_ui_smoke.py -v
```

## Where to Put New Code

| If the new code… | Put it in… |
|---|---|
| Builds toolbars, menus, or shortcuts | `actions.py` |
| Creates or configures scene, view, or paper | `canvas/controller.py` |
| Creates or wires dock widgets | `docks/` |
| Is a standalone dialog (no `mw` attribute access) | `dialogs/` |
| Handles save / load / autosave / recent-files | `persistence.py` |
| Adds or modifies layout presets | `presets.py` |
| Performs align / distribute / group / z-order / lock / nudge | `layout_ops.py` |
| Is a short (< 15 line) method tightly coupled to MainWindow state | Keep it in `main_window_impl.py` |
| Doesn't fit the above but is > ~50 lines | Create a new `ui/<name>.py` module; follow the `mw` rule |
