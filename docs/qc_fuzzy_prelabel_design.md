# Literature-backed fuzzy prelabels for UK WSR review

## Purpose

The review prelabel is an annotation assistant, not a production quality-control
mask and not ground truth. It reduces reviewer effort by proposing labels only
where independent raw-field evidence is strong. The sole reviewer must either
accept the proposal explicitly or edit it with the brush or polygon tools.
Uncertain gates remain unlabelled.

This distinction matters. A prelabel can accelerate a review, but accepting a
model's output without a human decision would train and validate the eventual
filter against itself.

## Evidence base

The implementation combines two established fuzzy-logic families.

1. **wradlib non-meteorological echo probability.** The implementation uses the
   default trapezoidal memberships and relative weights from
   [`classify_echo_fuzzy`](https://github.com/wradlib/wradlib/blob/main/wradlib/classify.py).
   Its core decision variables are texture of differential reflectivity,
   texture of copolar correlation coefficient, texture of differential phase,
   Doppler velocity and a static clutter map; raw correlation coefficient,
   depolarisation ratio and clutter phase alignment are optional additions.
   wradlib returns a probability, not an infallible binary truth. The current
   review implementation omits unavailable inputs and renormalises the
   remaining weights.

2. **LROSE C-band particle-identification memberships.** LROSE RadxPid selects
   a wavelength- and transmit-mode-specific threshold file; simultaneous H/V
   C-band data use
   [`pid_thresholds.cband.shv`](https://github.com/NCAR/lrose-core/blob/master/codebase/libs/radar/src/pid/pid_thresholds.cband.shv).
   The table includes explicit Flying Insects and Ground Clutter classes.
   The review assistant uses the relevant `Zh`, `Zdr` and `Sdzdr` memberships
   conservatively. It does not invent temperature or `Kdp` when those inputs
   are absent. See the
   [RadxPid documentation](https://ncar.github.io/lrose-core/docs/apps/radx/dualpol/RadxPid.html)
   for the wavelength-specific configuration contract.

The choice of local texture is supported by operational and research
classifiers. Hubbert et al. combine spatial variability and pulse-to-pulse
evidence in the Clutter Mitigation Decision fuzzy classifier and warn that
unconditional filtering biases weather at near-zero velocity
([Hubbert et al., 2009](https://doi.org/10.1175/2009JTECHA1160.1)).
For UK C-band data, Hall et al. use finite-gate standard deviation in a 3 by 3
window and identify `RHOHV` plus textures of `PHIDP`, `RHOHV` and `ZDR` as
important clutter discriminators
([Hall et al., 2017](https://doi.org/10.1002/qj.2959)).

The broader C-band evidence supports local calibration rather than universal
threshold claims. Rico-Ramirez and Cluckie trained and validated fuzzy and
Bayesian classifiers on C-band dual-polarisation measurements
([Rico-Ramirez and Cluckie, 2008](https://doi.org/10.1109/TGRS.2008.916979)).
Overeem et al. evaluated wradlib fuzzy filtering over a full year from two
temperate-climate C-band radars and tuned weights and the decision threshold on
local calibration data
([Overeem et al., 2020](https://doi.org/10.1175/JTECH-D-19-0149.1)).
This is the validation pattern the UK WSR project should follow.

## Implemented membership values

### wradlib-derived non-meteorological memberships

| Input | Non-meteorological trapezoid | Weight |
|---|---:|---:|
| `texture(ZDR)` | `[0.7, 1.0, +inf, +inf]` | 0.4 |
| `texture(RHOHV)` | `[0.10, 0.15, +inf, +inf]` | 0.4 |
| `texture(PHIDP)` | `[15, 20, +inf, +inf]` degrees | 0.1 |
| `VRADH` | `[-0.2, -0.1, 0.1, 0.2]` m s-1 | 0.1 |
| `RHOHV` | `[-inf, -inf, 0.95, 0.98]` | 0.4 |

The source defaults also assign weight 0.5 to a static clutter map and 0.4 each
to depolarisation ratio and clutter phase alignment. They are not currently
used because an independent static map, `DR`, and `CPA` are not consistently
available in the review inputs. A candidate learned clutter map must not be
used to create its own validation labels.

### LROSE C-band-derived memberships

| Class | Input | Membership or exclusion |
|---|---|---|
| Ground Clutter | `Zh` | rises from 0 at 5 dBZ to 1 at 10 dBZ |
| Ground Clutter | `ZDR` | 1 through 5 dB, falling to 0 at 10 dB |
| Ground Clutter | `texture(ZDR)` | class excluded below 2 dB |
| Flying Insects | `Zh` | `[-7, -5, 30, 35]` dBZ |
| Flying Insects | `ZDR` | class excluded below 2 dB |

The complete LROSE table uses weights `Tmp=20`, `Zh=20`, `Zdr=20`, `Kdp=10`,
`Rhv=20`, `Sdzdr=10`, `Sphi=10`, and `Svr=10`, with `Ldr=0`. The UK WSR
assistant uses only the subset actually observed in the source volume.

## Review decision logic

For each finite DBZH gate:

1. Compute 3 by 3 finite-gate textures, wrapping only across azimuth.
2. Compute wradlib-style non-meteorological membership over available fields.
3. Compute class scores for receiver noise, static ground clutter,
   precipitation and insects.
4. Select a proposal only when the best score is at least 0.68 and exceeds the
   second-best score by at least 0.12.
5. Encode proposed gate masks as row-major run-length regions.
6. Record the parameter hash and whether the reviewer accepted or edited the
   proposal.

The interface provides exact field colourbars, a touch-capable brush and
eraser, polygon regions, full-sweep labels, and two primary prelabel decisions:
**Correct** or **Wrong - edit**.

## Known limits and validation requirements

- `VRADH` near zero is supporting evidence only. It is not sufficient for
  clutter because real precipitation and some biological echoes can have small
  radial velocity.
- High polarimetric texture is supporting evidence, not proof. Echo boundaries,
  mixed-phase weather and low-SNR biological returns can also have high texture.
- Wind-turbine clutter needs a dedicated class and local examples. Hall et al.
  show that turbine echoes can overlap precipitation in `RHOHV` and several
  texture variables.
- The LROSE insect class also uses temperature and other evidence. An
  insect prelabel without those fields must remain conservative.
- The current thresholds are starting values for annotation acceleration.
  They must be calibrated on reviewer decisions by radar, pulse, elevation and
  evidence availability.
- Validation must report gate-level precision and recall per class, false
  removal of precipitation and biological echoes, calibration curves, and
  performance stratified by radar, elevation, pulse, season and range.
- Proposed labels must be evaluated against manual corrections on a
  pre-declared holdout set. The fuzzy assistant and the production removal
  model must remain separate artifacts.

## Additional references

- [Vulpiani et al. (2012), C-band polarimetric processing underlying the
  wradlib classifier](https://doi.org/10.5194/nhess-12-381-2012)
- [Dufton and Collier (2015), fuzzy non-meteorological echo filtering with
  dual-polarisation texture evidence](https://doi.org/10.5194/amt-8-3985-2015)
- [Gabella and Notarpietro (2002), residual ground-clutter texture
  filtering](https://copernicus.org/erad/online/erad-305.pdf)
- [LROSE core software and documentation](https://ncar.github.io/lrose-core/)
- [wradlib classification API](https://docs.wradlib.org/en/stable/generated/wradlib.classify.ClassifyMethods.classify_echo_fuzzy.html)
