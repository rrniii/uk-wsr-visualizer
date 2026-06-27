"""Animation export products for radar time workflows."""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .catalog import CatalogItem
from .compat import UTC
from .preview import PreviewRequest, generate_preview, preview_metadata_filename


@dataclass(frozen=True)
class AnimationRequest:
    radar: str
    date: str
    pulse: str
    quantity: str
    times: list[str] = field(default_factory=list)
    dataset: str | None = None
    palette: str = "gray"
    filters: dict[str, Any] = field(default_factory=dict)
    frame_delay_ms: int = 600


@dataclass(frozen=True)
class AnimationFrame:
    index: int
    time: str
    filename: str
    metadata_filename: str


@dataclass(frozen=True)
class AnimationProduct:
    request: AnimationRequest
    output_path: str
    manifest_path: str
    frame_count: int
    frames: list[AnimationFrame]
    created_at: str


def validate_animation_request(request: AnimationRequest) -> None:
    if not request.pulse:
        raise ValueError("animation requires pulse")
    if not request.quantity:
        raise ValueError("animation requires quantity")
    if request.frame_delay_ms < 50:
        raise ValueError("frame_delay_ms must be at least 50")


def animation_manifest(product: AnimationProduct) -> dict[str, Any]:
    return asdict(product)


def animation_stem(request: AnimationRequest) -> str:
    quantity = request.quantity.replace("/", "_").replace(" ", "_")
    dataset = request.dataset or "auto"
    return f"{request.radar}_{request.date}_{request.pulse}_{dataset}_{quantity}_{request.palette}_animation"


def run_animation(request: AnimationRequest, item: CatalogItem, output_dir: Path, preview_dir: Path) -> AnimationProduct:
    validate_animation_request(request)
    times = request.times or item.times
    if not times:
        raise ValueError("animation has no frames because no times were selected")

    output_dir.mkdir(parents=True, exist_ok=True)
    frame_dir = preview_dir / item.radar / item.date
    frame_dir.mkdir(parents=True, exist_ok=True)

    frames: list[AnimationFrame] = []
    zip_path = output_dir / f"{animation_stem(request)}.zip"
    manifest_path = output_dir / f"{animation_stem(request)}.json"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, time in enumerate(times):
            preview_request = PreviewRequest(
                aggregate_path=Path(item.path),
                radar=item.radar,
                date=item.date,
                pulse=request.pulse,
                time=time,
                quantity=request.quantity,
                dataset=request.dataset,
                palette=request.palette,
                filters=request.filters,
                output_dir=frame_dir,
            )
            frame_path = generate_preview(preview_request)
            metadata_path = frame_dir / preview_metadata_filename(preview_request)
            frame_arcname = f"frames/{index:04d}_{frame_path.name}"
            metadata_arcname = f"frames/{index:04d}_{metadata_path.name}"
            archive.write(frame_path, frame_arcname)
            if metadata_path.exists():
                archive.write(metadata_path, metadata_arcname)
            frames.append(
                AnimationFrame(
                    index=index,
                    time=time,
                    filename=frame_arcname,
                    metadata_filename=metadata_arcname,
                )
            )

        product = AnimationProduct(
            request=request,
            output_path=str(zip_path),
            manifest_path=str(manifest_path),
            frame_count=len(frames),
            frames=frames,
            created_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        )
        manifest = animation_manifest(product)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    manifest_path.write_text(json.dumps(animation_manifest(product), indent=2, sort_keys=True), encoding="utf-8")
    return product
