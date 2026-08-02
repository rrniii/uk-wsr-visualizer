# Local Catalogue Examples

These examples are for users who already have local HDF5 files. The desktop app
does not require them for the public catalogue.

## Per-volume PVOL files

~~~bash
uk-wsr-visualizer catalog build-raw-volume \
  --raw-volume-base /path/to/pvol \
  --output data/pvol-catalog.json \
  --metadata-mode fast
~~~

Use `--metadata-mode deep` to inspect every matching HDF5 object. Use
`--radar`, `--year`, `--date`, and `--max-files` to bound a test scan.

## Daily aggregate files

~~~bash
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/single-site \
  --output data/aggregate-catalog.json \
  --metadata-mode fast
~~~

## Serve a local catalogue

The catalogue is a global CLI option and must appear before the subcommand:

~~~bash
uk-wsr-visualizer --catalog data/pvol-catalog.json api \
  --host 127.0.0.1 \
  --port 8000
~~~

## Write STAC metadata

~~~bash
uk-wsr-visualizer --catalog data/pvol-catalog.json catalog stac \
  --output-dir data/stac \
  --object-prefix ukmo-nimrod
~~~

Public products must not expose private filesystem paths. Set an approved
object-store base when building publication catalogues and verify all referenced
objects before promotion.
