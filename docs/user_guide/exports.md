# Exports and Provenance

Choose an export by the coordinate system and intended use, not only by the
file extension.

## App export choices

| Choice | Coordinate form | Best use |
|---|---|---|
| Screen view PNG | Current map view | A figure matching the displayed PPI, rings, legend, and annotations |
| Polar PPI PNG | Radar range-azimuth | A single sweep for radar-coordinate inspection |
| Polar PPI MP4 | Radar range-azimuth over time | Animation and public-engagement playback |
| KMZ overlay | Georeferenced map overlay | Viewing in compatible globe/map software |
| GeoTIFF | Georeferenced Cartesian raster | GIS and scientific map workflows |
| Metadata JSON | No image coordinate grid | Selection, source, and catalogue evidence |
| Raw source HDF5 | Original published volume | Analysis in another scientific tool |

The polar image is not expected to look like the map screenshot. It preserves
radar coordinates, whereas the screen view includes a map projection and the
current viewport.

## What the manifest records

Each server-backed export writes `artifact-manifest.json`. A screen capture
downloads a companion local manifest. The manifest records:

- software version and Git commit;
- radar, date, pulse, time, variable, dataset, and elevation where applicable;
- coordinate mode;
- palette, display limits, filters, and QC settings;
- source item, object key, and public URL;
- artifact filename, size, SHA-256 checksum, and content type;
- software, article, source-data, and JASMIN citation fields.

Pending DOI and source-citation fields remain explicit. They must not be
silently replaced with a citation for a different data product.

## A tested metadata export

After building the one-volume catalogue from the
[first-look example](../example_gallery/first_look.md):

~~~bash
uk-wsr-visualizer --catalog /tmp/uk-wsr-example/catalog.json export \
  --radar castor-bay \
  --date 20140918 \
  --format metadata_json \
  --pulse lp \
  --time 1535 \
  --quantity DBZH \
  --dataset 1 \
  --qc-mode off \
  --export-dir /tmp/uk-wsr-example/exports
~~~

The tested manifest identifies the selection as **Horizontal Reflectivity
(DBZH)** from Castor Bay, 18 September 2014 at 15:35 UTC, dataset 1, with
`coordinate_mode: catalog_metadata`.

## Optional dependencies

Desktop beta packages include the dependencies required by their advertised
export controls. A source checkout can install:

~~~bash
python -m pip install -e ".[export,video]"
~~~

The `export` extra supplies GeoTIFF, NetCDF, and Shapefile dependencies. The
`video` extra supplies the MP4 encoder.

## Command-line formats

The CLI also supports field CSV, CF NetCDF, GeoJSON, Shapefile, QC-mask, and
batch workflows intended for specialist or operator use. Check the installed
version rather than relying on an old command list:

~~~bash
uk-wsr-visualizer export --help
~~~
