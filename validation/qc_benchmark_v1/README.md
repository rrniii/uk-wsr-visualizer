# UK WSR Independent QC Benchmark v1

Status: **complete and ready for triage**

This manifest defines the real-data evaluation corpus for clutter and noise
removal. It contains 816 complete PVOL files from
17 radars, both pulse types, all elevations, four
seasons, and six UTC time slots. The referenced source volume is approximately
3.96 GiB.

| Split | PVOL files |
| --- | ---: |
| development | 272 |
| holdout | 272 |
| validation | 272 |

Every source URL is unique and is excluded from learned-background training.
All elevations from one PVOL remain in one split. The holdout dates must not be
used for threshold selection, feature engineering, model training, or
qualitative tuning.

## Ground-Truth Contract

- Primary review uses raw DBZH and companion fields while remaining blind to
  current QC masks and scores.
- CI may be inspected as one instrument field, but it is never a label.
- Current `qc-v2`, community filters, and learned maps are benchmark
  predictions, never annotation sources.
- `remove` is limited to noise, clutter, interference, isolated speckle, and
  invalid measurements.
- Weather, birds, insects, clear-air structure, mixed echoes, and every other
  coherent measured signal are labelled `retain`.
- Ambiguous gates are `ignore`, not silently converted into removal targets.
- At least 20% of evaluated targets require an independent secondary review,
  followed by adjudication where remove/retain decisions disagree.

## Files

- `manifest.json`: immutable source selections and split assignments.
- `manifest.sha256`: checksum used by annotation files.
- `annotation.schema.json`: machine-readable region annotation contract.
- `annotations.template.json`: empty primary-review document.
- `excluded_from_training.txt`: source URLs that training jobs must reject.

Selection errors: 0. Validation errors:
0.
