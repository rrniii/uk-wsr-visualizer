# Catalogs and STAC

Catalogs are the index that lets the app and CLI discover available radar-day aggregate HDF5 files without opening every full data array.

## Build the internal catalog

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/single-site \
  --output data/catalog.json
```

The catalog records radar, date, source path, file size, checksum-related metadata where available, and the quantity/time/dataset selectors found in each aggregate file.

## Build a STAC catalog

```bash
uk-wsr-visualizer catalog stac \
  --catalog data/catalog.json \
  --output-dir data/stac \
  --object-prefix uk-radar
```

The STAC writer creates:

- a root catalog JSON file,
- a `uk-wsr-aggregate-h5` collection,
- one item JSON file per radar-day aggregate.

## Use a catalog with the API

```bash
uk-wsr-visualizer api --catalog data/catalog.json --host 0.0.0.0 --port 8000
```

The browser UI uses the catalog to populate radar and date selections. For PVOL object-store catalogues, optional field-index sidecars provide the time, variable, dataset, elevation, shape, and file-size metadata needed to populate plot controls without opening a raw HDF5 file. When a plot or export needs the source data, the local API downloads only the selected raw source object into its bounded disposable cache.

## Operational notes

- Keep private local filesystem paths out of public catalog products.
- Treat the raw aggregate HDF5 files as the source of truth.
- Publish STAC/catalog metadata beside the public aggregate objects when preparing community object-store releases.
- Use freshness checks to detect stale catalog, manifest, or validation products.
