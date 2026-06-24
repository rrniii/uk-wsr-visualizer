"""PNG preview generation for aggregate HDF5 fields."""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .dependencies import require_h5py, require_numpy, require_pillow
from .export_types import FieldSelection
from .geospatial import apply_polar_filters, dataset_nominal_height_m, radar_bin_location, read_polar_field

PALETTES = {"gray", "radar", "thermal", "velocity", "custom"}


@dataclass(frozen=True)
class PreviewRequest:
    aggregate_path: Path
    radar: str
    date: str
    pulse: str
    time: str
    quantity: str
    output_dir: Path
    dataset: str | None = None
    width: int = 900
    palette: str = "gray"
    filters: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreviewMetadata:
    radar: str
    date: str
    pulse: str
    time: str
    quantity: str
    dataset: str
    source_shape: list[int]
    image_width: int
    image_height: int
    valid_min: float | None
    valid_max: float | None
    scale_min: float | None
    scale_max: float | None
    palette: str
    data_group: str
    palette_stops: str | None = None
    nominal_height_m: float | None = None
    cappi_height_m: float | None = None


def preview_filename(request: PreviewRequest) -> str:
    safe_quantity = request.quantity.replace("/", "_").replace(" ", "_")
    dataset = request.dataset or "auto"
    palette = request.palette if request.palette in PALETTES else "gray"
    filter_suffix = ""
    if request.filters:
        payload = json.dumps(request.filters, sort_keys=True, separators=(",", ":"))
        filter_suffix = "_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"{request.radar}_{request.date}_{request.pulse}_{request.time}_{dataset}_{safe_quantity}_{palette}{filter_suffix}.png"


def preview_metadata_filename(request: PreviewRequest) -> str:
    return preview_filename(request).replace(".png", ".json")


def _find_data_group(h5: object, request: PreviewRequest):
    h5py = require_h5py()
    prefix = f"{request.pulse}/{request.time}/"
    matches: list[tuple[str, object]] = []

    def visit(name: str, obj: object) -> None:
        if not isinstance(obj, h5py.Group):
            return
        if not name.startswith(prefix) or "/data" not in name:
            return
        what = obj.get("what")
        quantity = None
        if what is not None and "quantity" in what.attrs:
            raw = what.attrs["quantity"]
            quantity = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        if quantity == request.quantity:
            if request.dataset is None or f"/{request.dataset}/" in f"/{name}/":
                matches.append((name, obj))

    h5.visititems(visit)
    if not matches:
        def visit_root_volume(name: str, obj: object) -> None:
            if not isinstance(obj, h5py.Group):
                return
            if not name.startswith("dataset") or "/data" not in name:
                return
            what = obj.get("what")
            quantity = None
            if what is not None and "quantity" in what.attrs:
                raw = what.attrs["quantity"]
                quantity = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if quantity == request.quantity:
                if request.dataset is None or f"/{request.dataset}/" in f"/{name}/":
                    matches.append((name, obj))

        h5.visititems(visit_root_volume)
    if not matches:
        raise ValueError(
            f"no data group found for pulse={request.pulse}, time={request.time}, "
            f"quantity={request.quantity}, dataset={request.dataset or 'auto'}"
        )
    target_height = _request_float(request, "cappi_height_m")
    if target_height is not None and request.dataset is None:
        return min(matches, key=lambda match: _preview_height_score(h5, match[0], target_height))
    return matches[0]


def _preview_attrs(group: Any | None) -> dict[str, Any]:
    if group is None:
        return {}
    return {key: _jsonable(value) for key, value in group.attrs.items()}


