# 🧾 Receipt Designer

**Receipt Designer** is an open-source **PySide6** desktop app for designing and printing **ESC/POS** thermal receipts — made for tinkerers, makers, and developers who want freedom from rigid, proprietary software.

## ✨ Features
- 🎨 **Visual layered editor** for pixel-perfect receipt layouts  
- 🧾 **Barcode & QR code embedding** for scannable designs  
- 🖨️ **Configurable printer profiles** (USB, serial, or network)  
- 🧩 **Modular architecture** — `core`, `ui`, `printing`, `legacy`  
- 📄 **JSON template system** for reproducible, shareable receipts  
- 🧠 **Extensible and script-friendly** — automate, integrate, experiment  

Whether you’re printing daily logs, random fortunes, or a clean monthly bill summary, Receipt Designer gives you the flexibility to explore and build your own workflow.

## 🗂️ Project Structure
```
receipt_designer/
  app.py
  core/
    barcodes.py
    commands.py
    models.py
    render.py
  printing/
    backends.py
    profiles.py
    worker.py
  ui/
    items.py
    layers.py
    main_window_impl.py
    main_window.py
    properties.py
    toolbox.py
    views.py
  legacy/
    receipt_designer_v4.py
  assets/
    Templates/
    icons/
```

## 🚀 Getting Started
```bash
git clone https://github.com/ByteAndConquer/receipt-designer.git
cd receipt-designer
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .            # or: pip install -r requirements.txt
python -m receipt_designer  # launch the app
```

## 🧰 Development Tips
- Run the app directly: `python -m receipt_designer`
- Edit UI or core modules; no build step required
- For PyInstaller builds, see `packaging/pyinstaller/ReceiptDesigner.spec`
- Pull requests welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md)

## 🪶 License
Licensed under the **MIT License** — see [LICENSE](./LICENSE) for details.
