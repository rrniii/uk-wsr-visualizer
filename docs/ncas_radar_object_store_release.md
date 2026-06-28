# NCAS Radar Object Store Release Setup

> Current Avocet production uses `ukmo-nimrod/pvol` and does not publish aggregate HDF5 to HPOS.
> This page is retained as a historical note for the earlier `uk-radar` rehearsal release.
> Current aggregate/pvol creation, checking, and upload are maintained on JASMIN at `/home/users/rrniii/bin/avocet_pipeline`, outside this app repository.

This operational note records the earlier release choices for UK WSR Visualizer
object-store data.

## Tenancy

- Tenancy: `ncas-radar-o`
- Required tenancy role: Manager or Deputy
- Staging bucket: `uk-wsr-visualizer-staging`
- Public bucket: `uk-wsr-visualizer-public`
- Public prefix: `uk-radar`
- Internal endpoint: `http://ncas-radar-o.s3.jc.rl.ac.uk`
- External endpoint: `https://ncas-radar-o.s3-ext.jc.rl.ac.uk`
- Public base URL: `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public`

## Operations Log

- 2026-06-23: Created `uk-wsr-visualizer-staging`.
- 2026-06-23: Created `uk-wsr-visualizer-public`.
- 2026-06-23: Applied CORS to `uk-wsr-visualizer-public` for `http://130.246.214.121` and `https://130.246.214.121`.
- 2026-06-23: Started deletion of non-empty `ukmo-nimrod` after cleanup approval. The bucket contained many derived plot objects, so deletion was moved to a detached JASMIN cleanup job on `sci1`.
- 2026-06-23: Completed the Chenies 2018-04-01 live object-store rehearsal with aggregate HDF5, STAC/catalog JSON, checksums, previews, tile pyramid, and public status/manifest objects.
- 2026-06-23: Confirmed public HTTPS access for `uk-radar/status.json`, `uk-radar/dataset.json`, `uk-radar/manifests/latest.json`, and the Chenies 2018-04-01 aggregate HDF5.
- 2026-06-23: Added `catalog build --metadata-mode fast` for full-year backfill planning without deep HDF5 traversal.
- 2026-06-23: Added object-store `sync --skip-existing` so interrupted or repeated backfills skip remote objects whose size and SHA-256 metadata already match.
- 2026-06-23: Added `object-store plan --sha256-cache` and updated the backfill runner to cache aggregate SHA-256 values between monthly plans and the final full-year manifest.
- 2026-06-23: Started detached Chenies 2018 full-year backfill on `sci1`, then restarted it with SHA-256 caching after the first uncached January planning attempt proved too slow. The runner was then changed from month-level batches to day-level batches, so each aggregate is hashed, uploaded, and verified independently before moving to the next day. Fast catalog result: 351 aggregate files, 1.773 TiB, missing days `20180204`, `20180210`, `20180211`, `20180212`, `20180214`, `20180215`, `20180216`, `20180217`, `20180218`, `20180219`, `20180220`, `20180224`, `20180225`, and `20180510`.
- 2026-06-24: Completed and published the Chenies 2018 full-year release. Public run ID: `chenies-2018-full-20260624T021843Z`. The published manifest contains 757 verified objects: 351 aggregate HDF5 files, 351 STAC items, 24 tiles, 22 validation reports, 2 previews, and the dataset/catalog/status/checksum objects. Public byte count: `1949203354595`.
- 2026-06-24: Confirmed public HTTPS `HEAD`/`GET` smoke checks for `uk-radar/status.json`, `uk-radar/manifests/latest.json`, `uk-radar/dataset.json`, `uk-radar/catalog/stac/catalog.json`, the first and last Chenies 2018 aggregate HDF5 objects, the public inventory, sample STAC items, and the checksum manifest. CORS returned `Access-Control-Allow-Origin: http://130.246.214.121`.
- 2026-06-24: Replaced the stalled `aws s3 rm --recursive` cleanup of `ukmo-nimrod` with `deploy/bin/uk-wsr-visualizer-purge-bucket.py`, a bounded boto3 batch purge utility. It deleted 220,000 listed plot objects before the old bucket reached two inconsistent residual entries. The final two entries still appear in `list_objects_v2`, but `head_object` returns 404 and repeated boto3/AWS CLI deletes return success without removing them from the listing. Bucket deletion remains blocked by `BucketNotEmpty` and likely needs JASMIN Object Store support cleanup.
- Detached cleanup PID file: `~/avocet-delete-ukmo-nimrod.pid` on `sci1`.
- Detached cleanup log: `~/avocet-delete-ukmo-nimrod.log` on `sci1`.
- Detached Chenies 2018 backfill PID file: `~/avocet-chenies-2018-backfill.pid` on `sci1`.
- Detached Chenies 2018 backfill log: `~/avocet-chenies-2018-backfill.log` on `sci1`.
- Detached Chenies 2018 backfill pre-cache log: `~/avocet-chenies-2018-backfill.precache.log` on `sci1`.
- Detached Chenies 2018 backfill month-batch log: `~/avocet-chenies-2018-backfill.month-batch.log` on `sci1`.
- Chenies 2018 SHA-256 cache: `~/uk-wsr-visualizer/data/uk-wsr-visualizer/object-store/backfill/chenies-2018/sha256-cache.json` on `sci1`.
- Chenies 2018 published manifest: `~/uk-wsr-visualizer/data/uk-wsr-visualizer/object-store/backfill/chenies-2018/verified-chenies-2018-full.json` on `sci1`.
- Latest public manifest URL: `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/manifests/latest.json`.

