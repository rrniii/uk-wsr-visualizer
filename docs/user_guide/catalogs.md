# Catalogues and Availability

The public collection contains millions of per-volume files. UK WSR Visualizer
therefore uses a lazy catalogue hierarchy rather than loading every file record
at startup.

## Public hierarchy

1. **Root catalogue**: radar sites, coordinates, years, counts, and coverage
   record keys.
2. **Radar-year coverage record**: available days, pulse counts, and the day
   catalogue key.
3. **Day catalogue**: individual pulse, time, filename, size, object key, and
   public URL records.
4. **Optional field index**: variables, sweeps, elevations, and shapes used to
   populate controls without opening a representative HDF5 file.
5. **Selected PVOL HDF5 object**: the values needed to render or export the
   requested sweep.

The root catalogue is:

~~~text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/
ukmo-nimrod/catalog/pvol/catalog.json
~~~

The line break is for readability; the URL contains no space.

## What an unavailable result means

The app disables radars with no overlap for the selected dates. It then offers
only the pulses and times recorded in the chosen day catalogue. Once a volume
has been indexed or scanned, variables and elevations are also constrained.

An empty result describes the loaded public catalogue. It is not a definitive
statement about every record held in the authoritative CEDA archive.

## Why the first selection can be slower

Field-index sidecars are optional. If one is missing, the app falls back to
downloading and scanning the selected HDF5 object. This preserves compatibility
and correctness, but the first variable/elevation population takes longer.

The root, coverage, day, and field-index records are cached separately from raw
HDF5 objects and revalidated using HTTP metadata when possible.

## Build a local per-volume catalogue

For a directory of individual PVOL HDF5 files:

~~~bash
uk-wsr-visualizer catalog build-raw-volume \
  --raw-volume-base /path/to/pvol \
  --output data/catalog.json \
  --metadata-mode fast
~~~

Fast mode reads one representative volume per pulse and propagates its field
layout. Use `--metadata-mode deep` when fields or sweeps may vary among files
and the exact inventory is more important than scan speed.

## Build a daily-aggregate catalogue

The legacy/internal daily-aggregate path remains available:

~~~bash
uk-wsr-visualizer catalog build \
  --aggregate-base /path/to/single-site \
  --output data/catalog.json
~~~

The current public desktop workflow uses per-volume PVOL objects. Daily
aggregates remain upstream working products on GWS and are not downloaded by
normal desktop use.

## STAC metadata

With a local catalogue supplied as the global CLI option:

~~~bash
uk-wsr-visualizer --catalog data/catalog.json catalog stac \
  --output-dir data/stac \
  --object-prefix ukmo-nimrod
~~~

The command writes a root catalogue, collection, and item documents. STAC
generation is an operator/developer workflow, not a requirement for viewing the
public catalogue.
