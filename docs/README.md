# Documentation Source

This directory builds the public Sphinx site. It uses MyST Markdown, the PyData
Sphinx Theme, sphinx-design, and sphinx-copybutton.

## Audience structure

| Section | Audience |
|---|---|
| `user_guide/` | Desktop and Python users |
| `example_gallery/` | Users following reproducible examples |
| `api_reference/` | Python developers |
| `developer_guide/` | Contributors and package maintainers |
| `operations/` | Service and data-publication maintainers |

Internal manuscript drafting does not belong in this documentation tree.
Dated operations history must be labelled as history rather than presented as
current user guidance.

## Build

From the repository root:

~~~bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ../uk-wsr-qc
python -m pip install -e ".[docs]"
python -m sphinx -W --keep-going -b html docs docs/_build/html
~~~

To inspect the result:

~~~bash
python -m http.server --directory docs/_build/html 8080
~~~

Open `http://127.0.0.1:8080`.

The GitHub Actions workflow builds `master` and deploys through GitHub Pages
when Pages is enabled for the repository.

## Writing rules

- Introduce a descriptive variable name before its ODIM code.
- Use UTC and state the date/time format.
- Separate authoritative archive, public mirror, local cache, and user export.
- Label mutable counts with a snapshot date.
- Test command examples against the current parser.
- Use real public selectors where practical and state what was verified.
- Keep credentials, private paths, and transient incident notes out of the
  public user journey.
- Describe optional cleanup as source-preserving and fallible.
