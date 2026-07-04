# UKMO WSR Processing Pipeline

Status date: 2026-07-01

This note centralises the current clutter-removal and noise-removal position for
UK WSR Visualizer, the VP processing path, and the desktop and iOS apps. It is
written as an engineering and scientific-processing contract: what is already
implemented, what is not yet safe to claim, and what the next implementation
steps must produce before the project describes the output as analysis-ready.

For the current validation evidence, gate-count results, and figures, see
[Noise and Background Subtraction Results](noise_background_subtraction_results.md).

The project currently works with two related source-object families:

- **Daily aggregate HDF5**: the historical UK WSR Visualizer source of truth for
  catalogue, preview, export, and STAC workflows. These files remain on JASMIN
  GWS in current production operations.
- **Per-volume PVOL HDF5**: the current published `ukmo-nimrod/pvol` object-store
  layout used by the desktop and iOS apps. These ODIM-like single-scan files are
  prepared for vol2bird and bioRad workflows and are discovered through
  `ukmo-nimrod/catalog/pvol/catalog.json`.

The source objects must remain immutable. Every cleanup stage must produce a
derived mask, derived field, preview, export, or VP product with explicit
provenance. The processing layer must never rewrite the source HDF5 in place.

## Current Status

### Implemented data handling

| Area | Current status | Main implementation |
| --- | --- | --- |
| Catalog discovery | Implemented for aggregate catalogues, raw-volume day catalogues, and the current final PVOL root/coverage/day catalogue pattern. | `src/uk_wsr_visualizer/catalog.py`, `tools/*pvol*catalog*.py`, `ios/UKWSRVisualizer/ServerSettings.swift` |
| Object-store layout | Current default object prefix is `ukmo-nimrod`; raw PVOL keys are `ukmo-nimrod/pvol/{radar}/{YYYY}/{MM}/{DD}/{pulse}/{filename}`. | `src/uk_wsr_visualizer/object_store.py`, `configs/object_store.ncas-radar-o.toml` |
| HDF5 decode | Python and iOS both read ODIM-like `datasetN/dataM` groups, apply ODIM `gain`, `offset`, `nodata`, and `undetect`, and return floating-point polar arrays. | `src/uk_wsr_visualizer/geospatial.py`, `ios/UKWSRVisualizer/UKHDF5Reader.c`, `ios/UKWSRVisualizer/VisualizerWebView.swift` |
| Georeferencing | Radar-centred polar coordinates, azimuth/range bins, beam-height estimates, projected bounds, and geographic bounds are available. | `src/uk_wsr_visualizer/geospatial.py`, `src/uk_wsr_visualizer/ground_mapping.py` |
| Display filters | Range, azimuth, value, and nearest-height/CAPPI-style dataset selection are implemented. | `src/uk_wsr_visualizer/geospatial.py`, `src/uk_wsr_visualizer/api/app.py`, desktop JS, iOS renderer |
| Ground/VP geometry helpers | Beam height, beam radius, terrain clearance, partial blockage, refractivity helpers, and simple vertical-profile detection fractions exist. | `src/uk_wsr_visualizer/ground_mapping.py` |

### Implemented canonical cleanup

The Python/web pipeline now routes display/export cleanup through a canonical
gate-level QC module, `src/uk_wsr_visualizer/qc.py`. The first implemented mask
schema is versioned as `qc-v1` and returns both a cleaned floating-point field
and a `uint16` reason bitmask.

The implemented `qc-v1` flags are:

| Flag | Meaning |
| --- | --- |
| `NO_DATA` | Source gate is nodata, undetect, or not finite after scaling. |
| `USER_DOMAIN` | Gate was excluded by explicit range, azimuth, value, or height/domain filters. |
| `NOISE_FLOOR` | Reflectivity gate is below the estimated range-dependent noise floor. |
| `TEXTURE_SPECKLE` | Gate is low-amplitude, isolated, and texture-like. |
| `STATIC_CLUTTER` | Gate matches stationary clutter criteria where velocity fields are available. |
| `DUALPOL_QC` | Gate fails available SQI, RHOHV, ZDR, or PHIDP quality checks. |
| `VELOCITY_QC` | Gate fails velocity or spectrum-width quality checks. |
| `BLOCKAGE` | Reserved for terrain/blockage integration. |
| `AP_RISK` | Reserved for anomalous-propagation risk integration. |
| `VP_DOMAIN` | Reserved for vertical-profile domain exclusions. |

