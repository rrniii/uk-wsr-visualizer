# Noise and Background Subtraction Results

Status date: 2026-07-06

This report records the current evidence for the `qc-v1` noise-floor,
background, speckle, companion-field, and static-clutter cleanup path. It is a
results document, not the full processing contract. The companion methods
document is [UKMO WSR Processing Pipeline](ukmo_wsr_processing_pipeline.md).

## Current Learned-Background Result

The current best result is now a learned polar background/clutter model family
trained on real public UKMO PVOL/HDF5 data for all 17 radars in the public PVOL
catalog, all DBZH elevations, and both public pulse types. These models are
implemented as default app artifacts for matching scans, not as display-only
visual cleanup.

| Field | Value |
| --- | --- |
| Status | Implemented, real-data trained, real hold-out validated for all 17 public radars, all DBZH sweeps, `lp` and `sp`, default-enabled for matching scans |
| Radars | `17` |
| Model targets | `187` radar/pulse/elevation DBZH model artifacts |
| Date used | `2026-07-03` |
| Pulses / quantity | `lp`, `sp` / `DBZH` |
| Elevations | LP `dataset1-5` and SP `dataset1-6`, including the SP near-vertical sweep |
| Training scans | Usually `50` real PVOL/HDF5 scans per target, starting at `12:00` UTC or later; Wardon Hill SP uses `48` because only `68` SP files were available |
| Hold-out scans | `20` real PVOL/HDF5 scans per target |
| LP model shape | `360 x 425` polar gates |
| SP model shape | `360 x 189` gates for `dataset1-5`; `360 x 160` for near-vertical `dataset6` |
| LP held-out finite gates | `260,100,000` |
| LP learned-background gates removed | `15,922,553` |
| LP aggregate removal | `6.12%` of finite gates |
| SP held-out finite gates | `135,252,000` |
| SP learned-background gates removed | `94,457,983` |
| SP aggregate removal | `69.84%` of finite gates |
| Packaged desktop defaults | `src/uk_wsr_visualizer/models/background/*.json` plus `manifest.json` |
| iOS bundled defaults | `ios/UKWSRVisualizer/BackgroundModels/*.json` |
| Validation report | `reports/learned_background_validation_all_radars_all_sweeps/README.md` |

![All-target learned-background validation summary](_static/qc_results/learned_background_all_sweeps/masked_percent_by_target.png)

| Pulse | Dataset | Typical elevation | Targets | Aggregate hold-out removal | Radar mean range |
| --- | --- | ---: | ---: | ---: | --- |
| `lp` | `dataset1` | `0.45-0.50 deg` | `17` | `12.55%` | `4.27-17.04%` |
| `lp` | `dataset2` | `0.95-1.00 deg` | `17` | `8.25%` | `2.42-15.55%` |
| `lp` | `dataset3` | `1.95-2.00 deg` | `17` | `4.08%` | `1.09-6.73%` |
| `lp` | `dataset4` | `2.95-3.00 deg` | `17` | `3.13%` | `0.95-5.73%` |
| `lp` | `dataset5` | `3.95-4.00 deg` | `17` | `2.59%` | `0.65-6.08%` |
| `sp` | `dataset1` | `0.95-1.00 deg` | `17` | `84.98%` | `71.00-90.57%` |
| `sp` | `dataset2` | `1.95-2.00 deg` | `17` | `81.94%` | `68.41-87.62%` |
| `sp` | `dataset3` | `4.00 deg` | `17` | `80.77%` | `66.88-85.54%` |
| `sp` | `dataset4` | `6.00 deg` | `17` | `79.58%` | `65.78-83.27%` |
| `sp` | `dataset5` | `8.95-9.00 deg` | `17` | `78.72%` | `65.68-82.38%` |
| `sp` | `dataset6` | `89.90 deg` | `17` | `2.74%` | `1.25-7.42%` |

The learned map stores polar azimuth by range statistics: persistent echo
frequency, DBZH p10/median/p90, near-zero VRAD frequency, low SQI frequency,
and low/unstable RHOHV/ZDR evidence. At application time, a gate is removed only
when the trained persistent-background evidence is supported by current or
learned static-velocity, SQI, or dual-pol instability evidence and the current
DBZH is not substantially stronger than the learned p90. This is the strong
current-signal guard that prevents the model from deleting new echoes merely
because they occur over a known clutter location.

