# UK WSR Temporal QC Blinded Review

Status: **ready for independent review; sealed holdout remains closed**

This package contains 376 raw review targets covering
187 validation geometries. Each geometry contributes
one candidate-challenge scan and one candidate-independent control. The package
also contains 2
reported regressions.

- LP targets: 171
- SP targets: 205
- Required independent double reviews: 376

Reviewers see raw current companion fields and raw previous, next, and
upper-elevation context where available. They do not see CI, Candidate 5 masks,
community masks, the challenge/control identity, or the reported-failure text.
Ambiguous gates must be labelled `uncertain` and excluded from accuracy scores.
