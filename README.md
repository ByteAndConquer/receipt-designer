# Receipt Designer – Refactor Scaffold

This scaffold breaks the monolith into a package layout. It **does not** change runtime behavior yet:
`ui/main_window.py` tries to import the extracted `MainWindow`, and falls back to `legacy/receipt_designer_v4.py` if needed.

## Structure

```
receipt_designer/
  app.py
  core/
    models.py
    commands.py
    render.py
    barcodes.py
  printing/
    backends.py
    worker.py
  ui/
    items.py
    layers.py
    views.py
    main_window_impl.py
    main_window.py        # Facade
  legacy/
    receipt_designer_v4.py  # Original monolith
  assets/
```

## Next steps (suggested)
1. Incrementally move logic from `legacy/receipt_designer_v4.py` into the above modules.
2. Update imports in `ui/main_window_impl.py` to use `core.*`, `printing.*`, and `ui.*` modules.
3. Remove legacy fallback once `MainWindow` exists in `ui/main_window_impl.py`.
4. Add unit tests for `core/barcodes.py` and `core/render.py`.
5. Consider adding a CLI: `python -m receipt_designer.app`.

## License

This project is licensed under the MIT License.  
See the [LICENSE](./LICENSE) file for details.

