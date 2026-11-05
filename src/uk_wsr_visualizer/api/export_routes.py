"""Export, animation and local-download API routes."""

from __future__ import annotations

import base64
import binascii
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from ..animation import AnimationRequest, run_animation
from ..export import (
    ExportRequest,
    export_artifact_files,
    export_download_path,
    read_job,
    run_export,
)
from ..math_ops import MathOperand, MathRequest, run_math
from ..tiles import TileRequest, generate_tile_pyramid, tile_manifest
from .support import (
    LOCAL_DOWNLOAD_LIMIT_BYTES,
    _desktop_download_dir,
    _download_payload,
    _export_download_folder_name,
    _safe_download_filename,
    _unique_download_path,
)


def register_export_routes(
    app, *, export_source_for_time, find_item, hydrate_item, settings
):
    @app.post("/api/export")
    def export(request: dict[str, object]):
        try:
            export_request = ExportRequest(**request)
        except TypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = hydrate_item(find_item(export_request.radar, export_request.date))
        source_resolver = (
            (lambda time: export_source_for_time(item, export_request, time))
            if item.source_type == "raw_volume_day"
            else None
        )
        job = run_export(
            export_request, item, settings.export_dir, source_for_time=source_resolver
        )
        return asdict(job)

    @app.post("/api/math")
    def math_product(request: dict[str, object]):
        try:
            left = MathOperand(**request["left"])  # type: ignore[arg-type]
            right = MathOperand(**request["right"])  # type: ignore[arg-type]
            math_request = MathRequest(
                radar=str(request["radar"]),
                date=str(request["date"]),
                operation=str(request["operation"]),
                left=left,
                right=right,
                format=str(request.get("format", "png")),
                filters=request.get("filters", {})
                if isinstance(request.get("filters", {}), dict)
                else {},
                palette=str(request.get("palette", "thermal")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = hydrate_item(find_item(math_request.radar, math_request.date))
        try:
            product = run_math(math_request, item, settings.export_dir / "math")
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        return asdict(product)

    @app.post("/api/animation")
    def animation_product(request: dict[str, object]):
        try:
            times_raw = request.get("times", [])
            times = (
                [str(value) for value in times_raw]
                if isinstance(times_raw, list)
                else []
            )
            animation_request = AnimationRequest(
                radar=str(request["radar"]),
                date=str(request["date"]),
                pulse=str(request["pulse"]),
                quantity=str(request["quantity"]),
                times=times,
                dataset=str(request["dataset"]) if request.get("dataset") else None,
                palette=str(request.get("palette", "gray")),
                filters=request.get("filters", {})
                if isinstance(request.get("filters", {}), dict)
                else {},
                frame_delay_ms=int(request.get("frame_delay_ms", 600)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        item = hydrate_item(find_item(animation_request.radar, animation_request.date))
        try:
            product = run_animation(
                animation_request,
                item,
                settings.export_dir / "animations",
                settings.preview_dir,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
        return asdict(product)

    @app.post("/api/tiles")
    def tile_product(request: dict[str, object]):
        try:
            filters = (
                request.get("filters", {})
                if isinstance(request.get("filters", {}), dict)
                else {}
            )
            item = hydrate_item(find_item(str(request["radar"]), str(request["date"])))
            source_request = ExportRequest(
                radar=str(request["radar"]),
                date=str(request["date"]),
                format="png",
                pulse=str(request["pulse"]),
                time=str(request["time"]),
                quantity=str(request["quantity"]),
                dataset=str(request["dataset"]) if request.get("dataset") else None,
                filters=filters,
            )
            tile_request = TileRequest(
                aggregate_path=export_source_for_time(
                    item, source_request, str(request["time"])
                ),
                radar=str(request["radar"]),
                date=str(request["date"]),
                pulse=str(request["pulse"]),
                time=str(request["time"]),
                quantity=str(request["quantity"]),
                dataset=str(request["dataset"]) if request.get("dataset") else None,
                palette=str(request.get("palette", "gray")),
                filters=filters,
                tile_size=int(request.get("tile_size", 256)),
                min_zoom=int(request.get("min_zoom", 0)),
                max_zoom=int(request.get("max_zoom", 2)),
                output_dir=settings.tile_dir,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return tile_manifest(generate_tile_pyramid(tile_request))
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc

    @app.get("/api/tiles/{tile_path:path}")
    def tile_file(tile_path: str):
        if ".." in Path(tile_path).parts:
            raise HTTPException(status_code=400, detail="invalid tile path")
        path = (settings.tile_dir / tile_path).resolve()
        try:
            path.relative_to(settings.tile_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid tile path") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="tile not found")
        return FileResponse(path)

    @app.get("/api/export/{job_id}")
    def export_status(job_id: str):
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        return asdict(job)

    def completed_export_artifact_path(job_id: str) -> Path:
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        if job.status != "complete":
            raise HTTPException(status_code=400, detail="export job is not complete")
        path = export_download_path(settings.export_dir, job)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="export artifact not found")
        try:
            path.resolve().relative_to(settings.export_dir.resolve())
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="invalid export artifact path"
            ) from exc
        return path

    @app.get("/api/export/{job_id}/download")
    def export_download(job_id: str):
        path = completed_export_artifact_path(job_id)
        return FileResponse(path, filename=path.name)

    @app.post("/api/export/{job_id}/save-to-downloads")
    def export_save_to_downloads(job_id: str):
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        if job.status != "complete":
            raise HTTPException(status_code=400, detail="export job is not complete")
        files = export_artifact_files(job)
        if not files:
            raise HTTPException(status_code=404, detail="export artifact not found")
        for path in files:
            if not path.exists() or not path.is_file():
                raise HTTPException(
                    status_code=404, detail=f"export artifact not found: {path.name}"
                )
            try:
                path.resolve().relative_to(settings.export_dir.resolve())
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail="invalid export artifact path"
                ) from exc

        target_dir = _desktop_download_dir()
        if len(files) == 1:
            source = files[0]
            target = _unique_download_path(target_dir, source.name)
            try:
                shutil.copy2(source, target)
            except OSError as exc:
                raise HTTPException(
                    status_code=500, detail=f"could not save export to Downloads: {exc}"
                ) from exc
            payload = _download_payload(target, source.name)
            payload["artifact_count"] = 1
            payload["artifacts"] = [
                {
                    "filename": target.name,
                    "path": str(target),
                    "bytes": target.stat().st_size,
                }
            ]
            return payload

        target = _unique_download_path(
            target_dir, _export_download_folder_name(job_id, job.request)
        )
        try:
            target.mkdir(parents=True)
            copied: list[dict[str, object]] = []
            for source in files:
                destination = target / _safe_download_filename(source.name)
                shutil.copy2(source, destination)
                copied.append(
                    {
                        "filename": destination.name,
                        "path": str(destination),
                        "bytes": destination.stat().st_size,
                    }
                )
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"could not save export folder to Downloads: {exc}",
            ) from exc
        payload = _download_payload(target, target.name)
        payload["artifact_count"] = len(copied)
        payload["artifacts"] = copied
        return payload

    @app.post("/api/local-download")
    def save_local_download(request: dict[str, object]):
        filename = _safe_download_filename(request.get("filename"))
        encoded = request.get("content_base64")
        if not isinstance(encoded, str) or not encoded:
            raise HTTPException(status_code=400, detail="content_base64 is required")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="content_base64 is not valid base64"
            ) from exc
        if len(data) > LOCAL_DOWNLOAD_LIMIT_BYTES:
            raise HTTPException(status_code=413, detail="download payload is too large")
        target_dir = _desktop_download_dir()
        target = _unique_download_path(target_dir, filename)
        try:
            target.write_bytes(data)
        except OSError as exc:
            raise HTTPException(
                status_code=500, detail=f"could not save file to Downloads: {exc}"
            ) from exc
        return _download_payload(target, filename)

    @app.get("/api/export/{job_id}/manifest")
    def export_manifest(job_id: str):
        job = read_job(settings.export_dir, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="export job not found")
        if job.status != "complete" or not job.artifact_manifest_path:
            raise HTTPException(
                status_code=400, detail="export manifest is not available"
            )
        path = Path(job.artifact_manifest_path).resolve()
        try:
            path.relative_to(settings.export_dir.resolve())
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="invalid export manifest path"
            ) from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="export manifest not found")
        return json.loads(path.read_text(encoding="utf-8"))
