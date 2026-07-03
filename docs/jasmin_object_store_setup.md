# JASMIN Object Store Setup

> Current Avocet production publishes pvol files under `ukmo-nimrod/pvol` and keeps aggregate HDF5 on GWS.
> Aggregate/pvol creation, checking, and upload are maintained on JASMIN at `/home/users/rrniii/bin/avocet_pipeline`, outside this app repository.
> The generic UK WSR Visualizer object-store commands below are retained for app-oriented metadata/publication workflows.

UK WSR Visualizer can publish approved UK WSR aggregate HDF5 source objects and
browser-ready metadata products to the JASMIN Object Store. Original restricted
archives should stay private unless redistribution is explicitly approved. The
community-facing dataset should be the approved UK WSR aggregate HDF5 source
objects plus derived STAC/catalog, preview, tile, and status products.

## Required Information

1. Object Store tenancy name from the JASMIN Accounts Portal.
2. Confirmation that your JASMIN account is a tenancy `MANAGER` or `DEPUTY`, or that the manager has granted your service account write access to the buckets. JASMIN notes that manager/deputy roles have admin access, while ordinary users only get default access to buckets they own.
3. Two buckets in that tenancy:
   - `uk-wsr-visualizer-staging`
   - `uk-wsr-visualizer-public`
4. S3 access key and secret for the service account or user that will run sync jobs. JASMIN's CORS guidance requires a valid S3 token ID and secret key before bucket CORS can be modified.
5. The final public web origin for CORS. Use `*` only for the first smoke test; after that use the deployed HTTPS origin or the exact workstation origin.
6. Confirmation that UK WSR aggregate HDF5 files may be publicly redistributed. Do not publish original NIMROD archives unless separate redistribution approval exists.
7. Confirmation of where credentials will live on the worker or workstation, for example `~/.aws/credentials`, `~ukwsr/.aws/credentials`, or a locked-down systemd environment file readable only by `root:ukwsr`.
8. Expected quota and retention policy for the public bucket. Aggregate HDF5 objects can be large, and JASMIN advises larger multipart upload chunks for files in the tens-of-GB range.
9. A short public dataset description, licence/terms text, citation text, and support contact to include beside the STAC/catalog landing page.

Put item 9 into `/etc/uk-wsr-visualizer/object_store.toml` using:

```toml
dataset_title = "UK WSR aggregate HDF5"
dataset_description = "Daily ODIM-like aggregate HDF5 files produced by the UK WSR pipeline."
dataset_license = "proprietary"
dataset_citation = ""
dataset_provider_name = "NCAS Radar Science Group"
dataset_provider_url = ""
dataset_contact_email = ""
dataset_terms_url = ""
```

These values are copied into STAC `catalog.json`, STAC `collection.json`, per-item STAC metadata, and public `status.json`.

The deployed workstation also exposes the same release metadata at `/api/public/dataset` and a human-readable landing page at `/public`, using the local verified object-store manifest when present.

Relevant JASMIN docs:

