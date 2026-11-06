# Protocol for an evidence-based first review

Version 1, 22 September 2026. This is a proposed scientific protocol, not a completed validation or a new operational approval. Source IDs refer to the [evidence register](LITERATURE.md).

## Decision and scope

Choose an exact processing configuration for an operational archive that preserves weather and biological signal while reducing unwanted surface returns, interference and instrument background. The object being evaluated is **versioned code + detector settings + training/calibration assets + masking policy + input modes**, not the package name.

The working preference is to avoid discarding coherent useful echoes, retain ambiguous mixtures and choose the simplest configuration meeting the intended scientific use. Any numerical loss budget is a project acceptance target to be recorded before final scoring; no paper supplies a universal permissible biological-loss threshold.

## Before assessing cleaning quality

1. Resolve the [mask and decoding findings](IMPLEMENTATION_FINDINGS.md). Establish the meanings of zero, one, nodata, undetect, detector non-response and unsupported scope for every field.
2. Verify positive and negative diagnostic examples and compare with the intended native algorithm chain. Confirm phase conventions, velocity aliasing, wavelength, transmit mode, units, azimuth registration and scan geometry.
3. Freeze processor, policy, training and calibration identities. Confirm that evaluation events were excluded from training maps and noise calibration. Missing training provenance is an unresolved validation condition.
4. Add a retain-everything control and inspect individual detector masks as well as their combination. A no-removal policy trivially preserves everything and must not win by that fact alone.
5. Preserve original moments and use a common display range, native geometry and labelled physical units. A fitted background, gap fill or interpolation must remain distinguishable from an observed signal.

These steps concern interpretation and comparability; passing them does not establish scientific performance. Developer sources D01–D04 govern field interpretation, while S01–S03 establish software context.

## Example atlas to consult during review

| Review example | Reference location | What the example should prompt us to inspect |
|---|---|---|
| Weather near zero radial velocity | P02, zero-velocity case studies and Figure 4 | Whether valid weather disappears along a velocity contour. |
| Persistent insect layer | P03, Clee Hill summer example, Figures 1–4 | Whether a frequency map learned a persistent atmospheric target as clutter. |
| Bird migration at different azimuthal aspects | P14, Figure 4 | Whether changing RHOHV/ZDR with viewing direction is being mistaken for changing target quality. |
| Biological altitude profile | P04 campaign validation; P08 methods and Figures 4–5 | Whether density/reflectivity, speed and direction are preserved in a matched sampling volume. |
| Biology adjacent to precipitation | P09, Figures 2–3 and independent evaluation design | Whether a boundary or mixture is erased by a broad weather/non-weather rule. |
| Persistent coastal contamination | P10, full-year evaluation design | Whether false accumulations disappear without losing true weak precipitation. |
| Offshore turbine returns | P06, UK operational radar examples | Whether a land-clutter rule misses rotating targets or harms nearby weather. |
| Interference overlapping weather | P15, Figure 1; P17, spike/precipitation cases | Whether quality variables corroborate a radial or sector feature; count discarded useful signal separately. |
| Strong ships and sidelobes | P16, mainlobe/sidelobe method | Whether the detected target and its sidelobes require different treatment; check waveform applicability. |
| Noise-floor error | P05, simulations and real-data evaluation | Whether an inflated floor removes weak real targets, or an underestimated floor leaves noise. |
| Clutter/weather mixtures with a known component | P13, controlled-mixture method and Figure 1 | Whether the available data level supports the claimed separation or recovery. |
| Combined operational QC | P12/P18, validation and monitoring methods | Whether adding stages actually improves independent downstream measurements. |

The reference locations were obtained from original text/captions or primary abstracts as detailed in the register. I also visually inspected P03 Figures 1–4, P14 Figure 4 and P15 Figure 1 from rendered original PDF pages. Other figures are text/caption references. The atlas links the originals rather than reproducing them.

Three observations from that visual inspection are especially useful:

- **P03:** the frequency-only flagged panel still contains the coherent red/blue insect-velocity patches; the revised map retains those patches. The text and plot headers say 29 June 2009, while the Figure 1 caption says 29 July. Use the figure reference, not an assumed exact event date.
- **P14:** bird and insect curves overlap for some viewing directions, and their RHOHV distributions overlap substantially. These are averaged S-band training data, not calibrated decision boundaries for an individual UK gate.
- **P15:** narrow interference rays extend through the southeast weather sector and stand out in the pulse-variability panel. The panel comparison supports using multiple fields; those pulse statistics are not established as available in our archive.

## How I will label a case

Inspect the original source and available contextual evidence first. Identify regions in native gate coordinates with a timestamp and input hash, and record the evidence before revealing candidate results. Use a dedicated assistant reviewer identity; never write my decisions under the user's identity.

Use these classes: weather; biological; mixed useful echo; ground clutter; sea clutter; interference; isolated artefact; receiver background; uncertain. Refine biological subtypes only when supported. Missing or undetected observations are data states, not receiver-background labels.

Each record contains supporting and conflicting observations, an alternative explanation, the relevant literature IDs, a proposed retain/remove/uncertain action and the scope of the judgment. Confidence is an ordinal judgment, not a calibrated probability. If the available snapshot cannot distinguish two explanations, retain the uncertainty and record which additional observation would resolve it.

