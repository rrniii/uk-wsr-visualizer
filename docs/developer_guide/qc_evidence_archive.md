# QC Evidence Archive

The application repository contains the implementation, deterministic test
fixtures, compact provenance manifests, and selected figures needed to explain
the quality-control method. It does not contain full training inventories,
blinded-review target lists, downloaded PVOL files, or generated validation
reports.

Those large outputs are reproducible from the versioned tools and must be
published to an approved object-store or release archive for each scientific or
software release. Record the Git commit, input object URLs and checksums,
commands, configuration, and generated summary with that archive.

## What belongs in Git

- quality-control, catalog, and validation code;
- small deterministic fixtures used by automated tests;
- templates, checksums, and compact release manifests;
- selected documentation figures and concise result summaries.

## What belongs in the evidence archive

- downloaded PVOL source objects and cache contents;
- training and validation inventories at network scale;
- blinded-review targets and annotations;
- generated report directories, galleries, and intermediate model-training
  shards.

This separation keeps normal application clones practical while retaining a
reproducible path from the released code to the full validation evidence.
