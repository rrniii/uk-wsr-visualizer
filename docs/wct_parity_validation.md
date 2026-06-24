# WCT 4.9.1 Parity Validation

The local reference installation is:

```text
/Applications/WCT-4.9.1.app
```

Important files discovered in that app bundle:

- `Contents/Resources/wct-export.sh`
- `Contents/Resources/wctBatchConfig.xml`
- `Contents/Resources/dist/wct-4.9.1.jar`
- bundled Java runtime under `Contents/Resources/jre`

The Avocet validation harness uses WCT's batch exporter where possible and records the exact command needed for reproducibility.

The same WCT-style filter names used by the app can be passed into Avocet export requests. `cappi_height_m` is written into WCT batch configs as `constantAltitudesInMeters`; in Avocet processing it selects the nearest available sweep/dataset unless a dataset is explicitly pinned.

## Dry Run

Dry run always works without launching Java. It runs the Avocet export, writes a WCT batch config, records the WCT command, and writes a JSON report:

```bash
avocet-wct validate wct \
  --catalog data/avocet-wct/catalog.json \
  --radar thurnham \
  --date 20260614 \
  --pulse lp \
  --time 0000 \
  --quantity DBZH \
  --format geotiff \
  --output-dir data/avocet-wct/validation/wct \
  --report data/avocet-wct/validation/wct/report.json
```

## Live WCT Execution

Add `--execute-wct` only after confirming that WCT can decode the selected input path:

```bash
avocet-wct validate wct \
  --catalog data/avocet-wct/catalog.json \
  --radar thurnham \
  --date 20260614 \
  --pulse lp \
  --time 0000 \
  --quantity DBZH \
  --format geotiff \
  --wct-input-path /path/to/wct-compatible-reference-input \
  --output-dir data/avocet-wct/validation/wct \
  --report data/avocet-wct/validation/wct/report.json \
  --execute-wct \
  --require-comparison
```

The `--wct-input-path` option is important. WCT 4.9.1 is the functional reference, but it may not understand the Avocet daily aggregate layout directly. If WCT cannot decode the aggregate HDF5, use a per-volume ODIM/NEXRAD-compatible export from the aggregate pipeline as the WCT input and keep the Avocet aggregate as the source of truth for this toolkit.

## Release Suite

Use `validate wct-suite` for the production gate. It expands each representative radar case across all configured parity formats and writes one report that can be published with the public object-store release:

```bash
avocet-wct validate wct-suite \
  --catalog data/avocet-wct/catalog.json \
  --cases-json configs/wct_parity_cases.json \
  --formats geotiff,kmz,shapefile,cf_netcdf \
  --wct-app /Applications/WCT-4.9.1.app \
  --output-dir data/avocet-wct/validation/wct/release-20260623 \
  --report data/avocet-wct/validation/wct/release-20260623/report.json \
  --execute-wct \
  --require-comparison
```

The cases file may be either a JSON list or an object with a `cases` list:

```json
{
  "cases": [
    {
      "case_id": "thurnham-20260614-lp-dbzh",
      "radar": "thurnham",
      "date": "20260614",
      "pulse": "lp",
      "time": "0000",
      "quantity": "DBZH",
      "formats": ["geotiff", "kmz", "shapefile", "cf_netcdf"],
      "wct_input_path": "/path/to/wct-compatible-reference-input"
    }
  ]
}
```

Every case must include `radar`, `date`, `pulse`, `time`, and `quantity`, unless those selectors are supplied as CLI defaults. Supported suite formats are `geotiff`, `kmz`, `shapefile`, and `cf_netcdf`.

## Report Contents

Each validation report records:

- Avocet export status, output path, size, SHA256
- WCT app path
- whether comparison was required for the command to pass
- generated WCT batch config path
- exact WCT command
- WCT status, output path, size, SHA256 if WCT ran
- `parity_status`, which is `passed`, `failed`, `warning`, or `not_comparable`
- structured comparison metrics when both outputs exist
- notes about skipped execution, missing WCT, comparison status, or output differences

Format-specific comparison evidence:

- GeoTIFF: shape, CRS, bounds, affine transform, nodata, value statistics, mean absolute error, max absolute error, and RMSE.
- CF NetCDF: dimensions, first 2-D numeric variable, value statistics, mean absolute error, max absolute error, and RMSE.
- Shapefile: shape count, record count, field names, and geographic bbox.
- KMZ: archive entries and KML `LatLonBox` extent.

Use `--max-mean-abs-error` and `--max-rmse` when exact floating-point equality is not expected. The defaults are `0.0`, which is intentionally strict.

## Formats

Configured parity formats:

- `geotiff`
- `kmz`
- `shapefile`
- `cf_netcdf`

These correspond to the WCT batch exporter output names `geotiff`, `kmz`, `shp`, and `netcdf`.

## Production Gate

Before claiming WCT export parity for public service:

1. Select representative radar-days across multiple radar sites, pulses, quantities, and elevations.
2. Confirm WCT can decode the chosen reference inputs.
3. Run `avocet-wct validate wct-suite --execute-wct --require-comparison` for GeoTIFF, KMZ, Shapefile, and NetCDF.
4. Set documented tolerances with `--max-mean-abs-error` and `--max-rmse` only after checking whether differences are caused by expected interpolation, projection, or WCT encoding behaviour.
5. Inspect reports and confirm `parity_status` is `passed` for every case.
6. Save the validation reports under `data/avocet-wct/validation/wct/...`; `avocet-wct object-store plan --validation-dir data/avocet-wct/validation/wct` publishes them under `uk-radar/validation/wct/...` and summarizes parity in `status.json`.
