# Operational radar cleaning and evaluation

This package compares BALTRAD, PyRAD, LROSE and RACK against the immutable
68-volume UK radar benchmark, collects scientific review evidence, and publishes
the selected cleaned release for archive analysis. Source PVOLs are never edited.

## Scientific status

**A successful integrity audit is not scientific acceptance.** No processor is
selected automatically. The release command requires an explicit decision tied
to the exact code, policy, review evidence and radar/pulse/geometry groups.
The intended endpoint is an operational cleaned dataset, with a selected release
and no silent substitution of unprocessed data.

PyRAD uses its existing `QC_DECISION_PYRAD_V3` decisions. The other three policies
are newly defined **evaluation hypotheses**, not established production filters:

| Policy | Removal proposal | Limitations |
|---|---|---|
| BALTRAD compound | clutter score >= 0.99 AND residual flag >= 0.5 | Requires verification of exported score semantics; does not provide a complete receiver-noise model. |
| LROSE compound | persistent/sea clutter flag AND instantaneous ground-clutter PID flag | Missing evidence remains unsupported; RLAN-only removal and broad receiver-noise cleaning are not enabled. |
| RACK compound | emitter AND jamming >= 0.95, or ship AND speckle >= 0.95 | Only the first three sweeps at <=2 degrees; intersection rules may be too conservative. |

The new compound policies retain complete, smooth 3x3 DBZH neighbourhoods
(spread <=3 dB) and RHOHV >=0.95. These are deliberately conservative protection
hypotheses, **not biological classification or calibrated confidence**. They can
retain clutter. Only labelled evaluation can establish their suitability.
Thresholds must not be tuned against final acceptance labels. Change the policy
version and use fresh evaluation evidence after any tuning.

The benchmark contains 17 radars, LP/SP, and two dates. A score on selected
regions is not a nationwide seasonal accuracy estimate. A result with no labels
has no scientific score. Unsupported gates are excluded from scores and reported
separately. Targeted disagreement/damage cards are not representative samples.

## Install and configure

Install this subproject into a dedicated Python >=3.11 environment:

```bash
python -m pip install -e ./radar-operations
uk-wsr-ops --config /path/to/config.json audit --index 0 --metrics
```

Configuration is an explicit local JSON file. Keep actual data paths and run
artifacts on the compute system, outside this public repository:

```json
{
  "manifest": "/data/benchmark.json",
  "source_root": "/data/source/single-site",
  "state_root": "/data/evaluation",
  "releases_root": "/data/cleaned-releases",
  "processors": {
    "baltrad": {"output_root": "/data/baltrad/single-site"},
    "pyrad": {"output_root": "/data/pyrad/single-site"},
    "lrose": {"output_root": "/data/lrose/single-site"},
    "rack": {"output_root": "/data/rack-preserved/single-site"}
  }
}
```

Paths under each processor root mirror paths relative to `source_root`.
The processor output and the matching native sidecar are required.
The audit hashes source and output and compares every original HDF5 object,
dataset value, datatype and attribute. It does not claim independent validation
of upstream training selection or algorithm calibration.

## Benchmark and decision session

Run `audit --index N --metrics` as bounded LOTUS tasks for indices 0–67. Each
case writes its own atomic audit and metric files. Then run:

```bash
uk-wsr-ops --config /path/to/config.json summarize
uk-wsr-ops --config /path/to/config.json pack
uk-wsr-ops --config /path/to/config.json serve --port 8791
```

The server binds to localhost. Access it through an SSH tunnel. It offers
synchronized **native ray/range views**, a polar view using measured ray azimuths and slant range, cleaned and
removed fields, decision/coverage views, and polygon labels. The scale is fixed
by moment across panels. Source fields are unchanged.

The decision pack contains 12 deterministic representative cards, eight
disagreements and four potential-damage prompts. A positive damage proxy is not
a finding that weather or biological echoes were removed. No card labels are
generated automatically.

Use one stable reviewer ID. Record source labels before revealing candidate
outputs. Named exploration also marks the case exposed for that reviewer.
Subsequent labels remain in the audit trail but are excluded from strict scoring.
Annotation corrections use `supersedes` with a previous revision ID. Replacing a
source-first label after exposure removes the old label from strict scoring;
it does not make the correction blinded. Overlapping retain/remove labels are
ignored, rather than settled by ordering.

Export strict labels through `/api/export?strict=true`; all revisions through
`strict=false`. `/api/scores` reports each reviewer/case/sweep/processor separately,
including class-specific metrics and unsupported/uncertain coverage. It does not
pool different reviewers into invented consensus. `score` in `scoring.py` can be
used independently with reviewed gate polygons.

