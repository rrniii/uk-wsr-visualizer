# UK WSR Visualizer

UK WSR Visualizer is a quick-look web app and command-line toolkit for discovering, visualising, exporting, and citing UK weather surveillance radar aggregate HDF5 data.

## Documentation sections

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User Guide
:link: user_guide
:link-type: doc

Install the package, run the viewer, and work with catalogues, radar fields, exports, citation, and publication workflows.
:::

:::{grid-item-card} Citation and Attribution
:link: citation
:link-type: doc

How to cite the software release, Weather article, source data, and JASMIN infrastructure.
:::

:::{grid-item-card} Example Gallery
:link: example_gallery/index
:link-type: doc

Copyable commands for catalogues, previews, exports, STAC metadata, and deployment checks.
:::

:::{grid-item-card} API Reference
:link: api_reference/index
:link-type: doc

Autodoc reference pages for the core Python modules.
:::

:::{grid-item-card} Developer Guide
:link: developer_guide/index
:link-type: doc

Development setup, repository layout, tests, documentation builds, and contribution notes.
:::

::::

```{toctree}
:hidden:
:maxdepth: 2
:caption: User Guide

user_guide
install_and_use
citation
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
```

```{toctree}
:hidden:
:maxdepth: 1
:caption: Release Notes

release_notes
release_checklist
```
