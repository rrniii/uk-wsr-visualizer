# A literature-informed route to choosing the radar cleaner

Research completed 22 September 2026. Scope: the four existing UK C-band archive implementations, preserving meteorological, biological and mixed echoes while removing instrumental background, interference and unwanted surface returns.

**The literature is sufficient to build a much better first review. It does not establish a winning package.** My provisional engineering recommendation is to evaluate the custom PyRAD cleaning profile first because it addresses the broadest set of requested contaminants. That is a starting order, not a scientific endorsement. A mask-meaning error, a decoding defect and an unvalidated detector combination must be resolved before a four-way ranking is trustworthy.

The intended result remains an operational cleaned archive. This research supplies the scientific basis for selecting it, with explicit evidence and uncertainty for each decision.

## What is in this knowledge base

- [Literature and evidence register](LITERATURE.md): 25 primary studies, software papers, developer documentation and source-code records, with applicability and access limitations.
- [Review protocol](REVIEW_PROTOCOL.md): a source-first procedure I can use to review the outputs, score each failure mode and recommend a release.
- [Current implementation findings](IMPLEMENTATION_FINDINGS.md): fresh checks of the actual comparison, including the reasons its current removal counts cannot identify a winner.
- [Machine-readable knowledge](knowledge.json): reference metadata, review rules and example records, suitable for later review tooling.
- [Review-record template](review-record-template.json): evidence fields for each decision; an assistant judgment is explicitly distinguished from independent truth.
- [Bibliography](references.bib): 13 DOI records checked against Crossref; eight other paper records use primary-source metadata, with abbreviated author lists where necessary; four developer sources.

## What the strongest examples teach us