The SP result is deliberately reported separately from LP. The non-vertical SP
sweeps have much shorter range and a persistent low-quality/noise signature on
this date; the learned model removes a large share of those finite gates. The
near-vertical SP sweep behaves differently and removes only a small share.
Before using the SP defaults as a biological-science decision filter, inspect
the per-radar plots and sidecars for the target regime being studied. The app
can apply them by default because the model key and shape must match, but this
report does not claim that every SP masked gate is non-biological.

The plots below show the Druim a Starraig low-elevation LP model as a
representative per-radar example. Equivalent model plots, raw/mask/cleaned
examples, persisted masks, and JSON sidecars are stored for every target under
the all-sweep validation report directory.

![Druim a Starraig learned persistent echo frequency](_static/qc_results/learned_background_druima_20260703/model_persistent_echo_frequency.png)

![Druim a Starraig learned near-zero VRAD frequency](_static/qc_results/learned_background_druima_20260703/model_near_zero_vrad_frequency.png)

![Druim a Starraig learned low SQI frequency](_static/qc_results/learned_background_druima_20260703/model_low_sqi_frequency.png)

![Druim a Starraig learned DBZH p90 guard](_static/qc_results/learned_background_druima_20260703/model_dbzh_p90.png)

The hold-out examples below show the real DBZH field, the learned background
mask, and the cleaned field. The fixed west-side clutter/background pattern is
removed consistently; variable echoes outside that learned background pattern
are retained.

![Druim a Starraig hold-out raw, mask, and cleaned examples](_static/qc_results/learned_background_druima_20260703/validation_holdout_examples.png)

![Druim a Starraig hold-out masked share by scan](_static/qc_results/learned_background_druima_20260703/validation_masked_percent_by_scan.png)

Default selection is constrained by model key. The Python desktop path selects a
packaged model only when radar, pulse, quantity, dataset, and elevation match.
The iOS path bundles the same keyed model set and rejects mismatched model keys
before application, so no artifact is used on another radar by shape alone.

This is now a complete same-day DBZH model set for the current public radar
catalog, all available DBZH elevations, and both pulse types. It is still not an
archive-wide claim for every season, weather regime, or biological target
regime; those additional artifacts should be trained and validated as separate
keyed model families.

## Technical Summary

The companion best validated configuration is `signal_preserving`. It uses the
estimated range-dependent noise profile as evidence, not as a hard reflectivity
cutoff. A gate is removed only when the background profile is supported by
texture, same-dataset companion-field, or static-clutter evidence. The default
evidence margin is `0 dB`, and hard noise-floor masking is disabled.

On the first real PVOL validation scan, the pipeline completed successfully,
persisted a `qc_mask` artifact, and retained `47,705` of `153,000` finite DBZH
gates (`31.2%`). Removed gates required explicit evidence: companion-field/SQI
QC removed `50,248` gates (`32.8%` of finite input), texture-speckle logic
removed `44,311` gates (`29.0%`), and static-clutter logic removed `10,736`
gates (`7.0%`). The hard `NOISE_FLOOR` count is `0`.

Synthetic/unit tests also pass for the implemented mask components: source
nodata and domain masking, legacy hard noise-floor masking,
signal-preserving low-SNR retention, texture-speckle masking, static clutter
from near-zero velocity, companion-field QC, same-dataset companion-field
auto-gathering, and legacy display-cleanup filter mapping.

The signal-preserving configuration and learned low-elevation background models
are ready to use as the default app/export cleanup path in the desktop and iOS
apps for matching scans. Broader VP scientific validation still needs separate
checks across elevations, pulses, seasons, precipitation regimes, and biological
target regimes.

## Key Results From Real PVOL Validation

The real-data validation used the public Chenies PVOL object below and required
a real local HDF5 source file, not a synthetic fallback.

| Field | Value |
| --- | --- |
| Validation status | Passed |
| Validation type | `qc_mask` |
| Mask version | `qc-v1` |
| Cleanup mode | `signal_preserving` |
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
| Retained after QC | 47,705 | 31.2% |
| Masked by companion/SQI QC | 50,248 | 32.8% |
| Masked by texture speckle | 44,311 | 29.0% |
| Masked by static clutter | 10,736 | 7.0% |
| Masked by hard noise floor | 0 | 0.0% |
| Total finite input | 153,000 | 100.0% |

