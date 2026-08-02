# Data Processing Boundary

This page explains which system owns each stage. It intentionally does not
duplicate scientific QC algorithms or JASMIN pipeline implementation.

## Ownership

| Stage | Owner and role |
|---|---|
| Authoritative observation archive | CEDA UK weather-surveillance radar record |
| Conversion and integrity checks | JASMIN data-production workflow |
| Daily aggregate working products | GWS processing storage |
| Public access products | Per-volume ODIM PVOL HDF5 plus lazy JSON catalogues in the JASMIN Object Store |
| Quick-look access | UK WSR Visualizer desktop, CLI, and API |
| Scientific QC implementation and evidence | Standalone UK WSR QC project |
| Specialist downstream analysis | User workflows such as Py-ART, wradlib, vol2bird, or bioRad |

## Source-preserving contract

1. Read source objects without modifying them.
2. Validate HDF5 structure, identifiers, shapes, and ODIM gain/offset metadata.
3. Convert nodata and undetect codes to missing values in memory.
4. Keep radar, UTC date/time, pulse, quantity, sweep, and source provenance.
5. Write new products to new paths; never overwrite archive or public source
   objects.
6. Verify checksums and catalogue references before publication.
7. Save processing/QC version and parameters with derived products.

## Catalogue contract

The public root contains radar coordinates and radar-year coverage keys. A
coverage record contains days and day-catalogue keys. A day catalogue lists
each pulse/time PVOL object and its public URL. Optional field indexes describe
variables and elevations but are not required for correctness.

The root is promoted only after its referenced children and HDF5 objects are
readable.

## QC boundary

UK WSR Visualizer may apply a versioned QC package in memory for display and
export. Algorithm definitions, learned models, validation corpora, review
annotations, and promotion evidence belong in the versioned `uk-wsr-qc`
project.

The visualizer must:

- expose a source-preserving baseline;
- identify the QC mode and version;
- keep uncertain weather/biological/clutter cases reviewable;
- avoid claiming perfect classification;
- include settings and diagnostics in provenance;
- never write a cleaned copy unless the user explicitly exports a derived
  diagnostic product.

## VP and VPTS use

Vertical-profile processing is downstream analysis. When an approved pre-VP
mask is requested, it is applied to decoded in-memory arrays, consistently
across fields used by the calculation. The source PVOL remains unchanged and
the output stores the preset, parameters, diagnostics, software version, and
source references.

Production defaults and promotion decisions must come from the standalone QC
validation record, not from this documentation page.
