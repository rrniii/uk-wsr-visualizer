# UK WSR Learned-Background Training Sources v2

This manifest is the leakage-controlled source contract for multi-date learned
noise and clutter priors.

- Radars: 17
- PVOL files: 2176
- Training year: 2023
- Independent validation/holdout year: 2025
- Selection errors: 0
- Validation errors: 0

Every PVOL contains all native elevations. DBZH supplies the reference gate
geometry while CI, VRAD, SQI, RHOHV, ZDR, PHIDP, and spectrum width provide
joint evidence. The resulting artifact decision is shared by collocated
quantities; missing or misaligned evidence fails open.

The QC benchmark URLs, radar/date pairs, and downloaded SHA-256 values are
excluded. Source hashes must be verified again while materialising the corpus.
Whole dates are exclusive to one of training, validation, or holdout for each
radar.
