# Object Store Publication

The object-store workflow prepares public catalog, aggregate, preview, tile, validation, and status products for JASMIN Object Store buckets.

## Design principles

- Publish only data products that are approved for community redistribution.
- Use dry-run commands before live sync, verification, or publication.
- Keep private paths and local-only settings out of public metadata.

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