def _preview_height_score(h5: object, name: str, target_height_m: float) -> float:
    parts = name.split("/")
    if parts and parts[0].startswith("dataset"):
        dataset_group = h5[parts[0]]
        height = dataset_nominal_height_m(_preview_attrs(h5.get("where")), _preview_attrs(dataset_group.get("where")))
        if height is None:
            return float("inf")
        return abs(height - target_height_m)
    if len(parts) < 3:
        return float("inf")
    time_group = h5[f"{parts[0]}/{parts[1]}"]
    dataset_group = h5[f"{parts[0]}/{parts[1]}/{parts[2]}"]
    height = dataset_nominal_height_m(_preview_attrs(time_group.get("where")), _preview_attrs(dataset_group.get("where")))
    if height is None:
        return float("inf")
    return abs(height - target_height_m)


def _preview_nominal_height(h5: object, name: str) -> float | None:
    parts = name.split("/")
    if parts and parts[0].startswith("dataset"):
        dataset_group = h5[parts[0]]
        return dataset_nominal_height_m(_preview_attrs(h5.get("where")), _preview_attrs(dataset_group.get("where")))
    if len(parts) < 3:
        return None
    time_group = h5[f"{parts[0]}/{parts[1]}"]
    dataset_group = h5[f"{parts[0]}/{parts[1]}/{parts[2]}"]
    return dataset_nominal_height_m(_preview_attrs(time_group.get("where")), _preview_attrs(dataset_group.get("where")))


def _request_float(request: PreviewRequest, key: str) -> float | None:
    if not request.filters:
        return None
    value = request.filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def _request_text(request: PreviewRequest, key: str) -> str | None:
    if not request.filters:
        return None
    value = request.filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return str(value)


def _scale_to_uint8(data):
    np = require_numpy()
    array = np.asarray(data, dtype=float)
    array = np.where(np.isfinite(array), array, np.nan)
    valid = array[np.isfinite(array)]
    if valid.size == 0:
        return np.zeros(array.shape, dtype=np.uint8), {
            "valid_min": None,
            "valid_max": None,
            "scale_min": None,
            "scale_max": None,
        }
    lo, hi = np.nanpercentile(valid, [2, 98])
    if hi <= lo:
        hi = lo + 1.0
    scaled = (array - lo) / (hi - lo)
    scaled = np.clip(scaled, 0, 1)
    scaled = np.where(np.isfinite(scaled), scaled, 0)
    return (scaled * 255).astype(np.uint8), {
        "valid_min": float(np.nanmin(valid)),
        "valid_max": float(np.nanmax(valid)),
        "scale_min": float(lo),
        "scale_max": float(hi),
    }


def _apply_palette(scaled, palette: str):
    np = require_numpy()
    palette = palette if palette in PALETTES else "gray"
    value = np.asarray(scaled, dtype=np.uint8)
    if palette == "custom":
        return _apply_custom_palette(value)
    if palette == "gray":
        return value
    if palette == "thermal":
        red = value
        green = np.clip(value.astype("int16") * 1.35 - 75, 0, 255).astype("uint8")
        blue = np.clip(255 - value.astype("int16") * 1.2, 0, 255).astype("uint8")
        return np.dstack([red, green, blue])
    if palette == "velocity":
        red = np.clip(value.astype("int16") * 2 - 255, 0, 255).astype("uint8")
        green = np.clip(255 - abs(value.astype("int16") - 128) * 2, 0, 255).astype("uint8")
        blue = np.clip(255 - value.astype("int16") * 2, 0, 255).astype("uint8")
        return np.dstack([red, green, blue])
    blue = np.clip(180 - value.astype("int16") * 2, 0, 255).astype("uint8")
    green = np.clip(value.astype("int16") * 2, 0, 255).astype("uint8")
    red = np.clip(value.astype("int16") * 2 - 120, 0, 255).astype("uint8")
    return np.dstack([red, green, blue])


def parse_palette_stops(spec: str | None) -> list[tuple[float, tuple[int, int, int]]]:
    if not spec:
        return []
    stops: list[tuple[float, tuple[int, int, int]]] = []
    for raw_stop in spec.split(","):
        raw_stop = raw_stop.strip()
        if not raw_stop:
            continue
        if ":" not in raw_stop:
            raise ValueError("palette stop must use position:#RRGGBB")
        raw_position, raw_color = raw_stop.split(":", 1)
        position = max(0.0, min(1.0, float(raw_position.strip())))
        color = raw_color.strip().lstrip("#")
        if len(color) != 6:
            raise ValueError("palette color must be #RRGGBB")
        rgb = tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))
        stops.append((position, rgb))  # type: ignore[arg-type]
    return sorted(stops)


