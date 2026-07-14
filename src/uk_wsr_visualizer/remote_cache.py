"""On-demand cache for public raw aggregate HDF5 objects."""

from __future__ import annotations

from pathlib import Path
import threading
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from .catalog import CatalogItem, RawVolumeRecord, scan_aggregate
from .object_store import join_object_url, relative_aggregate_path, relative_raw_volume_path


_download_locks: dict[str, threading.Lock] = {}
_download_locks_guard = threading.Lock()


def _download_lock(key: str) -> threading.Lock:
    with _download_locks_guard:
        lock = _download_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _download_locks[key] = lock
        return lock


def is_remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def item_aggregate_url(item: CatalogItem, public_base_url: str = "") -> str:
    if item.object_url and is_remote_url(item.object_url):
        return item.object_url
    if item.path and is_remote_url(item.path):
        return item.path
    if public_base_url and item.object_key:
        return join_object_url(public_base_url, item.object_key)
    return ""


def raw_volume_url(volume: RawVolumeRecord, public_base_url: str = "") -> str:
    if volume.object_url and is_remote_url(volume.object_url):
        return volume.object_url
    if volume.path and is_remote_url(volume.path):
        return volume.path
    if public_base_url and volume.object_key:
        return join_object_url(public_base_url, volume.object_key)
    return ""


def cached_aggregate_path(item: CatalogItem, cache_dir: Path) -> Path:
    return cache_dir / relative_aggregate_path(cache_dir, item.radar, item.date)


def cached_raw_volume_path(item: CatalogItem, volume: RawVolumeRecord, cache_dir: Path) -> Path:
    return cache_dir / relative_raw_volume_path(item.radar, item.date, volume.pulse, volume.filename)


def iter_cached_aggregates(cache_dir: Path):
    if not cache_dir.exists():
        return
    yield from sorted(cache_dir.rglob("*.h5"))


def raw_cache_status(cache_dir: Path) -> dict[str, object]:
    files = [path for path in iter_cached_aggregates(cache_dir) or [] if path.is_file()]
    return {
        "cache_dir": str(cache_dir),
        "file_count": len(files),
        "byte_count": sum(path.stat().st_size for path in files),
        "files": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "modified_time": path.stat().st_mtime,
            }
            for path in files
        ],
    }


def clear_raw_cache(cache_dir: Path) -> dict[str, object]:
    removed = 0
    byte_count = 0
    for path in list(iter_cached_aggregates(cache_dir) or []):
        if not path.is_file():
            continue
        size = path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
        byte_count += size
    for directory in sorted((p for p in cache_dir.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"cache_dir": str(cache_dir), "removed_count": removed, "removed_bytes": byte_count}


def prune_raw_cache(cache_dir: Path, max_age_seconds: int = 0, max_bytes: int = 25 * 1024 * 1024 * 1024) -> dict[str, object]:
    now = time.time()
    removed = 0
    removed_bytes = 0
    files = [path for path in iter_cached_aggregates(cache_dir) or [] if path.is_file()]
    survivors = []
    for path in files:
        stat = path.stat()
        if max_age_seconds > 0 and now - stat.st_mtime > max_age_seconds:
            path.unlink(missing_ok=True)
            removed += 1
            removed_bytes += stat.st_size
        else:
            survivors.append(path)

    total = sum(path.stat().st_size for path in survivors if path.exists())
    if max_bytes >= 0 and total > max_bytes:
        for path in sorted(survivors, key=lambda candidate: candidate.stat().st_mtime):
            if total <= max_bytes:
                break
            if not path.exists():
                continue
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            removed += 1
            removed_bytes += size
            total -= size
    for directory in sorted((p for p in cache_dir.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {"cache_dir": str(cache_dir), "removed_count": removed, "removed_bytes": removed_bytes}


def ensure_raw_aggregate_cached(
    item: CatalogItem,
    cache_dir: Path,
    public_base_url: str = "",
    max_age_seconds: int = 0,
    max_bytes: int = 25 * 1024 * 1024 * 1024,
) -> Path:
    prune_raw_cache(cache_dir, max_age_seconds=max_age_seconds, max_bytes=max_bytes)
    local_path = Path(item.path)
    if item.path and not is_remote_url(item.path) and local_path.exists() and local_path.is_file():
        return local_path

    url = item_aggregate_url(item, public_base_url)
    if not url:
        raise ValueError(f"no remote aggregate URL available for {item.radar} {item.date}")

    target = cached_aggregate_path(item, cache_dir)
    with _download_lock(str(target)):
        if target.exists() and (item.file_size <= 0 or target.stat().st_size == item.file_size):
            target.touch()
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        partial.unlink(missing_ok=True)
        with urlopen(url, timeout=60) as response, partial.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if item.file_size > 0 and partial.stat().st_size != item.file_size:
            partial.unlink(missing_ok=True)
            raise ValueError(f"downloaded size mismatch for {url}")
        partial.replace(target)
    prune_raw_cache(cache_dir, max_age_seconds=max_age_seconds, max_bytes=max_bytes)
    return target


def ensure_raw_volume_cached(
    item: CatalogItem,
    volume: RawVolumeRecord,
    cache_dir: Path,
    public_base_url: str = "",
    max_age_seconds: int = 0,
    max_bytes: int = 25 * 1024 * 1024 * 1024,
) -> Path:
    prune_raw_cache(cache_dir, max_age_seconds=max_age_seconds, max_bytes=max_bytes)
    local_path = Path(volume.path)
    if volume.path and not is_remote_url(volume.path) and local_path.exists() and local_path.is_file():
        return local_path

    url = raw_volume_url(volume, public_base_url)
    if not url:
        raise ValueError(f"no remote raw-volume URL available for {item.radar} {item.date} {volume.pulse} {volume.time}")

    target = cached_raw_volume_path(item, volume, cache_dir)
    with _download_lock(str(target)):
        if target.exists() and (volume.file_size <= 0 or target.stat().st_size == volume.file_size):
            target.touch()
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".partial")
        partial.unlink(missing_ok=True)
        with urlopen(url, timeout=60) as response, partial.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if volume.file_size > 0 and partial.stat().st_size != volume.file_size:
            partial.unlink(missing_ok=True)
            raise ValueError(f"downloaded size mismatch for {url}")
        partial.replace(target)
    prune_raw_cache(cache_dir, max_age_seconds=max_age_seconds, max_bytes=max_bytes)
    return target


def hydrate_item_from_raw_aggregate(
    item: CatalogItem,
    cache_dir: Path,
    public_base_url: str = "",
    max_age_seconds: int = 0,
    max_bytes: int = 25 * 1024 * 1024 * 1024,
) -> CatalogItem:
    aggregate = ensure_raw_aggregate_cached(item, cache_dir, public_base_url, max_age_seconds=max_age_seconds, max_bytes=max_bytes)
    hydrated = scan_aggregate(aggregate, cache_dir, public_base_url)
    hydrated.object_key = item.object_key or hydrated.object_key
    hydrated.object_url = item_aggregate_url(item, public_base_url) or hydrated.object_url
    hydrated.validation_status = item.validation_status
    return hydrated
