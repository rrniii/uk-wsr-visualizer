# Example Gallery

These examples are copyable starting points. Replace the radar, date, time, quantity, dataset, and path values with selectors from your own catalog.

## Build a catalog

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/single-site \
  --output data/catalog.json
```

## Start the viewer

```bash
uk-wsr-visualizer api \
  --catalog data/catalog.json \
  --host 127.0.0.1 \
  --port 8000
```

## Build one preview

```bash
uk-wsr-visualizer preview build \
  --catalog data/catalog.json \
  --radar chenies \
  --date 20240101 \
  --pulse long \
  --time 120000 \
  --quantity DBZH
```

## Export a GeoTIFF

```bash
uk-wsr-visualizer export \
  --catalog data/catalog.json \
  --radar chenies \
  --date 20240101 \
  --pulse long \
  --time 120000 \
  --quantity DBZH \
  --format geotiff
```

## Create a STAC catalog

```bash
uk-wsr-visualizer catalog stac \
  --catalog data/catalog.json \
  --output-dir data/stac \
  --object-prefix uk-radar
```

## Run WCT parity validation

```bash
uk-wsr-visualizer validate wct \
  --catalog data/catalog.json \
  --radar chenies \
  --date 20240101 \
  --pulse long \
  --time 120000 \
  --quantity DBZH \
  --format geotiff \
  --wct-app /Applications/WCT-4.9.1.app \
  --output-dir data/validation \
  --report data/validation/report.json
```

## Run a deployment preflight check

```bash
uk-wsr-visualizer deployment preflight \
  --catalog data/catalog.json \
  --base-url http://127.0.0.1:8000 \
  --output data/preflight.json
```
