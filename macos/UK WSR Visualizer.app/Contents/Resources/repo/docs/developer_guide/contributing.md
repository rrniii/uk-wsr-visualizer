# Contributing

## Before changing code

1. Create or update tests for behaviour changes.
2. Keep operational defaults conservative.
3. Keep user-facing documentation aligned with CLI options and app behaviour.

## Coding conventions

- Use Python 3.11-compatible syntax.
- Prefer small, typed dataclasses for command and API payloads.
- Keep optional geospatial and publication dependencies behind explicit extras or lazy imports.
- Raise actionable errors when optional dependencies are missing.

## Documentation conventions

- Put narrative documentation in Markdown under `docs/`.
- Use MyST Markdown directives for cards, grids, and Sphinx toctrees.
- Add API reference entries when adding user-facing modules or public dataclasses.

## Pull request checklist

- Tests pass with `pytest`.
- Documentation builds with `sphinx-build -b html docs docs/_build/html`.
- New CLI commands have help text and at least one documentation example.
