"""Radar field math operations for derived UK WSR products."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .catalog import CatalogItem
from .compat import UTC
from .dependencies import require_numpy, require_pillow
from .export_types import FieldSelection
from .geospatial import RadarGridMetadata, apply_polar_filters, read_polar_field
from .preview import _scale_to_uint8, apply_palette

SUPPORTED_MATH_OPERATIONS = {"difference", "sum", "product", "ratio", "mean", "min", "max"}
SUPPORTED_MATH_FORMATS = {"metadata_json", "field_csv", "png", "npy"}


@dataclass(frozen=True)
class MathOperand:
    pulse: str
    time: str
    quantity: str
    dataset: str | None = None


@dataclass(frozen=True)
class MathRequest:
    radar: str
    date: str
    operation: str
    left: MathOperand
    right: MathOperand
    format: str = "png"
    filters: dict[str, Any] = field(default_factory=dict)
    palette: str = "thermal"


@dataclass(frozen=True)
class MathProduct:
    request: MathRequest
    metadata: RadarGridMetadata
    shape: list[int]
    valid_min: float | None
    valid_max: float | None
    output_path: str
    created_at: str


def validate_math_request(request: MathRequest) -> None:
    if request.operation not in SUPPORTED_MATH_OPERATIONS:
        raise ValueError(f"unsupported math operation {request.operation!r}; supported: {sorted(SUPPORTED_MATH_OPERATIONS)}")
    if request.format not in SUPPORTED_MATH_FORMATS:
        raise ValueError(f"unsupported math format {request.format!r}; supported: {sorted(SUPPORTED_MATH_FORMATS)}")


def compute_math_array(left: Any, right: Any, operation: str) -> Any:
    np = require_numpy()
    left_array = np.asarray(left, dtype="float32")
    right_array = np.asarray(right, dtype="float32")
    if left_array.shape != right_array.shape:
        raise ValueError(f"math operands have different shapes: {left_array.shape} vs {right_array.shape}")
    if operation == "difference":
        result = left_array - right_array
    elif operation == "sum":
        result = left_array + right_array
    elif operation == "product":
        result = left_array * right_array
    elif operation == "ratio":
        with np.errstate(divide="ignore", invalid="ignore"):
            result = left_array / right_array
    elif operation == "mean":
        result = (left_array + right_array) / 2.0
    elif operation == "min":
        result = np.fmin(left_array, right_array)
    elif operation == "max":
        result = np.fmax(left_array, right_array)
    else:
        raise ValueError(f"unsupported math operation: {operation}")
    return np.where(np.isfinite(result), result, np.nan).astype("float32")


def _read_operand(source: Path, radar: str, date: str, operand: MathOperand, filters: dict[str, Any]):
    data, metadata = read_polar_field(
        source,
        radar,
        date,
        FieldSelection(
            pulse=operand.pulse,
            time=operand.time,
            quantity=operand.quantity,
            dataset=operand.dataset,
            cappi_height_m=_filter_float(filters, "cappi_height_m"),
        ),
    )
    return apply_polar_filters(data, metadata, filters), metadata


def _filter_float(filters: dict[str, Any], key: str) -> float | None:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def compute_math_product_array(source: Path, request: MathRequest) -> tuple[Any, RadarGridMetadata]:
    validate_math_request(request)
    left, metadata = _read_operand(source, request.radar, request.date, request.left, request.filters)
    right, _right_metadata = _read_operand(source, request.radar, request.date, request.right, request.filters)
    return compute_math_array(left, right, request.operation), metadata


def _safe_part(value: str | None) -> str:
    return (value or "auto").replace("/", "_").replace(" ", "_")


def math_output_stem(request: MathRequest) -> str:
    return (
        f"{request.radar}_{request.date}_{request.operation}_"
        f"{_safe_part(request.left.pulse)}-{_safe_part(request.left.time)}-{_safe_part(request.left.quantity)}_"
        f"{_safe_part(request.right.pulse)}-{_safe_part(request.right.time)}-{_safe_part(request.right.quantity)}"
    )


def _valid_stats(array: Any) -> tuple[float | None, float | None]:
    np = require_numpy()
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return None, None
    return float(np.nanmin(valid)), float(np.nanmax(valid))


def _write_png(array: Any, path: Path, palette: str, palette_stops: str | None = None) -> None:
    Image = require_pillow()
    scaled, _stats = _scale_to_uint8(array)
    Image.fromarray(apply_palette(scaled, palette, palette_stops)).save(path)


def _write_csv(array: Any, path: Path, max_cells: int = 2_000_000) -> None:
    np = require_numpy()
    if array.size > max_cells:
        raise ValueError(f"math product has {array.size} cells; CSV limit is {max_cells}")
    with path.open("w", encoding="utf-8") as handle:
        handle.write("row,column,value\n")
        for row_index, row in enumerate(np.asarray(array)):
            for column_index, value in enumerate(row):
                handle.write(f"{row_index},{column_index},{float(value)}\n")


def run_math(request: MathRequest, item: CatalogItem, output_dir: Path) -> MathProduct:
    validate_math_request(request)
    np = require_numpy()
    output_dir.mkdir(parents=True, exist_ok=True)
    array, metadata = compute_math_product_array(Path(item.path), request)
    stem = math_output_stem(request)
    if request.format == "png":
        output = output_dir / f"{stem}.png"
        _write_png(array, output, request.palette, request.filters.get("palette_stops"))
    elif request.format == "field_csv":
        output = output_dir / f"{stem}.csv"
        _write_csv(array, output)
    elif request.format == "npy":
        output = output_dir / f"{stem}.npy"
        np.save(output, array)
    elif request.format == "metadata_json":
        output = output_dir / f"{stem}_metadata.json"
    else:
        raise ValueError(f"unsupported math format: {request.format}")

    valid_min, valid_max = _valid_stats(array)
    product = MathProduct(
        request=request,
        metadata=metadata,
        shape=list(array.shape),
        valid_min=valid_min,
        valid_max=valid_max,
        output_path=str(output),
        created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    if request.format == "metadata_json":
        output.write_text(json.dumps(asdict(product), indent=2, sort_keys=True), encoding="utf-8")
    else:
        metadata_path = output.with_suffix(output.suffix + ".json")
        metadata_path.write_text(json.dumps(asdict(product), indent=2, sort_keys=True), encoding="utf-8")
    return product