Use contextual sources carefully: time of day is a prior rather than proof of birds; a terrain/coast map indicates plausibility rather than target identity; a temperature profile can support a melting-layer interpretation; a second classifier using the same radar moments is correlated evidence. Actual independent sensors provide stronger confirmation but have sampling limitations.

Keep assistant interpretation, human/expert annotation, independent-instrument evidence and algorithm-generated labels as separate provenance types. My familiarity with a case, including prior exposure to candidate results, must be recorded; a later annotation cannot be retrospectively called blinded. P09 is a useful example of retaining the distinction between weak labels and acceptance evidence.

## Sampling that supports a decision

The existing 24-card pack is for diagnostic development: 12 selected representative cases, eight disagreements and four potential-damage prompts. Review all of it, but report each stratum separately. The full 68-volume benchmark spans 17 radars, LP/SP and two dates. It cannot establish seasonal nationwide performance.

For acceptance, define event blocks from fresh dates before looking at candidate success. Stratify by radar/site conditions, pulse and geometry, range, elevation, sensitivity, season/day-night and echo class. Include biologically active events, weak stratiform weather, mixed precipitation, AP/sea clutter, coastal infrastructure, interference and clear-background cases. Multiple adjacent scans from one event stay in one split; gates are not independent replicates.

Use a development set for policy or threshold changes and an untouched acceptance set for selection. Include additional radars or leave-site-out tests if nationwide transfer is claimed. Repeatedly examining or tuning to a failed acceptance set converts it into development evidence and requires fresh acceptance events. P10 supplies an operational-duration example, not a mandatory one-year waiting period for a limited initial release.

## What to measure

Let R be gates a candidate removes, V be valid measured source gates, A_k be independent/reference artefact labels for class k, and U_c be useful-echo labels for weather, biology or mixed class c. Keep an ignored/uncertain region out of accuracy numerators and denominators and disclose its extent.

| Measure | Definition and interpretation |
|---|---|
| Useful-echo loss by class | `count(R ∩ U_c) / count(U_c)`. Report weather, biology and mixed separately. |
| Artefact removal by class | `count(R ∩ A_k) / count(A_k)`. Do not pool away a complete failure on one important class. |
| Removal precision | Labelled artefact removals divided by all confidently labelled removals. Also report the fraction of all removals that was labelled. |
| Unsupported/abstained coverage | Gates with missing/unsupported evidence or an explicit uncertain decision, divided by V. Report these states separately. |
| Overall operational effectiveness | Artefact removals divided by **all** labelled artefact gates in the claimed operating scope, counting unsupported retained artefacts as unremoved. Show conditional supported-only results additionally. |
| Signal-weighted loss | Removed useful linear reflectivity divided by original useful linear reflectivity; use `10**(dBZ/10)`, not an average or sum of dBZ. State whether weighting is per gate or physical sampling volume. |
| Structural damage | Lost connected features, systematic range/azimuth holes, discontinuities across elevations and disrupted temporal trajectories. Report exemplars and event counts. |
| Downstream impact | Matched-volume biological profiles/movement and matched weather occurrence or accumulation. Do not silently turn a missing gate into zero signal. |
| Operational cost | Wall time, resource use, failures/retries and completed fraction on the same hardware/input cohort. |

Zero denominators produce undefined values, not perfect scores. Report exact denominators. Summarise by event, radar and mode; also show pooled gate counts so neither large-volume dominance nor arbitrary equal weighting is hidden. Estimate paired uncertainty by resampling independent event blocks where enough blocks exist. Two dates are insufficient to support a credible nationwide seasonal confidence interval.

Candidate agreement is not correctness. Removal percentage is not performance. A sensible uncertainty band cannot compensate for wrong labels or shared training leakage.

## How to choose and move into operations

First require correct field interpretation, reproducibility and explicit coverage. Then require acceptable weather/biology/mixed retention and useful artefact reduction relative to the no-removal control. Rank passing candidates using class-specific performance, uncertainty, intended coverage and operating cost. Do not hide a scientific failure in a weighted average score.

A provisional priority is to test the broad PyRAD custom profile after auditing its static/noise rules, while repairing the BALTRAD and diagnostic-decoding comparisons. LROSE and RACK may be complete alternatives for a qualified subset or useful components of another configuration. A combined configuration is a new candidate and needs its own acceptance evidence.

The final recommendation should state the exact selected configuration, approved radar/pulse/geometry scope, evidence provenance, material failure examples, uncertainty and unsupported classes. If candidates are statistically indistinguishable for the intended use, favour the simpler, more reproducible one rather than inventing a ranking.

Then use the existing versioned-release mechanism: run a qualified real archive batch, validate products, activate the cleaned-product catalogue, verify the intended consumer and its exports, and expand to further qualified groups. Monitor input calibration and class-specific behaviour as well as processing success; P12 shows why downstream quality monitoring matters. A code or threshold change starts a new version and a new comparison.

I can prepare the first review and recommendation autonomously, with ambiguous cases collected for targeted expert adjudication. This protocol does not declare any present configuration scientifically accepted.
