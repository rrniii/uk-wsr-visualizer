# Exports

UK WSR Visualizer provides CLI and API export operations for WCT-style analysis products.

## Supported formats

The export command supports native HDF5, metadata JSON, PNG, KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and WCT batch configuration outputs.

## Example

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

## Filters

Preview and export commands support range, azimuth, value, and CAPPI-style height filters. Use `uk-wsr-visualizer export --help` and `uk-wsr-visualizer preview build --help` for the full selector set.

## Tiles and animation

Use `uk-wsr-visualizer tile build` to create browser tile pyramids and `uk-wsr-visualizer animation build` to create timeline frame packages.

## Derived math products

Use `uk-wsr-visualizer math` to generate difference, sum, product, ratio, mean, minimum, or maximum products between two selected fields.
