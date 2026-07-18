"""Leakage-controlled real-data training for learned UK WSR backgrounds."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from .background_model import (
    BACKGROUND_MODEL_SCHEMA,
    BACKGROUND_MODEL_SCHEMA_VERSION,
    BackgroundModel,
    BackgroundModelBuildConfig,
    BackgroundScan,
    build_background_model,
    hash_arrays,
)
from .background_model_v3 import (
    DateBalancedBackgroundConfig,
    build_date_balanced_background_model,
)
from .dependencies import require_h5py, require_numpy
from .export_types import FieldSelection
from .geospatial import read_polar_field_with_companions, scalar
from .qc import normalized_quantity

TRAINING_PIPELINE_SCHEMA = "uk_wsr_background_training_pipeline"
TRAINING_PIPELINE_SCHEMA_VERSION = 1
DEFAULT_ELEVATION_TOLERANCE_DEG = 0.075
NOMINAL_ELEVATION_STEP_DEG = 0.5


@dataclass(frozen=True)
class VerifiedTrainingSource:
    """One manifest source joined to its verified local ledger entry."""

    source_id: str
    radar: str
    pulse: str
    split: str
    date: str
    time: str
    local_path: str
    object_url: str
    object_key: str | None
    sha256: str
    size_bytes: int
    season: str | None = None
    utc_slot: str | None = None


@dataclass(frozen=True)
class SweepDescriptor:
    """A reflectivity sweep and its exact polar geometry in one source."""

    source_id: str
    radar: str
    pulse: str
    split: str
    date: str
    time: str
    local_path: str
    sha256: str
    dataset: str
    field_group: str
    quantity: str
    elevation_deg: float
    nrays: int
    nbins: int
    rstart_km: float
    rscale_m: float
    companion_quantities: tuple[str, ...]


@dataclass(frozen=True)
class BackgroundTrainingTarget:
    """One canonical radar/pulse/elevation/geometry model target."""

    target_id: str
    radar: str
    pulse: str
    quantity: str
    elevation_deg: float
    nrays: int
    nbins: int
    rstart_km: float
    rscale_m: float
    dataset_aliases: tuple[str, ...]
    sweeps: tuple[SweepDescriptor, ...]

    @property
    def shape(self) -> tuple[int, int]:
        return (self.nrays, self.nbins)

    def split_sweeps(self, split: str) -> tuple[SweepDescriptor, ...]:
        return tuple(sweep for sweep in self.sweeps if sweep.split == split)


def load_verified_training_sources(
    manifest_path: str | Path,
    ledger_path: str | Path,
    *,
    radar: Iterable[str] | None = None,
    pulse: Iterable[str] | None = None,
) -> tuple[VerifiedTrainingSource, ...]:
    """Join the immutable source manifest to a completed validation ledger."""

    manifest_source = Path(manifest_path)
    ledger_source = Path(ledger_path)
    manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_source.read_text(encoding="utf-8"))
    manifest_hash = sha256(manifest_source.read_bytes()).hexdigest()
    if ledger.get("manifest_sha256") != manifest_hash:
        raise ValueError("download ledger does not match the training manifest")
    if ledger.get("validated_file_count") != manifest.get("file_count"):
        raise ValueError("download ledger is not complete for the training manifest")
    if ledger.get("failures"):
        raise ValueError("download ledger contains failed sources")

    wanted_radars = {str(value) for value in radar or ()}
    wanted_pulses = {str(value).lower() for value in pulse or ()}
    ledger_files = ledger.get("files")
    if not isinstance(ledger_files, dict):
        raise ValueError("download ledger has no source file map")

    sources: list[VerifiedTrainingSource] = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "")
        if not source_id:
            raise ValueError("training manifest contains a source without source_id")
        if wanted_radars and str(item.get("radar")) not in wanted_radars:
            continue
        if wanted_pulses and str(item.get("pulse")).lower() not in wanted_pulses:
            continue
        verified = ledger_files.get(source_id)
        if not isinstance(verified, dict):
            raise ValueError(f"source {source_id} is missing from the download ledger")
        local_path = Path(str(verified.get("local_path") or ""))
        digest = str(verified.get("sha256") or "")
        if (
            verified.get("hdf5_valid") is not True
            or verified.get("benchmark_hash_exclusion_checked") is not True
            or len(digest) != 64
            or not local_path.is_file()
        ):
            raise ValueError(f"source {source_id} is not a verified local HDF5 file")
        if local_path.stat().st_size != int(verified.get("size_bytes") or -1):
            raise ValueError(f"source {source_id} local size no longer matches its ledger")
        sources.append(
            VerifiedTrainingSource(
                source_id=source_id,
                radar=str(item["radar"]),
                pulse=str(item["pulse"]).lower(),
                split=str(item["split"]),
                date=str(item["date"]),
                time=str(item["time"]),
                local_path=str(local_path),
                object_url=str(item["object_url"]),
                object_key=(
                    str(item["object_key"])
                    if item.get("object_key")
                    else None
                ),
                sha256=digest,
                size_bytes=int(verified["size_bytes"]),
                season=(
                    str(item["season"]) if item.get("season") else None
                ),
                utc_slot=(
                    str(item["utc_slot"]) if item.get("utc_slot") else None
                ),
            )
        )
    return tuple(
        sorted(
            sources,
            key=lambda source: (
                source.radar,
                source.pulse,
                source.split,
                source.date,
                source.time,
                source.source_id,
            ),
        )
    )


def discover_source_sweeps(
    source: VerifiedTrainingSource,
    *,
    quantity: str = "DBZH",
) -> tuple[SweepDescriptor, ...]:
    """Discover all matching sweeps without assuming stable dataset indices."""

    h5py = require_h5py()
    wanted = normalized_quantity(quantity)
    descriptors: list[SweepDescriptor] = []
    with h5py.File(source.local_path, "r") as h5:
        matches: list[tuple[str, Any]] = []

        def visit(name: str, obj: Any) -> None:
            if not isinstance(obj, h5py.Group) or "data" not in obj:
                return
            if "/data" not in name:
                return
            if normalized_quantity(_group_quantity(obj)) == wanted:
                matches.append((name, obj))

        h5.visititems(visit)
        for field_group, group in sorted(matches):
            dataset_path, dataset = _dataset_from_field_group(field_group)
            if not dataset:
                continue
            dataset_group = h5.get(dataset_path)
            where = dataset_group.get("where") if dataset_group is not None else None
            attrs = _attrs(where)
            shape = tuple(int(value) for value in group["data"].shape)
            if len(shape) != 2:
                continue
            nrays, nbins = shape
            attr_nrays = _optional_int(attrs.get("nrays"))
            attr_nbins = _optional_int(attrs.get("nbins"))
            if attr_nrays not in (None, nrays) or attr_nbins not in (None, nbins):
                raise ValueError(
                    f"{source.source_id} {dataset} shape {shape} conflicts "
                    "with ODIM where metadata"
                )
            elevation = _required_float(
                attrs,
                ("elangle", "elevation", "elevation_angle"),
                source_id=source.source_id,
                dataset=dataset,
            )
            companions = _dataset_quantities(dataset_group)
            descriptors.append(
                SweepDescriptor(
                    source_id=source.source_id,
                    radar=source.radar,
                    pulse=source.pulse,
                    split=source.split,
                    date=source.date,
                    time=source.time,
                    local_path=source.local_path,
                    sha256=source.sha256,
                    dataset=dataset,
                    field_group=field_group,
                    quantity=wanted,
                    elevation_deg=elevation,
                    nrays=nrays,
                    nbins=nbins,
                    rstart_km=float(attrs.get("rstart") or 0.0),
                    rscale_m=float(attrs.get("rscale") or 1000.0),
                    companion_quantities=companions,
                )
            )
    return tuple(
        sorted(
            descriptors,
            key=lambda sweep: (
                sweep.elevation_deg,
                sweep.nrays,
                sweep.nbins,
                sweep.rscale_m,
                sweep.dataset,
            ),
        )
    )


def build_sweep_inventory(
    sources: Iterable[VerifiedTrainingSource],
    *,
    quantity: str = "DBZH",
) -> tuple[SweepDescriptor, ...]:
    """Discover all source sweeps and reject duplicate geometries per source."""

    sweeps: list[SweepDescriptor] = []
    for source in sources:
        discovered = discover_source_sweeps(source, quantity=quantity)
        if not discovered:
            raise ValueError(f"source {source.source_id} has no {quantity} sweep")
        sweeps.extend(discovered)
    return tuple(sweeps)


def cluster_training_targets(
    sweeps: Iterable[SweepDescriptor],
    *,
    elevation_tolerance_deg: float = DEFAULT_ELEVATION_TOLERANCE_DEG,
) -> tuple[BackgroundTrainingTarget, ...]:
    """Cluster sweep aliases by elevation and exact polar range geometry."""

    np = require_numpy()
    grouped: dict[tuple[Any, ...], list[SweepDescriptor]] = {}
    for sweep in sweeps:
        geometry = (
            sweep.radar,
            sweep.pulse,
            sweep.quantity,
            sweep.nrays,
            sweep.nbins,
            round(sweep.rstart_km, 6),
            round(sweep.rscale_m, 3),
        )
        grouped.setdefault(geometry, []).append(sweep)

    targets: list[BackgroundTrainingTarget] = []
    for geometry, members in sorted(grouped.items()):
        elevation_clusters: list[list[SweepDescriptor]] = []
        for sweep in sorted(members, key=lambda value: value.elevation_deg):
            matching = next(
                (
                    cluster
                    for cluster in elevation_clusters
                    if abs(
                        sweep.elevation_deg
                        - float(
                            np.median(
                                [value.elevation_deg for value in cluster]
                            )
                        )
                    )
                    <= elevation_tolerance_deg
                ),
                None,
            )
            if matching is None:
                elevation_clusters.append([sweep])
            else:
                matching.append(sweep)

        for cluster in elevation_clusters:
            source_ids = [sweep.source_id for sweep in cluster]
            duplicate_ids = sorted(
                source_id
                for source_id, count in Counter(source_ids).items()
                if count > 1
            )
            if duplicate_ids:
                raise ValueError(
                    "multiple matching sweeps in one source: "
                    + ",".join(duplicate_ids)
                )
            elevation = float(
                np.median([sweep.elevation_deg for sweep in cluster])
            )
            radar, pulse_name, field, nrays, nbins, rstart, rscale = geometry
            target_id = _target_id(
                radar=str(radar),
                pulse=str(pulse_name),
                quantity=str(field),
                elevation_deg=elevation,
                nrays=int(nrays),
                nbins=int(nbins),
                rstart_km=float(rstart),
                rscale_m=float(rscale),
            )
            targets.append(
                BackgroundTrainingTarget(
                    target_id=target_id,
                    radar=str(radar),
                    pulse=str(pulse_name),
                    quantity=str(field),
                    elevation_deg=elevation,
                    nrays=int(nrays),
                    nbins=int(nbins),
                    rstart_km=float(rstart),
                    rscale_m=float(rscale),
                    dataset_aliases=tuple(
                        sorted(
                            {sweep.dataset for sweep in cluster},
                            key=_dataset_sort_key,
                        )
                    ),
                    sweeps=tuple(
                        sorted(
                            cluster,
                            key=lambda sweep: (
                                sweep.split,
                                sweep.date,
                                sweep.time,
                                sweep.source_id,
                            ),
                        )
                    ),
                )
            )
    return tuple(
        sorted(
            targets,
            key=lambda target: (
                target.radar,
                target.pulse,
                target.elevation_deg,
                target.nrays,
                target.nbins,
            ),
        )
    )


def training_inventory_manifest(
    sources: Iterable[VerifiedTrainingSource],
    sweeps: Iterable[SweepDescriptor],
    targets: Iterable[BackgroundTrainingTarget],
    *,
    source_manifest_sha256: str,
    ledger_sha256: str,
) -> dict[str, Any]:
    """Build a machine-readable coverage contract before model training."""

    source_list = list(sources)
    sweep_list = list(sweeps)
    target_list = list(targets)
    return {
        "schema": TRAINING_PIPELINE_SCHEMA,
        "schema_version": TRAINING_PIPELINE_SCHEMA_VERSION,
        "generated_at": _now_utc(),
        "source_manifest_sha256": source_manifest_sha256,
        "download_ledger_sha256": ledger_sha256,
        "source_count": len(source_list),
        "sweep_count": len(sweep_list),
        "target_count": len(target_list),
        "radar_count": len({source.radar for source in source_list}),
        "pulses": sorted({source.pulse for source in source_list}),
        "splits": dict(sorted(Counter(source.split for source in source_list).items())),
        "targets": [
            {
                "target_id": target.target_id,
                "radar": target.radar,
                "pulse": target.pulse,
                "quantity": target.quantity,
                "elevation_deg": target.elevation_deg,
                "shape": [target.nrays, target.nbins],
                "rstart_km": target.rstart_km,
                "rscale_m": target.rscale_m,
                "dataset_aliases": list(target.dataset_aliases),
                "source_counts": {
                    split: len(target.split_sweeps(split))
                    for split in ("training", "validation", "holdout")
                },
                "date_counts": {
                    split: len(
                        {
                            sweep.date
                            for sweep in target.split_sweeps(split)
                        }
                    )
                    for split in ("training", "validation", "holdout")
                },
                "companion_coverage": _companion_coverage(target.sweeps),
            }
            for target in target_list
        ],
    }


def train_background_target(
    target: BackgroundTrainingTarget,
    output_dir: str | Path,
    *,
    source_manifest_sha256: str,
    ledger_sha256: str,
    config: BackgroundModelBuildConfig | None = None,
) -> tuple[BackgroundModel, Path, Path]:
    """Train one target from the training split and persist research arrays."""

    training_sweeps = target.split_sweeps("training")
    if not training_sweeps:
        raise ValueError(f"target {target.target_id} has no training sweeps")
    scans = [
        _read_background_scan(sweep, target)
        for sweep in training_sweeps
    ]
    representative_dataset = Counter(
        sweep.dataset for sweep in training_sweeps
    ).most_common(1)[0][0]
    model = build_background_model(
        scans,
        key={
            "radar": target.radar,
            "pulse": target.pulse,
            "quantity": target.quantity,
            "dataset": representative_dataset,
            "dataset_aliases": list(target.dataset_aliases),
            "elevation_deg": round(target.elevation_deg, 3),
            "nrays": target.nrays,
            "nbins": target.nbins,
            "rstart_km": target.rstart_km,
            "rscale_m": target.rscale_m,
            "geometry_id": target.target_id,
            "season_bucket": "all",
            "time_of_day_bucket": "all",
        },
        config=config or BackgroundModelBuildConfig(),
    )
    metadata = dict(model.metadata) | {
        "training_pipeline_schema": TRAINING_PIPELINE_SCHEMA,
        "training_pipeline_schema_version": TRAINING_PIPELINE_SCHEMA_VERSION,
        "source_manifest_sha256": source_manifest_sha256,
        "download_ledger_sha256": ledger_sha256,
        "training_source_ids": [
            sweep.source_id for sweep in training_sweeps
        ],
        "training_source_sha256": [
            sweep.sha256 for sweep in training_sweeps
        ],
        "dataset_aliases": list(target.dataset_aliases),
        "geometry": {
            "elevation_deg": target.elevation_deg,
            "nrays": target.nrays,
            "nbins": target.nbins,
            "rstart_km": target.rstart_km,
            "rscale_m": target.rscale_m,
        },
        "split_source_counts": {
            split: len(target.split_sweeps(split))
            for split in ("training", "validation", "holdout")
        },
        "companion_coverage": _companion_coverage(training_sweeps),
        "promotion_eligible": False,
        "promotion_blockers": [
            "independent labelled benchmark is incomplete",
            "real validation and holdout scoring is incomplete",
            "desktop and iOS parity is incomplete",
        ],
    }
    trained = BackgroundModel(
        key=model.key,
        shape=model.shape,
        arrays=model.arrays,
        metadata=metadata,
        array_hash=hash_arrays(model.arrays),
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    npz_path = output / f"{target.target_id}.npz"
    json_path = output / f"{target.target_id}.json"
    _write_research_model(trained, npz_path, json_path)
    return trained, npz_path, json_path


def train_date_balanced_background_target(
    target: BackgroundTrainingTarget,
    output_dir: str | Path,
    *,
    training_contract: dict[str, Any],
    training_contract_sha256: str,
    base_config: BackgroundModelBuildConfig | None = None,
    date_config: DateBalancedBackgroundConfig | None = None,
) -> tuple[BackgroundModel, Path, Path]:
    """Train one qc-v3 target with date-balanced persistence statistics."""

    training_sweeps = target.split_sweeps("training")
    if not training_sweeps:
        raise ValueError(f"target {target.target_id} has no training sweeps")
    scans = [
        _read_background_scan(sweep, target)
        for sweep in training_sweeps
    ]
    representative_dataset = Counter(
        sweep.dataset for sweep in training_sweeps
    ).most_common(1)[0][0]
    model = build_date_balanced_background_model(
        scans,
        key={
            "radar": target.radar,
            "pulse": target.pulse,
            "quantity": target.quantity,
            "dataset": representative_dataset,
            "dataset_aliases": list(target.dataset_aliases),
            "elevation_deg": round(target.elevation_deg, 3),
            "nrays": target.nrays,
            "nbins": target.nbins,
            "rstart_km": target.rstart_km,
            "rscale_m": target.rscale_m,
            "geometry_id": target.target_id,
            "geometry_class": (
                "vertical" if target.elevation_deg >= 80.0 else "ppi"
            ),
            "season_bucket": "date_balanced",
            "time_of_day_bucket": "date_balanced",
        },
        base_config=base_config or BackgroundModelBuildConfig(),
        date_config=date_config or DateBalancedBackgroundConfig(),
    )
    metadata = dict(model.metadata) | {
        "training_pipeline_schema": TRAINING_PIPELINE_SCHEMA,
        "training_pipeline_schema_version": 2,
        "candidate": "qc-v3",
        "training_contract": training_contract,
        "training_contract_sha256": training_contract_sha256,
        "training_source_ids": [
            sweep.source_id for sweep in training_sweeps
        ],
        "training_source_sha256": [
            sweep.sha256 for sweep in training_sweeps
        ],
        "dataset_aliases": list(target.dataset_aliases),
        "geometry": {
            "geometry_class": (
                "vertical" if target.elevation_deg >= 80.0 else "ppi"
            ),
            "elevation_deg": target.elevation_deg,
            "nrays": target.nrays,
            "nbins": target.nbins,
            "rstart_km": target.rstart_km,
            "rscale_m": target.rscale_m,
        },
        "split_source_counts": {
            split: len(target.split_sweeps(split))
            for split in ("training", "validation", "holdout")
        },
        "companion_coverage": _companion_coverage(training_sweeps),
        "promotion_eligible": False,
        "promotion_blockers": [
            "temporal validation is incomplete",
            "independent blinded labels are incomplete",
            "desktop and iOS parity is incomplete",
        ],
    }
    trained = BackgroundModel(
        key=model.key,
        shape=model.shape,
        arrays=model.arrays,
        metadata=metadata,
        array_hash=hash_arrays(model.arrays),
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    npz_path = output / f"{target.target_id}.npz"
    json_path = output / f"{target.target_id}.json"
    _write_research_model(trained, npz_path, json_path)
    return trained, npz_path, json_path


def target_training_summary(
    target: BackgroundTrainingTarget,
    model: BackgroundModel,
    npz_path: Path,
    json_path: Path,
) -> dict[str, Any]:
    """Summarise coverage and conditioned support without promotion claims."""

    np = require_numpy()
    conditioned_count = np.minimum(
        np.asarray(model.arrays["low_ci_sample_count"], dtype="float32"),
        np.asarray(
            model.arrays["low_ci_vrad_sample_count"],
            dtype="float32",
        ),
    )
    support = conditioned_count >= 12
    return {
        "target_id": target.target_id,
        "radar": target.radar,
        "pulse": target.pulse,
        "quantity": target.quantity,
        "elevation_deg": target.elevation_deg,
        "shape": [target.nrays, target.nbins],
        "rstart_km": target.rstart_km,
        "rscale_m": target.rscale_m,
        "dataset_aliases": list(target.dataset_aliases),
        "training_source_count": len(target.split_sweeps("training")),
        "training_date_count": len(
            {sweep.date for sweep in target.split_sweeps("training")}
        ),
        "validation_source_count": len(target.split_sweeps("validation")),
        "holdout_source_count": len(target.split_sweeps("holdout")),
        "conditioned_support_gate_count": int(support.sum()),
        "conditioned_support_gate_fraction": float(support.mean()),
        "model_npz": str(npz_path),
        "model_json": str(json_path),
        "model_array_hash": model.array_hash,
        "status": "trained_research_artifact",
        "promotion_eligible": False,
    }


def file_sha256(path: str | Path) -> str:
    """Return a deterministic file digest for provenance."""

    digest = sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_background_scan(
    sweep: SweepDescriptor,
    target: BackgroundTrainingTarget,
) -> BackgroundScan:
    data, metadata, companions = read_polar_field_with_companions(
        Path(sweep.local_path),
        sweep.radar,
        sweep.date,
        FieldSelection(
            pulse=sweep.pulse,
            time=sweep.time,
            quantity=sweep.quantity,
            dataset=sweep.dataset,
        ),
    )
    if tuple(data.shape) != target.shape:
        raise ValueError(
            f"{sweep.source_id} {sweep.dataset} changed shape during read"
        )
    if (
        metadata.elevation_deg is None
        or abs(metadata.elevation_deg - target.elevation_deg)
        > DEFAULT_ELEVATION_TOLERANCE_DEG
        or abs(metadata.rstart_km - target.rstart_km) > 1e-6
        or abs(metadata.rscale_m - target.rscale_m) > 1e-3
    ):
        raise ValueError(
            f"{sweep.source_id} {sweep.dataset} does not match target geometry"
        )
    return BackgroundScan(
        values=data,
        metadata=metadata,
        companion_fields=companions,
    )


def _write_research_model(
    model: BackgroundModel,
    npz_path: Path,
    json_path: Path,
) -> None:
    np = require_numpy()
    np.savez_compressed(
        npz_path,
        **{
            name: np.asarray(values, dtype="float32")
            for name, values in sorted(model.arrays.items())
        },
    )
    payload = {
        "schema": BACKGROUND_MODEL_SCHEMA,
        "schema_version": BACKGROUND_MODEL_SCHEMA_VERSION,
        "generated_at": model.metadata.get("generated_at") or _now_utc(),
        "key": dict(model.key),
        "shape": list(model.shape),
        "arrays": {
            name: {
                "dtype": "float32",
                "shape": list(np.asarray(values).shape),
            }
            for name, values in sorted(model.arrays.items())
        },
        "inline_arrays": {},
        "array_hash": model.array_hash or hash_arrays(model.arrays),
        "metadata": dict(model.metadata),
        "npz_path": npz_path.name,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dataset_from_field_group(field_group: str) -> tuple[str, str]:
    parts = field_group.split("/")
    for index, part in enumerate(parts):
        if part.startswith("dataset"):
            return "/".join(parts[: index + 1]), part.lower()
    return "", ""


def _dataset_quantities(dataset_group: Any | None) -> tuple[str, ...]:
    h5py = require_h5py()
    if dataset_group is None:
        return ()
    quantities: set[str] = set()
    for group in dataset_group.values():
        if not isinstance(group, h5py.Group) or "data" not in group:
            continue
        quantity = normalized_quantity(_group_quantity(group))
        if quantity:
            quantities.add(quantity)
    return tuple(sorted(quantities))


def _group_quantity(group: Any) -> str:
    what = group.get("what")
    if what is None or "quantity" not in what.attrs:
        return ""
    return str(scalar(what.attrs["quantity"]) or "").strip()


def _attrs(group: Any | None) -> dict[str, Any]:
    if group is None:
        return {}
    return {
        str(name): scalar(value)
        for name, value in group.attrs.items()
    }


def _required_float(
    attrs: dict[str, Any],
    names: tuple[str, ...],
    *,
    source_id: str,
    dataset: str,
) -> float:
    for name in names:
        value = attrs.get(name)
        if value not in (None, ""):
            return float(value)
    raise ValueError(f"{source_id} {dataset} is missing elevation metadata")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _target_id(
    *,
    radar: str,
    pulse: str,
    quantity: str,
    elevation_deg: float,
    nrays: int,
    nbins: int,
    rstart_km: float,
    rscale_m: float,
) -> str:
    canonical_elevation = _canonical_target_elevation(elevation_deg)
    elevation_mdeg = int(round(canonical_elevation * 1000.0))
    rstart_m = int(round(rstart_km * 1000.0))
    rscale_mm = int(round(rscale_m * 1000.0))
    return (
        f"{radar}_{pulse}_{quantity.lower()}_"
        f"e{elevation_mdeg:05d}_{nrays}x{nbins}_"
        f"r{rstart_m}m_s{rscale_mm}mm"
    )


def _canonical_target_elevation(elevation_deg: float) -> float:
    nominal = (
        round(elevation_deg / NOMINAL_ELEVATION_STEP_DEG)
        * NOMINAL_ELEVATION_STEP_DEG
    )
    if abs(elevation_deg - nominal) <= DEFAULT_ELEVATION_TOLERANCE_DEG:
        return float(nominal)
    return float(elevation_deg)


def _dataset_sort_key(dataset: str) -> tuple[int, str]:
    suffix = dataset.lower().removeprefix("dataset")
    return (
        int(suffix) if suffix.isdigit() else 10_000,
        dataset,
    )


def _companion_coverage(
    sweeps: Iterable[SweepDescriptor],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for sweep in sweeps:
        counts.update(sweep.companion_quantities)
    return dict(sorted(counts.items()))


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
