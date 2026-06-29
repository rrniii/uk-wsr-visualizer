from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import os
import shlex
import time


@dataclass(frozen=True)
class PvolCatalogConfig:
    aws: str
    bucket: str
    endpoint: str
    profile: str
    region: str
    object_prefix: str
    pvol_base: Path
    public_base_url: str
    upload_base: Path


def env_value(name: str, default: str) -> str:
    return os.environ.get(name, default)


def config_from_env() -> PvolCatalogConfig:
    """Return JASMIN Object Store settings for the PVOL maintenance scripts."""

    return PvolCatalogConfig(
        aws=env_value("UK_WSR_AWS", "/home/users/rrniii/bin/aws"),
        bucket=env_value("UK_WSR_OBJECT_STORE_BUCKET", "uk-wsr-visualizer-public"),
        endpoint=env_value("UK_WSR_OBJECT_STORE_ENDPOINT", "http://ncas-radar-o.s3.jc.rl.ac.uk"),
        profile=env_value("UK_WSR_AWS_PROFILE", "ncas-radar-o"),
        region=env_value("UK_WSR_AWS_REGION", "us-east-1"),
        object_prefix=env_value("UK_WSR_OBJECT_PREFIX", "ukmo-nimrod"),
        pvol_base=Path(
            env_value(
                "UK_WSR_PVOL_BASE",
                "/gws/ssde/j25a/ncas_radar/vol2/avocet/ukmo-nimrod/vol2birdinput/single-site",
            )
        ),
        public_base_url=env_value(
            "UK_WSR_PUBLIC_BASE_URL",
            "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public",
        ),
        upload_base=Path(
            env_value(
                "UK_WSR_PVOL_UPLOAD_BASE",
                "/gws/ssde/j25a/ncas_radar/vol2/avocet/object-store/pvol-fast-upload",
            )
        ),
    )


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_or_error(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except Exception as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"}


def aws_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AWS_MAX_ATTEMPTS": "10",
            "AWS_RETRY_MODE": "adaptive",
            "AWS_REQUEST_CHECKSUM_CALCULATION": "when_required",
            "AWS_RESPONSE_CHECKSUM_VALIDATION": "when_required",
        }
    )
    if extra:
        env.update(extra)
    return env


def aws_base(config: PvolCatalogConfig) -> list[str]:
    return [config.aws, "--profile", config.profile, "--region", config.region, "--endpoint-url", config.endpoint]


def shell_join(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def object_key(prefix: str, *parts: str) -> str:
    return "/".join([prefix.strip("/"), *[str(part).strip("/") for part in parts if str(part).strip("/")]])


def join_object_url(base_url: str, key: str) -> str:
    return f"{base_url.rstrip('/')}/{key.lstrip('/')}"
