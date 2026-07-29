# QC v3: signal-preserving noise and clutter removal

Implementation and validation status, 26 July 2026

## Executive summary

`qc-v3` is implemented as a preservation-first nuisance detector for UK Met
Office weather-radar polar volumes. Its objective is narrow:

> Remove confirmed receiver noise and clutter while retaining precipitation,
> birds, insects, mixed echoes, clear-air atmospheric signal, and unresolved
> gates.

It is not a weather classifier, a biological classifier, or a display cleanup
effect. Every decision is represented as a scientific quality-control mask
with probabilities, reason flags, abstentions, feature availability, source
checksum, calibration stratum, and versioned provenance.

The current release posture is:

| Component | Status |
| --- | --- |
| Conservative `safe` runtime | Implemented and tested |
| Learned `shadow` runtime | Implemented; proposals do not delete gates |
| Learned `validated` runtime | Implemented; fails open without a signed, matching release bundle |
| Desktop integration | Implemented with automatic temporal/elevation context |
| Native iOS integration | Implemented with the same safe/shadow/validated contract |
| Persisted masks and sidecars | Implemented |
| Exact synthetic validation | Passed |
| Real PVOL regression execution | Complete for the two pinned failure cases |
| Human-labelled real-data accuracy | Not yet available |
| Learned-model promotion | Blocked |

The app default is therefore the minimal `safe` policy. A learned background
model is not allowed to remove data until it passes the independent,
preservation-first release process defined below.

## Scientific design

### Preserve echo classes; detect nuisance mechanisms

A conventional precipitation-only gate filter is unsuitable for this project.
Low correlation coefficient, low signal quality, near-zero velocity, weak
reflectivity, or spatial texture can occur in insects, birds, mixed-phase
weather, clear-air echoes, and clutter. None is a sufficient deletion rule.

`qc-v3` instead separates the nuisance mechanisms:

- receiver noise;
- persistent ground clutter;
- anomalous propagation;
- sea clutter;
- wind-turbine contamination;
- radial interference;
- isolated speckle;
- invalid or missing source data.

Each mechanism has its own evidence path. Unsupported or contradictory gates
abstain and remain visible.

This structure follows the strongest ideas in operational and community
systems without pretending that archived ODIM moments can reproduce signal
processing that requires I/Q data:

- wradlib separates Gabella clutter detection from fuzzy echo
  classification;
- Py-ART combines moment thresholds and textures in gate filters;
- LROSE RadxPid uses wavelength- and transmit-mode-specific fuzzy
  configurations;
- BALTRAD/RADVOL-QC decomposes artefacts into separate detectors and quality
  fields;
- conditional clutter mitigation applies filtering only where clutter has
  first been identified.

### Three runtime modes

| Mode | Applied deletion | Learned output |
| --- | --- | --- |
| `safe` | Only the minimal high-confidence evidence rules | Candidate probabilities and abstentions are retained for audit |
| `shadow` | Exactly the safe mask | Learned proposals are measured but never applied |
| `validated` | Learned proposal only when a hash-valid released bundle supports the exact stratum | Otherwise fails open to the safe mask |

The calibration stratum includes radar identifier, pulse type, elevation,
quantity, and available-field regime. A model released for one stratum cannot
silently operate in another.

### Evidence policy

- `CI` is auxiliary evidence only. It is never a truth label or a sole
  deletion rule. Its relationship to clutter and noise is calibrated per
  radar, pulse, elevation, range, and field regime.
- `LONG_RANGE_NOISE_DBC_H/V` remains disabled. It can be enabled only for an
  exact stratum whose audit establishes non-sentinel semantics and incremental
  value beyond interpretable LOG/SNR/SQI and texture evidence.
- A learned background is a prior, not a mask. It requires current-scan and
  cross-scan confirmation.
- The base learned map requires at least 12 distinct training dates spanning
  at least 90 days.
- Seasonal or time-of-day buckets require at least two years of coverage and
  at least 12 dates in each bucket.
- Every background map, calibration table, and historical statistic is refit
  inside each training fold. Validation and holdout dates cannot contribute to
  those priors.
- Isolated-speckle deletion is disabled in the safe runtime.

### Automatic companion gathering

For desktop processing, `qc-v3` now automatically gathers:

- previous and next DBZH;
- previous and next VRAD when present;
- the next compatible elevation DBZH;
- same-sweep CI, SQI, RHOHV, ZDR, PHIDP, WRADH, VRADH, and other supported
  moments.

Temporal scans must use the same pulse, compatible elevation, ray/range
geometry, and a gap no greater than 20 minutes. Upper-elevation support must
have the same ray/range geometry. A missing download, field, or geometry match
removes only that evidence source; it does not fail the frame or delete a
gate.

The desktop PPI, preview metadata, point inspection, PNG export, and
`qc_mask` export paths all use the same context resolver. This prevents the
interactive view and its persisted scientific mask from silently evaluating
different evidence.

