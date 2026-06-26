# BirdCast UK Implementation Plan

This plan describes how to build a UK migration monitoring and forecasting system inspired by BirdCast, using the existing UK WSR Visualizer UK Met Office Nimrod radar pipeline, ERA5 assets from the GAMB2LE project, JASMIN storage/compute, and a JASMIN Cloud web server.

## 1. Working Assumptions

- Raw UK radar data are already available on JASMIN.
- Existing UK WSR Visualizer code converts single-site Nimrod raw radar archives into daily ODIM-like HDF5 aggregate files.
- ERA5 data and ERA5 download/processing helpers are available in the GAMB2LE project.
- Heavy radar conversion, feature generation, backfills, and model inference should run on JASMIN LOTUS or JASMIN batch resources.
- The JASMIN Cloud server should serve the website/API and run only light operational tasks.
- There is no evidence of a public, complete, official BirdCast production codebase. The practical open-source building blocks are `vol2bird`, `bioRad`, `vol2birdR`, MistNet-related work, and published methods.

## 2. Existing Local Assets

### UK WSR Visualizer Nimrod Conversion Pipeline

The current local code under `jasmin_code/Nimrod_convert_and_aggregate/` already provides the upstream radar data foundation:

- `convert_all_files.sh` submits Slurm jobs for all 17 UK radars and writes daily aggregate HDF5 files.
- `convert_and_aggregate.py` converts raw single-site Nimrod files into ODIM_H5/V2_4-like aggregate files with `lp`, `sp`, and `ldr` pulse groups where available.
- `check_aggregate_raw_coverage.py` compares raw LP/SP availability with aggregate coverage.
- `find_aggregate_repair_candidates.py` checks aggregate integrity, including missing pulse groups, non-contiguous datasets, partial volumes, and bad `elangles_map` metadata.
- `submit_repair_candidates.sh` resubmits failed or suspicious aggregate days.
- `run_daily_update.sh` runs the daily operational aggregate update on JASMIN GWS.
- `run_validate_and_vol2birdinput_after_aggregates.sh` already points to a downstream JASMIN-only BioDAR/bioRad workflow at:
  `/home/users/rrniii/ncas_radar_smf_rrniii/BioDAR/ukmo_biorad`

That last path is the highest-priority missing codebase to inspect. It likely contains the first version of the aggregate-to-biological-radar-product bridge.

### GAMB2LE ERA5 Tooling

The GAMB2LE project has reusable ERA5 patterns in:

- `/Users/rrniii/Documents/GAMB2LE/aurora-les/src/aurora_les/model_adapters/era5.py`
- `/Users/rrniii/Documents/GAMB2LE/aurora-les/docs/era5_cds_api.md`
- `/Users/rrniii/Documents/GAMB2LE/aurora-cloud-infra`

Useful pieces include:

- CDS request builders for ERA5 single-level and pressure-level data.
- Safe archive extraction.
- xarray/netCDF reading and subsetting.
- Site-coordinate handling.
- JASMIN Cloud deployment patterns with Ansible, Nginx, systemd timers, and Python environments.

Important limitation: ERA5 is a reanalysis product, so it is excellent for training, hindcasts, backtesting, and historical feature generation. It is not a future forecast feed. The operational BirdCast UK forecast will need a future NWP source with comparable variables, such as ECMWF forecast data, Met Office NWP access, or a public global forecast feed.

## 3. Target Products

The first version should aim for BirdCast-like products without overclaiming precision:

- Recent migration intensity map from radar-derived biological echoes.
- Nightly radar summaries by radar and UK-wide region.
- 1 to 3 night forecast maps, once an operational NWP feed is selected.
- Local migration dashboard by radar/site.
- API endpoints for current intensity, forecast intensity, and radar metadata.
- Downloadable research tables for vetted radar-night products.

Initial outputs should emphasize relative intensity, migration traffic rate, direction, speed, altitude distribution, and uncertainty. Absolute "number of birds" estimates should be treated as a later calibrated product.

## 4. Proposed Storage Layout on JASMIN

Keep existing aggregate outputs unchanged, then add a downstream BirdCast UK project root.

