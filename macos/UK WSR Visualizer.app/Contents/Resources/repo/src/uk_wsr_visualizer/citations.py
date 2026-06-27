"""Citation and provenance metadata for UK WSR Visualizer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from . import __version__

SOFTWARE_NAME = "UK WSR Visualizer"
PACKAGE_NAME = "uk-wsr-visualizer"
REPOSITORY_URL = "https://github.com/rrniii/uk-wsr-visualizer"
SOFTWARE_DOI = "pending: mint a versioned software DOI with Zenodo"
ARTICLE_DOI = "pending: add the Weather article DOI after publication"
ARTICLE_TITLE = "UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data"

SOURCE_DATA_CITATION = (
    "Formal UK WSR aggregate HDF5 source-data citation pending. "
    "Do not substitute a citation for a different data product family, and do "
    "not cite the object-store mirror as the source-data record."
)
SOURCE_DATA_LICENCE = (
    "Licence and access terms pending confirmation for the released UK WSR "
    "aggregate HDF5 source objects."
)
JASMIN_ACKNOWLEDGEMENT = "This work used JASMIN, the UK's collaborative data analysis environment."
DESIGN_CONTEXT_NOTE = (
    "UK WSR Visualizer is an independent implementation for UK weather surveillance radar "
    "aggregate HDF5 archives and JASMIN Object Store access. Existing radar viewers and "
    "scientific Python tools informed the user-facing workflow, but no endorsement or "
    "affiliation is implied."
)
AI_ASSISTED_DEVELOPMENT_DISCLOSURE = (
    "Portions of the software were developed using AI-assisted programming with OpenAI Codex. "
    "The author specified the scientific requirements, reviewed and modified generated code, "
    "ran tests and validation checks, and remains responsible for the software design, "
    "implementation, validation, and manuscript content."
)


def _git_commit() -> str | None:
    """Return the current Git commit SHA when available."""

    for name in ("UK_WSR_VISUALIZER_GIT_SHA", "GITHUB_SHA", "SOURCE_VERSION"):
        value = os.environ.get(name)
        if value:
            return value

    repo_root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    sha = result.stdout.strip()
    return sha or None


def citation_payload(
    *,
    source_data_citation: str | None = None,
    source_data_licence: str | None = None,
) -> dict[str, Any]:
    """Return structured citation and acknowledgement metadata.

    The returned payload is intentionally explicit about the four credit layers:
    software, article, source data, and JASMIN infrastructure.
    """

    software_citation = (
        f"Neely, R. R. III. {SOFTWARE_NAME}, version {__version__}. "
        f"Zenodo. DOI: {SOFTWARE_DOI}."
    )
    article_citation = f"Neely, R. R. III. {ARTICLE_TITLE}. Weather. DOI: {ARTICLE_DOI}."
    resolved_source_citation = source_data_citation or SOURCE_DATA_CITATION
    return {
        "software": {
            "name": SOFTWARE_NAME,
            "package": PACKAGE_NAME,
            "version": __version__,
            "doi": SOFTWARE_DOI,
            "repository": REPOSITORY_URL,
            "git_commit": _git_commit(),
            "preferred_release_citation": software_citation,
        },
        "article": {
            "title": ARTICLE_TITLE,
            "journal": "Weather",
            "doi": ARTICLE_DOI,
            "preferred_article_citation": article_citation,
        },
        "source_data": {
            "citation": resolved_source_citation,
            "licence": source_data_licence or SOURCE_DATA_LICENCE,
        },
        "infrastructure": {
            "jasmin_acknowledgement": JASMIN_ACKNOWLEDGEMENT,
            "jasmin_reference": (
                "Lawrence, B. N. et al. (2013) Storing and manipulating environmental big data with JASMIN."
            ),
        },
        "acknowledgements": {
            "design_context": DESIGN_CONTEXT_NOTE,
            "ai_assisted_development": AI_ASSISTED_DEVELOPMENT_DISCLOSURE,
        },
        "citation": {
            "software": software_citation,
            "article": article_citation,
            "source_data": resolved_source_citation,
            "jasmin_acknowledgement": JASMIN_ACKNOWLEDGEMENT,
        },
        "user_instruction": (
            "If UK WSR Visualizer is used to produce a figure, export, derived object, "
            "case selection, or research result, cite the software release, the Weather article, "
            "the formal source-data record, and acknowledge JASMIN where applicable."
        ),
    }


def manifest_provenance(
    *,
    source_data_citation: str | None = None,
    source_data_licence: str | None = None,
) -> dict[str, Any]:
    """Return the citation/provenance block written into export manifests."""

    payload = citation_payload(
        source_data_citation=source_data_citation,
        source_data_licence=source_data_licence,
    )
    return {
        "software": payload["software"],
        "article": payload["article"],
        "source_data": payload["source_data"],
        "citation": payload["citation"],
        "infrastructure": payload["infrastructure"],
        "acknowledgements": payload["acknowledgements"],
        "user_instruction": payload["user_instruction"],
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
            "JASMIN acknowledgement:",
            str(data["infrastructure"]["jasmin_acknowledgement"]),
            "",
            str(data["user_instruction"]),
        ]
    )


# Backwards-compatible alias used by early tests and documentation drafts.
format_citation_text = citation_text


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
