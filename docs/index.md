# The UK WSR Visualizer

<div class="uk-wsr-hero">

UK WSR Visualizer is a UK-radar-specific Weather and Climate Toolkit-style app and command-line toolkit for UK WSR aggregate HDF5 radar files. It provides catalog discovery, local and web visualisation, preview generation, export workflows, object-store publication, and validation utilities for community radar workflows.

</div>

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User Guide
:link: user_guide/index
:link-type: doc

Install the package, run the app, connect to the public JASMIN Object Store catalog, and work through the main viewer and CLI workflows.
:::

:::{grid-item-card} Example Gallery
:link: example_gallery/index
:link-type: doc

Copyable examples for catalog building, preview rendering, export jobs, STAC publication, and operational smoke tests.
:::

:::{grid-item-card} API Reference
:link: api_reference/index
:link-type: doc

Autodoc reference pages for the package modules that back the CLI, FastAPI service, export engine, catalog logic, and publication tools.
:::

:::{grid-item-card} Developer Guide
:link: developer_guide/index
:link-type: doc

Repository layout, development installation, documentation build instructions, testing, and contribution conventions.
:::

::::

## What is UK WSR Visualizer?

The project is a UK radar workflow toolkit aimed at the WCT-style operations needed for UK WSR aggregate HDF5 data. The current implementation includes a macOS launcher, FastAPI/static browser viewer, command-line catalog and export operations, public object-store publication utilities, and validation assets for WCT parity checks.

## What can it do?

- Discover radar-day aggregate HDF5 files and build catalog or STAC metadata.
- Render georeferenced PPI previews with radar-field, palette, opacity, range, azimuth, value, CAPPI-style, and click-identify controls.
- Export native HDF5 metadata, PNG, KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and WCT batch configuration artifacts.
- Build preview animations, derived math products, contour overlays, and browser tile pyramids.
- Publish public catalog and data products to the JASMIN Object Store through dry-run-first operational commands.
- Run deployment, freshness, and WCT parity validation checks for repeatable operations.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,export,object-store,docs]"
```

Open the documentation locally with:

```bash
sphinx-build -b html docs docs/_build/html
python -m http.server --directory docs/_build/html 8080
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: User Guide

user_guide/index
user_guide/installation
user_guide/quickstart
user_guide/catalogs
user_guide/viewer
user_guide/exports
user_guide/object_store
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Example Gallery

example_gallery/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Reference

api_reference/index
release_notes
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Developer Guide

developer_guide/index
developer_guide/contributing
```
