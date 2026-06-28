# Object Store Publication

> Current Avocet production publishes pvol files under `ukmo-nimrod/pvol` and keeps aggregate HDF5 on GWS.
> See [Avocet Production Pipeline](../avocet_production_pipeline.md) for the production data workflow.
> This page describes the generic UK WSR Visualizer publication commands.

The object-store workflow prepares public catalogue, aggregate HDF5 source
objects, preview, tile, validation, checksum, manifest, and status products for
JASMIN Object Store buckets.

## Current state

The configured tenancy is `ncas-radar-o`, with `uk-wsr-visualizer-staging` and
`uk-wsr-visualizer-public` buckets. The published public prefix is `uk-radar/`.

The current public dataset is a staged release, not a complete national archive.
The verified public subset contains the Chenies 2018 release and the supporting
catalogue/status products. Broad backfill and sync jobs are paused until the
source-data licence, citation, access terms, quota, and publication policy are
confirmed.

The app should treat object-store files as source objects plus public metadata,
not as app-specific derivatives. User-generated exports are local/private by
default and are not published by the current object-store configuration.

## Design principles

- Publish only source objects and metadata products that are approved for
  community redistribution.
- Use dry-run commands before live sync, verification, or publication.
- Keep private paths and local-only settings out of public metadata.
- Keep original restricted archive files out of the public object store unless
  separate redistribution approval exists.

## Publication steps

Build a publication plan:

```bash
uk-wsr-visualizer object-store plan \
  --catalog data/catalog.json \
  --staging-dir data/object-store-staging \
  --output data/publication-plan.json
```

Sync and verify the plan:

```bash
uk-wsr-visualizer object-store sync \
  --plan data/publication-plan.json \
  --manifest data/synced.json

uk-wsr-visualizer object-store verify \
  --manifest data/synced.json \
  --output data/verified.json
```

Publish public status products:

```bash
uk-wsr-visualizer object-store publish \
  --manifest data/verified.json \
  --output data/publish-result.json
```

See the detailed operational notes in [JASMIN Object Store setup](../jasmin_object_store_setup.md) and [NCAS radar object-store release setup](../ncas_radar_object_store_release.md).
