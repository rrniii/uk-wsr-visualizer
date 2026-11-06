# UK WSR Visualizer

~~~{image} _static/uk-wsr-visualizer-logo.png
:alt: UK WSR Visualizer radar logo
:width: 140px
:align: right
~~~

Find, view, compare and export UK weather-radar scans. Choose a scan from the
public catalogue, inspect its PPI and keep the source and display settings with
your export.

The desktop apps run on macOS, Windows and Linux. Native mobile apps support
iPhone, iPad and Android. These are beta builds; check the release record for
platform verification, signing and store availability.

## Start here

- [Install the app](user_guide/installation.md).
- [Make your first plot](user_guide/quickstart.md) using a Castor Bay example.
- [Use the viewer](user_guide/viewer.md) for comparison, animation and exports.
- [Troubleshoot a problem](user_guide/troubleshooting.md).

## Data and interpretation

The app reads a root catalogue, a radar-year record and a day record before
fetching the selected HDF5 file. It does not download the archive at startup.
Catalogue coverage shows published data, not the full availability of original
observations.

CEDA is the authoritative archive; JASMIN provides the processed access files.
Source files stay unchanged. Compare optional cleanup with the decoded baseline
before interpreting weak weather, biological echoes or clutter.

Use the [data guide](user_guide/data_and_terms.md) for radar terms and the
[examples](example_gallery/index.md) for worked selections.

## Develop and cite

The [developer guide](developer_guide/index.md) covers structure, tests and
packaging. The [API reference](api_reference/index.rst) covers Python and HTTP
interfaces. Archive publication has a separate [operations guide](operations/index.md).

Check the citation metadata before sharing a result:

~~~bash
uk-wsr-visualizer citation --json
~~~

See [CITATION.md](https://github.com/rrniii/uk-wsr-visualizer/blob/master/CITATION.md)
for software, source-data and JASMIN attribution. Pending DOIs remain marked until
assigned.

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: User Guide

user_guide
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: Examples

example_gallery/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: API Reference

api_reference/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: Developer Guide

developer_guide/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 2
:caption: Maintainer Operations

operations/index
~~~

~~~{toctree}
:hidden:
:maxdepth: 1
:caption: Releases

release_notes
release_checklist
~~~
