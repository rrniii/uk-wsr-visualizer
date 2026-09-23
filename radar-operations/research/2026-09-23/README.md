# Repaired radar comparison and first development review

23 September 2026. **PyRAD echo-clean-v3 is the leading configuration for the next validation round, not an approved operational selection.** The corrected comparison now exposes real failures to investigate. No candidate has demonstrated biological retention, and the current two-date benchmark cannot establish archive-wide performance.

The intended endpoint remains a selected cleaned working archive. Raw PVOLs remain immutable. This round repairs the evidence and starts scientific review; it does not activate an archive release.

## What is complete

- Corrected diagnostic meanings, versioned all four policy identities, and made stale packs/metrics fail explicitly.
- Re-audited 68 source volumes and all 272 processor outputs, covering 374 sweeps. All source-preservation checks passed; there were no decision failures.
- Regenerated the 24-card decision pack: 12 representative, eight disagreement and four potential-damage prompts. It now has 170 eligible sweeps, compared with 106 previously; 12 card/sweep pairs overlap the previous pack.
- Inspected all 24 source panels from the previous development pack, recorded source observations, counted all four policies on those sweeps, and visually inspected six detailed candidate comparisons (cards 6, 8, 17, 20, 22 and 24). This is not a claim to have visually compared every candidate on every new card.
- Passed 27 tests locally and in the locked JASMIN Python 3.11 runtime, plus Ruff and diff checks. Eight LP/SP cleaned-product canaries passed preservation, retained-value and mask checks; source hashes were unchanged.
- Updated the existing reviewer and five-minute health service with a recovery copy and intact review history. The live browser rendered all four candidate panels under a dedicated test identity. Operational status remains `awaiting_scientific_selection`.

## What was repaired

LROSE binary false flags are valid zero-valued evidence rather than missing data. Known RACK detector `undetect` codes similarly mean zero response, including the emitter's reserved code whose ordinary gain/offset decoding gives -0.004. Moment-field undetect and diagnostic nodata remain unmeasured. Unsupported fields and sweeps remain explicit.

BALTRAD's residual one means retained; zero is not an independent clutter vote. The repaired evaluation policy uses the frozen native fuzzy-stage quality threshold of 0.75 and its input floor of -20 dBZ (TH, or DBZH if TH is absent), followed by the existing echo-protection rule. Below-floor gates remain unsupported and retained. Residual zero alone contributes uncertainty. This policy is a new evaluation hypothesis, not the complete native PPC removal chain or a validated biological classifier.

The PyRAD, LROSE and RACK removal counts are unchanged on every sweep. RACK's intersection rules have deliberately not been replaced by unvalidated unions. Individual detector responses are now visible in metrics. Whole-scope labelled scores count unsupported retained artefacts as unremoved, alongside the conditional supported-only scores.

## Measured behaviour across the benchmark

All fractions below use **39,535,200 finite source-DBZH gates**, including instrument background. These are behaviour and coverage counts, not scientific accuracy. Uncertain gates are retained; missing/undetected source gates are excluded.

| Current configuration | Supported gates, previous → repaired | Repaired coverage | Removed gates, previous → repaired | Uncertain retained |
|---|---:|---:|---:|---:|
| BALTRAD | 39,535,200 → 28,150,869 | 71.20% | 0 → 16,856,312 | 11,209,887 |
| PYRAD | 39,535,200 → 39,535,200 | 100.00% | 21,174,487 → 21,174,487 | 11,701,038 |
| LROSE | 252,970 → 37,576,800 | 95.05% | 197,077 → 197,077 | 19,205,906 |
| RACK | 238,365 → 20,232,720 | 51.18% | 0 → 0 | 13,913 |

The no-removal control retains all finite gates and removes none. It has no labelled accuracy score here. RACK's current final mask behaves like that control; its 51% diagnostic scope is still a separate limitation.

The automatic “potential useful echo loss” flag must not be used as a score. BALTRAD/LROSE/RACK explicitly protect the same smoothness/high-correlation proxy, making their zero proxy loss a consequence of their rule. Conversely, most of PyRAD's proxy overlap occurs in SP data where a smooth receiver background can trigger the proxy. A removed smooth gate is not necessarily lost weather or biology.

## What the first examples show

**PyRAD is the most promising candidate to validate first.** It retains the selected Dudwick, Chenies and Castor Bay probable-weather interiors while removing substantial off-echo background. However, it removes 252 of 3,000 gates in the Dean Hill probable-useful region and 19 of 135 in the small Chenies SP region. Those are regions needing investigation, not independently confirmed weather-loss rates. Source snapshots cannot settle mixed echoes or biological identity.

**BALTRAD's repaired mask reveals a substantial retention concern.** Its fuzzy stage proposes rejection for 28,066,199 of 28,150,869 supported gates (99.70%). In the selected Chenies weak-echo region it removes 170/225 gates, and in the Castor Bay connected-echo region 467/1,000, versus zero for PyRAD/LROSE/RACK. Visual comparisons show substantial holes in probable-weather structures. Correct mask interpretation does not validate the frozen PPC inputs, membership functions or thresholds for these UK modes.

**The shared smoothness protection also preserves probable background.** Both Wardon Hill SP background rectangles contain 3,200 finite gates, all satisfying that protection proxy. BALTRAD/LROSE/RACK remove zero there. PyRAD removes 2,631 in winter and 2,731 in summer. Instrument calibration and neighbouring volumes are still needed to confirm the background hypothesis.

