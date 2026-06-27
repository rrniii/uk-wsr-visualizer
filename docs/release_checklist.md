# Release checklist

Use this checklist before submitting or advertising the Weather article and before asking researchers to cite the toolkit.

## Repository metadata

- [ ] Confirm the repository visibility and long-term home.
- [ ] Confirm the public repository URL used in README, CITATION.cff, and Zenodo metadata.
- [ ] Confirm the project licence with institutional guidance.
- [ ] Keep README, pyproject metadata, CITATION.cff, and CITATION.md consistent.

## Citation

- [ ] Mint a Zenodo DOI from the first tagged software release.
- [ ] Replace pending software DOI text in CITATION.md, CITATION.cff, README, and `src/uk_wsr_visualizer/citations.py`.
- [ ] Add the Weather article DOI after publication.
- [ ] Confirm that export manifests include software, article, source-data, and JASMIN citation metadata.

## Source-data access and attribution

- [ ] Confirm the formal source-data citation for the UK WSR aggregate HDF5 data.
- [ ] Confirm the data licence and access conditions.
- [ ] Confirm required data-provider acknowledgement text.
- [ ] Confirm whether access is public, community-limited, or permissioned.
- [ ] Update `configs/data_citations.toml` and `src/uk_wsr_visualizer/citations.py` with the agreed wording.

## User-facing app

- [ ] Hide or clearly mark unfinished controls before taking screenshots.
- [ ] Confirm the app loads a representative source object reproducibly.
- [ ] Confirm map geolocation, time stepping, field selection, click identify, and cache clearing.
- [ ] Confirm no screenshots or public docs expose private paths or restricted-access details.

## Tests and smoke checks

- [ ] Run unit tests in a clean environment.
- [ ] Run catalogue search against a representative catalogue.
- [ ] Run selected source-object load.
- [ ] Render a PPI.
- [ ] Generate an export and inspect `artifact-manifest.json`.
- [ ] Run `uk-wsr-visualizer-citation` and `uk-wsr-visualizer-citation --json`.

## Paper submission

- [ ] Replace pending DOI, source-data citation, licence, and repository metadata.
- [ ] Add final figure screenshots from a clean, reproducible session.
- [ ] Confirm acknowledgement wording for NOAA WCT inspiration, JASMIN, funding, and AI-assisted programming.
