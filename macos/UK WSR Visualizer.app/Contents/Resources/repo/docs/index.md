# UK WSR Visualizer

```{image} _static/uk-wsr-visualizer-logo.png
:alt: UK WSR Visualizer radar logo
:width: 140px
:align: right
```

UK WSR Visualizer is a quick-look web app and command-line toolkit for
discovering, visualising, exporting, and citing UK weather surveillance radar
aggregate HDF5 data.

## What is UK WSR Visualizer?

UK WSR Visualizer helps researchers, students, and data-service teams move from
archived UK weather radar source objects to first scientific inspection. It
provides a local viewer for georeferenced PPI plots, command-line tools for
catalogues and exports, and object-store workflows for publishing approved
catalogue and source-object views.

## Citing UK WSR Visualizer

If UK WSR Visualizer contributes to a figure, case selection, export, or derived
analysis, cite the software release used, the underlying UK radar source-data
record, and JASMIN where JASMIN storage or compute was used. The command-line
citation helper prints the current citation and provenance guidance:

```bash
uk-wsr-visualizer-citation
uk-wsr-visualizer-citation --json
```

## What can UK WSR Visualizer do?

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User Guide
:link: user_guide
:link-type: doc

Install the package, run the viewer, search catalogues, inspect radar fields,
and use object-store-backed source data.
:::

:::{grid-item-card} Example Gallery
:link: example_gallery/index
:link-type: doc

Copyable examples for catalogue building, object-store workflows, and common
command-line tasks.
:::

:::{grid-item-card} API Reference
:link: api_reference/index
:link-type: doc

Autodoc reference pages for the core Python modules.
:::

:::{grid-item-card} Developer Guide
:link: developer_guide/index
:link-type: doc

Development setup, repository layout, tests, documentation builds, and
contribution notes.
:::

::::

## Install

Start with the [installation guide](user_guide/installation.md) for app-bundle
use, editable installs, and local documentation builds. Use a tagged release for
stable analysis and the default branch for active development.

## Dependencies

The core package depends on FastAPI, Uvicorn, h5py, NumPy, and Pillow. The
documentation site uses Sphinx, MyST, the PyData Sphinx Theme, sphinx-design,
and sphinx-copybutton.

## Optional Dependencies

Additional export and object-store workflows use optional dependencies such as
Rasterio, netCDF4, pyshp, and boto3. Install the relevant optional dependency
group only when you need those workflows.

## Getting help

Open an issue in the repository for reproducible bugs, missing documentation, or
viewer behaviour that is unclear. Include the radar, date, variable, elevation,
and app or command-line version where possible.

## Contributing

See the [Developer Guide](developer_guide/index.md) for local development,
testing, documentation builds, and contribution notes.

```{toctree}
:hidden:
:maxdepth: 2
:caption: User Guide and Operational Notes

user_guide
install_and_use
jasmin_object_store_setup
ncas_radar_object_store_release
uk_wsr_visualizer_deployment
uk_radar_wct_replica_roadmap
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
:caption: API Reference

api_reference/index
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Developer Guide

developer_guide/index
README
wct_parity_validation
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: Release Notes

release_notes
release_checklist
```