The legacy noise-floor filter is now implemented as one configuration of this
shared mask builder:

1. Start from a scaled floating-point polar field.
2. Compute a range-dependent low-signal profile by taking a configurable
   percentile across rays for each range bin.
3. Ignore the repeated ODIM undetect floor when enough above-floor values are
   available.
4. Smooth the profile with a rolling median and fill missing profile bins.
5. Mask gates whose value is below `profile + margin_db`.
6. Apply a conservative local texture check to remove isolated low-amplitude
   speckle using neighbouring reflectivity differences and support counts.

The default Python values are currently:

| Parameter | Default |
| --- | --- |
| Method | `estimated` |
| Operation | `mask` |
| Profile percentile | `10` |
| Profile window | `11` bins |
| Margin | `3.0 dB` unless overridden |
| Texture threshold | `10 dB` |
| Texture near-floor range | `20 dB` |
| Texture support tolerance | `6 dB` |
| Texture maximum reflectivity | `30 dBZ` |
| Minimum similar neighbours | `1` |

The filter returns metadata with the floor profile, finite gate counts before and
after masking, total masked count, and texture-masked count. The API exposes that
metadata in PPI and identify responses, and previews/exports can carry filtered
values through the Python request path.

PPI JSON, preview metadata, and identify responses also expose additive `qc`
metadata: mask version, mode, operation, per-flag counts, source quantity,
companion quantities, finite counts, and the active configuration. CLI commands
that use shared filter arguments now accept the same named cleanup controls for
noise floor, texture, companion QC, and static-clutter candidates.

Python readers now auto-attach same-shaped companion fields from the selected
ODIM dataset for API, preview, export, cartesian, and math paths. Persisted mask
artifacts are available through the `qc_mask` export format, which writes a
compressed `.npz` containing the `uint16` mask and cleaned values plus a JSON
sidecar with the scan metadata and QC summary. The `validate qc` command runs
that export path and writes a validation report, with an option to require a
real local `.h5` or `.hdf5` source.

### Implemented iOS cleanup

The iOS native renderer has its own cleanup implementation. It follows the same
estimated range-profile concept, but it has additional suppression logic:

- it attempts to load companion fields from the selected dataset, including
  `DBZH`, `SQIH`, `RHOHV`, `ZDR`, `PHIDP`/`UPHIDP`, `VRADH`, and `WRADH`;
- it can use a reflectivity field as the suppression gate even when the displayed
  quantity is not reflectivity;
- it scores low-quality gates using SQI, RHOHV, ZDR outliers, PHIDP texture,
  velocity texture, and spectrum width where those fields are present;
- it has a static-clutter candidate check based on reflectivity, near-zero radial
  velocity, and neighbouring clutter-candidate support.

Only the high-level cleanup strength is exposed in the current iOS UI. The
underlying defaults are present in `RadarFilterSet`, but they are not yet a
stable public scientific configuration.

### Current gaps

| Gap | Why it matters |
| --- | --- |
| Persisted masks are not yet wired into VP batch/publication | `qc_mask` exports persist gate masks for selected scans, but the VP batch runner and public product manifest still need to consume and publish those masks consistently. |
| Real archive validation set is not yet reviewed | `validate qc` can validate local HDF5/PVOL files, but the project still needs a curated real-scan validation set across radar/pulse/companion-field patterns. |
| iOS cleanup is not yet cross-validated against `qc-v1` | Static-clutter and companion-field decisions need Python-to-iOS golden tests and accepted tolerance thresholds. |
| No static clutter map | Persistent ground clutter is not yet learned from clear-air or dry-weather cases per radar/elevation/range/azimuth. |
| No anomalous propagation detector | Refractivity utilities exist, but AP detection is not yet applied to masks or VP products. |
| No precipitation/biology separation contract | VP processing needs explicit decisions on rain, insects, birds, sea clutter, and mixed pixels. |
| No all-radar inventory report | We do not yet have a published field-coverage matrix across all radars, years, pulses, elevations, and quantities. |
| No archive-scale performance budget | Runtime, cache footprint, and failure-rate targets for processing all published UKMO WSR data are not yet measured. |

