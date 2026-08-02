# UK WSR Visualizer

~~~{image} _static/uk-wsr-visualizer-logo.png
:alt: UK WSR Visualizer radar logo
:width: 150px
:align: right
~~~

UK WSR Visualizer is a quick-look desktop application and Python toolkit for
discovering, viewing, comparing, exporting, and citing single-site UK
weather-surveillance radar volumes.

It provides a practical path from a large archive to a traceable first
inspection: search small catalogues, download one selected ODIM PVOL HDF5
object, view a georeferenced PPI, and retain the source and display choices
needed to revisit the result.

> **Project status:** UK WSR Visualizer is active research software. The public
> catalogue is available; desktop packages are currently beta distributions
> rather than a stable, archived release.

## Published catalogue

The figures below describe the catalogue snapshot generated on 23 July 2026.
They are a dated inventory, not a promise that the archive will remain static.

::::{grid} 1 2 4 4
:gutter: 2

:::{grid-item-card} 17
:class-card: uk-wsr-stat-card

Radar sites
:::

:::{grid-item-card} 58,427
:class-card: uk-wsr-stat-card

Radar-days
:::

:::{grid-item-card} 23,557,040
:class-card: uk-wsr-stat-card

Per-volume HDF5 objects
:::

:::{grid-item-card} 132.4 TB
:class-card: uk-wsr-stat-card

Published data represented
:::

::::

The snapshot covers 21 January 2013 through 21 July 2026. The app does not load
this collection at startup. It reads a root catalogue, one selected
radar-year coverage record, and one selected day record before fetching a
volume.

## What the app is for

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} Discover
:class-card: uk-wsr-workflow-card

Find available dates and sites before downloading radar data. Valid pulses,
times, variables, and elevations are constrained by the selected source.
:::

:::{grid-item-card} Inspect and compare
:class-card: uk-wsr-workflow-card

View georeferenced PPIs with maps, range rings, physical colour scales, pointer
readouts, animation, and independent four-panel comparisons.
:::

:::{grid-item-card} Preserve evidence
:class-card: uk-wsr-workflow-card

Export a screen view, polar product, georeferenced product, source object, or
metadata with a manifest recording software, selection, source, and citation
information.
:::

::::

UK WSR Visualizer is a first-look and evidence-export tool. It does not replace
specialist analysis in Py-ART, wradlib, vol2bird, bioRad, or a validated local
workflow.

## Start here

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} User Guide
:link: user_guide
:link-type: doc

Install a desktop package, understand the data, select a valid volume, use the
viewer, export results, and diagnose common problems.
:::

:::{grid-item-card} Example Gallery
:link: example_gallery/index
:link-type: doc

Follow source-backed examples using Castor Bay on 18 September 2014, including
a first PPI, four-panel comparison, and provenance export.
:::

:::{grid-item-card} API Reference
:link: api_reference/index
:link-type: doc

Reference for the catalogue, preview, export, animation, tile, session,
publication, and FastAPI modules.
:::

:::{grid-item-card} Developer Guide
:link: developer_guide/index
:link-type: doc

Set up a development environment, run tests, build documentation, and preserve
cross-platform behavior.
:::

::::

## Source and responsibility

CEDA remains the authoritative source archive. JASMIN processing publishes
checked per-volume HDF5 objects and lazy JSON catalogues to the public JASMIN
Object Store. The Object Store is an access route, not a substitute source-data
citation.

Optional cleanup is performed in memory and never changes the published HDF5
object. Weak weather, biological echo, noise, and clutter can overlap, so
scientific users should compare cleanup with the baseline and preserve settings
in the export manifest.

## Citation

Use the exact software version, the formal source-data citation, the Weather
article when available, and the JASMIN acknowledgement where applicable:

~~~bash
uk-wsr-visualizer citation
uk-wsr-visualizer citation --json
~~~

The current software DOI, article DOI, and formal source-data citation are
explicitly marked pending until those records are published. See
[Citing UK WSR Visualizer](https://github.com/rrniii/uk-wsr-visualizer/blob/master/CITATION.md).

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: User Guide

user_guide
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: Examples

example_gallery/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: API Reference

api_reference/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: Developer Guide

developer_guide/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: Maintainer Operations

operations/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 1
:caption: Releases

release_notes
release_checklist
~~~
