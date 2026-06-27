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

STANDARD_PALETTES = {
    "homeyer": [
        (0.00, (245, 245, 245)),
        (0.08, (120, 200, 255)),
        (0.18, (20, 80, 220)),
        (0.30, (25, 170, 60)),
        (0.43, (250, 230, 30)),
        (0.56, (245, 125, 20)),
        (0.68, (210, 25, 35)),
        (0.80, (185, 35, 160)),
        (0.91, (250, 250, 250)),
        (1.00, (120, 70, 40)),
    ],
    "budrd18": [
        (0.00, (5, 48, 97)),
        (0.18, (33, 102, 172)),
        (0.34, (146, 197, 222)),
        (0.50, (247, 247, 247)),
        (0.66, (244, 165, 130)),
        (0.82, (178, 24, 43)),
        (1.00, (103, 0, 31)),
    ],
    "refdiff": [
        (0.00, (49, 54, 149)),
        (0.20, (69, 117, 180)),
        (0.40, (171, 217, 233)),
        (0.50, (255, 255, 191)),
        (0.60, (254, 224, 144)),
        (0.80, (244, 109, 67)),
        (1.00, (165, 0, 38)),
    ],
    "nws_spw": [
        (0.00, (255, 255, 255)),
        (0.15, (153, 204, 255)),
        (0.30, (76, 153, 255)),
        (0.45, (76, 204, 76)),
        (0.60, (255, 230, 0)),
        (0.78, (255, 128, 0)),
        (1.00, (180, 0, 0)),
    ],
    "wild25": [
        (0.00, (68, 1, 84)),
        (0.18, (59, 82, 139)),
        (0.34, (33, 145, 140)),
        (0.50, (94, 201, 98)),
        (0.66, (253, 231, 37)),
        (0.82, (241, 135, 33)),
        (1.00, (180, 40, 120)),
    ],
    "theodore16": [
        (0.00, (49, 54, 149)),
        (0.20, (69, 117, 180)),
        (0.40, (116, 173, 209)),
        (0.50, (255, 255, 191)),
        (0.64, (254, 224, 144)),
        (0.80, (244, 109, 67)),
        (1.00, (165, 0, 38)),
    ],
    "rrate11": [
        (0.00, (247, 252, 245)),
        (0.14, (199, 233, 192)),
        (0.28, (116, 196, 118)),
        (0.42, (49, 163, 84)),
        (0.58, (254, 224, 144)),
        (0.74, (253, 141, 60)),
        (1.00, (189, 0, 38)),
    ],
    "carbone17": [
        (0.00, (38, 38, 38)),
        (0.18, (88, 88, 88)),
        (0.36, (150, 150, 150)),
        (0.52, (210, 210, 210)),
        (0.68, (150, 200, 255)),
        (0.84, (60, 140, 220)),
        (1.00, (10, 65, 140)),
    ],
}
PALETTES = {"gray", "radar", "thermal", "velocity", "custom", *STANDARD_PALETTES}


def palette_key(palette: str) -> str:
    key = str(palette or "gray").lower()
    return key if key in PALETTES else "gray"


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
    noise_floor: dict[str, Any] | None = None


def preview_filename(request: PreviewRequest) -> str:
    safe_quantity = request.quantity.replace("/", "_").replace(" ", "_")
    dataset = request.dataset or "auto"
    palette = palette_key(request.palette)
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


def _apply_stop_palette(value: Any, stops: list[tuple[float, tuple[int, int, int]]]):
    np = require_numpy()
    if stops[0][0] > 0:
        stops = [(0.0, stops[0][1]), *stops]
    if stops[-1][0] < 1:
        stops = [*stops, (1.0, stops[-1][1])]
    normalized = np.asarray(value, dtype="float32") / 255.0
    channels = []
    positions = np.asarray([stop[0] for stop in stops], dtype="float32")
    for channel in range(3):
        colors = np.asarray([stop[1][channel] for stop in stops], dtype="float32")
        channels.append(np.interp(normalized, positions, colors).astype("uint8"))
    return np.dstack(channels)


def _apply_custom_palette(value: Any, spec: str | None = None):
    stops = parse_palette_stops(spec) or [
        (0.0, (0, 0, 0)),
        (0.5, (40, 180, 80)),
        (1.0, (255, 255, 255)),
    ]
    return _apply_stop_palette(value, stops)


def apply_palette(scaled: Any, palette: str, palette_stops: str | None = None):
    key = palette_key(palette)
    if key == "custom":
        return _apply_custom_palette(scaled, palette_stops)
    if key in STANDARD_PALETTES:
        return _apply_stop_palette(scaled, STANDARD_PALETTES[key])
    return _apply_palette(scaled, key)


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


def _apply_preview_filters(data: Any, request: PreviewRequest, *, return_metadata: bool = False):
    filters = request.filters or {}
    if not filters:
        return (data, {"enabled": False}) if return_metadata else data
    np = require_numpy()
    try:
        source_data, metadata = read_polar_field(
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
        result = apply_polar_filters(source_data, metadata, filters, return_metadata=True)
        return (result.values, result.noise_floor.to_dict()) if return_metadata else result.values
    except Exception:
        output = np.asarray(data, dtype="float32").copy()
        min_value = filters.get("min_value")
        max_value = filters.get("max_value")
        if min_value not in ("", None, "NONE"):
            output[output < float(min_value)] = np.nan
        if max_value not in ("", None, "NONE"):
            output[output > float(max_value)] = np.nan
        noise_floor = {"enabled": False}
        return (output, noise_floor) if return_metadata else output


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
        data, noise_floor = _apply_preview_filters(data, request, return_metadata=True)
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
        palette=palette_key(request.palette),
        palette_stops=_request_text(request, "palette_stops"),
        data_group=name,
        nominal_height_m=nominal_height_m,
        cappi_height_m=_request_float(request, "cappi_height_m"),
        noise_floor=noise_floor,
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
        data, noise_floor = _apply_preview_filters(data, request, return_metadata=True)
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
        palette=palette_key(request.palette),
        palette_stops=_request_text(request, "palette_stops"),
        data_group=name,
        nominal_height_m=nominal_height_m,
        cappi_height_m=_request_float(request, "cappi_height_m"),
        noise_floor=noise_floor,
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
        np = require_numpy()
        original_data = scaled_data
        filter_result = apply_polar_filters(original_data, metadata, request.filters, return_metadata=True)
        scaled_data = filter_result.values
        clipped_row = max(0, min(int(row), scaled_data.shape[0] - 1))
        clipped_column = max(0, min(int(column), scaled_data.shape[1] - 1))
        value = scaled_data[clipped_row, clipped_column]
        original_value = original_data[clipped_row, clipped_column]
        noise_floor = filter_result.noise_floor.to_dict()
        masked_by_noise_floor = bool(
            filter_result.noise_floor.enabled
            and np.isfinite(original_value)
            and not np.isfinite(value)
        )
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
            original_value = value
            noise_floor = {"enabled": False}
            masked_by_noise_floor = False
    value_out = None if not np.isfinite(value) else _jsonable(value)
    original_value_out = None if not np.isfinite(original_value) else _jsonable(original_value)
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
        "value": value_out,
        "original_value": original_value_out,
        "masked_by_noise_floor": masked_by_noise_floor,
        "noise_floor": noise_floor,
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