## Current Status

As of 2026-06-27, broad object-store transfer jobs are paused. The public bucket
contains the verified Chenies 2018 staged release plus supporting catalogue,
status, checksum, STAC, preview, tile, and validation objects. The data plan is
to keep that staged subset available for app and documentation testing while the
formal source-data citation, licence/access wording, quota, retention policy,
and next publication window are confirmed.

No generated user exports are part of the public release at this stage.

## Credentials

Use AWS profile `ncas-radar-o` in `~/.aws/credentials` on the account that runs live sync. The template is:

```text
configs/aws_credentials.ncas-radar-o.template
```

The real credential file should look like:

```ini
[ncas-radar-o]
aws_access_key_id = JASMIN_S3_TOKEN_ID
aws_secret_access_key = JASMIN_S3_SECRET_KEY
```

Do not store real secrets in this repository.

## First Release Scope

- Public release scope: approved UK WSR aggregate HDF5 outputs.
- Original NIMROD archives are excluded.
- Publish all approved aggregate HDF5 objects, STAC/catalog JSON, checksums, previews, tiles, and release validation reports.
- Keep generated user exports private for now: `publish_exports = false`.
- No retention limit requested; publish the complete approved dataset after the rehearsal and one-year backfill pass.

## Rehearsal Inputs

- First radar/day rehearsal: Chenies, 2018-04-01.
- Toolkit radar slug: `chenies`.
- Radar number: `05`.
- Aggregate filename: `20180401_polar_pl_radar05_aggregate.h5`.
- First larger backfill: Chenies, full year 2018.

## CORS Origin

Initial allowed origins are:

- `http://130.246.214.121`
- `https://130.246.214.121`

Replace or extend these when a final DNS name is attached to `ncas-rsg-cloud-workstation-ssh`.

## Commands

Dry-run bucket administration:

```bash
uk-wsr-visualizer object-store buckets \
  --config configs/object_store.local.toml \
  --delete-empty-bucket ukmo-nimrod \
  --create-bucket uk-wsr-visualizer-staging \
  --create-bucket uk-wsr-visualizer-public
```

Live bucket administration after the `ncas-radar-o` AWS profile is installed:

```bash
uk-wsr-visualizer object-store buckets --execute \
  --config configs/object_store.local.toml \
  --delete-empty-bucket ukmo-nimrod \
  --create-bucket uk-wsr-visualizer-staging \
  --create-bucket uk-wsr-visualizer-public
```

This probes `ukmo-nimrod` first and only deletes it if the bucket is already empty. It does not recursively remove bucket contents; a non-empty bucket is reported as `not_empty` and left untouched.

Create the Chenies day catalog:

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output data/uk-wsr-visualizer/catalog-chenies-20180401.json \
  --radar chenies \
  --year 2018 \
  --max-files 1 \
  --object-store-base https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

Create the Chenies 2018 catalog:

```bash
uk-wsr-visualizer catalog build \
  --aggregate-base /gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site \
  --output data/uk-wsr-visualizer/catalog-chenies-2018-fast.json \
  --radar chenies \
  --year 2018 \
  --metadata-mode fast \
  --object-store-base https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public
```

Historical note: the rehearsal used a resumable JASMIN year backfill runner that has now been removed from the production tree. Current Avocet production operations are maintained directly on JASMIN, outside this app repository.

The retired runner uploaded raw HDF5 aggregates one day at a time using `object-store sync --skip-existing` and a persistent `sha256-cache.json`. After all daily raw batches verified, it built a cumulative full-year plan, synced any missing generated metadata/STAC/previews/tiles/validation reports, verified all objects, and published `uk-radar/manifests/latest.json`.

For large completed backfills, the runner avoids re-checking multi-TiB aggregate objects in the final cumulative sync. It syncs/verifies only non-aggregate release objects, then merges the per-day verified aggregate manifests into the final full-year manifest.

