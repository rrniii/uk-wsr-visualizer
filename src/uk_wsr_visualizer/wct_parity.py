"""WCT 4.9.1 parity validation harness."""

from __future__ import annotations

import hashlib
import json
import math
import shlex
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .catalog import CatalogItem
from .compat import UTC
from .export import ExportRequest, run_export

DEFAULT_WCT_APP = Path("/Applications/WCT-4.9.1.app")

WCT_FORMAT_BY_VISUALIZER = {
    "geotiff": "geotiff",
    "kmz": "kmz",
    "shapefile": "shp",
    "cf_netcdf": "netcdf",
}


@dataclass(frozen=True)
class WctParityCase:
    case_id: str
    item: CatalogItem
    request: ExportRequest
    wct_input_path: str | None = None


@dataclass
class WctParityResult:
    case_id: str
    visualizer_status: str
    visualizer_output: str | None
    visualizer_sha256: str | None
    visualizer_size: int | None
    wct_command: list[str]
    wct_config: str
    wct_status: str
    wct_output: str | None = None
    wct_sha256: str | None = None
    wct_size: int | None = None
    comparable: bool = False
    parity_status: str = "not_comparable"
    comparison: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class WctParityReport:
    created_at: str
    wct_app: str
    execute_wct: bool
    require_comparison: bool
    max_mean_abs_error: float
    max_rmse: float
    output_dir: str
    results: list[WctParityResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def ok(self) -> bool:
        base_ok = all(result.visualizer_status == "complete" and result.wct_status in {"skipped", "complete"} for result in self.results)
        if not base_ok:
            return False
        if self.require_comparison:
            return all(result.parity_status == "passed" for result in self.results)
        return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wct_export_script(wct_app: Path = DEFAULT_WCT_APP) -> Path:
    return wct_app / "Contents" / "Resources" / "wct-export.sh"


def wct_installed(wct_app: Path = DEFAULT_WCT_APP) -> bool:
    return wct_export_script(wct_app).exists()


def _wct_variable(request: ExportRequest) -> str:
    quantity = (request.quantity or "").upper()
    if quantity.startswith("VRAD") or "VEL" in quantity:
        return "RadialVelocity"
    if quantity.startswith("WRAD") or "WIDTH" in quantity:
        return "SpectrumWidth"
    return "Reflectivity"


def write_wct_batch_config(case: WctParityCase, output: Path) -> None:
    request = case.request
    filters = request.filters or {}
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = f"""<?xml version="1.0"?>
<wctExportBatchOptions version="3">
  <logging>WARNING</logging>
  <useCache>FALSE</useCache>
  <radar>
    <radialOptions>
      <variable>{_wct_variable(request)}</variable>
      <sweep>{filters.get("sweep", 0)}</sweep>
      <classify>false</classify>
      <useRFvalues>true</useRFvalues>
      <exportPoints>false</exportPoints>
      <exportAllPoints>false</exportAllPoints>
      <exportCAPPI constantAltitudesInMeters="{filters.get("cappi_height_m", 4000)}" interpolationType="INVERSE_HEIGHT_DIFFERENCE_WEIGHTED_SQUARED">false</exportCAPPI>
    </radialOptions>
    <radialFilter>
      <minRange>{filters.get("min_range_km", "NONE")}</minRange>
      <maxRange>{filters.get("max_range_km", "NONE")}</maxRange>
      <minAzimuth>{filters.get("min_azimuth_deg", "NONE")}</minAzimuth>
      <maxAzimuth>{filters.get("max_azimuth_deg", "NONE")}</maxAzimuth>
      <minValue>{filters.get("min_value", "NONE")}</minValue>
      <maxValue>{filters.get("max_value", "NONE")}</maxValue>
      <minLat>NONE</minLat>
      <maxLat>NONE</maxLat>
      <minLon>NONE</minLon>
      <maxLon>NONE</maxLon>
      <minHeight>NONE</minHeight>
      <maxHeight>NONE</maxHeight>
    </radialFilter>
  </radar>
</wctExportBatchOptions>
"""
    output.write_text(payload, encoding="utf-8")


def wct_output_path(case: WctParityCase, output_dir: Path) -> Path:
    suffix = {
        "geotiff": ".tif",
        "kmz": ".kmz",
        "shapefile": ".shp",
        "cf_netcdf": ".nc",
    }.get(case.request.format, f".{case.request.format}")
    return output_dir / case.case_id / f"wct_{case.case_id}{suffix}"


def wct_command(case: WctParityCase, config_path: Path, output_path: Path, wct_app: Path = DEFAULT_WCT_APP) -> list[str]:
    if case.request.format not in WCT_FORMAT_BY_VISUALIZER:
        raise ValueError(f"WCT parity is not configured for UK WSR Visualizer format {case.request.format!r}")
    input_path = case.wct_input_path or case.item.path
    return [
        str(wct_export_script(wct_app)),
        input_path,
        str(output_path),
        WCT_FORMAT_BY_VISUALIZER[case.request.format],
        str(config_path),
    ]


def _file_record(path: Path) -> tuple[str | None, int | None]:
    if not path.exists():
        return None, None
    return sha256_file(path), path.stat().st_size


def _close_enough(left: float | None, right: float | None, tolerance: float = 1.0e-6) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def _seq_close_enough(left: list[float] | tuple[float, ...], right: list[float] | tuple[float, ...], tolerance: float = 1.0e-6) -> bool:
    return len(left) == len(right) and all(_close_enough(a, b, tolerance) for a, b in zip(left, right, strict=False))


def _array_stats(values: Any, nodata: float | None = None) -> dict[str, Any]:
    import numpy as np  # type: ignore

    array = np.asarray(values, dtype="float64")
    mask = np.isfinite(array)
    if nodata is not None:
        mask &= array != float(nodata)
    valid = array[mask]
    if valid.size == 0:
        return {"valid_count": 0}
    return {
        "valid_count": int(valid.size),
        "min": float(np.nanmin(valid)),
        "max": float(np.nanmax(valid)),
        "mean": float(np.nanmean(valid)),
        "std": float(np.nanstd(valid)),
    }


def _array_difference(left: Any, right: Any, left_nodata: float | None = None, right_nodata: float | None = None) -> dict[str, Any]:
    import numpy as np  # type: ignore

    left_array = np.asarray(left, dtype="float64")
    right_array = np.asarray(right, dtype="float64")
    if left_array.shape != right_array.shape:
        return {"shape_match": False, "left_shape": list(left_array.shape), "right_shape": list(right_array.shape)}
    mask = np.isfinite(left_array) & np.isfinite(right_array)
    if left_nodata is not None:
        mask &= left_array != float(left_nodata)
    if right_nodata is not None:
        mask &= right_array != float(right_nodata)
    if not mask.any():
        return {"shape_match": True, "valid_count": 0}
    diff = left_array[mask] - right_array[mask]
    abs_diff = np.abs(diff)
    return {
        "shape_match": True,
        "valid_count": int(diff.size),
        "mean_error": float(np.nanmean(diff)),
        "mean_abs_error": float(np.nanmean(abs_diff)),
        "max_abs_error": float(np.nanmax(abs_diff)),
        "rmse": float(np.sqrt(np.nanmean(diff * diff))),
    }


def _compare_geotiff(visualizer_path: Path, wct_path: Path) -> dict[str, Any]:
    import rasterio  # type: ignore

    with rasterio.open(visualizer_path) as visualizer, rasterio.open(wct_path) as wct:
        visualizer_values = visualizer.read(1)
        wct_values = wct.read(1)
        visualizer_bounds = list(visualizer.bounds)
        wct_bounds = list(wct.bounds)
        return {
            "driver": "geotiff",
            "shape_match": visualizer_values.shape == wct_values.shape,
            "visualizer_shape": list(visualizer_values.shape),
            "wct_shape": list(wct_values.shape),
            "crs_match": str(visualizer.crs) == str(wct.crs),
            "visualizer_crs": str(visualizer.crs),
            "wct_crs": str(wct.crs),
            "bounds_match": _seq_close_enough(visualizer_bounds, wct_bounds, tolerance=1.0e-3),
            "visualizer_bounds": visualizer_bounds,
            "wct_bounds": wct_bounds,
            "transform_match": _seq_close_enough(tuple(visualizer.transform)[:6], tuple(wct.transform)[:6], tolerance=1.0e-6),
            "nodata_match": _close_enough(visualizer.nodata, wct.nodata),
            "visualizer_stats": _array_stats(visualizer_values, visualizer.nodata),
            "wct_stats": _array_stats(wct_values, wct.nodata),
            "array_difference": _array_difference(visualizer_values, wct_values, visualizer.nodata, wct.nodata),
        }


def _first_2d_numeric_variable(dataset: Any) -> str | None:
    for name, variable in dataset.variables.items():
        if len(getattr(variable, "dimensions", ())) == 2 and getattr(variable, "dtype", None).kind in {"f", "i", "u"}:
            return str(name)
    return None


def _compare_cf_netcdf(visualizer_path: Path, wct_path: Path) -> dict[str, Any]:
    import netCDF4  # type: ignore

    with netCDF4.Dataset(visualizer_path) as visualizer, netCDF4.Dataset(wct_path) as wct:
        visualizer_var_name = _first_2d_numeric_variable(visualizer)
        wct_var_name = _first_2d_numeric_variable(wct)
        payload: dict[str, Any] = {
            "driver": "cf_netcdf",
            "visualizer_dimensions": {name: len(dim) for name, dim in visualizer.dimensions.items()},
            "wct_dimensions": {name: len(dim) for name, dim in wct.dimensions.items()},
            "dimensions_match": {name: len(dim) for name, dim in visualizer.dimensions.items()}
            == {name: len(dim) for name, dim in wct.dimensions.items()},
            "visualizer_variable": visualizer_var_name,
            "wct_variable": wct_var_name,
        }
        if visualizer_var_name and wct_var_name:
            visualizer_var = visualizer.variables[visualizer_var_name]
            wct_var = wct.variables[wct_var_name]
            visualizer_values = visualizer_var[:]
            wct_values = wct_var[:]
            visualizer_nodata = getattr(visualizer_var, "_FillValue", None)
            wct_nodata = getattr(wct_var, "_FillValue", None)
            payload.update(
                {
                    "variable_shape_match": visualizer_values.shape == wct_values.shape,
                    "visualizer_stats": _array_stats(visualizer_values, visualizer_nodata),
                    "wct_stats": _array_stats(wct_values, wct_nodata),
                    "array_difference": _array_difference(visualizer_values, wct_values, visualizer_nodata, wct_nodata),
                }
            )
        return payload


def _compare_shapefile(visualizer_path: Path, wct_path: Path) -> dict[str, Any]:
    import shapefile  # type: ignore

    with shapefile.Reader(str(visualizer_path)) as visualizer, shapefile.Reader(str(wct_path)) as wct:
        visualizer_fields = [field[0] for field in visualizer.fields[1:]]
        wct_fields = [field[0] for field in wct.fields[1:]]
        return {
            "driver": "shapefile",
            "shape_count_match": len(visualizer.shapes()) == len(wct.shapes()),
            "visualizer_shape_count": len(visualizer.shapes()),
            "wct_shape_count": len(wct.shapes()),
            "record_count_match": len(visualizer.records()) == len(wct.records()),
            "visualizer_record_count": len(visualizer.records()),
            "wct_record_count": len(wct.records()),
            "fields_match": visualizer_fields == wct_fields,
            "visualizer_fields": visualizer_fields,
            "wct_fields": wct_fields,
            "bbox_match": _seq_close_enough(list(visualizer.bbox), list(wct.bbox), tolerance=1.0e-5),
            "visualizer_bbox": list(visualizer.bbox),
            "wct_bbox": list(wct.bbox),
        }


def _latlon_box_from_kmz(path: Path) -> dict[str, float] | None:
    with zipfile.ZipFile(path) as kmz:
        kml_name = next((name for name in kmz.namelist() if name.lower().endswith(".kml")), None)
        if not kml_name:
            return None
        root = ElementTree.fromstring(kmz.read(kml_name))
    namespace = {"kml": "http://www.opengis.net/kml/2.2"}
    box = root.find(".//kml:LatLonBox", namespace)
    if box is None:
        box = root.find(".//LatLonBox")
    if box is None:
        return None

    def value(name: str) -> float:
        node = box.find(f"kml:{name}", namespace)
        if node is None:
            node = box.find(name)
        if node is None or node.text is None:
            raise ValueError(f"KMZ LatLonBox missing {name}")
        return float(node.text)

    return {name: value(name) for name in ("north", "south", "east", "west")}


def _compare_kmz(visualizer_path: Path, wct_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(visualizer_path) as visualizer_zip, zipfile.ZipFile(wct_path) as wct_zip:
        visualizer_entries = sorted(visualizer_zip.namelist())
        wct_entries = sorted(wct_zip.namelist())
    visualizer_box = _latlon_box_from_kmz(visualizer_path)
    wct_box = _latlon_box_from_kmz(wct_path)
    box_match = visualizer_box is not None and wct_box is not None and all(
        _close_enough(visualizer_box[name], wct_box[name], tolerance=1.0e-5) for name in ("north", "south", "east", "west")
    )
    return {
        "driver": "kmz",
        "visualizer_entries": visualizer_entries,
        "wct_entries": wct_entries,
        "visualizer_latlon_box": visualizer_box,
        "wct_latlon_box": wct_box,
        "latlon_box_match": box_match,
    }


def compare_outputs(visualizer_path: Path, wct_path: Path, export_format: str) -> dict[str, Any]:
    visualizer_sha, visualizer_size = _file_record(visualizer_path)
    wct_sha, wct_size = _file_record(wct_path)
    comparison: dict[str, Any] = {
        "format": export_format,
        "visualizer_path": str(visualizer_path),
        "wct_path": str(wct_path),
        "visualizer_size": visualizer_size,
        "wct_size": wct_size,
        "size_difference_bytes": None if visualizer_size is None or wct_size is None else visualizer_size - wct_size,
        "same_sha256": bool(visualizer_sha and wct_sha and visualizer_sha == wct_sha),
    }
    try:
        if export_format == "geotiff":
            comparison.update(_compare_geotiff(visualizer_path, wct_path))
        elif export_format == "cf_netcdf":
            comparison.update(_compare_cf_netcdf(visualizer_path, wct_path))
        elif export_format == "shapefile":
            comparison.update(_compare_shapefile(visualizer_path, wct_path))
        elif export_format == "kmz":
            comparison.update(_compare_kmz(visualizer_path, wct_path))
        else:
            comparison["driver"] = "bytewise"
    except Exception as exc:
        comparison.setdefault("errors", []).append(f"{type(exc).__name__}: {exc}")
    return comparison


def evaluate_comparison(comparison: dict[str, Any], max_mean_abs_error: float = 0.0, max_rmse: float = 0.0) -> str:
    if not comparison:
        return "not_comparable"
    if comparison.get("errors"):
        return "failed"
    if comparison.get("same_sha256"):
        return "passed"
    for key in (
        "shape_match",
        "crs_match",
        "bounds_match",
        "transform_match",
        "dimensions_match",
        "variable_shape_match",
        "shape_count_match",
        "record_count_match",
        "bbox_match",
        "latlon_box_match",
    ):
        if key in comparison and not comparison[key]:
            return "failed"
    diff = comparison.get("array_difference")
    if isinstance(diff, dict):
        if diff.get("shape_match") is False:
            return "failed"
        if "mean_abs_error" in diff and float(diff["mean_abs_error"]) > max_mean_abs_error:
            return "failed"
        if "rmse" in diff and float(diff["rmse"]) > max_rmse:
            return "failed"
        if "mean_abs_error" in diff or "rmse" in diff:
            return "passed"
    return "warning"


def _run_wct(command: list[str], cwd: Path, timeout_s: int) -> tuple[str, list[str]]:
    try:
        completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout_s, check=False)
    except Exception as exc:
        return "failed", [f"{type(exc).__name__}: {exc}"]
    notes = []
    if completed.stdout.strip():
        notes.append(completed.stdout.strip()[-2000:])
    if completed.stderr.strip():
        notes.append(completed.stderr.strip()[-2000:])
    return ("complete" if completed.returncode == 0 else "failed"), notes


def run_parity_case(
    case: WctParityCase,
    output_dir: Path,
    wct_app: Path = DEFAULT_WCT_APP,
    execute_wct: bool = False,
    timeout_s: int = 1800,
    max_mean_abs_error: float = 0.0,
    max_rmse: float = 0.0,
) -> WctParityResult:
    case_dir = output_dir / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    config_path = case_dir / "wctBatchConfig.xml"
    write_wct_batch_config(case, config_path)
    wct_output = wct_output_path(case, output_dir)
    notes: list[str] = []
    try:
        command = wct_command(case, config_path, wct_output, wct_app)
    except ValueError as exc:
        command = []
        notes.append(str(exc))

    visualizer_job = run_export(case.request, case.item, case_dir / "visualizer")
    visualizer_output = Path(visualizer_job.output_path) if visualizer_job.output_path else None
    visualizer_sha, visualizer_size = _file_record(visualizer_output) if visualizer_output else (None, None)

    if not command:
        wct_status = "skipped"
    elif not wct_installed(wct_app):
        wct_status = "skipped"
        notes.append(f"WCT app not found at {wct_app}")
    elif not execute_wct:
        wct_status = "skipped"
        notes.append("WCT execution skipped; rerun with --execute-wct to produce reference output")
    else:
        wct_status, wct_notes = _run_wct(command, case_dir, timeout_s)
        notes.extend(wct_notes)

    wct_sha, wct_size = _file_record(wct_output)
    comparable = bool(visualizer_output and visualizer_output.exists() and wct_output.exists())
    if comparable and visualizer_size != wct_size:
        notes.append(f"output sizes differ: UK WSR Visualizer={visualizer_size}, WCT={wct_size}")
    comparison: dict[str, Any] = {}
    parity_status = "not_comparable"
    if comparable and visualizer_output is not None:
        comparison = compare_outputs(visualizer_output, wct_output, case.request.format)
        parity_status = evaluate_comparison(comparison, max_mean_abs_error=max_mean_abs_error, max_rmse=max_rmse)
        notes.append(f"comparison parity_status={parity_status}")
    return WctParityResult(
        case_id=case.case_id,
        visualizer_status=visualizer_job.status,
        visualizer_output=str(visualizer_output) if visualizer_output else None,
        visualizer_sha256=visualizer_sha,
        visualizer_size=visualizer_size,
        wct_command=command,
        wct_config=str(config_path),
        wct_status=wct_status,
        wct_output=str(wct_output),
        wct_sha256=wct_sha,
        wct_size=wct_size,
        comparable=comparable,
        parity_status=parity_status,
        comparison=comparison,
        notes=notes,
    )


def run_parity_report(
    cases: list[WctParityCase],
    output_dir: Path,
    wct_app: Path = DEFAULT_WCT_APP,
    execute_wct: bool = False,
    timeout_s: int = 1800,
    require_comparison: bool = False,
    max_mean_abs_error: float = 0.0,
    max_rmse: float = 0.0,
) -> WctParityReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [
        run_parity_case(
            case,
            output_dir,
            wct_app,
            execute_wct,
            timeout_s,
            max_mean_abs_error=max_mean_abs_error,
            max_rmse=max_rmse,
        )
        for case in cases
    ]
    return WctParityReport(
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        wct_app=str(wct_app),
        execute_wct=execute_wct,
        require_comparison=require_comparison,
        max_mean_abs_error=max_mean_abs_error,
        max_rmse=max_rmse,
        output_dir=str(output_dir),
        results=results,
    )


def write_report(path: Path, report: WctParityReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def shell_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)