The persisted mask result contains no overlapping removal flags for this scan:
the three non-zero removal counts sum to the total masked count of `105,295`
gates.

## The Noise Profile Is Range Dependent

The estimated floor is derived per range bin using the configured low-signal
profile method. In `signal_preserving` mode, the floor is evidence used by the
texture, companion-field, and static-clutter checks; it is not a hard cutoff.
The evidence offset is `0 dB`, hard noise-floor masking is disabled, and the
separate near-noise evidence window is `6 dB` only when combined with other
quality or texture evidence. Near the radar, the estimated floor is materially
higher; after the first few kilometres it settles into a lower background level
and then rises gradually at long range.

![Chenies estimated noise profile](_static/qc_results/chenies_qc_noise_profile.png)

This profile-driven behaviour is the main reason the same fixed reflectivity
value is not treated identically at every range. For the validated scan, the
profile contributes context for texture and companion-field scoring, but it does
not independently delete weak coherent signal.

## Synthetic and Unit Validation

The synthetic tests exercise the mask mechanics independently of the Chenies
case. They are small by design, which makes them useful for proving that each
flag path is reachable and deterministic.

| Test coverage | Evidence |
| --- | --- |
| Source nodata and explicit domain masking | `NO_DATA` and `USER_DOMAIN` flags are set and masked values become `NaN`. |
| Legacy estimated noise floor and local texture | `display_standard` can still hard-mask low-profile gates and one isolated high-texture gate is flagged as `TEXTURE_SPECKLE`. |
| Signal-preserving low-SNR retention | Low reflectivity alone does not set `NOISE_FLOOR` or remove a coherent gate. |
| Static clutter | A near-zero velocity block with enough neighbouring support is flagged as `STATIC_CLUTTER`. |
| Companion QC | Low `SQIH` near the estimated profile can flag the target gate as `DUALPOL_QC`; low `RHOHV` alone is retained in the default path. |
| Companion-field auto-gathering | A synthetic ODIM/HDF5 file exposes `DBZH`, `SQIH`, and `RHOHV` to the shared filter path. |
| Legacy filter compatibility | Existing display cleanup parameters map into a deterministic `QCConfig`. |

The full project test suite passes with these checks included: `200 passed, 1
warning`. The warning is an existing Starlette/FastAPI test-client deprecation
warning and does not affect the QC result.

## Method and Configuration Used

The real-data validation was run through the same `qc_mask` export path used by
the app/API processing layer. The active app-default configuration was:

| Parameter | Value |
| --- | --- |
| `qc_mode` | `signal_preserving` |
| `noise_floor_method` | `estimated` |
| `noise_floor_percentile` | `10` |
| `noise_floor_window_bins` | `11` |
| `noise_floor_margin_db` | `0.0` |
| `noise_floor_hard_mask` | `false` |
| `near_noise_margin_db` | `6.0` |
| `rhohv_low_is_noise_evidence` | `false` |
| `companion_qc_near_noise_only` | `true` |
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
  --qc-mode signal_preserving \
  --noise-floor-margin-db 0 \
  --output-dir /tmp/uk_wsr_qc_validation_signal \
  --report /tmp/uk_wsr_qc_validation_signal/report.json \
  --require-real-hdf5
```

The persisted result was a compressed mask product plus JSON sidecar:

| Artifact | Result |
| --- | --- |
| Mask `.npz` | `chenies_20260625_DBZH_qc_mask.npz`, `133,023` bytes, SHA256 `29b3f0a063fff20ae2a4a7a092347416df165c71331b988b82125a5484903edf` |
| Sidecar `.json` | `chenies_20260625_DBZH_qc_mask.npz.json`, `15,520` bytes, SHA256 `4dbea0887c1b92709baf041dc7ec66372adb38a693a7b488303a25bc1f532d15` |

## Interpretation

The signal-preserving QC configuration is doing what it was designed to do on
this scan: it removes confident noise, isolated speckle, and stationary clutter
without treating low reflectivity as a sufficient deletion reason. The retained
gate count increased from the superseded hard `6 dB` validation result
(`3,414` gates, `2.2%`) to `47,705` gates (`31.2%`) while still removing
`105,295` gates with explicit noise/clutter evidence.

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
- The iOS renderer has matching concepts and now defaults to the same
  signal-preserving evidence-margin setting, but Python-to-iOS golden-array
  parity has not yet been established.
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