| Published example | What it contributes to this review | Limit on transfer |
|---|---|---|
| [Overeem et al. (2020)](https://www.knmi.nl/kennis-en-datacentrum/publicatie/full-year-evaluation-of-nonmeteorological-echo-removal-with-dual-polarization-fuzzy-logic-for-two-c-band-radars-in-a-temperate-climate) | Two operational C-band radars, a separate calibration period, a full year of evaluation and rain-gauge checks provide a useful design for testing clutter removal and precipitation retention. | Its rainfall objective does not test preservation of insects or birds. |
| [Rennie et al. (2010), discussion paper](https://centaur.reading.ac.uk/17547/) | Persistent UK insect echoes can defeat a simple frequency-of-detection clutter map. Temporal velocity variability provides additional discrimination. | A discussion version was found; no final journal version was verified. |
| [Dokter et al. (2011)](https://doi.org/10.1098/rsif.2010.0116) and [Nilsson et al. (2018)](https://doi.org/10.1111/1365-2664.13174) | Comparisons with dedicated biological radars establish a stronger reference for retained biological signal than visual appearance alone. | Their bird products are not a reference for every biological taxon or every mixed gate. |
| [Hubbert et al. (2009)](https://doi.org/10.1175/2009JTECHA1160.1) | Weather near zero radial velocity can be damaged by indiscriminate clutter filtering. | Their spectral filtering can recover signals in ways that censoring archived moments cannot. |
| [Schaper et al. (2022)](https://amt.copernicus.org/articles/15/6625/2022/) | DWD verified C-band interference detection using an independent Wi-Fi receiver. Interference deserves its own evidence and class. | Detection, deletion and recovery of an underlying signal are different claims. |
| [Husnoo et al. (2021)](https://repository.library.noaa.gov/view/noaa/31670/noaa_31670_DS1.pdf) | UK radar experiments combine observed weather and clutter signals with known components, then test the downstream precipitation result. | An equivalent controlled mixture cannot be made by adding dBZ values or fabricating polarimetric moments. |

These examples support a multi-evidence review: native moments, spatial structure, temporal behaviour, neighbouring elevations, relevant instrument metadata and independent observations where available. No single low correlation, unusual differential reflectivity, weak return, stationary Doppler value or map hit is a universal deletion instruction.

## How I would interpret the echoes

The following are review hypotheses, not automatic labels. A plausible pattern becomes stronger when several independent observations agree. Literature examples teach what to look for; they are not ground truth for a new UK gate.

| Situation | Evidence to inspect | Default when evidence is incomplete |
|---|---|---|
| Birds, insects and other biological echoes | Coherent velocity or motion, aspect-dependent polarimetric patterns, time of day, season and persistence through adjacent scans. See [Jatau et al. (2021)](https://repository.library.noaa.gov/view/noaa/34122/noaa_34122_DS1.pdf). | Retain as biological or uncertain; do not infer species from appearance. |
| Weather at the zero-velocity line | Continuity across the line and consistency with neighbouring weather gates. | Retain unless there is additional evidence of unwanted surface contamination. |
| Receiver background | Instrument sensitivity, noise calibration, range dependence and several quality variables together. [Ivić et al. (2013)](https://doi.org/10.1175/JTECH-D-13-00008.1) shows why noise estimation errors can either lose coverage or leave noise. | Keep weak coherent targets uncertain; do not equate finite DBZH or low SNR with noise. |
| Ground clutter and anomalous propagation | Repeated site geometry, temporal velocity behaviour, terrain context and inconsistent vertical extent; explicitly look for useful echo superposed on clutter. | Mark mixed or uncertain if censoring would also discard a useful component. |
| Sea clutter, ships and wind turbines | Coastal geometry, temporal evolution and a detector suitable for the specific target. [Hall et al. (2017)](https://doi.org/10.1002/qj.2959) shows why offshore wind-farm signatures need distinct consideration. | Avoid treating all coastal returns as ground clutter or all point targets as ships. |
| Radio interference | Ray or sector geometry, quality variables and persistence in azimuth. | Flag contaminated gates. An interpolated value is an estimate, not a recovered observation. |
| Mixed precipitation, melting layer and hail | Neighbouring heights, temperature information and cross-field consistency. | Low correlation alone is insufficient for removal. |
| Isolated specks and narrow biological features | Native resolution and continuity through time; whether the feature has a physical trajectory. | Small area alone does not establish artefact. |

An estimated depolarization ratio from ZDR and RHOHV can add a useful diagnostic, as in [Kilambi et al. (2018)](https://doi.org/10.1175/JTECH-D-17-0175.1). It separates weather-like from non-weather-like signatures; it does not separate wanted biology from all unwanted artefacts. It must not be substituted for measured LDR, which these inputs do not provide.

## What this means for the four options

| Implementation as currently configured | Role worth testing | Evidence still needed |
|---|---|---|
| Custom PyRAD `echo-clean-v3` | Broad cleaning candidate: explicit receiver-background, speckle, radial-interference and persistent-clutter rules, plus retained uncertainty. | Biological and weak-weather retention, calibration sensitivity and static-map cases. The custom rules are not validated by the PyRAD framework paper. |
| BALTRAD PPC plus our compound policy | A polarimetric clutter-processing candidate after the mask interpretation and removal policy are corrected and versioned. | Native-chain comparison, biological retention and background-noise capability. Its current zero-removal result is not evidence of excellent preservation. |
| LROSE plus our compound policy | Clutter/PID diagnostics and a possible weather-aware cleaner. | Correct flag decoding, mode/wavelength compatibility, mixed-echo tests, receiver-background coverage and explicit treatment of disabled features. |
| RACK plus our compound policy | Targeted interference and isolated-target detection, potentially useful as a component. | Correct no-detection/unsupported decoding and independent evaluation of the detectors. Our intersections do not constitute a validated full cleaning chain. |

The [PyRAD paper](https://doi.org/10.5334/jors.330), [BALTRAD paper](https://doi.org/10.5334/jors.193) and [LROSE paper](https://doi.org/10.5334/jors.630) establish software capabilities and provenance. They do not validate these particular UK wrappers, thresholds or training maps. The [NCAR PID documentation](https://github.com/NCAR/lrose-core/blob/master/docs/apps/radx/dualpol/RadxPid.md) specifically distinguishes wavelength and transmit-mode configurations. [RACK's developers](https://fmidev.github.io/rack/andrepage.html) distinguish detection from removal and describe different targets for its emitter and jamming detectors.

I found no direct published comparison of these four exact configurations in the searches performed. A modular combination might ultimately work best, but it must be evaluated as a new candidate. Combining masks is not a free improvement: it can combine the false removals too.

## The immediate finding changes the evaluation order

A read-only check on 22 September recovered 68 stored metric files covering 374 sweeps. The denominator is 39,535,200 finite source-DBZH gates, including instrumental background; it is not a count of scientifically useful echoes.

| Current proposed-removal policy | Removed gates | Fraction of finite source gates |
|---|---:|---:|
| BALTRAD compound | 0 | 0% |
| PyRAD custom | 21,174,487 | 53.56% |
| LROSE compound | 197,077 | 0.50% |
| RACK compound | 0 | 0% |

**These are behaviour checks, not accuracy scores.** In particular, a high PyRAD removal fraction could be appropriate removal of background, inappropriate loss of weak echoes, or both. Labels and independent checks must resolve that. The counts were reaggregated from stored metrics, not generated by rerunning all raw volumes. Current local/deployed policy and BALTRAD-wrapper hashes matched. Details and evidence are in the [implementation findings](IMPLEMENTATION_FINDINGS.md).

This also corrects the interpretation of our earlier successful 272-output integrity check. That check demonstrated preservation of the original data and valid derived files. It did not establish that the cleaning proposals were scientifically correct or even meaningfully comparable.

## How this reduces the work you need to do

I can undertake the first pass using the protocol: inspect source data before candidate outputs, document evidence, classify only to the level supported, measure what each method removes and retain uncertain cases. The result should be a proposed selection with specific failure examples and a short list of disputed cases for your attention, rather than an unstructured request for you to inspect all outputs.

My annotations would be recorded as **assistant-generated interpretations**, not independent ground truth. Agreement with a second algorithm or with a rule derived from the same moments does not make them independent. [Lin et al. (2019)](https://doi.org/10.1111/2041-210X.13280) provides a useful distinction between inexpensive weak training labels and separate human-labelled evaluation data. Calibration against independent or expert-labelled cases is how we determine whether my first-pass judgments are reliable enough for acceptance decisions.

The order of work is:

1. Repair and test field semantics and the comparison policies; freeze their new identities.
2. Use the existing 24 cases for diagnostic review and policy development. They are selected for specific purposes and should not provide a national accuracy estimate.
3. Freeze an independent event-based acceptance set before tuning further. Expand beyond the present two dates and include biological, weak-weather, clutter and interference events.
4. Compare each candidate against retaining everything, with class-specific retention, artefact removal, abstention and coverage reported separately.
5. Select the simplest candidate that meets the agreed scientific limits over its stated scope, then use the existing release mechanism to make it the working cleaned archive.

The remaining work is now a concrete scientific evaluation, rather than choosing a library by reputation or selecting whichever plot looks cleanest.

## Scope and limitations of this research

This is a targeted evidence review, not a registered systematic review or a meta-analysis. Searches covered the four systems, UK/C-band clutter, biological echoes, mixed returns, noise, RFI, wind farms, ships and validation design, with publications through 22 September 2026. Publisher pages, author institutions, NOAA/KNMI/NCAR repositories and developer sources were used. Search snippets were followed to original sources where accessible; access depth is recorded for each item. Six original figures across three papers were visually inspected. Some publisher full texts could not be opened, and the linked PPC technical report returned 404. Elicit was unavailable under the connected account, so web research supplied the literature evidence.

No new scientific labels, operational approval, pipeline edits or release activation were made during this research. The live status file read during the check still reported `awaiting_scientific_selection`.
