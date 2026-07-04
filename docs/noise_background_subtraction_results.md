# Noise and Background Subtraction Results

Status date: 2026-07-03

This report records the current evidence for the `qc-v1` noise-floor,
background, speckle, dual-pol, and static-clutter cleanup path. It is a results
document, not the full processing contract. The companion methods document is
[UKMO WSR Processing Pipeline](ukmo_wsr_processing_pipeline.md).

## Technical Summary

The current best validated configuration is `vp_standard` with an estimated
range-dependent noise floor, a `6 dB` margin, texture-speckle suppression,
same-dataset companion-field QC, and static-clutter detection. On the first real
PVOL validation scan, the pipeline completed successfully, persisted a `qc_mask`
artifact, and retained `3,414` of `153,000` finite DBZH gates (`2.2%`).

The result is intentionally conservative for this scan. Most removed gates were
low-amplitude range-dependent background noise (`82,591` gates, `54.0%` of the
finite input). Companion-field QC removed a further `44,040` gates (`28.8%`),
texture-speckle logic removed `13,010` gates (`8.5%`), and static-clutter logic
removed `9,945` gates (`6.5%`). No source nodata, explicit user-domain, blockage,
AP-risk, velocity-QC, or VP-domain flags were raised in this validation run.

Synthetic/unit tests also pass for the implemented mask components: source
nodata and domain masking, estimated noise-floor masking, texture-speckle
masking, static clutter from near-zero velocity, dual-pol companion QC,
same-dataset companion-field auto-gathering, and legacy display-cleanup filter
mapping.

The result is ready to use as the default display/export cleanup path in the
desktop and iOS apps. It is not yet enough to claim archive-wide VP scientific
validation: this report currently covers one real Chenies PVOL scan plus
synthetic tests, not a curated all-radar validation set.

## Key Results From Real PVOL Validation

The real-data validation used the public Chenies PVOL object below and required
a real local HDF5 source file, not a synthetic fallback.

| Field | Value |
| --- | --- |
| Validation status | Passed |
| Validation type | `qc_mask` |
| Mask version | `qc-v1` |
| Cleanup mode | `vp_standard` |
| Radar | Chenies |
| Scan time | 2026-06-25 00:00 UTC |
| Pulse | `lp` |
| Dataset/elevation | `dataset1`, `0.5 deg` |
| Quantity | `DBZH` |
| Shape | `360` rays by `425` bins |
| Gate spacing | `600 m` |
| Maximum range | `255 km` |
| Companion fields found | `DBZH`, `PHIDP`, `RHOHV`, `SQIH`, `VRADH`, `WRADH`, `ZDR` |
| Source object | `ukmo-nimrod/pvol/chenies/2026/06/25/lp/20260625_polar_pl_radar05_aggregate_lp_0000.h5` |

The figure below shows the gate-level outcome in range-azimuth coordinates. The
green gates are the finite gates retained after QC. The other colours are the
single removal reason assigned by the `qc-v1` mask in this validation artifact.

![Chenies QC gate outcome](_static/qc_results/chenies_qc_gate_outcome.png)

The same result as aggregate counts:

![Chenies QC flag counts](_static/qc_results/chenies_qc_flag_counts.png)

| Outcome | Gates | Share of finite input |
| --- | ---: | ---: |
| Retained after QC | 3,414 | 2.2% |
| Masked by noise floor | 82,591 | 54.0% |
| Masked by dual-pol QC | 44,040 | 28.8% |
| Masked by texture speckle | 13,010 | 8.5% |
| Masked by static clutter | 9,945 | 6.5% |
| Total finite input | 153,000 | 100.0% |

The persisted mask result contains no overlapping removal flags for this scan:
the four non-zero removal counts sum to the total masked count of `149,586`
gates.

## The Noise Profile Is Range Dependent

The estimated floor is derived per range bin using the configured low-signal
profile method. The applied noise threshold is the estimated floor plus the
active `6 dB` margin. Near the radar, the estimated floor is materially higher;
after the first few kilometres it settles into a lower background level and then
rises gradually at long range.

![Chenies estimated noise profile](_static/qc_results/chenies_qc_noise_profile.png)

This profile-driven behaviour is the main reason the same fixed reflectivity
value is not treated identically at every range. For the validated scan, the
largest single class of removed gates is therefore not a flat dBZ cutoff; it is
the range-adjusted background estimate plus margin.

## Synthetic and Unit Validation

The synthetic tests exercise the mask mechanics independently of the Chenies
case. They are small by design, which makes them useful for proving that each
flag path is reachable and deterministic.

| Test coverage | Evidence |
| --- | --- |
| Source nodata and explicit domain masking | `NO_DATA` and `USER_DOMAIN` flags are set and masked values become `NaN`. |
| Estimated noise floor and local texture | Low-profile gates are masked and one isolated high-texture gate is flagged as `TEXTURE_SPECKLE`. |
| Static clutter | A near-zero velocity block with enough neighbouring support is flagged as `STATIC_CLUTTER`. |
| Dual-pol companion QC | Low `SQIH` and low `RHOHV` companion values flag the target gate as `DUALPOL_QC`. |
| Companion-field auto-gathering | A synthetic ODIM/HDF5 file exposes `DBZH`, `SQIH`, and `RHOHV` to the shared filter path. |
| Legacy filter compatibility | Existing display cleanup parameters map into a deterministic `QCConfig`. |