Session: 10 minutes on coverage, 45–60 minutes on cards, 15–20 minutes to select
the candidate and exact operating scope. Reject confirmed coherent useful-echo
loss; then prioritise retention, artefact removal, coverage and operational cost.
Record specific failing conditions as fix-and-retest issues.

## RACK preservation adapter

The original RACK pilot preserved source moment arrays but changed metadata.
`python -m uk_wsr_ops.prepare` verifies that pilot, copies its RACK-owned quality
groups onto a fresh source copy, and verifies complete native preservation.
Original pilot outputs are retained. The new sidecar records both upstream and
merged-output hashes. Missing pilot results are generated with the separately
installed RACK runtime. The adapter does not invent diagnostic fields.

## Operational release

1. Export the reviewed strict annotation evidence to an immutable JSON file.
2. Generate a pending decision with `decision-template`. After the scientific
   session, record `status: approved`, selected `processor`, `policy_sha256`,
   reviewer, rationale, and the evidence file path and SHA-256. Freeze the selected vendor code/calibration files in `dependency_sha256` and record their canonical mapping hash as `runtime_identity_sha256`. Set
   `blocking_failures: []` only after those failures are resolved.
3. List approved `supported_groups` as `radar|pulse|geometry_sha256` using
   `operations.geometry_id(source)`. Code/policy or geometry changes require a
   new decision. The evidence must include source-first retain and artefact
   annotations; the approval is still the reviewer's scientific judgment.
4. Run a selected case, validate its cleaned output, and build the catalogue:

```bash
uk-wsr-ops --config config.json run-one --index 0 --decision decision.json --releases /data/releases
uk-wsr-ops --config config.json publish --decision decision.json --releases /data/releases
uk-wsr-ops --config config.json activate --catalogue /data/releases/RELEASE/catalogue.json --releases /data/releases
uk-wsr-ops --config config.json selected --releases /data/releases --case-id CASE
```

The selected-product resolver is the operational archive interface. Its output
contains the cleaned PVOL path, default `DBZH_CLEAN_OPS` quantity, release and
source checksum. The review service exposes it at `/api/operational/{case_id}`.
No selected release or missing products produce explicit errors; raw fields are
never substituted. Existing public/desktop catalogues are not silently rewritten.
Consumer migration to this interface is a separate integration check before
calling the full operational rollout complete.

Cleaned products retain all source objects and append supported `_CLEAN_OPS`
moments, `QC_DECISION_OPS` and `QC_REASON_OPS`. Decisions are 0 retain, 1 remove,
2 uncertain/retained, 3 unsupported/retained. Nodata and undetect inputs remain
unmeasured rather than labelled noise. Cleaned measured values use float32
encoding; validation checks preservation within documented numerical tolerance.

## Archive batches, recovery and monitoring

`freeze-archive --cases cases.json --destination archive.json` freezes an explicit
list of case IDs, radar, pulse and source paths with actual source checksums.
It does not discover a new scientific benchmark or access held-out data.
Point a new config at that archive manifest. `python -m uk_wsr_ops.vendor` adapts
the installed processing APIs to arbitrary checksum-frozen archive cases while
retaining each runtime and its calibration/geometry checks. All four adapters
have passed a separate one-volume archive-manifest canary. This does not qualify
unseen geometries or the entire archive. The processor
`command` array accepts `{source}`, `{output}`, `{case_id}`, `{manifest}` tokens
and runs without a shell. Missing commands/evidence fail explicitly.

`submit --decision ... --releases ... --interpreter ... --script ...` writes a
bounded LOTUS script and shows the submission arguments. Add `--execute` to
submit. Each task locks its own record; valid source/evidence/output identities
are skipped on restart. Transient processor exit codes 75/124 receive at most
two retries. Other failures are recorded and not blindly retried.

The catalogue reports requested, validated and pending cases. Failed case
records retain their error and runtime timestamps. Run summaries and review
inventory remain on the compute filesystem. The reviewer includes an operational-health panel and `/api/operations`;
`status` writes a timestamped status record. A five-minute user timer refreshes
health. Optional reviewed per-radar/pulse `drift_bounds` flag removed fractions
outside the recorded minimum/maximum; no bounds are fabricated before scientific
selection. No unattended incident messages are sent.

Publish/activate only after the batch validates. Activation retains previous
selection records under `history/`. Rollback reactivates the previous validated
catalogue. Republished catalogues require explicit activation; altered selected
catalogues/products fail checksum checks.

## Tests

```bash
PYTHONPATH=radar-operations python -m pytest radar-operations/tests -q
```

Tests cover full source preservation, RACK metadata repair, ODIM decoding,
ambiguous retention, unsupported coverage, polygon conflicts, useful-echo loss,
source-first annotation, revision exports, release approval, idempotent resume,
selected-product resolution and tamper detection. Synthetic test approvals are
confined to temporary fixtures; no real release approval is generated by tests.
