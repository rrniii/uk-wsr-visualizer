# Learned Background Model Registry: qc-v2 Qualification Audit

Status: **187 models quarantined; 0 eligible for automatic use.**

This audit supersedes the July 2026 same-day learned-background validation as
release evidence. A model is not selected automatically merely because its
file is packaged. It must be explicitly qualified in this schema-v2 registry
and must pass the independent runtime diversity check.

## Release Policy

- Required QC contract: `qc-v2`
- Minimum training dates: 7
- Minimum training span: 14 days
- Minimum independently held-out validation dates: 2
- Accepted validation designs: `date_held_out`, `site_and_date_held_out`
- Required runtime arrays: `sample_count`, `persistent_echo_frequency`, `dbzh_p90`, `near_zero_vrad_frequency`, `ci_sample_count`, `low_ci_frequency`

## Network Coverage

| Radar | LP targets | SP targets | Total | Eligible | Quarantined |
| --- | ---: | ---: | ---: | ---: | ---: |
| castor-bay | 5 | 6 | 11 | 0 | 11 |
| chenies | 5 | 6 | 11 | 0 | 11 |
| clee-hill | 5 | 6 | 11 | 0 | 11 |
| cobbacombe | 5 | 6 | 11 | 0 | 11 |
| crug-y-gorrllwyn | 5 | 6 | 11 | 0 | 11 |
| deanhill | 5 | 6 | 11 | 0 | 11 |
| druima-starraig | 5 | 6 | 11 | 0 | 11 |
| dudwick | 5 | 6 | 11 | 0 | 11 |
| hameldon-hill | 5 | 6 | 11 | 0 | 11 |
| high-moorsley | 5 | 6 | 11 | 0 | 11 |
| holehead | 5 | 6 | 11 | 0 | 11 |
| ingham | 5 | 6 | 11 | 0 | 11 |
| jersey | 5 | 6 | 11 | 0 | 11 |
| munduff-hill | 5 | 6 | 11 | 0 | 11 |
| predannack | 5 | 6 | 11 | 0 | 11 |
| thurnham | 5 | 6 | 11 | 0 | 11 |
| wardon-hill | 5 | 6 | 11 | 0 | 11 |

## Qualification Failures

| Reason | Models |
| --- | ---: |
| `insufficient_training_dates:1<7` | 187 |
| `insufficient_training_span_days:0<14` | 187 |
| `insufficient_validation_dates:0<2` | 187 |
| `missing_runtime_arrays:ci_sample_count,low_ci_frequency` | 187 |
| `qc_version:qc-v1-legacy!=qc-v2` | 187 |
| `validation_design:same_day_within_sequence` | 187 |

## Interpretation

The quarantined files remain available only as historical qc-v1 research
artifacts. They are excluded from desktop and iOS automatic selection. They
must not be described as validated clutter-removal defaults.

The next qualifying run must train across multiple dates and validate on
different dates. It must also persist CI statistics required by qc-v2 and pass
the signal-retention and vertical-profile release gates.
