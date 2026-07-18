"""Resumable integrity checks for learned-background training PVOL sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .qc_benchmark_download import download_and_validate_source


def download_and_validate_training_source(
    item: dict[str, Any],
    path: Path,
    *,
    retries: int,
    previous: dict[str, Any] | None,
    excluded_source_sha256: Iterable[str] = (),
) -> dict[str, Any]:
    """Download one source and reject benchmark-identical content by hash."""

    source_id = str(item["source_id"])
    adapted = {**item, "case_id": source_id}
    result = download_and_validate_source(
        adapted,
        path,
        retries=retries,
        previous=previous,
    )
    digest = str(result.get("sha256") or "")
    excluded = set(str(value) for value in excluded_source_sha256)
    if digest and digest in excluded:
        path.unlink(missing_ok=True)
        raise ValueError(
            f"{source_id}: downloaded SHA-256 matches an excluded QC benchmark source"
        )
    return {
        **result,
        "source_id": source_id,
        "case_id": None,
        "split": item["split"],
        "radar": item["radar"],
        "date": item["date"],
        "time": item["time"],
        "pulse": item["pulse"],
        "benchmark_hash_exclusion_checked": True,
    }
