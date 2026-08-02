# Provenance Export

This example creates a metadata export and inspects the manifest without
producing another radar image.

First complete the [one-volume catalogue](first_look.md), then run:

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

The command prints the job directory and
`artifact-manifest.json`. The tested manifest contains this core selection:

~~~json
{
  "coordinate_mode": "catalog_metadata",
  "selection": {
    "radar": "castor-bay",
    "date": "20140918",
    "pulse": "lp",
    "time": "1535",
    "quantity": "DBZH",
    "quantity_label": "Horizontal Reflectivity",
    "dataset": "1",
    "filters": {
      "qc_mode": "off"
    }
  },
  "software": {
    "name": "UK WSR Visualizer",
    "version": "0.2.2"
  },
  "infrastructure": {
    "jasmin_acknowledgement": "This work used JASMIN, the UK's collaborative data analysis environment."
  }
}
~~~

The full manifest also records the source object key and URL, artifact checksum,
software commit, citation instructions, and explicit pending fields for records
that have not yet been published.

## Review before sharing

1. Confirm the source object matches the volume used.
2. Confirm the coordinate mode matches the artifact.
3. Confirm filters and QC mode match the intended scientific comparison.
4. Keep the manifest beside the exported artifact.
5. Replace pending citation text only with the final approved records.
