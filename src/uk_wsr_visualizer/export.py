"""Export job records and lightweight export implementations."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from uk_wsr_qc.qc_v3 import QCMaskResultV3

from .catalog import CatalogItem
from .citations import citation_payload
from .compat import UTC
from .dependencies import require_h5py, require_netcdf4, require_numpy, require_rasterio, require_shapefile
from .geospatial import (
    CartesianField,
    apply_polar_filters,
    field_selection_from_request,
    geographic_point,
    read_cartesian_field,
    read_polar_field_with_companions,
    read_qc_v3_context_companions,
)
from .preview import PreviewRequest, generate_preview
from .quantities import quantity_label

SUPPORTED_FORMATS = {
    "native_hdf5",
    "metadata_json",
    "png",
    "mp4",
    "kmz",
    "field_csv",
    "wct_batch_config",
    "geotiff",
    "cf_netcdf",
    "geojson",
    "shapefile",
    "qc_mask",
}
FIELD_CONTEXT_FORMATS = {"png", "mp4", "kmz", "field_csv", "geotiff", "cf_netcdf", "geojson", "shapefile", "qc_mask"}


@dataclass
class ExportRequest:
    radar: str
    date: str
    format: str
    pulse: str | None = None
    time: str | None = None
    quantity: str | None = None
    dataset: str | None = None
    times: list[str] = field(default_factory=list)
    frame_delay_ms: int = 600
    animation_full_day: bool = True
    animation_start_time: str | None = None
    animation_end_time: str | None = None
    palette: str = "gray"
    bbox: list[float] | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    coordinate_mode: str | None = None


@dataclass
class ExportJob:
    job_id: str
    status: str
    request: ExportRequest
    created_at: str
    updated_at: str
    output_path: str | None = None
    error: str | None = None
    artifact_manifest_path: str | None = None
    download_url: str | None = None


def validate_export_request(request: ExportRequest) -> None:
    if request.format not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported format {request.format!r}; supported: {sorted(SUPPORTED_FORMATS)}")
    if request.format == "mp4":
        missing = [name for name in ("pulse", "quantity") if getattr(request, name) is None]
        if missing:
            raise ValueError(f"mp4 export requires {', '.join(missing)}")
        if request.frame_delay_ms < 50:
            raise ValueError("mp4 export requires frame_delay_ms of at least 50")
        return
    if request.format in FIELD_CONTEXT_FORMATS:
        missing = [name for name in ("pulse", "time", "quantity") if getattr(request, name) is None]
        if missing:
            raise ValueError(f"{request.format} export requires {', '.join(missing)}")


def export_coordinate_mode(request: ExportRequest) -> str:
    """Return the coordinate model represented by an export request."""

    if request.coordinate_mode:
        return request.coordinate_mode
    return {
        "native_hdf5": "source_native",
        "metadata_json": "catalog_metadata",
        "png": "polar_ppi",
        "mp4": "polar_ppi_animation",
        "kmz": "georeferenced_map_overlay",
        "geotiff": "georeferenced_cartesian",
        "cf_netcdf": "georeferenced_cartesian",
        "geojson": "georeferenced_vector",
        "shapefile": "georeferenced_vector",
        "field_csv": "polar_gate_table",
        "qc_mask": "polar_gate_mask",
        "wct_batch_config": "batch_configuration",
    }.get(request.format, "unspecified")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _job_path(export_dir: Path, job_id: str) -> Path:
    return export_dir / job_id / "job.json"


def write_job(export_dir: Path, job: ExportJob) -> None:
    path = _job_path(export_dir, job.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(job), indent=2, sort_keys=True), encoding="utf-8")


def read_job(export_dir: Path, job_id: str) -> ExportJob | None:
    path = _job_path(export_dir, job_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["request"] = ExportRequest(**payload["request"])
    payload.setdefault("artifact_manifest_path", None)
    payload.setdefault("download_url", f"/api/export/{job_id}/download")
    return ExportJob(**payload)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".csv": "text/csv",
        ".geojson": "application/geo+json",
        ".h5": "application/x-hdf5",
        ".hdf5": "application/x-hdf5",
        ".json": "application/json",
        ".kmz": "application/vnd.google-earth.kmz",
        ".mp4": "video/mp4",
        ".nc": "application/x-netcdf",
        ".npz": "application/octet-stream",
        ".png": "image/png",
        ".shp": "application/vnd.shp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".xml": "application/xml",
        ".zip": "application/zip",
    }.get(suffix, "application/octet-stream")


def export_artifact_files(job: ExportJob) -> list[Path]:
    if not job.output_path:
        return []
    output = Path(job.output_path)
    if not output.exists():
        return []
    files = [output]
    if output.suffix.lower() == ".shp":
        for suffix in (".shx", ".dbf", ".prj", ".cpg"):
            sidecar = output.with_suffix(suffix)
            if sidecar.exists():
                files.append(sidecar)
    preview_metadata = output.with_suffix(output.suffix + ".json")
    if preview_metadata.exists():
        files.append(preview_metadata)
    return sorted(set(files))


def _source_payload(item: CatalogItem | None) -> dict[str, object]:
    if item is None:
        return {}
    return {
        "item_id": item.item_id,
        "radar": item.radar,
        "radar_num": item.radar_num,
        "date": item.date,
        "path": item.path,
        "object_key": item.object_key,
        "object_url": item.object_url,
        "source_type": item.source_type,
        "file_size": item.file_size,
        "modified_time": item.modified_time,
    }


def write_artifact_manifest(export_dir: Path, job: ExportJob, item: CatalogItem | None = None) -> Path:
    files = export_artifact_files(job)
    manifest_path = export_dir / job.job_id / "artifact-manifest.json"
    request_payload = asdict(job.request)
    coordinate_mode = export_coordinate_mode(job.request)
    request_payload["coordinate_mode"] = coordinate_mode
    citation = citation_payload()
    payload = {
        "version": 2,
        "job_id": job.job_id,
        "status": job.status,
        "coordinate_mode": coordinate_mode,
        "download_url": f"/api/export/{job.job_id}/download",
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "request": request_payload,
        "selection": {
            "radar": job.request.radar,
            "date": job.request.date,
            "pulse": job.request.pulse,
            "time": job.request.time,
            "quantity": job.request.quantity,
            "quantity_label": quantity_label(job.request.quantity),
            "dataset": job.request.dataset,
            "format": job.request.format,
            "coordinate_mode": coordinate_mode,
            "palette": job.request.palette,
            "filters": job.request.filters,
        },
        "source": _source_payload(item),
        "software": citation["software"],
        "article": citation["article"],
        "source_data": citation["source_data"],
        "infrastructure": citation["infrastructure"],
        "citation_instruction": citation["user_instruction"],
        "artifact_count": len(files),
        "artifacts": [
            {
                "filename": path.name,
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
                "content_type": _content_type(path),
                "coordinate_mode": coordinate_mode,
            }
            for path in files
        ],
    }
    if job.request.format == "mp4":
        sidecar = Path(job.output_path).with_suffix(Path(job.output_path).suffix + ".json") if job.output_path else None
        timing_payload: dict[str, object] = {
            "full_day": job.request.animation_full_day,
            "start_time": job.request.animation_start_time,
            "end_time": job.request.animation_end_time,
            "frame_times": list(job.request.times),
            "frame_count": len(job.request.times),
            "frame_delay_ms": job.request.frame_delay_ms,
            "fps": 1000.0 / float(job.request.frame_delay_ms),
            "expected_duration_seconds": len(job.request.times) * job.request.frame_delay_ms / 1000.0,
            "actual_duration_seconds": len(job.request.times) * job.request.frame_delay_ms / 1000.0,
            "skipped_frames": [],
        }
        if sidecar and sidecar.exists():
            sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
            timing_payload.update(
                {
                    "start_time": sidecar_payload.get("start_time") or timing_payload["start_time"],
                    "end_time": sidecar_payload.get("end_time") or timing_payload["end_time"],
                    "frame_times": sidecar_payload.get("times", timing_payload["frame_times"]),
                    "frame_count": sidecar_payload.get("frame_count", timing_payload["frame_count"]),
                    "fps": sidecar_payload.get("fps", timing_payload["fps"]),
                    "expected_duration_seconds": sidecar_payload.get(
                        "expected_duration_seconds", timing_payload["expected_duration_seconds"]
                    ),
                    "actual_duration_seconds": sidecar_payload.get(
                        "actual_duration_seconds", timing_payload["actual_duration_seconds"]
                    ),
                    "skipped_frames": sidecar_payload.get("skipped_frames", []),
                }
            )
        payload["timing"] = timing_payload
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def export_download_path(export_dir: Path, job: ExportJob) -> Path | None:
    files = export_artifact_files(job)
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    archive = export_dir / job.job_id / f"{job.job_id}_artifacts.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, path.name)
    return archive


def _field_group(source: Path, request: ExportRequest):
    h5py = require_h5py()
    matches: list[object] = []
    prefix = f"{request.pulse}/{request.time}/"
    with h5py.File(source, "r") as h5:
        def visit(name: str, obj: object) -> None:
            if not isinstance(obj, h5py.Group):
                return
            if not name.startswith(prefix) or "/data" not in name:
                return
            if request.dataset and f"/{request.dataset}/" not in f"/{name}/":
                return
            what = obj.get("what")
            quantity = None
            if what is not None and "quantity" in what.attrs:
                raw = what.attrs["quantity"]
                quantity = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if quantity == request.quantity:
                matches.append(obj["data"][()])

        h5.visititems(visit)
    if not matches:
        raise ValueError(
            f"no field found for pulse={request.pulse}, time={request.time}, quantity={request.quantity}"
        )
    return matches[0]


def _write_field_csv(source: Path, request: ExportRequest, output: Path, max_cells: int = 2_000_000) -> None:
    np = require_numpy()
    try:
        data, metadata, companion_fields = read_polar_field_with_companions(
            source, request.radar, request.date, field_selection_from_request(request)
        )
        data = apply_polar_filters(data, metadata, request.filters, companion_fields=companion_fields)
    except Exception:
        data = np.asarray(_field_group(source, request))
    if data.size > max_cells:
        raise ValueError(f"field has {data.size} cells; CSV export limit is {max_cells}")
    with output.open("w", encoding="utf-8") as handle:
        handle.write("row,column,value\n")
        for row_index, row in enumerate(data):
            for column_index, value in enumerate(row):
                handle.write(f"{row_index},{column_index},{float(value)}\n")


def _qc_v3_requested(filters: dict[str, Any] | None) -> bool:
    values = filters or {}
    mode = str(
        values.get("qc_v3_runtime_mode")
        or values.get("qc_mode")
        or ""
    ).strip().lower()
    return mode in {
        "safe",
        "shadow",
        "validated",
        "qc_v3_safe",
        "qc_v3_shadow",
        "qc_v3_validated",
    }


def _time_minutes(value: str) -> int:
    text = str(value)
    if (
        len(text) != 4
        or not text.isdigit()
        or int(text[:2]) > 23
        or int(text[2:]) > 59
    ):
        return 24 * 60
    return int(text[:2]) * 60 + int(text[2:])


def _qc_v3_export_context_sources(
    item: CatalogItem,
    request: ExportRequest,
    source: Path,
    source_for_time: SourceForTime | None,
) -> dict[str, tuple[Path, str]]:
    if (
        not _qc_v3_requested(request.filters)
        or not request.pulse
        or not request.time
    ):
        return {}
    if item.raw_volumes:
        times = {
            record.time
            for record in item.raw_volumes
            if record.pulse == request.pulse
        }
    else:
        times = set(
            item.times_by_pulse.get(request.pulse)
            or item.times
        )
    ordered = sorted(times, key=_time_minutes)
    if request.time not in ordered:
        return {}
    index = ordered.index(request.time)
    candidates = {
        "previous": ordered[index - 1] if index > 0 else None,
        "next": (
            ordered[index + 1]
            if index + 1 < len(ordered)
            else None
        ),
    }
    current_minutes = _time_minutes(request.time)
    resolved: dict[str, tuple[Path, str]] = {}
    for role, candidate_time in candidates.items():
        if (
            candidate_time is None
            or abs(_time_minutes(candidate_time) - current_minutes) > 20
        ):
            continue
        try:
            candidate_source = (
                source_for_time(candidate_time)
                if source_for_time is not None
                else source
            )
        except Exception:
            continue
        resolved[role] = (Path(candidate_source), candidate_time)
    return resolved


def _write_qc_mask(
    source: Path,
    request: ExportRequest,
    output: Path,
    item: CatalogItem,
    *,
    context_sources: dict[str, tuple[Path, str]] | None = None,
) -> None:
    np = require_numpy()
    selection = field_selection_from_request(request)
    data, metadata, companion_fields = read_polar_field_with_companions(
        source,
        request.radar,
        request.date,
        selection,
    )
    if _qc_v3_requested(request.filters):
        previous = (context_sources or {}).get("previous")
        following = (context_sources or {}).get("next")
        companion_fields.update(
            read_qc_v3_context_companions(
                source,
                request.radar,
                request.date,
                selection,
                metadata,
                previous_source=(
                    previous[0] if previous is not None else None
                ),
                previous_time=(
                    previous[1] if previous is not None else None
                ),
                next_source=(
                    following[0] if following is not None else None
                ),
                next_time=(
                    following[1] if following is not None else None
                ),
            )
        )
    result = apply_polar_filters(
        data,
        metadata,
        request.filters,
        return_metadata=True,
        companion_fields=companion_fields,
    )
    if result.qc is None:
        raise ValueError("QC mask was not produced")
    qc = result.qc
    if isinstance(qc, QCMaskResultV3):
        arrays = {
            "mask": np.asarray(qc.removal_mask, dtype="uint16"),
            "removal_mask": np.asarray(qc.removal_mask, dtype="uint8"),
            "proposed_removal_mask": np.asarray(
                qc.proposed_removal_mask,
                dtype="uint8",
            ),
            "abstention_mask": np.asarray(
                qc.abstention_mask,
                dtype="uint8",
            ),
            "reason_flags": np.asarray(qc.reason_flags, dtype="<u2"),
            "applied_reason_flags": np.asarray(
                qc.applied_reason_flags,
                dtype="<u2",
            ),
            "retained_quality_score": np.asarray(
                qc.retained_quality_score,
                dtype="<f4",
            ),
            "feature_availability": np.asarray(
                qc.feature_availability,
                dtype="<u4",
            ),
            "values": np.asarray(result.values, dtype="<f4"),
        }
        arrays.update(
            {
                f"probability_{name}": np.asarray(
                    probability,
                    dtype="<f4",
                )
                for name, probability in qc.nuisance_probabilities.items()
            }
        )
        if qc.domain_mask is not None:
            arrays["domain_mask"] = np.asarray(
                qc.domain_mask,
                dtype="uint8",
            )
        sidecar_version = 3
    else:
        arrays = {
            "mask": np.asarray(qc.mask, dtype="uint16"),
            "values": np.asarray(result.values, dtype="float32"),
        }
        sidecar_version = 1
    np.savez_compressed(output, **arrays)
    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar.write_text(
        json.dumps(
            {
                "version": sidecar_version,
                "format": "qc_mask",
                "source": _source_payload(item),
                "selection": {
                    "radar": request.radar,
                    "date": request.date,
                    "pulse": request.pulse,
                    "time": request.time,
                    "quantity": request.quantity,
                    "dataset": metadata.dataset,
                    "filters": request.filters,
                },
                "metadata": metadata.to_dict(),
                "shape": [int(value) for value in result.values.shape],
                "npz_sha256": _sha256_file(output),
                "qc": qc.to_dict(),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_kmz(source: Path, request: ExportRequest, job_dir: Path, output: Path, item: CatalogItem) -> None:
    preview_path = generate_preview(
        PreviewRequest(
            aggregate_path=source,
            radar=item.radar,
            date=item.date,
            pulse=request.pulse or "",
            time=request.time or "",
            quantity=request.quantity or "",
            dataset=request.dataset,
            palette=request.palette,
            filters=request.filters,
            output_dir=job_dir,
        )
    )
    cartesian = read_cartesian_field(source, item.radar, item.date, field_selection_from_request(request), filters=request.filters)
    west, south, east, north = cartesian.metadata.geographic_bbox()
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{item.radar} {item.date} {request.quantity}</name>
    <description>UK WSR Visualizer georeferenced radar overlay.</description>
    <GroundOverlay>
      <name>{request.quantity}</name>
      <Icon><href>{preview_path.name}</href></Icon>
      <LatLonBox>
        <north>{north}</north>
        <south>{south}</south>
        <east>{east}</east>
        <west>{west}</west>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>
"""
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as kmz:
        kmz.write(preview_path, preview_path.name)
        kmz.writestr("doc.kml", kml)