Native iOS resolves the same adjacent-volume and upper-elevation context before
running its local evaluator.

## Output contract

Each sweep produces a `QCMaskResultV3` with:

- applied removal mask;
- proposed learned-removal mask;
- abstention mask;
- probability for each nuisance mechanism;
- candidate and applied reason flags;
- retained-quality score;
- feature-availability flags;
- calibration stratum;
- source checksum;
- exact array hashes;
- runtime policy and model qualification;
- finite-gate counts before and after masking.

The exact arrays are stored in compressed NPZ and a JSON sidecar stores the
contract, counts, hashes, model identifiers, and provenance. The source PVOL
is never modified. Desktop `qc_mask` exports use this v3 contract while
retaining a compatibility `mask` array for existing readers.

## Real-data regression results

The immutable regression manifest contains the two user-reported High
Moorsley failures:

- LP, 11 July 2026 at 14:00 UTC, reported near-total loss at 4 degrees;
- SP, 11 July 2026 at 15:00 UTC, reported 97.3% loss at 1 degree.

The manifest pins previous/current/next PVOLs by SHA-256. Six files were
verified and every DBZH sweep in each current PVOL was evaluated: five LP
elevations and six SP elevations.

| Measure | LP | SP | Combined |
| --- | ---: | ---: | ---: |
| Sweeps | 5 | 6 | 11 |
| Finite gates | 765,000 | 397,800 | 1,162,800 |
| Safe removals | 683 | 34,475 | 35,158 |
| Safe removal share | 0.089% | 8.666% | 3.024% |
| Abstentions retained | 26,235 | 125,879 | 152,114 |
| Abstention share | 3.429% | 31.644% | 13.082% |

At the two reported elevations:

| Case | Finite gates | Safe removals | Share | Abstentions retained |
| --- | ---: | ---: | ---: | ---: |
| LP 3.95 degrees | 153,000 | 60 | 0.039% | 2,454 |
| SP 1.00 degree | 68,040 | 29 | 0.043% | 30,987 |

The SP 1-degree result is the critical regression: the old app removed 97.3%
of the displayed sweep; `qc-v3` safe mode removes 0.043%. Weather and the
near-radar mixed echo remain visible.

![SP 1-degree regression](_static/qc_results/qc_v3_real_regressions_20260726/plots/high-moorsley-20260711-sp-1500-e0100-dataset1-e01.000.png)

The combined removal percentage is dominated by SP at 9 degrees. That sweep
contains a broad annular pedestal; the safe receiver-noise rule removes 33,711
of 68,040 gates (49.55%). Those gates account for 95.9% of all removals in the
11-sweep run. This appearance and its supporting moments are consistent with
receiver noise, but appearance is not truth. The sweep is explicitly retained
as a high-priority human-review case.

![SP 9-degree high-removal case](_static/qc_results/qc_v3_real_regressions_20260726/plots/high-moorsley-20260711-sp-1500-e0100-dataset5-e09.000.png)

For this run:

- safe and shadow applied masks are byte-identical;
- no learned bundle or background prior is loaded;
- long-range-noise fields are disabled;
- isolated-speckle deletion is disabled;
- all candidate uncertainty remains visible.

These are descriptive results, not accuracy estimates. Without blinded human
truth, they cannot establish removal precision or retained-signal recall.

## Exact synthetic validation

The current exact-truth suite uses 24 independently seeded scenes: 12 LP and
12 SP. Each scene contains disjoint precipitation, biological, and clear-air
objects plus exact receiver-noise, static-clutter, anomalous-propagation,
radial-interference, and isolated-speckle masks.

Temporal brackets are complete but deliberately disagree by 5 dB and use
opposing high velocities. This prevents accidental temporal persistence from
becoming clutter evidence.

| Metric | Result |
| --- | ---: |
| Retained gates | 361,314 |
| Retained gates removed | 0 |
| Removal precision | 1.000 |
| Overall retained recall | 1.000 |
| Precipitation recall | 1.000 |
| Biological-echo recall | 1.000 |
| Clear-air recall | 1.000 |
| Retained objects | 72 |
| Completely removed retained objects | 0 |
| Minimum object area preserved | 1.000 |
| Nuisance recall | 0.546 |

Nuisance recall is intentionally secondary:

| Nuisance | Safe-mode recall |
| --- | ---: |
| Receiver noise | 0.612 |
| Radial interference | 0.330 |
| Isolated speckle | 0.011 |
| Static clutter | 0.000 |
| Anomalous propagation | 0.000 |

Static clutter and AP remain visible when the minimal evidence path cannot
prove nuisance. That is the intended safe baseline. A learned model must
improve these recalls only after every preservation gate passes.

![Exact synthetic truth examples](_static/qc_results/qc_v3_synthetic_20260726/examples.png)

Synthetic validation checks deterministic masks and implementation errors. It
does not authorise real-data promotion.

## Learned background design

The learned artefact is keyed by radar identifier, pulse type, elevation,
quantity, geometry, and optional qualified seasonal/time bucket. Polar
azimuth-by-range statistics include:

