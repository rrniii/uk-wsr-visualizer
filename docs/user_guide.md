# User Guide

This guide covers the operational path from installation to catalog discovery, browser viewing, export generation, and publication workflows.

```{toctree}
:maxdepth: 2

user_guide/installation
user_guide/quickstart
user_guide/catalogs
user_guide/viewer
user_guide/exports
user_guide/object_store
```

## Main workflows

**Local visualisation**
: Use the macOS app bundle or the FastAPI/static web service to select radar files from the catalog, download the selected raw aggregate into a disposable cache, and render WCT-style georeferenced PPI views.

**Command-line processing**
: Use `uk-wsr-visualizer` subcommands to build catalogs, create previews, generate tiles and animations, export analysis products, run derived math operations, and validate WCT parity.

**Community publication**
: Use the dry-run-first object-store commands to stage, sync, verify, and publish public catalog and data products.

## Existing operational notes

The repository also contains detailed notes written during implementation:

- [Install and use guide](install_and_use.md)
- [WCT parity validation](wct_parity_validation.md)
- [UK radar WCT replica roadmap](uk_radar_wct_replica_roadmap.md)
- [JASMIN Object Store setup](jasmin_object_store_setup.md)
- [NCAS radar object-store release setup](ncas_radar_object_store_release.md)
- [Deployment notes](uk_wsr_visualizer_deployment.md)
