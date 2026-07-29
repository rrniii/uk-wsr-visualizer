# Exports

UK WSR Visualizer provides app, CLI, and API export operations for quick-look
figures and analysis products.

## App exports

The viewer sidebar includes **Export & Provenance** for the current primary
panel. It intentionally exposes only the formats that are useful for routine
beta testing and article figures:

- **Screen view PNG: map, PPI, rings and legend + local manifest** downloads a
  publication-ready capture of the current app view. It includes the selected
  map view, radar PPI, range rings, colour legend and selection summary. This
  is the best match to what a user sees on screen.
- **Polar PPI PNG (range-azimuth) + manifest** exports the selected sweep as a
  radar-coordinate image using the current variable, time, elevation, palette,
  and filters.
- **Polar PPI MP4 animation + manifest** exports either the full available
  radar day or a selected start/end interval, using the selected variable,
  elevation, palette, filters, and frame delay. Before export, the app reports
  the frame count, frame rate, and estimated video duration.
- **Georeferenced map overlay KMZ + manifest** exports a map-overlay product for
  geospatial viewing.
- **Georeferenced GeoTIFF + manifest** exports a Cartesian georeferenced raster
  product for GIS/scientific workflows.
- **Metadata JSON + manifest** exports the selected catalog item metadata.

**Save current map image** is the immediate equivalent of the screen-view PNG:
it saves the visible primary panel without opening an export job.

After an export completes, use **View Manifest** to inspect the provenance JSON.
MP4 manifests also include the selected frame times, start/end time, frame
delay, frame rate, expected and actual duration, and any skipped frames.
The manifest records the software version, selected radar/date/time/variable,
elevation, coordinate mode, source object, generated artifacts, current
source-data citation text, and JASMIN acknowledgement. Until the formal
source-data citation is confirmed, the manifest states that the citation is
pending rather than substituting a different data record. Use **Download** to
retrieve the requested file. Single-file exports download as that file; only
multi-file products download as a clearly named archive when needed.

Desktop beta builds include the MP4 encoder. A missing-dependency message in a
source checkout means that the optional video dependencies have not been
installed; run `python -m pip install -e ".[video]"` before using MP4 export.

## Supported formats

The command-line export tool supports native HDF5, metadata JSON, PNG, MP4,
KMZ, field CSV, GeoTIFF, CF NetCDF, GeoJSON, Shapefile, qc-v3 mask, and
batch-configuration outputs. The `qc_mask` product is a compressed NPZ plus
JSON provenance sidecar containing the applied mask, learned proposal,
abstention mask, nuisance probabilities, reason flags, feature availability,
array hashes, and source checksum.

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