def _apply_custom_palette(value: Any, spec: str | None = None):
    np = require_numpy()
    stops = parse_palette_stops(spec) or [
        (0.0, (0, 0, 0)),
        (0.5, (40, 180, 80)),
        (1.0, (255, 255, 255)),
    ]
    if stops[0][0] > 0:
        stops.insert(0, (0.0, stops[0][1]))
    if stops[-1][0] < 1:
        stops.append((1.0, stops[-1][1]))
    normalized = np.asarray(value, dtype="float32") / 255.0
    channels = []
    positions = np.asarray([stop[0] for stop in stops], dtype="float32")
    for channel in range(3):
        colors = np.asarray([stop[1][channel] for stop in stops], dtype="float32")
        channels.append(np.interp(normalized, positions, colors).astype("uint8"))
    return np.dstack(channels)


def apply_palette(scaled: Any, palette: str, palette_stops: str | None = None):
    if palette == "custom":
        return _apply_custom_palette(scaled, palette_stops)
    return _apply_palette(scaled, palette)


def _jsonable(value: Any) -> Any:
    try:
        np = require_numpy()
        if isinstance(value, np.generic):
            return value.item()
    except RuntimeError:
        pass
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _apply_preview_filters(data: Any, request: PreviewRequest):
    filters = request.filters or {}
    if not filters:
        return data
    np = require_numpy()
    try:
        _source_data, metadata = read_polar_field(
            request.aggregate_path,
            request.radar,
            request.date,
            FieldSelection(
                pulse=request.pulse,
                time=request.time,
                quantity=request.quantity,
                dataset=request.dataset,
                cappi_height_m=_request_float(request, "cappi_height_m"),
            ),
        )
        return apply_polar_filters(data, metadata, filters)
    except Exception:
        output = np.asarray(data, dtype="float32").copy()
        min_value = filters.get("min_value")
        max_value = filters.get("max_value")
        if min_value not in ("", None, "NONE"):
            output[output < float(min_value)] = np.nan
        if max_value not in ("", None, "NONE"):
            output[output > float(max_value)] = np.nan
        return output


