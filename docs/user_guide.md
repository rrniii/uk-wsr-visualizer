# User Guide

This guide covers the operational path from installation to catalogue discovery,
local viewing, command-line processing, export generation, and object-store
publication workflows.

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
: Use the macOS app bundle or the FastAPI/static web service to select radar files from the catalogue, download the selected source object into a disposable cache, and render georeferenced PPI views.

**Command-line processing**
: Use `uk-wsr-visualizer` subcommands to build catalogues, create previews, generate tiles and animations, export analysis products, run derived math operations, check freshness, and prepare object-store publication workflows.

**Object-store and publication workflow**
: Use the object-store commands to stage, sync, verify, and publish catalogue and approved source objects after access conditions are confirmed.

**Citation and provenance**
: Use `uk-wsr-visualizer-citation` and export `artifact-manifest.json` files to keep software, source-data, and JASMIN attribution visible in research workflows.

## Additional operational notes

The repository also contains operational references for administrators and
developers:

- [Install and use guide](install_and_use.md)
- [Development roadmap](uk_radar_wct_replica_roadmap.md)
- [JASMIN Object Store setup](jasmin_object_store_setup.md)
- [NCAS radar object-store release setup](ncas_radar_object_store_release.md)
- [Standalone UK WSR QC project](https://github.com/rrniii/uk-wsr-qc)
- [UKMO WSR processing pipeline](ukmo_wsr_processing_pipeline.md)
- [Deployment notes](uk_wsr_visualizer_deployment.md)
