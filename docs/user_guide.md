# User Guide

This guide follows the normal user journey: install the application, understand
the source data, select a valid radar volume, inspect it, compare related scans,
and export a result with provenance.

~~~{toctree}
:maxdepth: 2

user_guide/installation
linux_install_and_use
user_guide/quickstart
user_guide/data_and_terms
user_guide/catalogs
user_guide/viewer
user_guide/exports
user_guide/object_store
user_guide/troubleshooting
~~~

## Choose your route

**Desktop user**
: Install the beta package for macOS, Windows, or Linux. The app opens in its
  own window and uses the public catalogue by default. No JASMIN account or
  system Python is required by a packaged build.

**Python user**
: Install the visualizer and its separate scientific-QC dependency in an
  isolated environment. Start the local API, use the CLI, or import the package.

**Data publisher**
: Read [Maintainer Operations](operations/index.md). Publication, object-store
  credentials, and service deployment are intentionally kept out of the
  first-time user path.

## Normal workflow

1. Choose a data era and date range.
2. Select an available radar and pulse.
3. Let the app load the selected day's small catalogue.
4. Choose a time, descriptive variable, and elevation offered for that volume.
5. Inspect the baseline PPI before interpreting optional cleanup.
6. Compare times, variables, elevations, or sites when needed.
7. Export the appropriate coordinate form and inspect its manifest.

The [Quick Start](user_guide/quickstart.md) uses a verified public Castor Bay
volume so that the selections and expected controls are concrete.

## Scientific boundaries

- The visualizer never overwrites source HDF5 files.
- Catalogue absence is not proof that no data exist in the authoritative CEDA
  archive.
- Long-pulse and short-pulse scans are separate source choices.
- Cleanup is optional and reproducible, but it is not a perfect classifier of
  weather, biological echo, clutter, or noise.
- The displayed map and polar radar export are different coordinate products.
- A provenance manifest supports reproducibility but does not replace the
  formal source-data citation.
