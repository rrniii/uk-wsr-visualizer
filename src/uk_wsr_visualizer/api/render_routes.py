"""Radar preview, PPI, identify and contour API routes."""

from __future__ import annotations

import json
import time as time_module
from dataclasses import asdict
from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from ..dependencies import require_numpy
from ..export import ExportRequest, contour_feature_collection
from ..geospatial import (
    apply_polar_filters,
    field_selection_from_request,
    read_cartesian_field,
    read_polar_field_with_companions,
)
from ..preview import generate_preview, identify_value, preview_metadata
from .support import (
    QCQueryParameters,
    _elapsed_ms,
    _quantity_display_config,
    _scale_to_uint8_with_limits,
    _timed_step,
)


def register_render_routes(
    app,
    *,
    cached_ppi_response,
    export_source_for_time,
    find_item,
    hydrate_item,
    preview_request,
    radar_filters,
    record_performance_event,
    sampled_gate_edges,
    store_ppi_response,
):
    @app.get("/api/preview/{radar}/{date}/{pulse}/{time}/{quantity}")
    def preview(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        qc_query: QCQueryParameters = Depends(),
        dataset: str | None = None,
        palette: str = "gray",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        output = generate_preview(
            preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    noise_floor_percentile,
                    noise_floor_window_bins,
                    noise_floor_texture_enabled,
                    noise_floor_texture_db,
                    noise_floor_texture_near_margin_db,
                    noise_floor_texture_support_db,
                    noise_floor_texture_max_db,
                    noise_floor_texture_min_similar_neighbors,
                    qc_companion_enabled,
                    qc_static_clutter_enabled,
                    qc_background_model_enabled,
                    qc_background_model_path,
                    qc_background_persistent_frequency_min,
                    qc_background_min_samples,
                    qc_background_static_vrad_frequency_min,
                    qc_background_low_sqi_frequency_min,
                    qc_background_dbzh_excess_max_db,
                    qc_background_evidence_score_threshold,
                    additional_qc=qc_query.filters,
                ),
            )
        )
        return FileResponse(output)

    @app.get("/api/preview-meta/{radar}/{date}/{pulse}/{time}/{quantity}")
    def preview_meta(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        qc_query: QCQueryParameters = Depends(),
        dataset: str | None = None,
        palette: str = "gray",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        return asdict(
            preview_metadata(
                preview_request(
                    item,
                    pulse,
                    time,
                    quantity,
                    dataset,
                    palette,
                    radar_filters(
                        min_range_km,
                        max_range_km,
                        min_azimuth_deg,
                        max_azimuth_deg,
                        min_value,
                        max_value,
                        cappi_height_m,
                        palette_stops,
                        noise_floor_enabled,
                        noise_floor_method,
                        noise_floor_margin_db,
                        noise_floor_operation,
                        qc_mode,
                        noise_floor_percentile,
                        noise_floor_window_bins,
                        noise_floor_texture_enabled,
                        noise_floor_texture_db,
                        noise_floor_texture_near_margin_db,
                        noise_floor_texture_support_db,
                        noise_floor_texture_max_db,
                        noise_floor_texture_min_similar_neighbors,
                        qc_companion_enabled,
                        qc_static_clutter_enabled,
                        qc_background_model_enabled,
                        qc_background_model_path,
                        qc_background_persistent_frequency_min,
                        qc_background_min_samples,
                        qc_background_static_vrad_frequency_min,
                        qc_background_low_sqi_frequency_min,
                        qc_background_dbzh_excess_max_db,
                        qc_background_evidence_score_threshold,
                        additional_qc=qc_query.filters,
                    ),
                )
            )
        )

    @app.get("/api/ppi-image/{radar}/{date}/{pulse}/{time}/{quantity}")
    def ppi_image(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        qc_query: QCQueryParameters = Depends(),
        dataset: str | None = None,
        palette: str = "auto",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
    ):
        steps: list[dict[str, object]] = []
        start = time_module.perf_counter()
        with _timed_step(steps, "find and hydrate item"):
            item = hydrate_item(find_item(radar, date))
        with _timed_step(steps, "resolve raw file and request"):
            request = preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    additional_qc=qc_query.filters,
                ),
            )
        with _timed_step(steps, "render PNG preview"):
            output = generate_preview(request)
        elapsed = _elapsed_ms(start)
        record_performance_event(
            {
                "kind": "operation",
                "operation": "ppi image",
                "radar": radar,
                "date": date,
                "pulse": pulse,
                "time": time,
                "quantity": quantity,
                "dataset": dataset,
                "elapsed_ms": elapsed,
                "source_path": str(request.aggregate_path),
                "output": str(output),
                "steps": steps,
            }
        )
        return FileResponse(
            output,
            media_type="image/png",
            headers={
                "X-UK-WSR-Coordinate-Mode": "polar-ppi",
                "X-UK-WSR-Frame": f"{radar}/{date}/{pulse}/{time}/{quantity}",
                "X-UK-WSR-Operation-Elapsed-Ms": str(elapsed),
            },
        )

    @app.get("/api/ppi/{radar}/{date}/{pulse}/{time}/{quantity}")
    def ppi(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        qc_query: QCQueryParameters = Depends(),
        dataset: str | None = None,
        palette: str = "auto",
        max_rays: int = 360,
        max_bins: int = 320,
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        display_min: float | None = None,
        display_max: float | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        operation_start = time_module.perf_counter()
        steps: list[dict[str, object]] = []
        with _timed_step(steps, "find and hydrate item"):
            item = hydrate_item(find_item(radar, date))
        with _timed_step(steps, "resolve raw file and request"):
            request = preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    noise_floor_percentile,
                    noise_floor_window_bins,
                    noise_floor_texture_enabled,
                    noise_floor_texture_db,
                    noise_floor_texture_near_margin_db,
                    noise_floor_texture_support_db,
                    noise_floor_texture_max_db,
                    noise_floor_texture_min_similar_neighbors,
                    qc_companion_enabled,
                    qc_static_clutter_enabled,
                    qc_background_model_enabled,
                    qc_background_model_path,
                    qc_background_persistent_frequency_min,
                    qc_background_min_samples,
                    qc_background_static_vrad_frequency_min,
                    qc_background_low_sqi_frequency_min,
                    qc_background_dbzh_excess_max_db,
                    qc_background_evidence_score_threshold,
                    additional_qc=qc_query.filters,
                ),
            )
        cache_key = json.dumps(
            {
                "radar": radar,
                "date": date,
                "pulse": pulse,
                "time": time,
                "quantity": quantity,
                "dataset": dataset,
                "palette": palette,
                "max_rays": max_rays,
                "max_bins": max_bins,
                "display_min": display_min,
                "display_max": display_max,
                "filters": request.filters,
            },
            sort_keys=True,
            default=str,
        )
        cached = cached_ppi_response(cache_key)
        if cached is not None:
            elapsed = _elapsed_ms(operation_start)
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "ppi",
                    "radar": radar,
                    "date": date,
                    "pulse": pulse,
                    "time": time,
                    "quantity": quantity,
                    "dataset": dataset,
                    "cache_hit": True,
                    "elapsed_ms": elapsed,
                    "steps": steps,
                }
            )
            payload = dict(cached)
            payload["_performance"] = {
                "elapsed_ms": elapsed,
                "cache_hit": True,
                "steps": steps,
            }
            return payload
        try:
            with _timed_step(steps, "read HDF5 field and companions"):
                data, metadata, companion_fields = read_polar_field_with_companions(
                    request.aggregate_path,
                    request.radar,
                    request.date,
                    field_selection_from_request(request),
                )
            with _timed_step(steps, "apply filters and QC"):
                filter_result = apply_polar_filters(
                    data,
                    metadata,
                    request.filters,
                    return_metadata=True,
                    companion_fields=companion_fields,
                )
                data = filter_result.values
            with _timed_step(steps, "sample and scale field"):
                np = require_numpy()
                max_rays = max(24, min(int(max_rays), 1440))
                max_bins = max(24, min(int(max_bins), 1200))
                row_stride = max(1, int((data.shape[0] + max_rays - 1) // max_rays))
                column_stride = max(1, int((data.shape[1] + max_bins - 1) // max_bins))
                sampled = data[::row_stride, ::column_stride]
                display = _quantity_display_config(quantity, palette)
                resolved_palette = str(display["palette"])
                display_scale_min = (
                    display_min if display_min is not None else display["scale_min"]
                )
                display_scale_max = (
                    display_max if display_max is not None else display["scale_max"]
                )
                scaled, stats = _scale_to_uint8_with_limits(
                    sampled,
                    display_scale_min if isinstance(display_scale_min, float) else None,
                    display_scale_max if isinstance(display_scale_max, float) else None,
                )
                valid = np.isfinite(sampled)
                if display["mask_below_min"] and isinstance(display_scale_min, float):
                    valid &= sampled >= display_scale_min
                rows = int(sampled.shape[0])
                columns = int(sampled.shape[1])
            elapsed = _elapsed_ms(operation_start)
            payload = {
                "metadata": metadata.to_dict(),
                "source_shape": [int(data.shape[0]), int(data.shape[1])],
                "rows": rows,
                "columns": columns,
                "row_stride": row_stride,
                "column_stride": column_stride,
                "gate_edges": sampled_gate_edges(
                    metadata, row_stride, column_stride, rows, columns
                ),
                "scaled": scaled.tolist(),
                "valid": valid.astype("uint8").tolist(),
                "stats": stats,
                "palette": resolved_palette,
                "requested_palette": palette,
                "mask_below_min": bool(display["mask_below_min"]),
                "palette_stops": palette_stops,
                "filters": request.filters or {},
                "noise_floor": filter_result.noise_floor.to_dict(),
                "qc": filter_result.qc.to_dict()
                if filter_result.qc is not None
                else {"enabled": False},
                "_performance": {
                    "elapsed_ms": elapsed,
                    "cache_hit": False,
                    "steps": steps,
                    "source_path": str(request.aggregate_path),
                },
            }
            store_ppi_response(cache_key, payload)
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "ppi",
                    "radar": radar,
                    "date": date,
                    "pulse": pulse,
                    "time": time,
                    "quantity": quantity,
                    "dataset": dataset,
                    "cache_hit": False,
                    "elapsed_ms": elapsed,
                    "source_shape": [int(data.shape[0]), int(data.shape[1])],
                    "sampled_shape": [rows, columns],
                    "source_path": str(request.aggregate_path),
                    "steps": steps,
                }
            )
            return payload
        except Exception as exc:
            record_performance_event(
                {
                    "kind": "operation",
                    "operation": "ppi",
                    "radar": radar,
                    "date": date,
                    "pulse": pulse,
                    "time": time,
                    "quantity": quantity,
                    "dataset": dataset,
                    "cache_hit": False,
                    "elapsed_ms": _elapsed_ms(operation_start),
                    "steps": steps,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc

    @app.get("/api/identify/{radar}/{date}/{pulse}/{time}/{quantity}")
    def identify(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        row: int,
        column: int,
        qc_query: QCQueryParameters = Depends(),
        dataset: str | None = None,
        palette: str = "gray",
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
        palette_stops: str | None = None,
        noise_floor_enabled: bool | None = None,
        noise_floor_method: str | None = None,
        noise_floor_margin_db: float | None = None,
        noise_floor_operation: str | None = None,
        qc_mode: str | None = None,
        noise_floor_percentile: float | None = None,
        noise_floor_window_bins: int | None = None,
        noise_floor_texture_enabled: bool | None = None,
        noise_floor_texture_db: float | None = None,
        noise_floor_texture_near_margin_db: float | None = None,
        noise_floor_texture_support_db: float | None = None,
        noise_floor_texture_max_db: float | None = None,
        noise_floor_texture_min_similar_neighbors: int | None = None,
        qc_companion_enabled: bool | None = None,
        qc_static_clutter_enabled: bool | None = None,
        qc_background_model_enabled: bool | None = None,
        qc_background_model_path: str | None = None,
        qc_background_persistent_frequency_min: float | None = None,
        qc_background_min_samples: int | None = None,
        qc_background_static_vrad_frequency_min: float | None = None,
        qc_background_low_sqi_frequency_min: float | None = None,
        qc_background_dbzh_excess_max_db: float | None = None,
        qc_background_evidence_score_threshold: int | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        return identify_value(
            preview_request(
                item,
                pulse,
                time,
                quantity,
                dataset,
                palette,
                radar_filters(
                    min_range_km,
                    max_range_km,
                    min_azimuth_deg,
                    max_azimuth_deg,
                    min_value,
                    max_value,
                    cappi_height_m,
                    palette_stops,
                    noise_floor_enabled,
                    noise_floor_method,
                    noise_floor_margin_db,
                    noise_floor_operation,
                    qc_mode,
                    noise_floor_percentile,
                    noise_floor_window_bins,
                    noise_floor_texture_enabled,
                    noise_floor_texture_db,
                    noise_floor_texture_near_margin_db,
                    noise_floor_texture_support_db,
                    noise_floor_texture_max_db,
                    noise_floor_texture_min_similar_neighbors,
                    qc_companion_enabled,
                    qc_static_clutter_enabled,
                    qc_background_model_enabled,
                    qc_background_model_path,
                    qc_background_persistent_frequency_min,
                    qc_background_min_samples,
                    qc_background_static_vrad_frequency_min,
                    qc_background_low_sqi_frequency_min,
                    qc_background_dbzh_excess_max_db,
                    qc_background_evidence_score_threshold,
                    additional_qc=qc_query.filters,
                ),
            ),
            row,
            column,
        )

    @app.get("/api/contours/{radar}/{date}/{pulse}/{time}/{quantity}")
    def contours(
        radar: str,
        date: str,
        pulse: str,
        time: str,
        quantity: str,
        dataset: str | None = None,
        levels: str | None = None,
        max_segments: int = 50_000,
        min_range_km: float | None = None,
        max_range_km: float | None = None,
        min_azimuth_deg: float | None = None,
        max_azimuth_deg: float | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        cappi_height_m: float | None = None,
    ):
        item = hydrate_item(find_item(radar, date))
        filters = radar_filters(
            min_range_km,
            max_range_km,
            min_azimuth_deg,
            max_azimuth_deg,
            min_value,
            max_value,
            cappi_height_m,
            None,
        )
        filters["max_segments"] = float(max_segments)
        if levels:
            try:
                filters["levels"] = [
                    float(value.strip()) for value in levels.split(",") if value.strip()
                ]
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="levels must be a comma-separated list of numbers",
                ) from exc
        request = ExportRequest(
            radar=radar,
            date=date,
            format="geojson",
            pulse=pulse,
            time=time,
            quantity=quantity,
            dataset=dataset,
            filters=filters,
        )
        try:
            source_path = export_source_for_time(item, request, time)
            cartesian = read_cartesian_field(
                source_path,
                item.radar,
                item.date,
                field_selection_from_request(request),
                filters=filters,
            )
            return contour_feature_collection(cartesian, request)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"{type(exc).__name__}: {exc}"
            ) from exc