Existing aggregate input:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/raw_h5_data_final/single-site/{radar}/{year}/{date}_polar_pl_radar{num}_aggregate.h5
```

New project root:

```text
/gws/ssde/j25a/ncas_radar/vol2/avocet/birdcast-uk/
```

Suggested downstream layout:

```text
birdcast-uk/
  manifests/
    aggregate_coverage.parquet
    vpts_coverage.parquet
    processing_runs.parquet
  vpts/
    radar={radar}/year={YYYY}/date={YYYYMMDD}.parquet
  nightly/
    radar_metrics/year={YYYY}/part-*.parquet
    regional_metrics/year={YYYY}/part-*.parquet
  weather/
    era5_site_features/year={YYYY}/part-*.parquet
    era5_grid_features/year={YYYY}/part-*.zarr
    forecast_features/source={source}/cycle={cycle}/
  models/
    {model_id}/
      config.yaml
      model.pkl
      metrics.json
      feature_schema.json
  public/
    latest/
      status.json
      recent_migration.json
      forecast_1_to_3_nights.json
      radar_sites.json
    tiles/
    archive/
```

Use Parquet for tabular radar-night and radar-altitude products. Use Zarr for gridded weather and gridded forecast features. Use compact JSON, PMTiles, Cloud Optimized GeoTIFF, or precomputed vector tiles for web artifacts.

## 5. Processing Architecture

### Stage A: Radar Aggregate QA

Use the existing UK WSR aggregate pipeline as the upstream source of truth.

Inputs:

- Raw Nimrod single-site radar archives.

Outputs:

- Daily aggregate HDF5 files.
- Aggregate coverage manifest.
- Repair candidate manifest.

Implementation:

- Keep current `run_daily_update.sh` and validation scripts.
- Add a small manifest writer that records aggregate file path, radar, date, pulse groups, scan counts, elevations, file size, validation status, and processing timestamp.

### Stage B: Biological Radar Extraction

Convert daily aggregate HDF5 into biological vertical profile products.

Preferred route:

- Inspect and reuse the existing JASMIN BioDAR/bioRad workflow referenced by `run_validate_and_vol2birdinput_after_aggregates.sh`.
- Standardize its outputs into a versioned VPTS schema.

Likely tools:

- `vol2bird` for weather-radar biological profile extraction.
- `bioRad` for reading, quality control, visualization, and VPTS handling.
- `vol2birdR` where useful for R-driven batch workflows.

Key decision:

- Confirm whether `vol2bird` can process the current daily aggregate structure directly.
- If not, add an exporter that writes per-volume ODIM files from the daily aggregate groups before running `vol2bird`.

Minimum VPTS fields:

- radar ID, radar name, latitude, longitude
- timestamp start/end
- altitude layer bounds
- reflectivity or bird density proxy
- migration traffic rate
- ground speed
- direction
- u/v biological velocity components
- radial velocity quality metrics
- rain/weather contamination flags
- pulse/elevation coverage metadata
- processing version

### Stage C: Nightly Radar Metrics

Aggregate VPTS products into radar-night records.

Core metrics:

- total migration traffic rate per night
- peak 10 minute, 30 minute, and hourly intensity
- median/weighted altitude
- altitude distribution bands
- mean and circular dispersion of direction
- mean speed
- first/last detected movement timing relative to sunset/sunrise
- quality flags for precipitation, missing scans, and anomalous data

Use local sunset/sunrise boundaries rather than calendar days.

### Stage D: Weather Feature Generation

Use ERA5 for historical model features.

Initial site-level features:

- 2 m temperature and dewpoint
- surface pressure and mean sea-level pressure
- pressure tendency
- 10 m wind
- pressure-level winds from 1000 to 700 hPa, and higher levels if relevant
- wind support, tailwind, crosswind, and wind profit along likely migration bearings
- relative humidity and specific humidity
- cloud cover by layer
- boundary layer height
- precipitation or rain proxies where available

Additional useful features:

- day-of-year sine/cosine
- night length
- sunset/sunrise times
- moon illumination and phase
- radar coordinates and regional grouping
- coast distance and broad habitat/land-sea context

Operational forecast requirement:

- Select a future NWP source and build a forecast-feature adapter with the same feature schema as the ERA5 historical adapter.
- Treat ERA5 as the training/backtesting source, not the live forecast source.

### Stage E: Modeling

Start simple, then increase sophistication only where validation shows value.

Baseline models:

- Climatology by radar and day-of-year.
- Persistence model using previous nights.
- Weather-conditioned generalized additive model or gradient boosted tree model.

Primary target:

- log migration intensity or migration traffic rate by radar-night.

Secondary targets:

- probability of high migration night
- timing of peak movement
- altitude distribution class
- broad movement direction class

Recommended first machine learning model:

- LightGBM, XGBoost, scikit-learn histogram gradient boosting, or a GAM.

Validation design:

- Blocked year holdout.
- Holdout radars.
- Seasonal holdout around spring/autumn peaks.
- Compare against climatology and persistence.
- Report calibration for "low", "moderate", "high", and "very high" migration classes.

Avoid deep learning for the first forecast model unless the simpler models fail. The main technical risk is not model capacity; it is biological signal quality, weather contamination, target definition, and operational data reliability.

### Stage F: Gridded Forecast Products

BirdCast-style maps require interpolation or spatial modeling.

First version:

- Predict at radar locations.
- Interpolate to a UK grid using conservative spatial smoothing.
- Mask low-confidence areas far from radar coverage.
- Publish uncertainty or confidence classes.

Later version:

- Train a spatiotemporal model that predicts on a regular UK grid using weather features, geography, seasonality, and radar-derived labels.

Output artifacts:

- radar-point GeoJSON
- gridded intensity GeoTIFF or Zarr
- web-optimized vector/raster tiles
- compact JSON summary for the website

## 6. Web and API Architecture

Recommended stack:

- FastAPI for API endpoints.
- Static JavaScript frontend using MapLibre GL or deck.gl.
- Nginx reverse proxy on the JASMIN Cloud VM.
- Systemd services/timers for artifact sync, health checks, and API service management.
- Optional PostGIS if interactive historical queries become important; otherwise start with Parquet/JSON artifacts and a small SQLite metadata database.

API endpoints:

```text
GET /api/status
GET /api/radars
GET /api/recent
GET /api/forecast/latest
GET /api/forecast/{cycle}
GET /api/radar/{radar_id}/recent
GET /api/radar/{radar_id}/archive?start=YYYY-MM-DD&end=YYYY-MM-DD
```

Frontend views:

- UK map with recent migration intensity.
- Forecast map with night selector.
- Radar detail panel with intensity, direction, speed, altitude, and data quality.
- Archive date picker.
- Methods/status page with caveats and data latency.

The web server should read precomputed artifacts from GWS/object storage. It should not run radar extraction or model inference.

## 7. Deployment on JASMIN

Batch side:

- LOTUS/Slurm jobs for aggregate conversion, biological extraction, feature generation, model training, and operational inference.
- Daily scheduler for:
  - raw radar update
  - aggregate validation
  - VPTS extraction
  - nightly metric generation
  - forecast-feature generation
  - model inference
  - public artifact publication

Cloud side:

- JASMIN Cloud VM with Nginx, FastAPI service, and static frontend.
- Reuse GAMB2LE Ansible patterns for Python envs, Nginx, systemd services, timers, and deployment layout.
- Keep application checkout under `/opt/birdcast-uk`.
- Keep public data mounted read-only or synced to the VM from GWS/object storage.

Monitoring:

- Processing manifest with per-stage status.
- API health endpoint.
- Daily freshness checks.
- Alert on missing radar updates, failed VPTS extraction, stale forecast artifacts, and web service failures.

## 8. Repository Implementation Plan

Create a new Python package in UK WSR Visualizer or a sibling repo:

```text
src/visualizer_birdcast_uk/
  config.py
  radars.py
  manifests.py
  vpts_schema.py
  nightly_metrics.py
  era5_features.py
  forecast_features.py
  model_training.py
  inference.py
  public_artifacts.py
  api/
    app.py
  web/
