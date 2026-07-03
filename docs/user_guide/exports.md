# Exports

UK WSR Visualizer provides app, CLI, and API export operations for quick-look
figures and analysis products.

## App exports

The viewer sidebar includes **Export & Provenance** for the current primary
panel. It intentionally exposes only the formats that are useful for routine
beta testing and article figures:

- **Screenshot: as displayed PNG + local manifest** downloads the current
  browser view. This is the best match to what the user sees on screen,
  including the current zoom and range-ring overlay. If a third-party basemap
  blocks canvas export, the app still saves the radar/range overlay and records
  the warning in the local manifest.
- **Polar PPI PNG (range-azimuth) + manifest** exports the selected sweep as a
  radar-coordinate image using the current variable, time, elevation, palette,
  and filters.
- **Polar PPI MP4 animation + manifest** exports the current radar day,
  variable, elevation, palette, and filters across the available times for that
  selection.
- **Georeferenced map overlay KMZ + manifest** exports a map-overlay product for
  geospatial viewing.
- **Georeferenced GeoTIFF + manifest** exports a Cartesian georeferenced raster
  product for GIS/scientific workflows.
- **Metadata JSON + manifest** exports the selected catalog item metadata.

After an export completes, use **View Manifest** to inspect the provenance JSON.
The manifest records the software version, selected radar/date/time/variable,
elevation, coordinate mode, source object, generated artifacts, current
source-data citation text, and JASMIN acknowledgement. Until the formal
source-data citation is confirmed, the manifest states that the citation is
pending rather than substituting a different data record. Use **Download** to
retrieve the generated artifact or artifact bundle.

## Supported formats

The command-line export tool supports native HDF5, metadata JSON, PNG, MP4, KMZ,
field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, and batch-configuration
outputs.

## Example

```bash
uk-wsr-visualizer export \
  --catalog data/catalog.json \
  --radar chenies \
  --date 20240101 \
  --pulse long \
  --time 120000 \
  --quantity DBZH \
  --format mp4 \
  --times 1200,1205,1210 \
  --frame-delay-ms 500
```

## Filters

Preview and export commands support range, azimuth, value, and CAPPI-style height filters. Use `uk-wsr-visualizer export --help` and `uk-wsr-visualizer preview build --help` for the full selector set.

## Tiles and animation

Use `uk-wsr-visualizer tile build` to create browser tile pyramids and `uk-wsr-visualizer animation build` to create timeline frame packages.

## Derived math products

Use `uk-wsr-visualizer math` to generate difference, sum, product, ratio, mean, minimum, or maximum products between two selected fields.
