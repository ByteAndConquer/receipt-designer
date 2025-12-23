# 🧾 Receipt Designer

**Receipt Designer** is an open-source **PySide6** desktop application for designing and printing **ESC/POS** thermal receipts — built for tinkerers, makers, and developers who want full creative control without being locked into rigid, proprietary tools.

## ✨ Features
- 🎨 **Visual layered editor** for pixel-perfect receipt layouts  
- 🧾 **Barcode & QR code embedding** for scannable designs  
- 🖨️ **Configurable printer profiles** (USB, Serial, or Network)  
- 🧩 **Modular architecture** — `core`, `ui`, `printing`, `legacy`  
- 📄 **JSON template system** for reproducible, shareable layouts  
- 🧠 **Extensible and script-friendly** — automate, integrate, experiment  

Whether you’re printing daily logs, random fortunes, or a clean monthly bill summary, Receipt Designer is designed to fit into *your* workflow — not force you into someone else’s.

> **Transport status:**  
> Network printing is tested and working. USB and Serial transports are currently experimental and require additional verification and tuning (timeouts, device paths, write/flush behavior). Contributions are welcome.

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

## 🧰 Development Notes
- Run directly via `python -m receipt_designer`
- UI and core modules can be edited without a build step
- PyInstaller configuration lives at `packaging/pyinstaller/ReceiptDesigner.spec`
- Architectural overview: [`docs/architecture.md`](./docs/architecture.md)
- Contributions welcome — see [CONTRIBUTING.md](./CONTRIBUTING.md)

## 📦 Downloads
Prebuilt binaries (Windows) are available on the  
👉 **[GitHub Releases](https://github.com/ByteAndConquer/receipt-designer/releases)** page.

## 🪶 License
Licensed under the **MIT License** — see [LICENSE](./LICENSE) for details.
