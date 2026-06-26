# Installation

UK WSR Visualizer requires Python 3.11 or newer.

## Developer installation

Create an isolated environment and install the project in editable mode:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store]"
```

The extras enable the common development and operational workflows:

- `dev`: test dependencies.
- `export`: GeoTIFF, CF NetCDF, and Shapefile export dependencies.
- `object-store`: JASMIN/S3 publication dependencies.
- `docs`: Sphinx, PyData Sphinx Theme, and documentation extensions.

For documentation work, install:

```bash
pip install -e ".[docs]"
```

or combine it with the development extras:

```bash
pip install -e ".[dev,export,object-store,docs]"
```

## macOS app bundle

The repository includes a lightweight local app bundle:

```text
macos/UK WSR Visualizer.app
```

On first launch, the app creates a Python virtual environment and installs the bundled checkout into:

```text
~/Library/Application Support/UK WSR Visualizer/
```

Application logs are written to:

```text
~/Library/Application Support/UK WSR Visualizer/uk-wsr-visualizer.log
```

The app starts the local API and opens the browser UI at:

```text
http://127.0.0.1:8765
```

## Build the documentation locally

```bash
pip install -e ".[docs]"
sphinx-build -b html docs docs/_build/html
python -m http.server --directory docs/_build/html 8080
```

Open `http://127.0.0.1:8080` in a browser.