def _require_imageio():
    try:
        import imageio.v2 as imageio  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional video extra.
        raise RuntimeError(
            "MP4 export requires the video dependencies. Install them with: "
            'pip install -e ".[video]"'
        ) from exc
    return imageio


def _mp4_times(request: ExportRequest, item: CatalogItem) -> list[str]:
    if request.times:
        return sorted({str(time) for time in request.times if str(time).strip()})
    if request.time:
        return [request.time]
    if item.raw_volumes and request.pulse:
        return sorted({volume.time for volume in item.raw_volumes if volume.pulse == request.pulse})
    if request.pulse and item.times_by_pulse.get(request.pulse):
        return sorted({str(time) for time in item.times_by_pulse[request.pulse]})
    return sorted({str(time) for time in item.times})


def _mp4_stem(request: ExportRequest, item: CatalogItem) -> str:
    quantity = (request.quantity or "field").replace("/", "_").replace(" ", "_")
    dataset = (request.dataset or "auto").replace("/", "_").replace(" ", "_")
    return f"{item.radar}_{item.date}_{request.pulse or 'pulse'}_{dataset}_{quantity}_animation"


SourceForTime = Callable[[str], Path]


def _write_mp4(
    source: Path,
    request: ExportRequest,
    job_dir: Path,
    output: Path,
    item: CatalogItem,
    source_for_time: SourceForTime | None = None,
) -> None:
    imageio = _require_imageio()
    np = require_numpy()
    times = _mp4_times(request, item)
    if not times:
        raise ValueError("mp4 export has no available frame times")
    if request.frame_delay_ms < 50:
        raise ValueError("frame_delay_ms must be at least 50")

    frame_dir = job_dir / "mp4-frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    frame_records: list[dict[str, object]] = []
    for index, time in enumerate(times):
        frame_source = source_for_time(time) if source_for_time else source
        volume = item.raw_volume_for(request.pulse or "", time) if item.raw_volumes else None
        preview_request = PreviewRequest(
            aggregate_path=frame_source,
            radar=item.radar,
            date=item.date,
            pulse=request.pulse or "",
            time=time,
            quantity=request.quantity or "",
            dataset=request.dataset,
            palette=request.palette,
            filters=request.filters,
            output_dir=frame_dir,
        )
        frame_path = generate_preview(preview_request)
        frame_paths.append(frame_path)
        frame_records.append(
            {
                "index": index,
                "time": time,
                "filename": frame_path.name,
                "source_path": str(frame_source),
                "object_key": volume.object_key if volume else item.object_key,
                "object_url": volume.object_url if volume else item.object_url,
            }
        )

    fps = max(0.1, 1000.0 / float(request.frame_delay_ms))
    duration_seconds = len(frame_paths) / fps
    with imageio.get_writer(output, fps=fps, codec="libx264", macro_block_size=16) as writer:
        for frame_path in frame_paths:
            frame = imageio.imread(frame_path)
            if getattr(frame, "ndim", 0) == 2:
                frame = np.stack([frame, frame, frame], axis=-1)
            elif getattr(frame, "ndim", 0) == 3 and frame.shape[2] > 3:
                frame = frame[:, :, :3]
            writer.append_data(frame)

    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar.write_text(
        json.dumps(
            {
                "version": 1,
                "format": "mp4",
                "coordinate_mode": export_coordinate_mode(request),
                "radar": item.radar,
                "date": item.date,
                "pulse": request.pulse,
                "quantity": request.quantity,
                "dataset": request.dataset,
                "palette": request.palette,
                "frame_delay_ms": request.frame_delay_ms,
                "fps": fps,
                "frame_count": len(frame_paths),
                "start_time": times[0],
                "end_time": times[-1],
                "expected_duration_seconds": duration_seconds,
                "actual_duration_seconds": duration_seconds,
                "skipped_frames": [],
                "times": times,
                "frames": frame_records,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_geotiff(cartesian: CartesianField, output: Path) -> None:
    rasterio, from_origin = require_rasterio()
    metadata = cartesian.metadata
    transform = from_origin(cartesian.west, cartesian.north, cartesian.pixel_size_m, cartesian.pixel_size_m)
    with rasterio.open(
        output,
        "w",
        driver="GTiff",
        height=cartesian.values.shape[0],
        width=cartesian.values.shape[1],
        count=1,
        dtype="float32",
        crs=metadata.projected_crs_proj4,
        transform=transform,
        nodata=metadata.nodata,
        compress="deflate",
        tiled=True,
    ) as dataset:
        dataset.write(cartesian.values, 1)
        dataset.update_tags(**{k: str(v) for k, v in metadata.to_dict().items() if k != "attrs"})


def _write_cf_netcdf(cartesian: CartesianField, output: Path) -> None:
    netCDF4 = require_netcdf4()
    metadata = cartesian.metadata
    with netCDF4.Dataset(output, "w") as dataset:
        dataset.createDimension("y", len(cartesian.y))
        dataset.createDimension("x", len(cartesian.x))
        x_var = dataset.createVariable("x", "f4", ("x",))
        y_var = dataset.createVariable("y", "f4", ("y",))
        field_var = dataset.createVariable(metadata.quantity, "f4", ("y", "x"), zlib=True, fill_value=metadata.nodata)
        crs_var = dataset.createVariable("radar_azimuthal_equidistant", "i4")

        x_var[:] = cartesian.x
        y_var[:] = cartesian.y
        field_var[:, :] = cartesian.values

        dataset.Conventions = "CF-1.8"
        dataset.title = "UK WSR Cartesian export"
        dataset.source = "UK WSR aggregate ODIM-like HDF5"
        dataset.radar = metadata.radar
        dataset.date = metadata.date
        dataset.time = metadata.time

        x_var.standard_name = "projection_x_coordinate"
        x_var.units = "m"
        y_var.standard_name = "projection_y_coordinate"
        y_var.units = "m"
        field_var.grid_mapping = "radar_azimuthal_equidistant"
        field_var.coordinates = "y x"
        field_var.long_name = metadata.quantity

        crs_var.grid_mapping_name = "azimuthal_equidistant"
        crs_var.latitude_of_projection_origin = metadata.latitude
        crs_var.longitude_of_projection_origin = metadata.longitude
        crs_var.false_easting = 0.0
        crs_var.false_northing = 0.0
        crs_var.semi_major_axis = 6378137.0
        crs_var.inverse_flattening = 298.257223563


def _contour_levels(cartesian: CartesianField, request: ExportRequest) -> list[float]:
    np = require_numpy()
    raw_levels = request.filters.get("levels") if request.filters else None
    if isinstance(raw_levels, list) and raw_levels:
        return sorted(float(level) for level in raw_levels)
    values = cartesian.values
    valid = values[(values != cartesian.metadata.nodata) & np.isfinite(values)]
    if valid.size == 0:
        return []
    return [float(value) for value in np.nanpercentile(valid, [50, 75, 90])]


def _edge_point(p0: tuple[float, float], v0: float, p1: tuple[float, float], v1: float, level: float) -> tuple[float, float]:
    if v1 == v0:
        fraction = 0.5
    else:
        fraction = (level - v0) / (v1 - v0)
    fraction = max(0.0, min(1.0, fraction))
    return (p0[0] + fraction * (p1[0] - p0[0]), p0[1] + fraction * (p1[1] - p0[1]))


def _contour_segments(cartesian: CartesianField, level: float, max_segments: int) -> list[list[list[float]]]:
    np = require_numpy()
    values = cartesian.values
    nodata = cartesian.metadata.nodata
    segments: list[list[list[float]]] = []
    for row in range(values.shape[0] - 1):
        if len(segments) >= max_segments:
            break
        for col in range(values.shape[1] - 1):
            corners = [
                float(values[row, col]),
                float(values[row, col + 1]),
                float(values[row + 1, col + 1]),
                float(values[row + 1, col]),
            ]
            if any(value == nodata or not np.isfinite(value) for value in corners):
                continue
            states = [value >= level for value in corners]
            if all(states) or not any(states):
                continue
            points = [
                (float(cartesian.x[col]), float(cartesian.y[row])),
                (float(cartesian.x[col + 1]), float(cartesian.y[row])),
                (float(cartesian.x[col + 1]), float(cartesian.y[row + 1])),
                (float(cartesian.x[col]), float(cartesian.y[row + 1])),
            ]
            crossings: list[tuple[float, float]] = []
            for start, end in ((0, 1), (1, 2), (2, 3), (3, 0)):
                if states[start] != states[end]:
                    crossings.append(_edge_point(points[start], corners[start], points[end], corners[end], level))
            if len(crossings) == 2:
                line = [geographic_point(cartesian.metadata, *crossings[0]), geographic_point(cartesian.metadata, *crossings[1])]
                segments.append([[line[0][0], line[0][1]], [line[1][0], line[1][1]]])
            elif len(crossings) == 4:
                for first, second in ((0, 1), (2, 3)):
                    line = [
                        geographic_point(cartesian.metadata, *crossings[first]),
                        geographic_point(cartesian.metadata, *crossings[second]),
                    ]
                    segments.append([[line[0][0], line[0][1]], [line[1][0], line[1][1]]])
            if len(segments) >= max_segments:
                break
    return segments


def contour_feature_collection(cartesian: CartesianField, request: ExportRequest) -> dict[str, object]:
    max_segments = int(request.filters.get("max_segments", 50_000)) if request.filters else 50_000
    features: list[dict[str, object]] = []
    for level in _contour_levels(cartesian, request):
        segments = _contour_segments(cartesian, level, max_segments=max_segments)
        if not segments:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "MultiLineString", "coordinates": segments},
                "properties": {
                    "level": level,
                    "quantity": cartesian.metadata.quantity,
                    "radar": cartesian.metadata.radar,
                    "date": cartesian.metadata.date,
                    "time": cartesian.metadata.time,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "bbox": cartesian.metadata.geographic_bbox(),
        "properties": {"uk_wsr:metadata": cartesian.metadata.to_dict()},
        "features": features,
    }


def _write_geojson(cartesian: CartesianField, request: ExportRequest, output: Path) -> None:
    output.write_text(json.dumps(contour_feature_collection(cartesian, request), indent=2, sort_keys=True), encoding="utf-8")


def _write_shapefile(cartesian: CartesianField, request: ExportRequest, output: Path) -> None:
    shapefile = require_shapefile()
    output_base = output.with_suffix("")
    with shapefile.Writer(str(output_base), shapeType=shapefile.POLYLINE) as writer:
        writer.field("level", "F", decimal=3)
        writer.field("quantity", "C", size=16)
        writer.field("radar", "C", size=32)
        writer.field("date", "C", size=8)
        writer.field("time", "C", size=4)
        collection = contour_feature_collection(cartesian, request)
        for feature in collection["features"]:
            properties = feature["properties"]
            for line in feature["geometry"]["coordinates"]:
                writer.line([line])
                writer.record(
                    properties["level"],
                    properties["quantity"],
                    properties["radar"],
                    properties["date"],
                    properties["time"],
                )
    output_base.with_suffix(".prj").write_text('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]', encoding="utf-8")


def _write_wct_batch_config(request: ExportRequest, item: CatalogItem, output: Path) -> None:
    payload = f"""<?xml version="1.0"?>
<ukWsrVisualizerBatchConfig version="1">
  <source radar="{item.radar}" date="{item.date}" path="{item.path}" objectKey="{item.object_key}" />
  <selection pulse="{request.pulse or ''}" time="{request.time or ''}" quantity="{request.quantity or ''}" dataset="{request.dataset or ''}" palette="{request.palette}" />
  <filters>{json.dumps(request.filters, sort_keys=True)}</filters>
  <export format="{request.format}" />
</ukWsrVisualizerBatchConfig>
"""
    output.write_text(payload, encoding="utf-8")


def run_export(
    request: ExportRequest,
    item: CatalogItem,
    export_dir: Path,
    source_for_time: SourceForTime | None = None,
) -> ExportJob:
    validate_export_request(request)
    request.coordinate_mode = export_coordinate_mode(request)
    job_id = uuid.uuid4().hex
    job = ExportJob(job_id=job_id, status="running", request=request, created_at=_now(), updated_at=_now())
    write_job(export_dir, job)
    job_dir = export_dir / job_id

    try:
        source = Path(item.path)
        if source_for_time is not None and request.time:
            source = source_for_time(request.time)
        qc_context_sources = _qc_v3_export_context_sources(
            item,
            request,
            source,
            source_for_time,
        )
        if request.format == "native_hdf5":
            output = job_dir / source.name
            shutil.copy2(source, output)
        elif request.format == "metadata_json":
            output = job_dir / f"{item.radar}_{item.date}_metadata.json"
            output.write_text(json.dumps(asdict(item), indent=2, sort_keys=True), encoding="utf-8")
        elif request.format == "png":
            output = generate_preview(
                PreviewRequest(
                    aggregate_path=source,
                    radar=item.radar,
                    date=item.date,
                    pulse=request.pulse or "",
                    time=request.time or "",
                    quantity=request.quantity or "",
                    dataset=request.dataset,
                    palette=request.palette,
                    filters=request.filters,
                    output_dir=job_dir,
                    qc_previous_source=(
                        qc_context_sources["previous"][0]
                        if "previous" in qc_context_sources
                        else None
                    ),
                    qc_previous_time=(
                        qc_context_sources["previous"][1]
                        if "previous" in qc_context_sources
                        else None
                    ),
                    qc_next_source=(
                        qc_context_sources["next"][0]
                        if "next" in qc_context_sources
                        else None
                    ),
                    qc_next_time=(
                        qc_context_sources["next"][1]
                        if "next" in qc_context_sources
                        else None
                    ),
                )
            )
        elif request.format == "mp4":
            output = job_dir / f"{_mp4_stem(request, item)}.mp4"
            _write_mp4(source, request, job_dir, output, item, source_for_time=source_for_time)
        elif request.format == "kmz":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}.kmz"
            _write_kmz(source, request, job_dir, output, item)
        elif request.format == "field_csv":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}.csv"
            _write_field_csv(source, request, output)
        elif request.format == "qc_mask":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}_qc_mask.npz"
            _write_qc_mask(
                source,
                request,
                output,
                item,
                context_sources=qc_context_sources,
            )
        elif request.format == "geotiff":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}.tif"
            _write_geotiff(
                read_cartesian_field(source, item.radar, item.date, field_selection_from_request(request), filters=request.filters),
                output,
            )
        elif request.format == "cf_netcdf":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}.nc"
            _write_cf_netcdf(
                read_cartesian_field(source, item.radar, item.date, field_selection_from_request(request), filters=request.filters),
                output,
            )
        elif request.format == "geojson":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}_contours.geojson"
            _write_geojson(
                read_cartesian_field(source, item.radar, item.date, field_selection_from_request(request), filters=request.filters),
                request,
                output,
            )
        elif request.format == "shapefile":
            output = job_dir / f"{item.radar}_{item.date}_{request.quantity or 'field'}_contours.shp"
            _write_shapefile(
                read_cartesian_field(source, item.radar, item.date, field_selection_from_request(request), filters=request.filters),
                request,
                output,
            )
        elif request.format == "wct_batch_config":
            output = job_dir / f"{item.radar}_{item.date}_batch_config.xml"
            _write_wct_batch_config(request, item, output)
        else:
            raise ValueError(f"unsupported format: {request.format}")

        job.status = "complete"
        job.output_path = str(output)
        job.download_url = f"/api/export/{job.job_id}/download"
        job.artifact_manifest_path = str(write_artifact_manifest(export_dir, job, item))
        job.updated_at = _now()
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.updated_at = _now()

    write_job(export_dir, job)
    return job