The practical conclusion is that the current cleanup is useful for inspection,
screenshots, and exploratory exports, but it should not yet be advertised as the
final quantitative clutter-removal pipeline for VP products.

## Processing Contract

All UKMO WSR processing should follow the same high-level sequence.

### 1. Discover source objects

Use the published PVOL catalog for app workflows and archive-scale per-volume
processing:

```text
{public_base_url}/ukmo-nimrod/catalog/pvol/catalog.json
{public_base_url}/ukmo-nimrod/catalog/pvol/{radar}/{YYYY}/coverage.json
{public_base_url}/ukmo-nimrod/catalog/pvol/{radar}/{YYYY}/{MM}/{DD}/catalog.json
```

Use aggregate catalogues only when the required workflow explicitly targets the
daily aggregate files on JASMIN. Do not mix aggregate and PVOL products without
recording the source family in the output manifest.

### 2. Validate each HDF5 object before processing arrays

For each source object, read only metadata first:

- root `where` latitude, longitude, and site height;
- dataset-level `where` elevation angle, range start, range scale, number of
  bins, and number of rays;
- each `dataN/what.quantity`;
- `gain`, `offset`, `nodata`, and `undetect`;
- array shape and dtype;
- scan time, pulse, radar, object key, byte size, and checksum when available.

Reject or quarantine a file if the quantity metadata, shape, range metadata, or
site location is missing in a way that prevents georeferenced processing.

### 3. Decode fields without changing the source

Convert raw ODIM-style values into physical floating-point values:

```text
scaled = raw * gain + offset
scaled[raw == nodata] = NaN
scaled[raw == undetect] = NaN
```

Keep the original source object, raw metadata, selected dataset, selected
quantity, software version, and cleanup configuration in the derived product
manifest.

### 4. Build the canonical gate mask

Ad-hoc display-only cleanup should be expressed as the shared `qc-v1` gate mask.
The current mask is a typed bitmask with these flags:

| Flag | Meaning |
| --- | --- |
| `NO_DATA` | Source gate is nodata, undetect, or not finite after scaling. |
| `USER_DOMAIN` | Gate was excluded by explicit range, azimuth, value, elevation, or height filters. |
| `NOISE_FLOOR` | Reflectivity gate is below the estimated range-dependent noise floor. |
| `TEXTURE_SPECKLE` | Gate is low-amplitude, isolated, and texture-like. |
| `STATIC_CLUTTER` | Gate matches stationary clutter criteria or a learned clutter map. |
| `DUALPOL_QC` | Gate fails available SQI, RHOHV, ZDR, PHIDP, or width criteria. |
| `VELOCITY_QC` | Gate fails velocity or velocity-texture criteria. |
| `BLOCKAGE` | Reserved for gates affected by terrain blockage beyond the accepted threshold. |
| `AP_RISK` | Reserved for gates in anomalous-propagation risk regions. |
| `VP_DOMAIN` | Reserved for gates outside the accepted VP altitude, range, elevation, or biological-processing domain. |

The bitmask is produced by the canonical Python implementation first. Desktop
previews and API responses already consume that result. Batch VP processing,
persisted mask products, and iOS parity should align to the same definition.

### 5. Apply cleanup in a stable order

The recommended order is:

1. Source validity: nodata, undetect, non-finite, impossible metadata.
2. User/domain filter: range, azimuth, selected dataset/elevation, value bounds.
3. Noise floor: estimated profile plus margin.
4. Texture speckle: local support and reflectivity texture.
5. Companion-field QC: SQI, RHOHV, ZDR, PHIDP texture, velocity texture, spectrum
   width, and static-clutter candidates where fields exist.