Monitor the running Chenies 2018 backfill:

```bash
ssh sci1 'cd ~/uk-wsr-visualizer && \
  PYTHONPATH="$PWD/.deps:$PWD/src" \
  /apps/jasmin/jaspy/miniforge_envs/jaspy3.12/mf3-25.3.0-3/bin/python -B \
  -m uk_wsr_visualizer.cli object-store backfill-status \
  --backfill-dir data/uk-wsr-visualizer/object-store/backfill/chenies-2018'
```

For process/log details:

```bash
ssh sci1 'pid=$(cat ~/avocet-chenies-2018-backfill.pid 2>/dev/null || true); \
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo backfill_running pid=$pid; else echo backfill_not_running pid=$pid; fi; \
  tail -50 ~/avocet-chenies-2018-backfill.log; \
  python - <<'"'"'PY'"'"'
import json
from pathlib import Path
p = Path("~/uk-wsr-visualizer/data/uk-wsr-visualizer/object-store/backfill/chenies-2018/sha256-cache.json").expanduser()
if p.exists():
    entries = json.loads(p.read_text()).get("entries", {})
    print("sha256_cache_entries", len(entries), "bytes", sum(int(v.get("size", 0)) for v in entries.values()))
else:
    print("sha256_cache_entries", 0)
PY'
```

Monitor the old `ukmo-nimrod` purge:

```bash
ssh sci1 'pid=$(cat ~/avocet-delete-ukmo-nimrod.pid 2>/dev/null || true); \
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then echo cleanup_running pid=$pid; else echo cleanup_not_running pid=$pid; fi; \
  tail -20 ~/avocet-delete-ukmo-nimrod.log; \
  AWS_PAGER= aws --profile ncas-radar-o --endpoint-url http://ncas-radar-o.s3.jc.rl.ac.uk \
    s3api list-objects-v2 --bucket ukmo-nimrod --max-keys 1 \
    --query "{KeyCount:KeyCount,FirstKey:Contents[0].Key}" --output json'
```

Generate CORS XML:

```bash
uk-wsr-visualizer object-store cors-template \
  --config configs/object_store.local.toml \
  --output data/uk-wsr-visualizer/object-store/cors.xml
```

Dry-run a publication plan:

```bash
uk-wsr-visualizer object-store plan \
  --config configs/object_store.local.toml \
  --catalog data/uk-wsr-visualizer/catalog-chenies-20180401.json \
  --staging-dir data/uk-wsr-visualizer/object-store/staging \
  --preview-dir data/uk-wsr-visualizer/previews \
  --tile-dir data/uk-wsr-visualizer/tiles \
  --export-dir data/uk-wsr-visualizer/exports \
  --validation-dir data/uk-wsr-visualizer/validation \
  --output data/uk-wsr-visualizer/object-store/plan-chenies-20180401.json
```

Live sync only after credentials, buckets, CORS, and the dry-run plan are verified:

```bash
uk-wsr-visualizer object-store sync --execute \
  --skip-existing \
  --config configs/object_store.local.toml \
  --plan data/uk-wsr-visualizer/object-store/plan-chenies-20180401.json \
  --manifest data/uk-wsr-visualizer/object-store/synced-chenies-20180401.json
```

## Current Public Smoke-Test URLs

- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/status.json`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/dataset.json`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/manifests/latest.json`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/stac/catalog.json`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/catalog/inventory/catalog.json`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/aggregate-h5/radar=chenies/year=2018/20180401_polar_pl_radar05_aggregate.h5`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/aggregate-h5/radar=chenies/year=2018/20180101_polar_pl_radar05_aggregate.h5`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/aggregate-h5/radar=chenies/year=2018/20181231_polar_pl_radar05_aggregate.h5`
- `https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/uk-radar/checksums/sha256/2018/chenies.json`

## Current `ukmo-nimrod` Cleanup Blocker

All but two objects have been purged from the old `ukmo-nimrod` bucket. The remaining listed keys are:

```text
plots/High Moorsley/2017-02-03/lp/ele4_0/240km/High Moorsley_2017-02-03T062618Z_ele4_0_lp.png
plots/Thurnham/2014-01-31/sp/ele9_0/60km/Thurnham_2014-01-31T153056Z_ele9_0_sp.png
```

Observed behavior on 2026-06-24:

- `list_objects_v2` and `list_object_versions` still show both keys with `VersionId: "null"`.
- `head_object` returns 404 for both keys.
- `delete_object`, `delete_objects`, and `aws s3 rm` return success/204 but the keys remain listed.
- `delete_bucket` returns `BucketNotEmpty`.

Escalate this exact state to JASMIN Object Store support if it persists; it appears to be a bucket index/versioning inconsistency rather than an application-side permission or key-encoding issue.
