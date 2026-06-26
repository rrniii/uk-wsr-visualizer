# Catalog build examples

## Build a single catalog

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/single-site \
  --output data/catalog.json
```

## Build a catalog and serve it locally

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/single-site \
  --output data/catalog.json

uk-wsr-visualizer api \
  --catalog data/catalog.json \
  --host 127.0.0.1 \
  --port 8000
```

## Build STAC metadata

```bash
uk-wsr-visualizer catalog stac \
  --catalog data/catalog.json \
  --output-dir data/stac \
  --object-prefix uk-radar
```

The STAC command writes a root catalog, collection metadata, and item JSON documents that can be staged with the rest of the public release.
