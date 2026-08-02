# First Look from One Public Volume

This example downloads one 6.6 MB public HDF5 object, creates a one-item local
catalogue, and renders Horizontal Reflectivity (DBZH) at 0.50 degrees.

## Download the source

~~~bash
mkdir -p /tmp/uk-wsr-example/castor-bay/2014/09/18/lp
curl --fail --location \
  --output /tmp/uk-wsr-example/castor-bay/2014/09/18/lp/20140918_polar_pl_radar07_aggregate_lp_1535.h5 \
  "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/pvol/castor-bay/2014/09/18/lp/20140918_polar_pl_radar07_aggregate_lp_1535.h5"
~~~

## Build a one-volume catalogue

~~~bash
uk-wsr-visualizer catalog build-raw-volume \
  --raw-volume-base /tmp/uk-wsr-example \
  --output /tmp/uk-wsr-example/catalog.json \
  --radar castor-bay \
  --date 20140918 \
  --object-store-base "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public" \
  --metadata-mode deep
~~~

Expected summary:

~~~text
wrote 1 raw-volume catalog item(s), 1 volume file(s)
~~~

Deep metadata inspection finds five sweeps at 0.50, 0.95, 2.00, 3.00, and
4.00 degrees. Each sweep has 360 rays and 425 gates in this volume.

## Render the baseline range-azimuth preview

~~~bash
uk-wsr-visualizer preview build \
  --catalog /tmp/uk-wsr-example/catalog.json \
  --radar castor-bay \
  --date 20140918 \
  --pulse lp \
  --time 1535 \
  --quantity DBZH \
  --dataset 1 \
  --palette homeyer \
  --qc-mode off \
  --preview-dir /tmp/uk-wsr-example/previews
~~~

~~~{figure} ../_static/example-castor-bay-20140918-lp-1535-dbzh.png
:alt: Baseline range-azimuth preview of Castor Bay Horizontal Reflectivity at 1535 UTC on 18 September 2014
:width: 720px

Tested baseline CLI preview for Castor Bay, 18 September 2014, long pulse,
15:35 UTC, Horizontal Reflectivity (DBZH), dataset 1 at 0.50 degrees. This is a
range-azimuth array preview, not the georeferenced PPI shown over a map in the
desktop application.
~~~

## What this proves

- The object URL is readable without authentication.
- The filename, pulse, time, and radar identifiers decode as expected.
- The catalogue inventory matches the HDF5 contents.
- A source-preserving baseline can be rendered before optional cleanup.

It does not establish that every visible echo is weather or biological signal.
That question requires scientific interpretation and, where appropriate,
validated downstream processing.