6. Site/radar geometry: terrain blockage, range gates, beam-height limits, and
   AP-risk flags.
7. VP-domain filter: altitude limits, range limits, pulse/elevation choice, and
   biological-processing inclusion rules.

The order matters because downstream diagnostics should say why a gate was
removed. Earlier hard failures such as source nodata should not be counted as
clutter or noise.

## VP Pipeline Requirements

The VP path must treat cleanup as a scientific mask, not just a display control.

Minimum VP-ready outputs:

- cleaned polar field or masked array;
- gate-level bitmask;
- per-scan summary counts by mask flag;
- field-availability summary for required and optional quantities;
- selected VP domain: radar, date, pulse, time, elevation/dataset, range limits,
  height limits, and beam-geometry settings;
- downstream product manifest recording source object, software version, mask
  version, configuration, and command line.

Recommended VP processing sequence:

1. Read the PVOL day catalog and iterate files in object-key order.
2. Decode each HDF5 scan and inspect available quantities.
3. Select the reflectivity source field for signal/noise and gate support.
4. Attach companion fields where present and same-shaped.
5. Build the canonical mask.
6. Write a scan-level QC summary.
7. Pass only accepted gates into vol2bird/bioRad or project-native VP
   computation.
8. Write VP outputs with the same mask/config provenance.
9. Aggregate run-level diagnostics by radar, date, pulse, and failure reason.

For all-radar processing, every batch should be restartable. The unit of work
should be a radar/day or radar/day/pulse, with idempotent output paths and a
small status JSON file written after each unit completes.

## Desktop and iOS Alignment

Desktop apps currently share the FastAPI/static viewer, so the desktop path
should consume the canonical Python QC result directly.

iOS currently computes cleanup natively after reading HDF5. There are two viable
alignment options:

| Option | Tradeoff |
| --- | --- |
| Port the canonical mask algorithm to Swift | Fully offline iOS rendering remains possible, but cross-language golden tests are mandatory. |
| Precompute or fetch scan-level mask metadata | Strong parity with server/VP output, but iOS depends on derived mask availability. |

The near-term recommendation is to keep native iOS rendering, but formalise a
cross-platform golden suite:

- same small HDF5 fixtures for Python and iOS;
- same selected quantities, datasets, and filter settings;
- expected mask counts by flag;
- expected identify behaviour for gates masked by cleanup;
- tolerance-defined agreement for scaled display products;
- regression tests that fail if Python and iOS cleanup diverge without an
  intentional mask-version change.

## Implementation Plan

### Phase 1: Inventory and terminology

- Publish an all-radar field inventory covering radars, years, pulses, datasets,
  elevations, shapes, and quantities.
- Record which radars/scans contain DBZH/TH, SQI, RHOHV, ZDR, PHIDP, VRAD, WRAD,
  and any explicit quality fields.
- Decide the project vocabulary: `noise floor`, `texture speckle`, `static
  clutter`, `dual-pol quality`, `AP risk`, and `VP domain`.
- Update public text so display cleanup is not mistaken for final VP-grade QC.

### Phase 2: Canonical Python QC module

Initial implementation completed:

- `src/uk_wsr_visualizer/qc.py` defines `QCConfig`, `QCMaskResult`, `QCMaskFlag`,
  and `qc-v1` flag names.
- The existing estimated noise-floor and texture logic now route through the
  canonical mask builder.
- Static-clutter candidates and companion-field scoring have a Python
  implementation for same-shaped fields.
- `apply_polar_filters` returns both the cleaned field and QC metadata; range,
  azimuth, and value exclusions are recorded as `USER_DOMAIN`.
- API PPI, preview metadata, and identify responses expose additive `qc`
  summaries while preserving the legacy `noise_floor` payload.
- Shared CLI filter arguments expose QC mode, noise floor, texture, companion QC,
  and static-clutter controls.
- Same-dataset companion fields are auto-attached for API, preview, export,
  cartesian, and math paths.
