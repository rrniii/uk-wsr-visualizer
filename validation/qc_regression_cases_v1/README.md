# UK WSR QC regression cases

This manifest pins user-reported cleanup failures as exact, reproducible
real-data validation inputs. Each case contains the displayed PVOL plus its
two same-pulse temporal neighbours. Source bytes must match the recorded
SHA-256 digest before scoring.

The cases are not labels. Candidate removal masks remain ineligible for
promotion until the raw DBZH and companion fields have been reviewed without
seeing CI or any cleanup output. Uncertain gates default to retain.

Candidate 5 currently removes 0.64% of finite gates in the High Moorsley LP
4-degree case and 1.80% in the SP 1-degree case. These descriptive footprints
replace the deployed filter's reported 96-97% blanking, but the SP mask still
contains high-reflectivity gates and therefore requires blinded review.

Run a downloaded case with `tools/validate_qc_regression_case.py`, then render
its exact raw, baseline, learned-only, and cleaned masks with
`tools/render_background_validation_report.py`.
