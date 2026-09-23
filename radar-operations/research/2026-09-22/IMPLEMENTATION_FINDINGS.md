# Findings from applying the research to the current comparison

Observed 22 September 2026. This is a targeted read-only assessment of output meaning and stored behaviour, not a completed scientific validation or full code audit.

The comparison code I previously built has defects that need correcting before its results are used to select an operational method. The native-data preservation checks remain useful, but passing them did not test the scientific meaning of the derived masks.

## 1. BALTRAD residual-mask meaning conflicts with the compound rule

**Confirmed:** the local wrapper exports the result of PPC's `residualClutterFilter` directly as `RESIDUAL_CLUTTER_MASK_BALTRAD_V1`. The comparison requires that value to be at least 0.5 along with clutter membership at least 0.99.

The [upstream PPC implementation](https://github.com/baltrad/baltrad-ppc/blob/831190ec8c0ead27c72a9f672de0f9b30c1e252b/ppc/pdp_processor.c#L511) applies the opposite residual-mask interpretation: zero or mask nodata causes censoring; one survives that stage. The wrapper first suppresses high-clutter TH before computing this residual mask, so these fields also represent sequential stages, not two independent votes about the same original gate.

I checked the installed primitive with the current options in a small, in-memory diagnostic probe. A uniform 9×9 field of 20 dBZ returned 81 ones; a uniform −32 dBZ field returned 81 zeros. This establishes the relevant implementation convention, not the physical identity of a real echo. A sampled real LP sweep contained 152,996 zero-mask gates and four one-mask gates.

**Consequence:** requiring residual mask one as additional clutter evidence is invalid. All 68 stored benchmark volumes have zero removals under this compound policy. That result must not favour BALTRAD in a preservation ranking or disqualify the underlying library as ineffective.

**Required repair:** specify whether the candidate is native PPC censoring or a separately designed biology-preserving policy. Model the sequential stages correctly, preserve their diagnostics, test known positive and negative examples and version the result. Blindly changing `>=0.5` to `<0.5` would still confuse below-threshold/no-signal cells with scientifically confirmed clutter.

## 2. Diagnostic zero is being decoded as missing

**Confirmed for sampled LROSE flags:** their data contain zero for false and one for true, with `nodata=255` and `undetect=0`. The shared `physical()` function masks both nodata and undetect for all fields. It therefore turns false into NaN, and the compound policy's finite-value check interprets that as unsupported.

A sampled LP sweep had 153,000 persistent-clutter flags equal to zero and a ground-clutter PID flag with 151,470 zeros and 1,530 ones. Discarding the zeros is inappropriate for this categorical diagnostic. It can distort reported support and related comparisons, even where a positive-removal decision is unchanged.

RACK's sampled detector arrays also encode `undetect=0`, and non-detection values are widespread. Their exact physical conversion needs a field-specific contract: not every reserved code should simply be assigned a generic numerical value. The ship detector in the sampled sweep was entirely zero.

**Required repair:** separate decoding of measured radar moments from decoding of categorical flags and detector responses. Distinguish a known negative response, an algorithm that did not run, missing input, and an unsupported sweep. Test each representation and recompute coverage and comparison metrics. The currently reported 0.64% LROSE and 0.60% RACK finite support must not be interpreted as each package's intrinsic capability.

## 3. RACK's intersections have not been scientifically justified

**Confirmed policy:** removal requires emitter AND jamming responses at least 0.95, or ship AND speckle responses at least 0.95, followed by the common protection rule. This is limited to the first three sweeps at elevation no greater than 2°.

The [developer descriptions](https://fmidev.github.io/rack/andrepage.html) identify different target structures for these detectors. They do not establish these intersections as the appropriate operational rule. Stored results show zero removals in every volume.

**Interpretation:** the result is consistent with restrictive composition, decoding effects or both. The present evidence does not isolate their relative contributions. Evaluate individual detectors and then justified combinations on a development set; do not switch to a union and assume it is safe. Freeze the chosen policy before acceptance testing.

## 4. PyRAD's broad cleaning profile needs a specific preservation test

**Confirmed code behaviour:** its final removal mask is the union of receiver, speckle, radial and static rules. The static branch requires high historical echo/near-zero-velocity frequency, current absolute velocity no more than 1 m/s and elevation no greater than 2.1°. Unlike the other branches, it does not apply `~protected`; the protection definition also excludes sufficiently high static frequency.

This is a concern to test, not evidence that a real biological echo was lost. Persistent insects and near-zero-velocity weather are precisely the situations suggested by [Rennie et al.](https://centaur.reading.ac.uk/17547/) and [Hubbert et al.](https://doi.org/10.1175/2009JTECHA1160.1). The 53.56% overall removal fraction cannot distinguish useful background removal from harmful censorship.

**Required test:** inspect static-rule removals in independently identified useful echo, including map-contaminated biology, weather crossing the zero-velocity line and mixed weather/clutter. Inspect receiver/speckle removal separately in weak targets near sensitivity. Quantify their contributions without double-counting overlapping detector bits.

## 5. Stored behaviour and provenance

The fresh aggregation used 68 distinct stored case-metric files and 374 sweep records per processor. Every processor's valid-source denominator was 39,535,200 finite DBZH gates. Background may be finite and contributes to this denominator.

| Policy | Removed | Uncertain/retained | Reported finite support | Volumes with any removal |
|---|---:|---:|---:|---:|
| BALTRAD | 0 | 84,681 | 39,535,200 | 0/68 |
| PyRAD | 21,174,487 | 11,701,038 | 39,535,200 | 68/68 |
| LROSE | 197,077 | 55,893 | 252,970 | 41/68 |
| RACK | 0 | 21 | 238,365 | 0/68 |

These counts are **not** true-positive/false-positive counts. Finite support is affected by the decoding defect above; do not compare removal divided by supported gates as if it were skill. This check did not rerun all processors or re-hash all source PVOLs.

The local and deployed comparison policy files matched SHA-256 `46741bf912120e9fb1061e91e152d47da9df15e2722f4bb19317d75ed619942d`. The BALTRAD wrapper matched `1cc6751be1adf834b5349b26603117a85897632a93ba26565d5bf9235a773bd7`. The comparison worktree was at commit `11135787f8f27734ef32ef616bb1d98b5a0b3075`. The upstream PPC C source fetched for interpretation had SHA-256 `897ebf75ef7a04910677f591970954d532619aae1e4e4b626e2b24eebe1af52e`; it is not asserted to identify the deployed compiled binary.

Machine-readable evidence is in `evidence/current-evaluation-snapshot.json`, `evidence/field-semantics-sample.json` and `evidence/baltrad-runtime-semantics-probe.json`. The first includes the hashes of the 68 metric files. The live status file read during the assessment reported `awaiting_scientific_selection`; it is status-file evidence, not a new end-to-end service health check.

No pipeline configuration or scientific approval was changed. The appropriate next implementation work is a versioned semantic repair and reevaluation, followed by the [scientific review protocol](REVIEW_PROTOCOL.md).
