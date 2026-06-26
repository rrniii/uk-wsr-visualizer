"""Citation and provenance helpers for UK WSR Visualizer."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from . import __version__

SOFTWARE_NAME = "UK WSR Visualizer"
REPOSITORY_URL = "https://github.com/rrniii/uk-wsr-visualizer"
SOFTWARE_DOI = "TODO: Zenodo software DOI after first archived release"
ARTICLE_DOI = "TODO: Weather article DOI after publication"
SOURCE_DATA_CITATION = (
    "TODO: replace with the formal UK WSR aggregate HDF5 source-data citation "
    "agreed with the data owner and archive."
)
JASMIN_ACKNOWLEDGEMENT = "This work used JASMIN, the UK's collaborative data analysis environment."
WCT_ACKNOWLEDGEMENT = (
    "The design of UK WSR Visualizer was informed by user-facing workflows in "
    "NOAA's Weather and Climate Toolkit. UK WSR Visualizer is an independent "
    "implementation for UK weather surveillance radar aggregate HDF5 archives "
    "and JASMIN Object Store access; it is not affiliated with or endorsed by "
    "NOAA or NCEI."
)
AI_ASSISTED_DEVELOPMENT_NOTE = (
    "Portions of the software were developed using AI-assisted programming with "
    "OpenAI Codex. The author specified the scientific requirements, reviewed "
    "and modified generated code, ran tests and validation checks, and remains "
    "responsible for the software design, implementation, validation, and "
    "manuscript content."
)


@dataclass(frozen=True)
class CitationMetadata:
    """Stable citation fields used by the CLI, API, and export manifests."""

    software_name: str = SOFTWARE_NAME
    version: str = __version__
    repository_url: str = REPOSITORY_URL
    software_doi: str = SOFTWARE_DOI
    article_doi: str = ARTICLE_DOI
    source_data_citation: str = SOURCE_DATA_CITATION
    jasmin_acknowledgement: str = JASMIN_ACKNOWLEDGEMENT
    wct_acknowledgement: str = WCT_ACKNOWLEDGEMENT
    ai_assisted_development_note: str = AI_ASSISTED_DEVELOPMENT_NOTE


def _git_commit() -> str:
    """Return the current Git commit when available."""

    env_value = os.environ.get("UK_WSR_VISUALIZER_GIT_COMMIT")
    if env_value:
        return env_value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def citation_payload() -> dict[str, object]:
    """Return machine-readable citation guidance."""

    metadata = CitationMetadata()
    software_citation = (
        f"Neely, R. R. III. {metadata.software_name}, version {metadata.version}. "
        f"Zenodo. DOI: {metadata.software_doi}."
    )
    article_citation = (
        "Neely, R. R. III. UK WSR Visualizer: community access and "
        f"visualisation to UK weather surveillance radar data. Weather. DOI: {metadata.article_doi}."
    )
    return {
        "software": {
            "name": metadata.software_name,
            "version": metadata.version,
            "repository_url": metadata.repository_url,
            "software_doi": metadata.software_doi,
            "git_commit": _git_commit(),
        },
        "article": {
            "title": "UK WSR Visualizer: community access and visualisation to UK weather surveillance radar data",
            "journal": "Weather",
            "doi": metadata.article_doi,
        },
        "citation": {
            "software": software_citation,
            "article": article_citation,
            "source_data": metadata.source_data_citation,
            "jasmin": metadata.jasmin_acknowledgement,
        },
        "source_data": {
            "citation": metadata.source_data_citation,
        },
        "infrastructure": {
            "jasmin_acknowledgement": metadata.jasmin_acknowledgement,
        },
        "acknowledgements": {
            "wct_inspiration": metadata.wct_acknowledgement,
            "ai_assisted_development": metadata.ai_assisted_development_note,
        },
    }


def manifest_provenance() -> dict[str, object]:
    """Return provenance metadata for export manifests."""

    return citation_payload()


def format_citation_text() -> str:
    """Return human-readable citation guidance."""

    payload = citation_payload()
    citation = payload["citation"]
    infrastructure = payload["infrastructure"]
    return "\n".join(
        [
            f"{SOFTWARE_NAME} citation guidance",
            "",
            "If you use this software in research, cite:",
            f"1. Software: {citation['software']}",
            f"2. Article: {citation['article']}",
            f"3. Source data: {citation['source_data']}",
            f"4. JASMIN acknowledgement: {infrastructure['jasmin_acknowledgement']}",
            "",
            "Record the exact software version and Git commit in methods or provenance metadata.",
        ]
    )
