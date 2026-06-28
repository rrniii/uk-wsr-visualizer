# Developer Guide

This section records the development workflow for code, tests, documentation, and operational assets.

```{toctree}
:maxdepth: 2

contributing
apple_xcode
```

## Repository layout

```text
src/uk_wsr_visualizer/   Python package
src/uk_wsr_visualizer/api/ FastAPI application
docs/                    Sphinx documentation and operational notes
tests/                   Test suite
deploy/                  Deployment assets
configs/                 Example configuration
examples/                Example payloads and workflows
macos/                   Local macOS app launcher
apple/                   Xcode workspace for Apple app development
tools/                   Utility scripts
```

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store,docs]"
```

## Run tests

```bash
pytest
```

## Build docs

```bash
sphinx-build -b html docs docs/_build/html
```

The documentation uses Sphinx, MyST Markdown, PyData Sphinx Theme, sphinx-design cards, and sphinx-copybutton.

## Check the CLI

```bash
uk-wsr-visualizer --help
uk-wsr-visualizer catalog build --help
uk-wsr-visualizer export --help
uk-wsr-visualizer object-store plan --help
```
