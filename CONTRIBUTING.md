# Contributing

Thanks for helping improve Receipt Designer!

## Dev Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -U pip
pip install -e .[dev] || pip install -r requirements.txt
```

## Running
```bash
python -m receipt_designer.app
# or
python -m receipt_designer
```

## Lint & Test
```bash
pip install ruff pytest
ruff check receipt_designer
pytest
```

## Pull Requests
- Fork the repo, create a feature branch.
- Keep PRs focused and small.
- Add tests where sensible.
- Update docs when behavior changes.