- persistent echo date frequency;
- median, p10, and p90 DBZH;
- near-zero VRAD date frequency;
- low-SQI date frequency;
- low or unstable RHOHV/ZDR frequency;
- sample/date counts and coverage span.

The model receives only training-fold dates. A gate can become a learned
clutter proposal only when the prior is qualified and the current scan supplies
multiple independent evidence families, complete temporal support, and
upper-elevation evidence where expected. A learned prior never overrides
coherent Doppler, spatial, temporal, or upper-elevation protection.

## Human review

One reviewer is sufficient for this project if reliability is measured.
Review is organised around connected regions, not complete 24-sweep batches.
The queue ranks:

- disagreement between safe rules, learned proposal, and community baselines;
- probability near the decision threshold;
- under-represented radar/pulse/elevation/range/season strata;
- high-reflectivity or coherent objects at risk;
- high-removal scans such as the SP 9-degree case;
- suspected sea clutter, AP, turbines, and interference.

For each region the reviewer chooses `Keep`, `Remove`, or `Uncertain`, adds a
nuisance subtype only when `Remove` is selected, and may paint corrections.
Validation and holdout prelabels are hidden. Events are append-only and retain
review duration, source checksum, and mask hashes.

Ten percent of decisions are repeated blindly after at least 14 days. The
release report includes raw agreement and Cohen's kappa for
`Keep/Remove/Uncertain`; the target is kappa at least 0.80.

## Release criteria

Whole PVOL/date groups are kept intact across train, calibration, validation,
and sealed holdout splits. Thresholds are selected to satisfy preservation
risk first, then maximise nuisance recall. Low-confidence gates abstain.

The learned candidate cannot be promoted unless the sealed real holdout meets
all of the following:

| Gate | Required value |
| --- | ---: |
| Overall retained-gate recall | at least 99.9% |
| Recall for each retained class | at least 99.5% |
| Removal precision | at least 99.0% |
| Median retained-object area preserved | at least 99.5% |
| Each retained class median object area preserved | at least 99.0% |
| Completely removed retained objects | 0 |
| Retained-signal removal in every sampled stratum | at most 0.5% |
| Sparse or unsupported strata | fail open |
| Python/desktop/iOS masks, abstentions, and reasons | byte-identical |
| Grouped bootstrap nuisance-recall improvement | lower confidence bound above 0 |

The real regression plots and synthetic pass do not satisfy these gates
because the real data are not yet independently labelled.

## Deployment policy

1. Keep `safe` as the desktop and iOS default.
2. Run learned bundles in `shadow` only.
3. Build the single-reviewer labelled development set through short,
   uncertainty-ranked sessions.
4. Audit CI and long-range-noise semantics per stratum.
5. Train fold-local backgrounds and a calibrated monotonic nuisance model.
6. Freeze code, thresholds, priors, and bundle hashes before opening the
   sealed holdout.
7. Require the preservation and parity gates above.
8. Roll out a passing model in shadow across every radar identifier represented
   in the corpus before changing any default.

There is no `Strong` user mode while learned subtraction is unvalidated.

## Reproduction

Run the real pinned regressions:

```bash
PYTHONPATH=src:/path/to/Avocet/src python \
  tools/validate_qc_v3_regression_manifest.py \
  --source-root /path/to/verified/pvol/files
```

Run the exact synthetic suite:

```bash
PYTHONPATH=src:/path/to/Avocet/src python \
  tools/validate_qc_v3_synthetic.py
```

The real report includes per-sweep CSV, colour-barred plots, compressed exact
masks/probabilities, JSON sidecars, input hashes, and array hashes.

## References

- [Met Office radar network and dual-polarisation programme](https://www.metoffice.gov.uk/research/approach/observations/weather-radar)
- [Met Office receiver-noise estimator](https://www.metoffice.gov.uk/research/news/2019/new-radar-noise-level-estimator)
- [Ivić, Curtis and Torres: automated receiver-noise estimation](https://journals.ametsoc.org/view/journals/atot/30/12/jtech-d-13-00008_1.xml)
- [wradlib clutter and echo-classification workflows](https://docs.wradlib.org/)
- [Py-ART GateFilter API](https://arm-doe.github.io/pyart/API/generated/pyart.filters.GateFilter.html)
- [LROSE RadxPid](https://github.com/NCAR/lrose-core)
- [BALTRAD/RADVOL-QC quality-control chain](https://rmets.onlinelibrary.wiley.com/doi/10.1002/met.1323)
- [ODIM HDF5 information model](https://www.eumetnet.eu/activities/observations-programme/current-activities/opera/)
- [Rico-Ramirez and Cluckie: dual-polarisation ground-clutter/AP classification](https://research-information.bris.ac.uk/en/publications/classification-of-ground-clutter-and-anomalous-propagation-using-/)
- [UK weather radar for aerial arthropod monitoring](https://doi.org/10.1111/gcb.70425)
