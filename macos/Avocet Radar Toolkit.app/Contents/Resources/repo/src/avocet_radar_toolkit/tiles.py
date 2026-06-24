"""Browser tile pyramid generation for selected radar fields."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .dependencies import require_pillow
from .export_types import FieldSelection
from .geospatial import read_polar_field
from .preview import PreviewRequest, generate_preview


@dataclass(frozen=True)
class TileRequest:
    aggregate_path: Path
    radar: str
    date: str
    pulse: str
    time: str
    quantity: str
    output_dir: Path
    dataset: str | None = None
    palette: str = "gray"
    filters: dict[str, Any] = field(default_factory=dict)
    tile_size: int = 256
    min_zoom: int = 0
    max_zoom: int = 2


@dataclass(frozen=True)
class TileProduct:
    root_dir: str
    manifest_path: str
    preview_path: str
    tile_count: int
    tile_size: int
    min_zoom: int
    max_zoom: int
    url_template: str
    source_width: int
    source_height: int
    bbox: list[float]
    request: TileRequest


def _safe(value: str) -> str:
    return value.replace("/", "_").replace(" ", "_")


def tile_request_hash(request: TileRequest) -> str:
    payload = {
        "dataset": request.dataset,
        "palette": request.palette,
        "filters": request.filters,
        "tile_size": request.tile_size,
        "min_zoom": request.min_zoom,
        "max_zoom": request.max_zoom,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:10]


def tile_root(request: TileRequest) -> Path:
    dataset = request.dataset or "auto"
    return (
        request.output_dir
        / f"radar={request.radar}"
        / f"date={request.date}"
        / f"pulse={request.pulse}"
        / f"quantity={_safe(request.quantity)}"
        / f"time={request.time}"
        / f"dataset={dataset}"
        / f"palette={request.palette}"
        / f"variant={tile_request_hash(request)}"
    )


def validate_tile_request(request: TileRequest) -> None:
    if not request.pulse:
        raise ValueError("tile generation requires pulse")
    if not request.time:
        raise ValueError("tile generation requires time")
    if not request.quantity:
        raise ValueError("tile generation requires quantity")
    if request.tile_size < 64 or request.tile_size > 1024:
        raise ValueError("tile_size must be between 64 and 1024")
    if request.min_zoom < 0 or request.max_zoom < request.min_zoom:
        raise ValueError("zoom range is invalid")
    if request.max_zoom > 8:
        raise ValueError("max_zoom must be <= 8 for preview-derived tiles")


def _geographic_bbox(request: TileRequest) -> list[float]:
    try:
        _data, metadata = read_polar_field(
            request.aggregate_path,
            request.radar,
            request.date,
            FieldSelection(
                pulse=request.pulse,
                time=request.time,
                quantity=request.quantity,
                dataset=request.dataset,
                cappi_height_m=_filter_float(request.filters, "cappi_height_m"),
            ),
        )
        return metadata.geographic_bbox()
    except Exception:
        return []


def _filter_float(filters: dict[str, Any], key: str) -> float | None:
    value = filters.get(key)
    if value in ("", None, "NONE"):
        return None
    return float(value)


def tile_manifest(product: TileProduct) -> dict[str, Any]:
    payload = asdict(product)
    payload["request"] = {
        **payload["request"],
        "aggregate_path": str(product.request.aggregate_path),
        "output_dir": str(product.request.output_dir),
    }
    return payload


def generate_tile_pyramid(request: TileRequest) -> TileProduct:
    validate_tile_request(request)
    Image = require_pillow()
    root = tile_root(request)
    source_dir = root / "source"
    preview_path = generate_preview(
        PreviewRequest(
            aggregate_path=request.aggregate_path,
            radar=request.radar,
            date=request.date,
            pulse=request.pulse,
            time=request.time,
            quantity=request.quantity,
            dataset=request.dataset,
            palette=request.palette,
            filters=request.filters,
            width=request.tile_size * (2 ** request.max_zoom),
            output_dir=source_dir,
        )
    )

    image = Image.open(preview_path).convert("RGBA")
    source_width, source_height = image.size
    tile_count = 0
    for zoom in range(request.min_zoom, request.max_zoom + 1):
        tiles_per_side = 2**zoom
        canvas_size = request.tile_size * tiles_per_side
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        ratio = min(canvas_size / max(source_width, 1), canvas_size / max(source_height, 1))
        resized_size = (max(1, int(source_width * ratio)), max(1, int(source_height * ratio)))
        resized = image.resize(resized_size)
        offset = ((canvas_size - resized_size[0]) // 2, (canvas_size - resized_size[1]) // 2)
        canvas.alpha_composite(resized, offset)
        for x in range(tiles_per_side):
            for y in range(tiles_per_side):
                tile = canvas.crop(
                    (
                        x * request.tile_size,
                        y * request.tile_size,
                        (x + 1) * request.tile_size,
                        (y + 1) * request.tile_size,
                    )
                )
                tile_path = root / "tiles" / str(zoom) / str(x) / f"{y}.png"
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                tile.save(tile_path)
                tile_count += 1

    product = TileProduct(
        root_dir=str(root),
        manifest_path=str(root / "tile-manifest.json"),
        preview_path=str(preview_path),
        tile_count=tile_count,
        tile_size=request.tile_size,
        min_zoom=request.min_zoom,
        max_zoom=request.max_zoom,
        url_template="tiles/{z}/{x}/{y}.png",
        source_width=source_width,
        source_height=source_height,
        bbox=_geographic_bbox(request),
        request=request,
    )
    manifest_path = Path(product.manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(tile_manifest(product), indent=2, sort_keys=True), encoding="utf-8")
    return product
