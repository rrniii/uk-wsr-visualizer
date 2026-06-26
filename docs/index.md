# The UK WSR Visualizer

<div class="uk-wsr-hero">

UK WSR Visualizer is a UK-radar-specific Weather and Climate Toolkit-style app and command-line toolkit for UK WSR aggregate HDF5 radar files. The documentation section uses Sphinx, MyST Markdown, sphinx-design cards, and the PyData Sphinx Theme.

</div>

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User Guide
:link: user_guide
:link-type: doc

Run the local viewer, work with UK WSR catalogs, and use radar display controls.
:::

:::{grid-item-card} Setup
:link: setup
:link-type: doc

Prepare a local checkout and documentation build environment.
:::

:::{grid-item-card} Operations Notes
:link: install_and_use
:link-type: doc

Use the existing collaborator notes for app paths, catalog URLs, cache paths, and operational context.
:::

:::{grid-item-card} Roadmap
:link: uk_radar_wct_replica_roadmap
:link-type: doc

Review the current UK radar WCT-style scope and implementation plan.
:::

::::

## What can it do?

- Discover radar-day aggregate HDF5 files and build catalog or STAC metadata.
- Render georeferenced PPI previews with palette, opacity, range, azimuth, value, CAPPI-style, and click-identify controls.
- Export native HDF5 metadata, PNG, KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and WCT batch configuration artifacts.
- Build preview animations, derived math products, contour overlays, and browser tile pyramids.
- Publish catalog and data products to the JASMIN Object Store through dry-run-first operational commands.
- Run deployment, freshness, and WCT parity validation checks for repeatable operations.

```{toctree}
:hidden:
:maxdepth: 2
:caption: Documentation

user_guide
setup
install_and_use
wct_parity_validation
jasmin_object_store_setup
ncas_radar_object_store_release
uk_wsr_visualizer_deployment
uk_radar_wct_replica_roadmap
```
