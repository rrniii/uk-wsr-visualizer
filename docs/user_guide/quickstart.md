# Quick Start

This page gives a minimal path for running the toolkit from a checkout.

## Start the API and browser UI

```bash
git clone git@github.com:rrniii/uk-wsr-qc.git
git clone git@github.com:rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
python -m venv .venv
. .venv/bin/activate
pip install -e ../uk-wsr-qc
pip install -e ".[dev,export]"
uk-wsr-visualizer api --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

When no local catalog is supplied, the application uses its configured catalog path. For public community use, the current JASMIN Object Store catalog endpoint is:

```text
https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/ukmo-nimrod/catalog/pvol/catalog.json
```

## Build a local catalog

For a JASMIN/GWS-side checkout with access to the aggregate HDF5 files:

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output data/catalog.json
```

Then start the API against that catalog:

```bash
uk-wsr-visualizer api --catalog data/catalog.json --host 127.0.0.1 --port 8000
```

## Generate one preview

```bash
uk-wsr-visualizer preview build \
  --catalog data/catalog.json \
  --radar chenies \
  --date 20240101 \
  --pulse long \
  --time 120000 \
  --quantity DBZH \
  --palette homeyer
```

Adjust the radar, date, pulse, time, quantity, and dataset selectors to match the catalog item you are working with.

## Run tests

```bash
pytest
```
