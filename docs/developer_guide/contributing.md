# Contributing

## Before changing code

1. Read the existing behavior and tests before choosing an implementation.
2. Keep source files immutable and caches disposable.
3. Preserve valid selection constraints across radar, pulse, time, variable,
   and elevation.
4. Add focused tests for behavior changes.
5. Update user documentation when a control, default, export, or error message
   changes.

## Code conventions

- Support Python 3.11 or newer.
- Follow existing typed dataclass and local helper patterns.
- Keep optional geospatial, video, publication, and packaging dependencies
  behind explicit extras or lazy imports.
- Raise actionable errors that identify the failed source or selection.
- Cancel or ignore stale asynchronous results rather than letting an older
  request overwrite a newer user choice.
- Put scientific QC implementation and model evidence in `uk-wsr-qc`, not in
  this repository.

## Documentation conventions

- Write for a reader who knows neither ODIM nor the deployment history.
- Introduce long variable names before codes, for example Horizontal
  Reflectivity (DBZH).
- Use real selectors and test each command.
- State whether a count or status is a dated snapshot.
- Keep operations pages separate from the normal user path.
- Do not present a public mirror as the authoritative source archive.
- Explain coordinate form for every export.
- Explain that cleanup is optional, in memory, source-preserving, and fallible.

## Pull request checklist

- `pytest` passes.
- Sphinx builds with warnings treated as errors.
- New CLI behavior appears in `--help` and has a tested example.
- App controls do not expose unavailable combinations.
- macOS, Windows, and Linux shared behavior remains aligned.
- Release notes describe user-visible changes.
- No credentials, private paths, generated build trees, or unrelated files are
  included.
