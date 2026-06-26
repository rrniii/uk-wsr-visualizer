# UK WSR Visualizer release checklist

Use this checklist before the first public, citable release and before submitting the Weather article.

## Citation and credit

- [ ] Confirm the formal UK WSR aggregate HDF5 source-data citation with the data owner and archive.
- [ ] Confirm the access and licence statement for the source objects exposed through the selected route.
- [ ] Replace the source-data TODO in `src/uk_wsr_visualizer/citations.py` and `CITATION.md`.
- [ ] Tag a release and archive it on Zenodo.
- [ ] Replace the software DOI TODO in `src/uk_wsr_visualizer/citations.py`, `CITATION.md`, and `CITATION.cff`.
- [ ] After article publication, add the Weather DOI to `src/uk_wsr_visualizer/citations.py`, `CITATION.md`, and `CITATION.cff`.

## Repository readiness

- [ ] Confirm whether the repository remains under `rrniii` or moves to an organisational account.
- [ ] Confirm repository visibility and public release timing.
- [ ] Confirm the BSD-3-Clause licence is institutionally acceptable.
- [ ] Ensure public documentation does not imply official NOAA, Met Office, CEDA, JASMIN, or RMetS endorsement unless formally approved.
- [ ] Remove or move internal developer notes that are not relevant to first public users.

## App and CLI checks

- [ ] `uk-wsr-visualizer citation` prints human-readable citation guidance.
- [ ] `uk-wsr-visualizer citation --json` prints machine-readable citation metadata.
- [ ] `/api/citation` returns the same core metadata.
- [ ] The app header Citation button opens citation/provenance metadata.
- [ ] Export `artifact-manifest.json` includes software metadata, article metadata, source-data citation, and JASMIN acknowledgement.

## Screenshot and paper checks

- [ ] Hide unfinished controls before taking paper screenshots.
- [ ] Use a scientifically neutral single-radar/single-day example.
- [ ] Check labels, units, colour legend, map geolocation, and click-identify output.
- [ ] Ensure screenshots contain no private paths, credentials, or internal-only access details.

## Smoke tests

- [ ] Run `pytest` in a clean environment.
- [ ] Run a catalogue search.
- [ ] Load a selected source object.
- [ ] Render a PPI.
- [ ] Step through time.
- [ ] Use click identify.
- [ ] Clear the raw cache.
- [ ] Generate at least one export and inspect its manifest.
