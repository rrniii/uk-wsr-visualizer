# Maintainer Operations

This section is for maintainers who publish catalogues, operate a service, or
prepare a release. It is not required to use the desktop application.

Operational pages can contain JASMIN paths, service names, and dated migration
history. Treat those values as deployment-specific examples and verify the live
configuration before running a command.

~~~{toctree}
:maxdepth: 2

../jasmin_object_store_setup
../ncas_radar_object_store_release
../uk_wsr_visualizer_deployment
../ukmo_wsr_processing_pipeline
~~~

## Operational boundaries

- CEDA remains the authoritative archive.
- Source HDF5 objects are never modified by the visualizer.
- Public catalogues must not reference objects that are not yet readable.
- Credentials and local configuration stay outside version control.
- Publication uses a plan, dry run, checksum verification, and an explicit
  promotion step.
- Scientific QC implementation and evidence belong in the standalone,
  versioned `uk-wsr-qc` project.
