"""Citation and provenance metadata for UK WSR Visualizer."""

from __future__ import annotations

import argparse
import json
from typing import Any

from . import __version__

SOFTWARE_NAME = "UK WSR Visualizer"
PACKAGE_NAME = "uk-wsr-visualizer"
REPOSITORY_URL = "https://github.com/rrniii/uk-wsr-visualizer"
SOFTWARE_DOI = "TBD: mint a versioned software DOI with Zenodo after the first tagged release"
ARTICLE_DOI = "TBD: add the Weather article DOI after publication"
ARTICLE_TITLE = "UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data"

SOURCE_DATA_CITATION = (
    "TODO: replace with the formal UK WSR aggregate HDF5 source-data citation agreed with "
    "the data owner and archive. Do not substitute a citation for a different data product family."
)
SOURCE_DATA_LICENCE = "TODO: replace with agreed UK WSR aggregate HDF5 licence/access terms."
JASMIN_ACKNOWLEDGEMENT = "This work used JASMIN, the UK's collaborative data analysis environment."


def citation_payload(
    *,
    source_data_citation: str | None = None,
    source_data_licence: str | None = None,
) -> dict[str, Any]:
    """Return structured citation and acknowledgement metadata.

    The returned payload is intentionally explicit about the four credit layers:
    software, article, source data, and JASMIN infrastructure.
    """

    return {
        "software": {
            "name": SOFTWARE_NAME,
            "package": PACKAGE_NAME,
            "version": __version__,
            "doi": SOFTWARE_DOI,
            "repository": REPOSITORY_URL,
            "preferred_release_citation": (
                f"Neely, R. R. III. {SOFTWARE_NAME}, version {__version__}. "
                f"Zenodo. DOI: {SOFTWARE_DOI}."
            ),
        },
        "article": {
            "title": ARTICLE_TITLE,
            "journal": "Weather",
            "doi": ARTICLE_DOI,
            "preferred_article_citation": (
                f"Neely, R. R. III. {ARTICLE_TITLE}. Weather. DOI: {ARTICLE_DOI}."
            ),
        },
        "source_data": {
            "citation": source_data_citation or SOURCE_DATA_CITATION,
            "licence": source_data_licence or SOURCE_DATA_LICENCE,
        },
        "infrastructure": {
            "jasmin_acknowledgement": JASMIN_ACKNOWLEDGEMENT,
            "jasmin_reference": (
                "Lawrence, B. N. et al. (2013) Storing and manipulating environmental big data with JASMIN."
            ),
        },
        "user_instruction": (
            "If UK WSR Visualizer is used to produce a figure, export, derived object, "
            "case selection, or research result, cite the software release, the Weather article, "
            "the formal source-data record, and acknowledge JASMIN where applicable."
        ),
    }


def citation_text(payload: dict[str, Any] | None = None) -> str:
    """Return a human-readable citation block for CLI and UI display."""

    data = payload or citation_payload()
    return "\n".join(
        [
            f"{data['software']['name']} v{data['software']['version']}",
            "",
            "Software:",
            str(data["software"]["preferred_release_citation"]),
            "",
            "Article:",
            str(data["article"]["preferred_article_citation"]),
            "",
            "Source data:",
            str(data["source_data"]["citation"]),
            "",
            "Infrastructure:",
            str(data["infrastructure"]["jasmin_acknowledgement"]),
            "",
            str(data["user_instruction"]),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uk-wsr-visualizer-citation")
    parser.add_argument("--json", action="store_true", help="Write structured citation metadata as JSON.")
    args = parser.parse_args(argv)
    payload = citation_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(citation_text(payload))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
