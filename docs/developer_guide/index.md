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
src/uk_wsr_visualizer/api/   FastAPI application and route modules
src/uk_wsr_visualizer/cli_commands/  Command implementations
tests/                       Automated tests
docs/                        Public Sphinx documentation
ios/                         Native iPhone and iPad app and simulator tests
macos/                       Native macOS shell and Xcode build
windows/                     WinForms/WebView2 shell and packaging
linux/                       Qt shell and packaging
deploy/                      Service deployment assets
configs/                     Non-secret example configuration
tools/                       Maintainer utilities
~~~

The desktop scientific mask implementation, model registry, and QC evidence
live in the separate, versioned `uk-wsr-qc` project. The native app has its own
on-device implementation and parity fixtures. Source development for the
desktop currently requires collaborator access to the QC dependency; its
repository is not a public documentation link during the beta.

Desktop and native iPhone/iPad code are maintained together. Shared catalogue,
selection, filtering, export, and provenance contracts must move forward without
regressing either surface. The separate `uk-wsr-qc` repository remains pinned in
CI; production processing and publication remain separate operations.

The desktop viewer loads its classic scripts in the order listed in
`static/index.html`: state, catalogue, rendering, then the application controls.
They share a browser scope, so preserve this order when moving code.

## Development setup

~~~bash
git clone git@github.com:rrniii/uk-wsr-qc.git
git clone git@github.com:rrniii/uk-wsr-visualizer.git
cd uk-wsr-visualizer
git -C ../uk-wsr-qc checkout 10f05f615c8ea9c5924fac7d4fa00a6d8fb21cae
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
publishing a beta set. The [iOS guide](https://github.com/rrniii/uk-wsr-visualizer/blob/master/ios/README.md)
describes the simulator unit and interface suites for both device families.
