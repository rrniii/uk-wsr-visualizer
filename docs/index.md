# The UK WSR Visualizer

UK WSR Visualizer is a UK-radar-specific quick-look web app and command-line toolkit for UK weather surveillance radar aggregate HDF5 data.

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User Guide
:link: user_guide
:link-type: doc

Install the package, run the local viewer, and work with UK WSR catalogues and radar controls.
:::

:::{grid-item-card} Example Gallery
:link: example_gallery/index
:link-type: doc

Copyable examples for catalogue building, preview rendering, exports, validation, and deployment checks.
:::

:::{grid-item-card} API Reference
:link: api_reference/index
:link-type: doc

Reference pages for the modules behind the CLI, API service, catalogues, previews, exports, and operational tools.
:::

:::{grid-item-card} Developer Guide
:link: developer_guide/index
:link-type: doc

Repository layout, development setup, documentation build instructions, tests, and contribution conventions.
:::

::::

## What can it do?

- Discover radar-day aggregate HDF5 files and build catalog or STAC metadata.
- Render georeferenced PPI previews with palette, opacity, range, azimuth, value, and click-identify controls.
- Export native HDF5 metadata, PNG, KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and WCT batch configuration artifacts.
- Build preview animations, derived math products, contour overlays, and browser tile pyramids.
- Run deployment, freshness, citation, and WCT parity validation checks.

```{toctree}
:hidden:
:maxdepth: 2
:caption: User Guide

user_guide
setup
install_and_use
wct_parity_validation
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
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: Release Notes

release_notes
```