```

Add command-line entry points:

```text
birdcast-uk manifest aggregates
birdcast-uk extract-vpts --date YYYYMMDD --radar RADAR
birdcast-uk build-nightly --start YYYY-MM-DD --end YYYY-MM-DD
birdcast-uk build-era5-features --start YYYY-MM-DD --end YYYY-MM-DD
birdcast-uk train --config configs/model.yaml
birdcast-uk infer --cycle CYCLE
birdcast-uk publish --cycle CYCLE
birdcast-uk api
```

Keep R/bioRad or command-line `vol2bird` execution isolated behind a wrapper so the rest of the pipeline sees stable Parquet outputs.

## 9. Phased Delivery

### Phase 0: Confirm Downstream Radar Extraction - 1 week

- Inspect `/home/users/rrniii/ncas_radar_smf_rrniii/BioDAR/ukmo_biorad` on JASMIN.
- Identify its inputs, outputs, environment, and assumptions.
- Bring the relevant scripts under version control or document them if they cannot be moved.
- Run one known-good radar-day through aggregate to biological product.
- Decide whether a per-volume ODIM exporter is required.

### Phase 1: End-to-End Sample Pipeline - 2 to 3 weeks

- Select 2 to 3 representative radars and 2 to 4 sample periods covering spring, autumn, rain-contaminated nights, and quiet nights.
- Build standardized VPTS Parquet output.
- Build nightly radar metrics.
- Generate ERA5 site-level features for the same radar-nights.
- Produce a static prototype recent-migration map.

### Phase 2: Historical Backfill and QA - 3 to 5 weeks

- Backfill VPTS and nightly metrics for all radars and available years.
- Generate coverage dashboards and data-quality summaries.
- Build aggregate-to-VPTS failure repair tooling.
- Create versioned manifests for reproducibility.

### Phase 3: Forecast Model Backtesting - 4 to 6 weeks

- Build ERA5 historical feature tables.
- Train climatology, persistence, and weather-conditioned baseline models.
- Validate by year, radar, and season.
- Define public intensity classes and confidence flags.
- Decide whether absolute bird-count estimates are defensible for the first public release.

### Phase 4: Public MVP - 4 to 6 weeks

- Build FastAPI service and static map frontend.
- Publish recent observed migration from radar data.
- Publish forecast maps once a future NWP source is connected.
- Add radar detail views, status metadata, and methods/caveat pages.
- Deploy on JASMIN Cloud using Nginx and systemd.

### Phase 5: Operations - 2 to 4 weeks

- Add daily scheduled inference and publication.
- Add monitoring and stale-data alerts.
- Add model/version metadata to every public artifact.
- Write runbooks for failed radar days, failed weather downloads, model failures, and web service issues.

### Phase 6: Scientific Improvement - ongoing

- Improve biological/weather classification.
- Evaluate MistNet-style segmentation if weather contamination remains a limiting issue.
- Calibrate bird-density estimates against independent data where possible.
- Add expected species/migration-context products using BTO, BirdTrack, eBird, ringing, or other observational datasets if licensing permits.

## 10. Immediate Next Actions

1. SSH to JASMIN and inspect:

   ```text
   /home/users/rrniii/ncas_radar_smf_rrniii/BioDAR/ukmo_biorad
   ```

2. Run one clean radar-day through:

   ```text
   raw Nimrod -> UK WSR aggregate HDF5 -> BioDAR/vol2bird/bioRad -> standardized VPTS Parquet
   ```

3. Inventory the VPTS output fields and compare them with the proposed schema.

4. Add a manifest table for aggregate coverage and VPTS coverage.

5. Adapt the GAMB2LE ERA5 helpers into a site-feature generator for the 17 UK radars.

6. Build a first nightly radar-metrics table and one static UK map artifact.

7. Select the operational future weather source for forecasts.

## 11. Key Risks and Decisions

- `vol2bird` compatibility: the daily aggregate HDF5 layout may need per-volume ODIM export before biological extraction.
- Forecast weather source: ERA5 cannot drive future forecasts; a separate NWP feed is required.
- Weather contamination: UK C-band radar biological signal extraction may need classifier tuning or MistNet-style approaches.
- Absolute counts: public "number of birds" claims require calibration and uncertainty treatment.
- Web load: JASMIN Cloud should serve precomputed artifacts, not run heavy analysis.
- Licensing: confirm terms for raw radar data, derived products, ERA5, and any biodiversity validation datasets before public release.

## 12. Core Reading List

- Van Doren, B. M. and Horton, K. G. 2018. A continental system for forecasting bird migration. Science. DOI: 10.1126/science.aat7526
- Sheldon, D. et al. 2013. Approximate Bayesian Inference for Reconstructing Velocities of Migrating Birds from Weather Radar. AAAI. DOI: 10.1609/aaai.v27i1.8486
- Farnsworth, A. et al. 2016. A characterization of autumn nocturnal migration detected by weather surveillance radars in the northeastern USA. Ecological Applications. DOI: 10.1890/15-0023
- La Sorte, F. A. et al. 2014. The role of atmospheric conditions in the seasonal dynamics of North American migration flyways. Journal of Biogeography. DOI: 10.1111/jbi.12328
- Horton, K. G. et al. 2016. Nocturnally migrating songbirds drift when they can and compensate when they must. Scientific Reports. DOI: 10.1038/srep21249
- Dokter, A. M. et al. 2011. Bird migration flight altitudes studied by a network of operational weather radars. Journal of the Royal Society Interface. DOI: 10.1098/rsif.2010.0116
- Dokter, A. M. et al. 2019. bioRad: biological analysis and visualization of weather radar data. Ecography. DOI: 10.1111/ecog.04028
- Lin, T. Y. et al. 2019. MistNet: Measuring historical bird migration in the US using archived weather radar data and convolutional neural networks. Methods in Ecology and Evolution. DOI: 10.1111/2041-210X.13280
