# Release Checklist

Use this checklist before publishing a software release, replacing beta
packages, or asking researchers to cite the toolkit. Record the release commit
and catalogue snapshot alongside the completed checklist.

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

- [ ] Confirm the formal source-data citation for the UK WSR archive data and
      the published per-volume PVOL HDF5 access objects.
- [ ] Confirm the data licence and access conditions.
- [ ] Confirm required data-provider acknowledgement text.
- [ ] Confirm whether access is public, community-limited, or permissioned.
- [ ] Update `configs/data_citations.toml` and `src/uk_wsr_visualizer/citations.py` with the agreed wording.

## User-facing app

- [ ] Hide or clearly mark unfinished controls before taking screenshots.
- [ ] Confirm the app loads a representative source object reproducibly.
- [ ] Confirm map geolocation, time stepping, field selection, click identify, and cache clearing.
- [ ] Confirm four independent panels retain their own item, variable,
      elevation, palette, and display limits unless the corresponding link is
      enabled.
- [ ] Confirm the decoded baseline and optional cleanup can be compared and
      that cleanup settings appear in provenance.
- [ ] Confirm no screenshots or public docs expose private paths or restricted-access details.

## Public catalogue

- [ ] Fetch the external root catalogue without credentials.
- [ ] Record `generated_at`, `upload_complete`, site count, date coverage, and
      one representative radar-year and day record.
- [ ] Verify that one referenced PVOL object is publicly readable and that its
      size matches the day catalogue.
- [ ] Confirm missing dates are described as catalogue coverage, not proof of
      archive absence.

## Tests and smoke checks

- [ ] Run `pytest` in a clean environment.
- [ ] Build Sphinx with warnings treated as errors.
- [ ] Run catalogue search against a representative catalogue.
- [ ] Run selected source-object load.
- [ ] Render a PPI.
- [ ] Generate an export and inspect `artifact-manifest.json`.
- [ ] Run `uk-wsr-visualizer-citation` and `uk-wsr-visualizer-citation --json`.

## Desktop packages

- [ ] Build macOS, Windows, and Linux packages from the same committed desktop
      source revision.
- [ ] Run each native launcher's self-test and at least one real PPI smoke test.
- [ ] Confirm MP4 support is present in every package.
- [ ] Generate SHA-256 checksums and use unambiguous platform and version names.
- [ ] Remove or replace superseded beta packages so testers cannot mistake an
      old build for the current one.
- [ ] Confirm logs, caches, and exports are written outside the installation
      directory and source checkout.

## Mobile beta

- [ ] Build from the intended mobile branch and record the commit and build
      number separately from desktop.
- [ ] Test the same catalogue selection on iPhone and iPad.
- [ ] Confirm recent selections, native sharing, cache clearing, and optional
      cleanup provenance.
- [ ] Verify the exact TestFlight build assigned to the tester group.

## Paper submission

- [ ] Replace pending DOI, source-data citation, licence, and repository metadata.
- [ ] Add final figure screenshots from a clean, reproducible session.
- [ ] Confirm acknowledgement wording for design context, JASMIN, funding, and AI-assisted programming.
