# Avocet Production Pipeline

This is the supported Avocet workflow for recreating the UKMO NIMROD aggregate and pvol datasets from raw data on JASMIN.

## Source And Outputs

Raw source data remains the source of truth:

```text
/badc/ukmo-nimrod/data/single-site
```

The daily aggregate HDF5 database is stored on the NCAS Radar GWS only:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site
```

The aggregate converter uses the deployed `Nimrod_convert_and_aggregate` code, including the bad-time rollback fix and HDF5 verification. Production aggregate output is gzip level 4 with HDF5 shuffle enabled. Aggregates are not published to HPOS because the provisioned object-store allocation is for pvol only.

The pvol files used by vol2bird and bioRad are stored on GWS here:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site
```

The public object-store layout is:

```text
ukmo-nimrod/pvol/{radar}/{YYYY}/{MM}/{DD}/{pulse}/{filename}.h5
ukmo-nimrod/catalog/pvol/catalog.json
ukmo-nimrod/catalog/pvol/coverage.json
ukmo-nimrod/catalog/pvol/coverage.csv
ukmo-nimrod/catalog/pvol/{radar}/{YYYY}/coverage.json
ukmo-nimrod/catalog/pvol/{radar}/{YYYY}/{MM}/{DD}/catalog.json
```

## Full Rebuild

Use this when the aggregate and pvol databases must be recreated from raw data:

```bash
cd /home/users/rrniii/uk-wsr-visualizer
nohup env MAX_ACTIVE=2500 PVOL_UPLOAD_WORKERS=96 \
  bash tools/jasmin_pipeline/run_full_avocet_rebuild.sh \
  > /gws/ssde/j25a/ncas_radar/vol2/avocet/full_rebuild_logs/full_rebuild.nohup 2>&1 < /dev/null &
```

The wrapper runs the full compressed aggregate rewrite, validates aggregate coverage, submits the vol2birdinput update, waits for those jobs to finish, uploads pvol files, and rebuilds the public pvol catalog. The pvol uploader runs locally from the wrapper host by default; set `PVOL_UPLOAD_HOST` only when host-to-host SSH has been configured and tested.

## Daily Cron

The daily update path is:

```bash
/home/users/rrniii/uk-wsr-visualizer/tools/jasmin_pipeline/run_daily_avocet_pipeline.sh
```

Cron should run it on `cron-01.jasmin.ac.uk` at 20:00 UTC:

```cron
CRON_TZ=UTC
0 20 * * * crontamer -t 23h -l /home/users/rrniii/uk-wsr-visualizer/tools/jasmin_pipeline/run_daily_avocet_pipeline.sh
```

The daily wrapper runs the existing Nimrod daily aggregate update, waits for aggregate validation, runs the stale pvol update, waits for pvol-generating jobs, then uploads the recent pvol window to object store. The default pvol upload window is the last 14 UTC days so late raw arrivals and reruns are picked up. The uploader runs on the cron host unless `PVOL_UPLOAD_HOST` is explicitly set.

## Production Tools

- `tools/jasmin_pipeline/run_full_avocet_rebuild.sh`: full from-raw rebuild, pvol generation, and pvol upload.
- `tools/jasmin_pipeline/run_daily_avocet_pipeline.sh`: cron-safe daily aggregate, pvol, and upload workflow.
- `tools/jasmin_pvol_upload/launch_fast_pvol_upload.sh`: detached pvol upload launcher for full or date-windowed uploads.
- `tools/jasmin_pvol_upload/fast_pvol_upload_worker.py`: shard worker that syncs pvol pulse directories to HPOS.
- `tools/build_pvol_catalog_mirror.py`: builds JSON and CSV pvol catalogs and optionally uploads them.
- `jasmin_code/Nimrod_convert_and_aggregate/run_full_compressed_rewrite.sh`: deployed aggregate full rewrite driver.
- `jasmin_code/Nimrod_convert_and_aggregate/run_daily_update.sh`: deployed aggregate daily update driver.
- `jasmin_code/Nimrod_convert_and_aggregate/run_validate_and_vol2birdinput_after_aggregates.sh`: aggregate validation and pvol submission driver.

## Retired Workflows

The old `uk-radar/raw-volume` and aggregate object-store backfill scripts are retired for Avocet production. Do not use them to recreate the dataset. The maintained object-store product is pvol under `ukmo-nimrod/pvol`; aggregate HDF5 stays on GWS.
