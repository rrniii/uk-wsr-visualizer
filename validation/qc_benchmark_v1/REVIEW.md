# UK WSR QC Blinded Review Targets

Status: **ready for review**

The review workload contains 1,632 DBZH sweeps selected from
816 independent PVOL files. Every volume
contributes its lowest elevation and one round-robin coverage elevation.

- LP targets: 816
- SP targets: 816
- Lowest-elevation targets: 816
- Rotating all-elevation targets: 816
- Independently double-reviewed targets: 408

Primary reviewers see raw DBZH and available VRADH, SQIH, RHOHV, ZDR, PHIDP,
and WRADH panels. CI and every current/community/learned QC prediction are
hidden during primary review. Ambiguous areas must be labelled `uncertain`
rather than forced into remove or retain.

Validation errors: 0.

## Run the reviewer

Primary review:

```bash
PYTHONPATH=src .venv/bin/python tools/serve_qc_review.py \
  --reviewer REVIEWER_NAME \
  --stage primary
```

Independent secondary review is restricted to the 408 targets marked for
double review:

```bash
PYTHONPATH=src .venv/bin/python tools/serve_qc_review.py \
  --reviewer SECOND_REVIEWER_NAME \
  --stage secondary
```

The application runs at `http://127.0.0.1:8765`. Use `--radar`, `--split`, or
`--limit` to make an assignment. Each reviewer/stage writes a separate,
atomically replaced JSON file under `validation/qc_benchmark_v1/annotations/`.

The server only reads the target's explicitly whitelisted raw fields. Requests
for CI, current QC masks, learned maps, or community-filter predictions are
rejected. A `polar_gate_polygon` vertex is stored as
`[ray_index, gate_index]`; ray zero is north, rays increase clockwise, and gate
zero is at the radar.