- [The JASMIN Object Store](https://help.jasmin.ac.uk/docs/short-term-project-storage/object-store/jasmin-object-store/)
- [Configuring CORS for object storage](https://help.jasmin.ac.uk/docs/short-term-project-storage/object-store/configuring-cors-for-object-storage/)

## Endpoint Pattern

JASMIN currently documents separate endpoint names for internal and external access:

- Internal/JASMIN processing: `http://{tenancy}-o.s3.jc.rl.ac.uk`
- External/community browser reads: `https://{tenancy}-o.s3-ext.jc.rl.ac.uk`

Set these in `configs/object_store.example.toml`, then save the real file outside version control as `configs/object_store.local.toml`.

Use the internal endpoint for LOTUS, sci-server, and GWS-side processing jobs. Use the external endpoint for the deployed browser UI, STAC asset links, public inventory, and community download URLs.

## Setup Actions

1. Request or join the Object Store tenancy through the JASMIN Accounts Portal and confirm who is manager/deputy.
2. Create `uk-wsr-visualizer-staging` and `uk-wsr-visualizer-public` in the tenancy.
3. Decide whether the sync identity is your user token or a named service account. Generate/store the S3 token ID and secret.
4. Grant the sync identity write access to both buckets. Grant anonymous or community read access only to the public bucket and only after redistribution approval is recorded.
5. Record the tenancy name, bucket names if different, public browser origin, and where credentials should live on the deployment host or JASMIN worker.
6. Confirm the public release scope: UK WSR aggregate HDF5 source objects, STAC/catalog JSON, checksums, previews, tiles, and release-validation reports. Keep `publish_exports = false`; user-generated exports should stay outside the public dataset unless a separate release policy is agreed.
7. Apply CORS to the public bucket with `GET` and `HEAD`, then run a browser fetch smoke test from the deployed origin.
8. Provide one representative radar/day for a first live sync rehearsal and one larger backfill window for performance/quota testing.

## Public Prefix Layout

The publication tools write under `uk-radar/`:

- `uk-radar/index.html`
- `uk-radar/dataset.json`
- `uk-radar/aggregate-h5/radar={radar}/year={YYYY}/{YYYYMMDD}_polar_pl_radar{num}_aggregate.h5`
- `ukmo-nimrod/catalog/pvol/catalog.json`
- `uk-radar/catalog/stac/catalog.json`
- `uk-radar/catalog/stac/uk-wsr-aggregate-h5/collection.json`
- `uk-radar/catalog/stac/uk-wsr-aggregate-h5/{radar}-{YYYYMMDD}.json`
- `uk-radar/previews/...`
- `uk-radar/tiles/radar={radar}/date={YYYYMMDD}/pulse={pulse}/quantity={quantity}/...`
- `uk-radar/checksums/sha256/{YYYY}/{radar}.json`
- `uk-radar/validation/...`
- `uk-radar/exports/job={job_id}/...`
- `uk-radar/exports/animations/...`
- `uk-radar/exports/math/...`
- `uk-radar/manifests/sync-runs/{run_id}.json`
- `uk-radar/manifests/latest.json`
- `uk-radar/status.json`

## CORS

The browser needs `GET` and `HEAD` on the public bucket. Generate the XML template:

```bash
uk-wsr-visualizer object-store cors-template \
  --config configs/object_store.local.toml \
  --output data/uk-wsr-visualizer/object-store/cors.xml
```

Apply it with the S3-compatible tool configured for your JASMIN credentials, for example:

```bash
s3cmd setcors data/uk-wsr-visualizer/object-store/cors.xml s3://uk-wsr-visualizer-public
s3cmd info s3://uk-wsr-visualizer-public
```

## Dry-Run Publication Workflow

Build or refresh the catalog first:

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output data/uk-wsr-visualizer/catalog.json \
  --object-store-base https://TENANCY-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

Create a publication plan. This computes SHA256 checksums and stages generated public inventory, per-radar/year checksum manifests, STAC, and status JSON locally. The published inventory redacts private GWS/local source paths:

```bash
uk-wsr-visualizer object-store plan \
  --config configs/object_store.local.toml \
  --catalog data/uk-wsr-visualizer/catalog.json \
  --staging-dir data/uk-wsr-visualizer/object-store/staging \
  --preview-dir data/uk-wsr-visualizer/previews \
  --tile-dir data/uk-wsr-visualizer/tiles \
  --export-dir data/uk-wsr-visualizer/exports \
  --validation-dir data/uk-wsr-visualizer/validation \
  --output data/uk-wsr-visualizer/object-store/plan.json
```

Tiles are included when `publish_tiles = true`, which is the default in `configs/object_store.example.toml`.

Release validation reports are included when `publish_validation_reports = true` and `--validation-dir` points at generated validation reports. `status.json` summarizes report counts and validation status.

Generated products are included only when `publish_exports = true` is set in the object-store config. Keep that off until a release process decides which export, animation, and math products should be public.

Dry-run sync, verify, and publish:

```bash
uk-wsr-visualizer object-store sync \
  --config configs/object_store.local.toml \
  --plan data/uk-wsr-visualizer/object-store/plan.json \
  --manifest data/uk-wsr-visualizer/object-store/synced.json

uk-wsr-visualizer object-store verify \
  --config configs/object_store.local.toml \
  --manifest data/uk-wsr-visualizer/object-store/synced.json \
  --output data/uk-wsr-visualizer/object-store/verified.json

uk-wsr-visualizer object-store publish \
  --config configs/object_store.local.toml \
  --manifest data/uk-wsr-visualizer/object-store/verified.json \
  --output data/uk-wsr-visualizer/object-store/published.json
```

Run the operational freshness gate:

```bash
uk-wsr-visualizer freshness check \
  --catalog data/uk-wsr-visualizer/catalog.json \
  --object-store-manifest data/uk-wsr-visualizer/object-store/verified.json \
  --require-object-store
```

Create a release-candidate summary before enabling live publication or advertising a public update:

```bash
uk-wsr-visualizer object-store release-candidate \
  --config configs/object_store.local.toml \
  --catalog data/uk-wsr-visualizer/catalog.json \
  --manifest data/uk-wsr-visualizer/object-store/verified.json \
  --staging-dir data/uk-wsr-visualizer/object-store/release-candidate-staging \
  --preview-dir data/uk-wsr-visualizer/previews \
  --tile-dir data/uk-wsr-visualizer/tiles \
  --export-dir data/uk-wsr-visualizer/exports \
  --validation-dir data/uk-wsr-visualizer/validation \
  --plan-output data/uk-wsr-visualizer/object-store/release-candidate-plan.json \
  --output data/uk-wsr-visualizer/object-store/release-candidate-summary.json
```

The command exits non-zero unless sources are present, the candidate plan matches the manifest, all manifest objects are verified, public inventory is sanitized, and required release validation checks pass.

Add `--execute` only after the dry-run manifest looks right and the credentials are configured:

```bash
uk-wsr-visualizer object-store sync --execute ...
uk-wsr-visualizer object-store verify --execute ...
uk-wsr-visualizer object-store publish --execute ...
```

## Deployment Target

Use `ncas-rsg-cloud-workstation-ssh` at `130.246.214.121` for the web implementation host. The workstation should run:

- FastAPI service and static frontend behind Nginx.
- Read-only API access to the local catalog and latest object-store manifest.
- No heavy HDF5 rendering jobs except small admin/debug operations.

Keep the heavy catalog, preview, tile, and export work on JASMIN/GWS-side workers. Use systemd timers on the workstation or JASMIN worker to run:

- catalog refresh
- preview/tile generation
- object-store plan
- object-store sync
- object-store verify
- object-store publish
- freshness/reconcile checks

## Minimum Production Gate

Do not advertise the dataset publicly until:

1. `status.json` is present in the public bucket.
2. `index.html` and `dataset.json` are present and contain the approved licence, citation, and contact metadata.
3. `manifests/latest.json` exists and all required objects are `verified`.
4. Browser CORS succeeds from the deployed web origin.
5. Checksums for a sample of aggregate HDF5 objects match local GWS source files.
6. The public catalog inventory contains no private GWS-only source paths.
7. Release validation reports are present under `validation/` when enabled, and every release-critical check has passed.