def generate_preview(request: PreviewRequest) -> Path:
    h5py = require_h5py()
    Image = require_pillow()
    request.output_dir.mkdir(parents=True, exist_ok=True)
    output = request.output_dir / preview_filename(request)
    metadata_output = request.output_dir / preview_metadata_filename(request)
    if output.exists() and metadata_output.exists():
        return output

    with h5py.File(request.aggregate_path, "r") as h5:
        name, group = _find_data_group(h5, request)
        if "data" not in group:
            raise ValueError("matching group has no data dataset")
        data = group["data"][()]
        data = _apply_preview_filters(data, request)
        scaled, stats = _scale_to_uint8(data)
        dataset = name.split("/")[2] if len(name.split("/")) > 2 else request.dataset or "auto"
        nominal_height_m = _preview_nominal_height(h5, name)

    image = Image.fromarray(apply_palette(scaled, request.palette, _request_text(request, "palette_stops")))
    if request.width and image.width > request.width:
        ratio = request.width / image.width
        image = image.resize((request.width, max(1, int(image.height * ratio))))
    image.save(output)
    metadata = PreviewMetadata(
        radar=request.radar,
        date=request.date,
        pulse=request.pulse,
        time=request.time,
        quantity=request.quantity,
        dataset=dataset,
        source_shape=list(data.shape),
        image_width=image.width,
        image_height=image.height,
        palette=request.palette if request.palette in PALETTES else "gray",
        palette_stops=_request_text(request, "palette_stops"),
        data_group=name,
        nominal_height_m=nominal_height_m,
        cappi_height_m=_request_float(request, "cappi_height_m"),
        **stats,
    )
    metadata_output.write_text(
        json.dumps(asdict(metadata), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output


def preview_metadata(request: PreviewRequest) -> PreviewMetadata:
    h5py = require_h5py()
    np = require_numpy()
    metadata_path = request.output_dir / preview_metadata_filename(request)
    if metadata_path.exists():
        return PreviewMetadata(**json.loads(metadata_path.read_text(encoding="utf-8")))
    with h5py.File(request.aggregate_path, "r") as h5:
        name, group = _find_data_group(h5, request)
        data = np.asarray(group["data"][()])
        data = _apply_preview_filters(data, request)
        _scaled, stats = _scale_to_uint8(data)
        dataset = name.split("/")[2] if len(name.split("/")) > 2 else request.dataset or "auto"
        nominal_height_m = _preview_nominal_height(h5, name)
    width = int(data.shape[1])
    height = int(data.shape[0])
    if request.width and width > request.width:
        ratio = request.width / width
        width = request.width
        height = max(1, int(height * ratio))
    return PreviewMetadata(
        radar=request.radar,
        date=request.date,
        pulse=request.pulse,
        time=request.time,
        quantity=request.quantity,
        dataset=dataset,
        source_shape=list(data.shape),
        image_width=width,
        image_height=height,
        palette=request.palette if request.palette in PALETTES else "gray",
        palette_stops=_request_text(request, "palette_stops"),
        data_group=name,
        nominal_height_m=nominal_height_m,
        cappi_height_m=_request_float(request, "cappi_height_m"),
        **stats,
    )


def identify_value(request: PreviewRequest, row: int, column: int) -> dict[str, Any]:
    h5py = require_h5py()
    location = None
    geospatial_error = ""
    scaled_data = None
    metadata = None
    try:
        scaled_data, metadata = read_polar_field(
            request.aggregate_path,
            request.radar,
            request.date,
            FieldSelection(
                pulse=request.pulse,
                time=request.time,
                quantity=request.quantity,
                dataset=request.dataset,
                cappi_height_m=_request_float(request, "cappi_height_m"),
            ),
        )
        location = radar_bin_location(metadata, row, column)
    except Exception as exc:
        geospatial_error = f"{type(exc).__name__}: {exc}"

    if scaled_data is not None and metadata is not None:
        clipped_row = max(0, min(int(row), scaled_data.shape[0] - 1))
        clipped_column = max(0, min(int(column), scaled_data.shape[1] - 1))
        value = scaled_data[clipped_row, clipped_column]
        dataset = metadata.dataset
        data_group = metadata.dataset
    else:
        np = require_numpy()
        with h5py.File(request.aggregate_path, "r") as h5:
            name, group = _find_data_group(h5, request)
            data = np.asarray(group["data"][()])
            dataset = name.split("/")[2] if len(name.split("/")) > 2 else request.dataset or "auto"
            clipped_row = max(0, min(int(row), data.shape[0] - 1))
            clipped_column = max(0, min(int(column), data.shape[1] - 1))
            value = data[clipped_row, clipped_column]
            data_group = name
    result = {
        "radar": request.radar,
        "date": request.date,
        "pulse": request.pulse,
        "time": request.time,
        "quantity": request.quantity,
        "dataset": dataset,
        "data_group": data_group,
        "row": clipped_row,
        "column": clipped_column,
        "value": _jsonable(value),
    }
    if location is not None:
        result.update(
            {
                "range_m": location.range_m,
                "range_km": location.range_km,
                "azimuth_deg": location.azimuth_deg,
                "x_m": location.x_m,
                "y_m": location.y_m,
                "longitude": location.longitude,
                "latitude": location.latitude,
                "elevation_deg": location.elevation_deg,
            }
        )
    else:
        result["geospatial_error"] = geospatial_error
    return result
