# Developer Guide

This section covers the shared desktop code, tests, documentation, and
packaging contracts.

~~~{toctree}
:maxdepth: 2

contributing
apple_xcode
cross_platform_parity
~~~

## Repository layout

~~~text
src/uk_wsr_visualizer/       Shared Python package and static viewer
src/uk_wsr_visualizer/api/   FastAPI application
tests/                       Automated tests
docs/                        Public Sphinx documentation
macos/                       Native macOS shell and Xcode build
windows/                     WinForms/WebView2 shell and packaging
linux/                       Qt shell and packaging
deploy/                      Service deployment assets
configs/                     Non-secret example configuration
tools/                       Maintainer utilities
~~~

The scientific mask implementation, model registry, and QC evidence live in
the separate, versioned `uk-wsr-qc` project. The visualizer owns only
integration, display, selection, export, and provenance behavior. Source
development currently requires collaborator access to that dependency; its
repository is not a public documentation link during the beta.

Native iPhone and iPad development is kept in a separate branch/worktree while
mobile release work remains independent of desktop `master`. Shared catalog,
selection, filtering, export, and provenance contracts must move forward
without regressing either surface.

## Development setup

~~~bash
git clone git@github.com:rrniii/uk-wsr-qc.git
git clone git@github.com:rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ../uk-wsr-qc
python -m pip install -e ".[dev,export,video,object-store,docs]"
~~~

## Validation

~~~bash
pytest
python -m sphinx -W --keep-going -b html docs docs/_build/html
uk-wsr-visualizer --help
uk-wsr-visualizer export --help
~~~

Platform packaging adds a native-shell self-test. Build Mac and Windows from
the same desktop commit, and build Linux on every supported runner before
publishing a beta set.
