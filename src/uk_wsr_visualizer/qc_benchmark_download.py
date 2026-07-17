"""Resumable download and integrity checks for QC benchmark PVOL sources."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import h5py


def download_and_validate_source(
    item: dict[str, Any],
    path: Path,
    *,
    retries: int,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    expected_size = int(item.get("size_bytes") or 0)
    if (
        previous
        and path.exists()
        and path.stat().st_size == int(previous.get("size_bytes") or -1)
        and previous.get("sha256")
        and validate_pvol_source(path)
    ):
        digest = sha256_file(path)
        if digest == previous["sha256"]:
            actual_size = path.stat().st_size
            return {
                **previous,
                "catalog_size_bytes": expected_size,
                "size_bytes": actual_size,
                "catalog_size_match": (
                    expected_size <= 0 or actual_size == expected_size
                ),
                "status": "cached",
                "validated_at": utc_now(),
            }

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            digest, actual_size, catalog_size_match = _download(
                item["object_url"],
                path,
                expected_size=expected_size,
            )
            validate_pvol_source(path, raise_on_error=True)
            return {
                "case_id": item["case_id"],
                "object_url": item["object_url"],
                "local_path": str(path),
                "catalog_size_bytes": expected_size,
                "size_bytes": actual_size,
                "catalog_size_match": catalog_size_match,
                "sha256": digest,
                "hdf5_valid": True,
                "status": (
                    "downloaded"
                    if catalog_size_match
                    else "downloaded_catalog_drift"
                ),
                "attempt": attempt,
                "validated_at": utc_now(),
            }
        except Exception as exc:  # noqa: BLE001 - retry network and integrity errors.
            last_error = exc
            path.with_suffix(path.suffix + ".part").unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
    assert last_error is not None
    raise last_error


def validate_pvol_source(path: Path, *, raise_on_error: bool = False) -> bool:
    try:
        with h5py.File(path, "r") as h5:
            datasets = [name for name in h5 if str(name).startswith("dataset")]
            if not datasets:
                raise ValueError("no dataset groups")
            quantities = []
            for dataset_name in datasets:
                dataset = h5[dataset_name]
                for name, group in dataset.items():
                    if not str(name).startswith("data") or not isinstance(group, h5py.Group):
                        continue
                    what = group.get("what")
                    if what is not None and "quantity" in what.attrs:
                        value = what.attrs["quantity"]
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors="replace")
                        quantities.append(str(value).upper())
            if "DBZH" not in quantities:
                raise ValueError("no DBZH data group")
        return True
    except Exception:
        if raise_on_error:
            raise
        return False


def load_download_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"files": {}}
    return value if isinstance(value, dict) else {"files": {}}


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _download(url: str, path: Path, *, expected_size: int) -> tuple[str, int, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    digest = sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "uk-wsr-qc-benchmark/1"})
    with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as handle:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            handle.write(block)
            digest.update(block)
        handle.flush()
        os.fsync(handle.fileno())
    actual_size = temporary.stat().st_size
    temporary.replace(path)
    return (
        digest.hexdigest(),
        actual_size,
        expected_size <= 0 or actual_size == expected_size,
    )
