# Documentation source

This directory contains the Sphinx documentation site for UK WSR Visualizer. It uses MyST Markdown, sphinx-design cards, and the PyData Sphinx Theme.

The main entry point is `index.md`. The Sphinx settings live in `conf.py`, and custom theme tweaks live in `_static/custom.css`.

Build it locally from the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[docs]"
python -m sphinx -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` after the build completes.

The GitHub Actions workflow in `.github/workflows/docs.yml` builds and publishes the `master` branch documentation through GitHub Pages when Pages is configured to use GitHub Actions.