- The `qc_mask` export format persists the gate mask and sidecar QC summary.
- The `validate qc` command writes reproducible QC validation reports and can
  require a real local HDF5/PVOL source.
- Synthetic Python tests cover `NO_DATA`, `USER_DOMAIN`, `NOISE_FLOOR`,
  `TEXTURE_SPECKLE`, `STATIC_CLUTTER`, and `DUALPOL_QC`.

Remaining Phase 2 work:

- Wire persisted gate-level mask products into VP batch manifests and public
  publication manifests.
- Add `BLOCKAGE`, `AP_RISK`, and `VP_DOMAIN` integrations.
- Publish the mask schema and mask-version migration policy.

### Phase 3: Validation suite

- Build fixture scans covering clear air, precipitation, sea clutter, likely
  biological signal, static clutter, and missing companion fields.
- Add Python unit tests for each mask flag.
- Add API tests for query-parameter propagation and mask metadata.
- Add `validate qc` cases for curated real local PVOL/HDF5 scans and publish the
  resulting reports beside release validation artifacts.
- Add iOS tests comparing native mask summaries against Python golden JSON.
- Add archive-scale dry-run reports: failure counts, field availability, median
  runtime, p95 runtime, and mask-count distributions.

### Phase 4: VP integration

- Define the VP input contract: required fields, optional fields, accepted
  elevations, altitude/range gates, and precipitation handling.
- Build a restartable radar/day batch runner for cleaned PVOL-to-VP processing.
- Write per-scan and per-day QC summaries.
- Integrate with vol2bird/bioRad where that is the target path, and keep a
  project-native intermediate that can be audited independently.
- Validate VP stability against selected manually reviewed cases before scaling
  to all radars.

### Phase 5: Product publication

- Publish the mask schema and mask-version history.
- Publish field-inventory and QC-validation reports beside the catalog.
- Include source-data citation, access terms, mask configuration, and software
  release in every product manifest.
- Keep generated user exports private unless a separate release policy approves
  them.

## Acceptance Criteria

The cleanup/QC work is ready to describe as the project processing standard when
all of the following are true:

- The same source scan and config produce the same mask summary in Python,
  desktop/API, and iOS.
- Every mask-producing command writes a provenance manifest with source object,
  software version, mask version, and config.
- CLI, API, desktop, and iOS expose the same named cleanup modes, even if iOS
  hides advanced parameters in the normal UI.
- The all-radar inventory is published and can be regenerated.
- Archive-scale dry runs report no unexplained decode failures.
- VP outputs preserve mask counts and can be traced back to source object keys.
- At least one reviewed validation set covers each accepted radar/pulse family
  and each common companion-field availability pattern.
- Public docs distinguish exploratory display cleanup from VP-grade QC.

## References

- Project implementation: `src/uk_wsr_visualizer/geospatial.py`,
  `src/uk_wsr_visualizer/ground_mapping.py`,
  `ios/UKWSRVisualizer/VisualizerWebView.swift`,
  `ios/UKWSRVisualizer/UKHDF5Reader.c`.
- Current PVOL object-store configuration:
  `configs/object_store.ncas-radar-o.toml`.
- Current iOS catalog and HDF5 notes: `ios/README.md`.
- Py-ART ODIM_H5 reader:
  <https://arm-doe.github.io/pyart/API/generated/pyart.aux_io.read_odim_h5.html>.
- Py-ART gate filtering and radar QC references:
  <https://arm-doe.github.io/pyart/API/generated/pyart.correct.GateFilter.html>,
  <https://arm-doe.github.io/pyart/API/generated/pyart.correct.despeckle_field.html>.
- Py-ART vertical-profile references:
  <https://arm-doe.github.io/pyart/API/generated/pyart.retrieve.compute_vp.html>,
  <https://arm-doe.github.io/pyart/API/generated/pyart.retrieve.compute_qvp.html>.
- xradar ODIM_H5 reference material:
  <https://docs.openradarscience.org/projects/xradar/en/stable/notebooks/ODIM_H5.html>.