**LROSE and RACK are currently more useful as diagnostic components than complete background cleaners.** LROSE's persistent-clutter flag is positive at zero gates despite 37,576,800 supported gates; its sea-clutter flag is positive at 19,166,611 gates. Those distributions need a map/PID/input-mode audit. RACK has 13,913 jamming-positive gates at the configured threshold, and no emitter/ship/speckle positives at that threshold. Its intersections therefore remove nothing. This does not establish that the libraries themselves are ineffective.

Hameldon Hill's narrow radial structures remain ambiguous: shape and high RHOHV alone do not establish interference or weather. None of this round provides a defensible biological-echo ground truth or subtype classification.

## Region counts for reproducibility

Rectangles were chosen from source panels before generating the new candidate plots, but earlier candidate metrics and selection criteria were known. They are **assistant hypotheses, not independent acceptance labels**. Bounds and source hashes are in the JSON records. A rectangle may contain mixed or misidentified gates; do not pool these into an accuracy estimate.

| Original card | Region hypothesis | Finite gates | BALTRAD removed | PyRAD removed | LROSE removed | RACK removed |
|---|---|---:|---:|---:|---:|---:|
| 01 | Probable useful echo | 3,000 | 2,165 | 252 | 8 | 0 |
| 04 | Probable useful echo | 135 | 93 | 19 | 0 | 0 |
| 05 | Probable useful echo | 750 | 195 | 0 | 0 | 0 |
| 06 | Probable background | 3,200 | 0 | 2,631 | 0 | 0 |
| 07 | Probable useful echo | 600 | 317 | 0 | 0 | 0 |
| 08 | Probable useful echo | 1,200 | 526 | 0 | 0 | 0 |
| 10 | Probable useful echo | 400 | 235 | 4 | 0 | 0 |
| 12 | Probable useful echo | 225 | 111 | 0 | 0 | 0 |
| 13 | Probable useful echo | 400 | 282 | 0 | 0 | 0 |
| 19 | Probable useful echo | 800 | 89 | 0 | 0 | 0 |
| 20 | Probable useful echo | 225 | 170 | 0 | 0 | 0 |
| 21 | Probable background | 3,200 | 0 | 2,731 | 0 | 0 |
| 22 | Probable background | 7,500 | 3,621 | 5,535 | 49 | 0 |
| 24 | Probable useful echo | 1,000 | 467 | 0 | 0 | 0 |

The source and comparison atlases accompany the private delivery. They use native ray/gate geometry, common DBZH limits, physical units and explicit missing/removed states. Source velocity panels use the same -20 to +20 m/s display range; clipping is recorded. The observed native velocity ranges differ between LP (approximately ±4 m/s) and SP (approximately ±48 m/s); confirm acquisition/Nyquist metadata before interpreting velocity differences as target differences.

## Work queue and decision gates

| Priority | Next investigation | Concrete completion evidence |
|---|---|---|
| 1 | Trace PyRAD removals in Dean Hill and the small Chenies SP feature; test static-map overrides, weak weather, biology and mixed echoes. | Source/context evidence for removed gates, detector attribution, adjacent scans/elevations, and separately identified expert or independent reference labels. |
| 2 | Audit BALTRAD's nearly universal fuzzy rejection and LP/SP input conventions. | Native-chain reference comparison, field/units/Nyquist and membership-function checks, and positive/negative meteorological examples. Any policy revision gets a new identity and fresh evaluation. |
| 3 | Audit LROSE persistent-map and sea/PID distributions; review RACK detectors individually at native response scales. | Confirmed map/geometry coverage and target-specific positive/negative cases. A combined policy must be evaluated as a new candidate. |
| 4 | Freeze new event blocks, beyond these two dates, before additional tuning. | Training/calibration exclusion proof; development and untouched acceptance splits by event, site/mode, echo class and difficult conditions. Include actual biologically active events and mixed cases. |
| 5 | Select and activate the simplest configuration meeting agreed scientific limits over its stated scope. | Class-specific useful-echo loss and artefact removal, uncertainty and coverage, event-level uncertainty, operational cost, a checksum-bound decision, validated archive batch and consumer check. |

The existing benchmark is now development evidence. The new 24-card pack is still drawn from the same 68 volumes; it is not an independent acceptance set. No numeric scientific acceptance threshold has been invented, and no assistant observation has been submitted as a strict acceptance annotation or under the user's identity.

The literature links and examples supporting the review method remain in the [22 September knowledge base](../2026-09-22/README.md), particularly noise-floor error (P05), useful biological echoes in frequency maps (P03), polarimetric aspect dependence (P14), interference overlap (P15/P17), and independent evaluation design (P09). Those examples guide tests; they do not label these data.

## Reproducible evidence

- `semantic-repair-summary.json`: complete before/after counts, LP/SP strata, detector counts, manifest and policy hashes.
- `source-observations.json` and `source-card-index.json`: 24 assistant source observations, source hashes, native geometry, displayed ranges and clipping counts.
- `development-comparison.json`: per-sweep and per-region behaviour, frozen observation-file hash, and explicit non-acceptance provenance.
- `verification.json`: code identity, 272 integrity checks, 27 tests, eight canary identities and deployment checks.
- `SHA256SUMS`: this evidence bundle's file identities.

Raw data and radar images are kept outside Git. Code changes are part of draft PR #7. No cleaned archive has been selected or activated.
