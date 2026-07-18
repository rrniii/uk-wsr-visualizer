"""Small persistent JSON cache for object-store catalog sidecars."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cache_paths(cache_dir: Path, url: str) -> tuple[Path, Path]:
    key = _cache_key(url)
    return cache_dir / f"{key}.json", cache_dir / f"{key}.meta.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"cached JSON is not an object: {path}")
    return payload


def load_json_cached(url: str, cache_dir: Path, timeout_s: float = 30.0) -> dict[str, Any]:
    """Fetch a JSON object with conditional requests and disk fallback.

    The object-store catalog is intentionally split into small JSON sidecars.
    Keeping these sidecars on disk removes avoidable startup and selection
    latency while still checking ETag/Last-Modified when the server provides
    them. If the network is temporarily unavailable, the last valid cached
    object is used.
    """

    cache_dir.mkdir(parents=True, exist_ok=True)
    body_path, meta_path = _cache_paths(cache_dir, url)
    headers: dict[str, str] = {}
    if meta_path.exists():
        try:
            meta = _read_json(meta_path)
        except Exception:
            meta = {}
        etag = meta.get("etag")
        last_modified = meta.get("last_modified")
        if isinstance(etag, str) and etag:
            headers["If-None-Match"] = etag
        if isinstance(last_modified, str) and last_modified:
            headers["If-Modified-Since"] = last_modified
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout_s) as response:
            data = response.read()
            payload = json.loads(data.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError(f"catalog endpoint did not return an object: {url}")
            tmp = body_path.with_suffix(body_path.suffix + ".partial")
            tmp.write_bytes(data)
            tmp.replace(body_path)
            meta_payload = {
                "url": url,
                "fetched_at": time.time(),
                "etag": response.headers.get("ETag") or "",
                "last_modified": response.headers.get("Last-Modified") or "",
            }
            meta_path.write_text(json.dumps(meta_payload, indent=2, sort_keys=True), encoding="utf-8")
            return payload
    except HTTPError as exc:
        if exc.code == 304 and body_path.exists():
            return _read_json(body_path)
        if body_path.exists():
            return _read_json(body_path)
        raise
    except (OSError, URLError, json.JSONDecodeError):
        if body_path.exists():
            return _read_json(body_path)
        raise
