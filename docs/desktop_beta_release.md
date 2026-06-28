# Desktop beta release workflow

Use this workflow whenever the Mac or Windows desktop app changes. The release
principle is simple: Mac and Windows beta artifacts must come from the same pushed `master` commit.

## Release line

- Keep `master` as the desktop Mac/Windows release line.
- Do not merge the iOS branch into `master` until it is intentionally ready for
  the same release standard.
- Do not build or share a Windows zip from uncommitted local files or an
  accidental feature branch.

## Local smoke gate

From a clean `master` checkout, run:

```bash
scripts/desktop_beta_smoke.sh
```

The smoke gate checks:

- the working tree is clean and on `master`;
- viewer JavaScript syntax for source and bundled macOS app assets;
- the Python test suite;
- the Sphinx documentation build;
- citation metadata output.

If a check fails, fix the issue before building or sharing a beta.

## Windows beta artifact

After the smoke gate passes, push `master`, then build the Windows portable zip
on GitHub Actions:

```bash
git push origin master
windows/build-via-github.sh --ref master
```

The workflow runs on `windows-latest`, builds the WebView2 shell and bundled
Python server, runs the packaged `--self-test`, and downloads:

```text
build/windows-beta-artifacts/UK WSR Visualizer Windows Beta.zip
```

## Google Drive beta target

Replace the existing shared Drive file in place so testers keep one stable
download link:

```text
UK WSR Visualizer Windows Beta.zip
https://drive.google.com/file/d/1dhDYp0GCiaNWINbgEYpHWCnXlVeLVjmB/view
```

The file should remain readable by Chris Hassall and Tommy Matthews. Record the
commit SHA, GitHub Actions run URL, file size, and SHA256 checksum whenever a
new zip is uploaded.

## Manual beta smoke test

For every shared beta, verify at least one representative single-site source
object on macOS and ask a Windows tester to verify the same workflow:

1. Launch the app.
2. Search the catalogue by date or date range.
3. Select radar, item, variable, time, and elevation.
4. Plot a georeferenced PPI.
5. Zoom, pan, step time/elevation, and click a gate readout.
6. Toggle range rings and optional noise-floor masking.
7. Create a PNG or metadata export from **Export & Provenance**.
8. Inspect the export manifest for software, source-object, citation, and
   checksum metadata.
9. Clear the raw cache.

Bug reports should include the app version or commit, operating system, radar,
date, pulse, time, variable, elevation, screenshot, and log file.

## Citable release blockers

Before advertising a citable release or asking researchers to cite the toolkit,
complete the external release items in the release checklist:

- mint the Zenodo DOI from a tagged GitHub release;
- replace pending software DOI placeholders;
- confirm the formal UK WSR aggregate HDF5 source-data citation;
- confirm data licence/access terms and acknowledgement wording.