The current full test suite passes with these checks included: `184 passed, 1
warning`. The warning is an existing Starlette/FastAPI test-client deprecation
warning and does not affect the QC result.

## Method and Configuration Used

The real-data validation was run through the same `qc_mask` export path used by
the app/API processing layer. The active cleanup configuration was:

| Parameter | Value |
| --- | --- |
| `qc_mode` | `vp_standard` |
| `noise_floor_method` | `estimated` |
| `noise_floor_percentile` | `10` |
| `noise_floor_window_bins` | `11` |
| `noise_floor_margin_db` | `6.0` |
| `texture_enabled` | `true` |
| `texture_threshold_db` | `10.0` |
| `texture_near_margin_db` | `20.0` |
| `texture_support_db` | `6.0` |
| `texture_max_dbz` | `30.0` |
| `texture_min_similar_neighbors` | `1` |
| `companion_qc_enabled` | `true` |
| `static_clutter_enabled` | `true` |
| `static_clutter_dbz_min` | `5.0` |
| `static_clutter_vrad_abs_max_ms` | `1.0` |
| `static_clutter_min_neighbors` | `3` |
| `score_threshold` | `4` |
| `near_noise_score_threshold` | `3` |

The validation command was:

```bash
PYTHONPATH=src .venv/bin/python -c 'import sys; from uk_wsr_visualizer.cli import main; sys.exit(main(sys.argv[1:]))' \
  validate qc \
  --catalog /tmp/chenies_real_catalog.json \
  --radar chenies \
  --date 20260625 \
  --pulse lp \
  --time 0000 \
  --quantity DBZH \
  --dataset 1 \
  --qc-mode vp_standard \
  --noise-floor-margin-db 6 \
  --output-dir /tmp/uk_wsr_qc_validation \
  --report /tmp/uk_wsr_qc_validation/report.json \
  --require-real-hdf5
```

The persisted result was a compressed mask product plus JSON sidecar:

| Artifact | Result |
| --- | --- |
| Mask `.npz` | `chenies_20260625_DBZH_qc_mask.npz`, `43,429` bytes, SHA256 `bb25103aa9e9792b0b4c4763c897c7da131458c5e5c5c95866648f77af23ba06` |
| Sidecar `.json` | `chenies_20260625_DBZH_qc_mask.npz.json`, `15,378` bytes, SHA256 `94a140706cd6aa8ba59e87776411f17ba310aecbcd47bc7b5e72e47521c9d2d5` |

## Interpretation

The standard QC configuration is doing what it was designed to do on this scan:
it heavily suppresses background-like gates, uses same-dataset companion fields
when they exist, and preserves only a small coherent subset of DBZH gates. The
result is appropriate for a default app cleanup setting because it removes the
dominant low-level background and clutter-like signals without mutating the
source HDF5.

The most important technical result is that the pipeline now emits a persistent,
auditable gate mask rather than only a display-side cleaned image. That makes the
result inspectable by flag, reproducible through the CLI, and suitable for the
next stage of VP pipeline integration.

## Limitations and Robustness

This is a first real validation result, not a full validation campaign. The
largest limitations are:

- The real-data evidence covers one Chenies low-pulse scan at one time and one
  elevation.
- The exported `qc_mask` artifact persists the mask and cleaned values, but it
  does not persist the original unmasked DBZH array in the same `.npz`; the
  original source object is therefore still needed for a full before/after
  reflectivity figure.
- The iOS renderer has matching concepts and now defaults to the same standard
  cleanup strength, but Python-to-iOS golden-array parity has not yet been
  established.
- Persistent clear-air clutter maps, anomalous-propagation detection, terrain
  blockage flags, and VP-domain flags remain future work.
- The result has not yet been evaluated across the all-radar PVOL archive or
  across weather regimes, precipitation cases, biological cases, and mixed
  clutter/precipitation scenes.

## Recommended Next Steps

1. Build a curated real validation set across radars, pulses, elevations,
   companion-field combinations, clear-air cases, precipitation cases, and
   biological targets.
2. Persist original reflectivity, cleaned reflectivity, and mask side by side
   for validation figures, while keeping source HDF5 immutable.
3. Add Python-to-iOS golden tests for the same scan and accepted numerical
   tolerances.
4. Wire persisted `qc_mask` artifacts into VP batch runs and publication
   manifests.
5. Produce archive-scale summary reports: companion-field coverage, per-flag mask
   rates, decode failures, runtime, and cache footprint by radar/day/pulse.
6. Add manual review plots for the highest-risk cases: static clutter, dual-pol
   removal near precipitation, and low-level biological signal retention.

## Further Questions

- What retention-rate range is acceptable for VP processing by radar, pulse, and
  elevation?
- Which companion fields are required for the VP-ready product, and which should
  remain opportunistic?
- Should static clutter use only per-scan near-zero velocity evidence, or should
  it also consume learned radar/elevation clutter maps?
- What review set should be signed off before advertising this as
  analysis-ready rather than display/export-ready?
