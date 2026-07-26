# UKMO WSR Processing Pipeline

Status date: 2026-07-26

:::{important}
The governing cleanup specification and current measured results are now
[QC v3: signal-preserving noise and clutter removal](qc_v3_implementation_and_validation.md).
The `qc-v2` sections retained below are an implementation-history record and
must not be read as the current app policy. The current default is `qc-v3`
safe mode; learned clutter runs in shadow and cannot delete gates until the
sealed real-data release gates pass.
:::

This note centralises the current clutter-removal and noise-removal position for
UK WSR Visualizer, the VP processing path, and the desktop and iOS apps. It is
written as an engineering and scientific-processing contract: what is already
implemented, what is not yet safe to claim, and what the next implementation
steps must produce before the project describes the output as analysis-ready.

The scientific QC implementation, validation evidence, gate-count results, and
figures are maintained in the standalone
[UK WSR QC project](https://github.com/rrniii/uk-wsr-qc). This repository
contains only the viewer integration and user-facing controls.

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

The Python/web pipeline routes display/export cleanup through the installed
`uk_wsr_qc` package. The current mask schema is `qc-v2` and returns both a
cleaned floating-point field and a `uint16` reason bitmask.

The implemented `qc-v2` flags are:

| Flag | Meaning |
| --- | --- |
| `NO_DATA` | Source gate is nodata, undetect, or not finite after scaling. |
| `USER_DOMAIN` | Gate was excluded by explicit range, azimuth, value, or height/domain filters. |
| `NOISE_FLOOR` | Reflectivity gate was hard-masked by the legacy/display noise-floor mode. |
| `RECEIVER_NOISE` | Gate satisfies the conservative CI, SQI, near-floor, and multi-moment receiver-noise rule. |
| `TEXTURE_SPECKLE` | Gate is low-amplitude, isolated, and texture-like. |
| `STATIC_CLUTTER` | Gate matches stationary clutter criteria where velocity fields are available. |
| `DUALPOL_QC` | Gate fails available SQI, RHOHV, ZDR, or PHIDP quality checks. |
| `VELOCITY_QC` | Gate fails velocity or spectrum-width quality checks. |
| `BLOCKAGE` | Reserved for terrain/blockage integration. |
| `AP_RISK` | Reserved for anomalous-propagation risk integration. |
| `VP_DOMAIN` | Reserved for vertical-profile domain exclusions. |

The app-default `signal_preserving` cleanup mode now removes only CI-confirmed
receiver noise and clutter from a qualified multi-date learned map. It computes
the range-dependent low-signal profile, but low reflectivity alone is not a
removal reason. Standalone static velocity, texture-speckle, and generic
companion-field QC are disabled unless requested explicitly. The older hard
noise-floor filter remains available as `display_standard` for diagnostics and
backwards-compatible visual cleanup:

1. Start from a scaled floating-point polar field.
2. Compute a range-dependent low-signal profile by taking a configurable
   percentile across rays for each range bin.
3. Ignore the repeated ODIM undetect floor when enough above-floor values are
   available.
4. Smooth the profile with a rolling median and fill missing profile bins.
5. In `display_standard`, mask gates whose value is below
   `profile + margin_db`; in `signal_preserving`, use the profile only to bound
   receiver-noise candidates.
6. Require high CI, very low SQI, and at least three independent bad-moment
   indicators before setting `RECEIVER_NOISE`.
7. Apply a keyed learned map only after its training-date/span qualification
   succeeds and current CI plus current radial velocity confirm static clutter.
8. Enable standalone static, texture, or generic companion QC only for explicit
   diagnostics.

The default Python values are currently:

| Parameter | Default |
| --- | --- |
| Method | `estimated` |
| Operation | `mask` |
| Profile percentile | `10` |
| Profile window | `11` bins |
| Signal-preserving margin | `0.0 dB` evidence offset |
| Receiver-noise margin | `0.25 dB` above the estimated profile |
| Receiver-noise CI threshold | `CI >= 6` |
| Receiver-noise SQI threshold | `SQI <= 0.05` |
| Receiver-noise bad moments | At least `3` |
| Legacy/display hard-mask margin | `3.0 dB` unless overridden |
| Texture / generic companion QC | Disabled by default |
| Standalone static clutter | Disabled by default |
| Learned persistence | `>= 0.95` with at least `40` samples |
| Learned training diversity | At least `7` dates spanning `14` days |
| Learned/current static confirmation | Learned near-zero VRAD `>= 0.80`, current `abs(VRAD) <= 0.50 m/s`, current `CI <= 2` |
| Learned DBZH guard | Current DBZH `<= p90 + 3 dB` |

The filter returns metadata with the floor profile, finite gate counts before and
after masking, total masked count, and texture-masked count. The API exposes that
metadata in PPI and identify responses, and previews/exports can carry filtered
values through the Python request path.

PPI JSON, preview metadata, and identify responses expose additive `qc`
metadata: mask version, mode, operation, per-flag counts, evidence counts, noise
metadata, model qualification, source quantity, companion quantities, finite
counts, and the active configuration. CLI commands that use shared filter
arguments accept the same named cleanup controls.

Python readers auto-attach same-shaped companion fields from the selected ODIM
dataset and now also inspect `qualityN` groups. Per-ray `(rays, 1)` ambient-noise
quality arrays are broadcast across range for aligned evidence. Persisted mask
artifacts are available through the `qc_mask` export format, which writes a
compressed `.npz` containing the `uint16` mask and cleaned values plus a JSON
sidecar with the scan metadata and QC summary. The `validate qc` command runs
that export path and writes a validation report, with an option to require a
real local `.h5` or `.hdf5` source.

### Implemented iOS cleanup

The iOS native renderer implements the same conservative decision contract
offline:

- it attempts to load companion fields from the selected dataset, including
  `CI`, `DBZH`, `SQIH`, `RHOHV`, `ZDR`, `PHIDP`/`UPHIDP`, `VRADH`, `WRADH`,
  and long-range noise quality fields;
- it can use a reflectivity field as the suppression gate even when the displayed
  quantity is not reflectivity;
- its normal preset requires near-floor DBZH, high CI, very low SQI, and three
  bad-moment indicators before removing receiver noise;
- low RHOHV, low SQI, or near-zero velocity alone are retained;
- it decodes model CI statistics and training diversity metadata, and fails open
  for one-day or otherwise unqualified learned models;
- standalone texture, generic companion QC, and local static-clutter deletion
  are disabled in normal and strong presets.

The high-level iOS controls are Off, Normal, and Strong. Normal uses a 0.25 dB
receiver-noise margin. Strong widens that margin to 1.0 dB but retains the same
CI/SQI/multi-moment and learned-model qualification requirements.

### Current gaps

| Gap | Why it matters |
| --- | --- |
| Persisted masks are not yet wired into VP batch/publication | `qc_mask` exports persist gate masks for selected scans, but the VP batch runner and public product manifest still need to consume and publish those masks consistently. |
| Real archive validation set is not yet reviewed | High Moorsley has now been validated across both pulses and all 11 DBZH sweeps, but the project still needs labelled cases across radars, seasons, weather, biology, sea clutter, AP, and field-availability patterns. |
| No cross-language golden arrays from real PVOL | Python and iOS synthetic contracts and native tests now pass, but the same persisted real scan should be compared gate-for-gate across languages. |
| No learned clutter maps are currently qualified | The 187 single-day qc-v1 maps are explicitly quarantined by the schema-v2 registry and excluded from desktop and iOS packaging. Every radar/pulse/elevation map needs multi-date training plus independent date-held-out validation before clutter removal activates. |
| No anomalous propagation detector | Refractivity utilities exist, but AP detection is not yet applied to masks or VP products. |
| No downstream target classifier | Cleanup deliberately preserves weather, biology, and unknown echoes. Any later rain/insect/bird classification must be a separate product with separate labels. |
| No all-radar inventory report | We do not yet have a published field-coverage matrix across all radars, years, pulses, elevations, and quantities. |
| No archive-scale performance budget | Runtime, cache footprint, and failure-rate targets for processing all published UKMO WSR data are not yet measured. |

The practical conclusion is that the current default is now the right direction
for app and VP integration: remove confident noise and clutter while retaining
precipitation, biology, and unknown signal. It still needs archive-scale review
before being advertised as the final quantitative clutter-removal pipeline.

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

Ad-hoc display-only cleanup should be expressed as the shared `qc-v2` gate mask.
The current mask is a typed bitmask with these flags:

| Flag | Meaning |
| --- | --- |
| `NO_DATA` | Source gate is nodata, undetect, or not finite after scaling. |
| `USER_DOMAIN` | Gate was excluded by explicit range, azimuth, value, elevation, or height filters. |
| `NOISE_FLOOR` | Gate was hard-masked by a legacy/display noise-floor configuration. |
| `RECEIVER_NOISE` | Gate meets near-floor DBZH, high-CI, low-SQI, and multi-moment noise criteria. |
| `TEXTURE_SPECKLE` | Gate is low-amplitude, isolated, and texture-like. |
| `STATIC_CLUTTER` | Gate matches an explicitly enabled local stationary-clutter diagnostic. |
| `BACKGROUND_CLUTTER` | Gate matches a qualified learned persistent-clutter map plus current CI/VRAD confirmation. |
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
3. Receiver noise: estimated profile plus high CI, very low SQI, and at least
   three independent bad moments. Do not hard-remove weak gates from DBZH, CI,
   SQI, RHOHV, or texture alone.
4. Learned background clutter: require a qualified multi-date keyed model,
   learned persistent/static/low-CI evidence, current low CI, current near-zero
   radial velocity, and the learned p90 DBZH guard.
5. Optional diagnostics: standalone static clutter, texture speckle, and generic companion-field QC using SQI, ZDR,
   PHIDP texture, velocity texture, and spectrum width. Low RHOHV alone is
   retained in the default path.
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
consumes the canonical Python QC result directly. The preview, PPI, PPI-image,
and identify routes accept the same receiver-noise, CI, and learned-model
qualification controls emitted by the desktop client. Bundle tests require the
checked-in app to embed the current Python QC runtime.

iOS computes cleanup natively after reading HDF5. The current implementation
uses the first alignment option below:

| Option | Tradeoff |
| --- | --- |
| Port the canonical mask algorithm to Swift | Fully offline iOS rendering remains possible, but cross-language golden tests are mandatory. |
| Precompute or fetch scan-level mask metadata | Strong parity with server/VP output, but iOS depends on derived mask availability. |

Native iOS build and unit-test parity now cover defaults, receiver-noise
evidence, strong-signal retention, optional diagnostic rules, qualified learned
clutter, and one-day-model fail-open behaviour. The remaining cross-platform
golden suite should add:

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

Initial implementation completed and upgraded to `qc-v2`:

- `uk_wsr_qc.qc` defines `QCConfig`, `QCMaskResult`, `QCMaskFlag`, and `qc-v2`
  flag names, including `RECEIVER_NOISE`.
- The existing estimated noise-floor and texture logic now route through the
  canonical mask builder.
- CI-aware receiver noise and qualified learned clutter have Python and iOS
  implementations. Static-clutter, texture, and generic companion scoring remain
  available as explicit diagnostics.
- `apply_polar_filters` returns both the cleaned field and QC metadata; range,
  azimuth, and value exclusions are recorded as `USER_DOMAIN`.
- API preview, PPI, PPI-image, and identify routes accept the complete CI,
  receiver-noise, and learned-model qualification controls. Their responses
  expose additive `qc` summaries while preserving the legacy `noise_floor`
  payload.
- Shared CLI filter arguments expose QC mode, noise floor, texture, companion QC,
  and static-clutter controls.
- Same-dataset data and quality fields are auto-attached for API, preview,
  export, cartesian, and math paths; per-ray quality fields are broadcast across
  range.
- The `qc_mask` export format persists the gate mask and sidecar QC summary.
- The `validate qc` command writes reproducible QC validation reports and can
  require a real local HDF5/PVOL source.
- Synthetic Python and iOS tests cover receiver-noise evidence, strong-signal
  preservation, optional diagnostics, learned clutter, and model qualification.
- A real High Moorsley validation covers LP and SP at all 11 DBZH sweeps and
  persists original, cleaned, mask, profile, metrics, and plots.

Remaining Phase 2 work:

- Wire persisted gate-level mask products into VP batch manifests and public
  publication manifests.
- Add `BLOCKAGE`, `AP_RISK`, and `VP_DOMAIN` integrations.
- Publish the mask schema and mask-version migration policy.

### Phase 3: Validation suite

- Expand fixture scans beyond the implemented receiver-noise/weather cases to
  sea clutter, insects, birds, mixed precipitation/biology, AP, interference,
  static clutter, and missing companion fields.
- Add gate-for-gate Python/iOS golden arrays from the same real PVOL selections.
- Add `validate qc` cases for a curated, labelled multi-radar PVOL/HDF5 set and
  publish the reports beside release validation artifacts.
- Add archive-scale dry-run reports: failure counts, field availability, median
  runtime, p95 runtime, and mask-count distributions.
- Measure nuisance precision/recall, non-nuisance retention, object continuity,
  and VP bias rather than relying on removal percentage alone.

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
