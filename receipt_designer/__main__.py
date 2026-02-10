"""
Module entrypoint for `python -m receipt_designer`.

This allows running the application as a module from the repository root:
    python -m receipt_designer
"""
from receipt_designer.app import main

if __name__ == "__main__":
    main()
