"""Blinded local review application for the independent UK WSR QC benchmark."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles
except ImportError as exc:  # pragma: no cover - required project dependency.
    raise RuntimeError("FastAPI is required for the QC review application") from exc

from .dependencies import require_numpy, require_pillow
from .export_types import FieldSelection
from .geospatial import read_polar_field_with_companions
from .preview import apply_palette
from .qc_benchmark import (
    BENCHMARK_ID,
    LABEL_TAXONOMY,
    benchmark_local_path,
    canonical_json_sha256,
)

REVIEW_STAGES = {"primary", "secondary", "adjudicated"}
REVIEW_IMAGE_SIZE = 720
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

FIELD_RENDERING: dict[str, tuple[float, float, str]] = {
    "DBZH": (-30.0, 70.0, "homeyer"),
    "VRADH": (-30.0, 30.0, "velocity"),
    "SQIH": (0.0, 1.0, "thermal"),
    "RHOHV": (0.0, 1.0, "thermal"),
    "ZDR": (-5.0, 10.0, "budrd18"),
    "PHIDP": (-180.0, 180.0, "budrd18"),
    "WRADH": (0.0, 10.0, "thermal"),
}


class ReviewStore:
    """Validated benchmark state and independent reviewer annotations."""

    def __init__(
        self,
        *,
        benchmark_path: str | Path,
        targets_path: str | Path,
        source_root: str | Path,
        output_dir: str | Path,
        reviewer: str,
        stage: str,
        radars: set[str] | None = None,
        splits: set[str] | None = None,
        limit: int | None = None,
    ) -> None:
        self.benchmark_path = Path(benchmark_path)
        self.targets_path = Path(targets_path)
        self.source_root = Path(source_root)
        self.output_dir = Path(output_dir)
        self.reviewer = reviewer.strip()
        self.stage = stage.strip().lower()
        if not self.reviewer:
            raise ValueError("reviewer must not be empty")
        if self.stage not in REVIEW_STAGES:
            raise ValueError(f"invalid review stage: {stage}")

        self.benchmark = json.loads(self.benchmark_path.read_text(encoding="utf-8"))
        self.review = json.loads(self.targets_path.read_text(encoding="utf-8"))
        if self.benchmark.get("benchmark_id") != BENCHMARK_ID:
            raise ValueError("benchmark id mismatch")
        if self.review.get("benchmark_id") != BENCHMARK_ID:
            raise ValueError("review-target benchmark id mismatch")
        benchmark_hash = canonical_json_sha256(self.benchmark)
        if self.review.get("benchmark_manifest_sha256") != benchmark_hash:
            raise ValueError("review targets do not match the benchmark manifest")
        if self.review.get("errors"):
            raise ValueError("review-target manifest contains selection errors")

        files = {
            str(item["case_id"]): item
            for item in self.benchmark.get("files", [])
        }
        targets = []
        for target in self.review.get("targets", []):
            if str(target.get("case_id")) not in files:
                raise ValueError(f"unknown benchmark case: {target.get('case_id')}")
            if self.stage == "secondary" and not target.get("double_review_required"):
                continue
            if radars and str(target.get("radar")) not in radars:
                continue
            if splits and str(target.get("split")) not in splits:
                continue
            targets.append(target)
        if limit is not None:
            targets = targets[: max(0, int(limit))]
        self.files = files
        self.targets = targets
        self.targets_by_id = {
            str(target["target_id"]): target
            for target in targets
        }
        if len(self.targets_by_id) != len(targets):
            raise ValueError("review target ids are not unique")
        if not targets:
            raise ValueError("review selection contains no targets")

        safe_reviewer = SAFE_NAME.sub("-", self.reviewer).strip("-") or "reviewer"
        self.annotation_path = (
            self.output_dir / f"{safe_reviewer}.{self.stage}.json"
        )
        self.annotation = self._load_annotation(benchmark_hash)

    def review_state(self) -> dict[str, Any]:
        completed = {
            str(item.get("target_id"))
            for item in self.annotation.get("items", [])
        }
        summaries = [
            {
                "target_id": target["target_id"],
                "radar": target["radar"],
                "pulse": target["pulse"],
                "date": target["date"],
                "time": target["time"],
                "dataset": target["dataset"],
                "elevation_deg": target.get("elevation_deg"),
                "split": target["split"],
                "selection_role": target["selection_role"],
                "completed": target["target_id"] in completed,
            }
            for target in self.targets
        ]
        return {
            "benchmark_id": BENCHMARK_ID,
            "reviewer": self.reviewer,
            "stage": self.stage,
            "target_count": len(summaries),
            "completed_count": sum(item["completed"] for item in summaries),
            "blinding": {
                "qc_outputs_visible": False,
                "ci_available_to_reviewer": False,
                "current_filter_available_to_reviewer": False,
            },
            "taxonomy": LABEL_TAXONOMY,
            "targets": summaries,
        }

    def target_payload(self, target_id: str) -> dict[str, Any]:
        target = self._target(target_id)
        completed = next(
            (
                item
                for item in self.annotation.get("items", [])
                if item.get("target_id") == target_id
            ),
            None,
        )
        visible = [
            quantity
            for quantity in target.get("primary_visible_fields", [])
            if quantity in FIELD_RENDERING
        ]
        if "DBZH" not in visible:
            visible.insert(0, "DBZH")
        return {
            "target_id": target_id,
            "case_id": target["case_id"],
            "radar": target["radar"],
            "pulse": target["pulse"],
            "date": target["date"],
            "time": target["time"],
            "dataset": target["dataset"],
            "elevation_deg": target.get("elevation_deg"),
            "shape": target["shape"],
            "split": target["split"],
            "season": target["season"],
            "utc_slot": target["utc_slot"],
            "selection_role": target["selection_role"],
            "visible_fields": [
                {
                    "quantity": quantity,
                    "image_url": f"/api/targets/{target_id}/fields/{quantity}.png",
                    "scale_min": FIELD_RENDERING[quantity][0],
                    "scale_max": FIELD_RENDERING[quantity][1],
                }
                for quantity in visible
            ],
            "coordinate_contract": {
                "geometry": "polar_gate_polygon",
                "vertex_order": ["ray_index", "gate_index"],
                "ray_origin": "north",
                "ray_direction": "clockwise",
                "gate_origin": "radar",
            },
            "annotation": completed,
        }

    def field_png(self, target_id: str, quantity: str) -> bytes:
        target = self._target(target_id)
        normalized = str(quantity).upper()
        visible = {
            str(value).upper()
            for value in target.get("primary_visible_fields", [])
        }
        if normalized not in visible or normalized not in FIELD_RENDERING:
            raise KeyError(f"field is not available in blinded review: {quantity}")
        return self._render_field(target_id, normalized)

    def save_annotation(self, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self._target(target_id)
        regions = self._validate_regions(payload.get("regions"), target)
        item = {
            "target_id": target_id,
            "case_id": target["case_id"],
            "dataset": target["dataset"],
            "elevation_deg": target.get("elevation_deg"),
            "quantity": "DBZH",
            "shape": list(target["shape"]),
            "review_stage": self.stage,
            "qc_outputs_visible": False,
            "ci_used_as_ground_truth": False,
            "current_filter_used_as_ground_truth": False,
            "regions": regions,
            "notes": str(payload.get("notes") or ""),
            "reviewed_at": _now_utc(),
        }
        items = [
            previous
            for previous in self.annotation.get("items", [])
            if previous.get("target_id") != target_id
        ]
        items.append(item)
        items.sort(key=lambda value: str(value.get("target_id")))
        self.annotation["items"] = items
        self.annotation["updated_at"] = _now_utc()
        self._write_annotation()
        return {
            "saved": True,
            "target_id": target_id,
            "region_count": len(regions),
            "completed_count": len(items),
            "annotation_path": str(self.annotation_path),
        }

    @lru_cache(maxsize=96)
    def _render_field(self, target_id: str, quantity: str) -> bytes:
        target = self._target(target_id)
        source_item = self.files[str(target["case_id"])]
        source = benchmark_local_path(self.source_root, source_item)
        if not source.exists():
            raise FileNotFoundError(f"benchmark source missing: {source}")
        selection = FieldSelection(
            pulse=str(target["pulse"]),
            time=str(target["time"]),
            quantity="DBZH",
            dataset=str(target["dataset"]),
        )
        dbzh, _, companions = read_polar_field_with_companions(
            source,
            str(target["radar"]),
            str(target["date"]),
            selection,
            quantities=tuple(
                value
                for value in target.get("primary_visible_fields", [])
                if value in FIELD_RENDERING and value != "DBZH"
            ),
        )
        values = dbzh if quantity == "DBZH" else companions.get(quantity)
        if values is None:
            raise KeyError(f"field is missing from source sweep: {quantity}")
        vmin, vmax, palette = FIELD_RENDERING[quantity]
        return render_polar_field_png(
            values,
            vmin=vmin,
            vmax=vmax,
            palette=palette,
            size=REVIEW_IMAGE_SIZE,
        )

    def _target(self, target_id: str) -> dict[str, Any]:
        target = self.targets_by_id.get(str(target_id))
        if target is None:
            raise KeyError(f"unknown review target: {target_id}")
        return target

    def _load_annotation(self, benchmark_hash: str) -> dict[str, Any]:
        if self.annotation_path.exists():
            annotation = json.loads(
                self.annotation_path.read_text(encoding="utf-8")
            )
            if annotation.get("manifest_sha256") != benchmark_hash:
                raise ValueError("existing annotations use a different benchmark")
            if annotation.get("reviewer") != self.reviewer:
                raise ValueError("existing annotation reviewer mismatch")
            if annotation.get("review_stage") != self.stage:
                raise ValueError("existing annotation stage mismatch")
            return annotation
        return {
            "schema": "uk_wsr_qc_annotations",
            "schema_version": 1,
            "benchmark_id": BENCHMARK_ID,
            "manifest_sha256": benchmark_hash,
            "review_targets_sha256": canonical_json_sha256(self.review),
            "reviewer": self.reviewer,
            "review_stage": self.stage,
            "created_at": _now_utc(),
            "review_policy": {
                "qc_outputs_visible": False,
                "ci_used_as_ground_truth": False,
                "current_filter_used_as_ground_truth": False,
                "ambiguous_action": "ignore",
            },
            "items": [],
        }

    def _write_annotation(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.annotation_path.with_suffix(
            self.annotation_path.suffix + ".part"
        )
        temporary.write_text(
            json.dumps(self.annotation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.annotation_path)

    @staticmethod
    def _validate_regions(
        raw_regions: Any,
        target: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_regions, list) or not raw_regions:
            raise ValueError("at least one labelled region is required")
        nrays, nbins = (int(value) for value in target["shape"])
        regions: list[dict[str, Any]] = []
        region_ids: set[str] = set()
        for raw in raw_regions:
            if not isinstance(raw, dict):
                raise ValueError("region must be an object")
            region_id = str(raw.get("region_id") or "").strip()
            if not region_id or region_id in region_ids:
                raise ValueError("region ids must be non-empty and unique")
            region_ids.add(region_id)
            label = str(raw.get("label") or "")
            taxonomy = LABEL_TAXONOMY.get(label)
            if taxonomy is None:
                raise ValueError(f"unknown label: {label}")
            action = str(raw.get("action") or "")
            if action != taxonomy["action"]:
                raise ValueError(
                    f"label {label} requires action {taxonomy['action']}"
                )
            confidence = float(raw.get("confidence"))
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be between zero and one")
            geometry = _validate_geometry(raw.get("geometry"), nrays, nbins)
            regions.append(
                {
                    "region_id": region_id,
                    "label": label,
                    "action": action,
                    "confidence": confidence,
                    "geometry": geometry,
                    "notes": str(raw.get("notes") or ""),
                }
            )
        return regions


def create_review_app(store: ReviewStore) -> FastAPI:
    """Create the isolated local review server."""

    app = FastAPI(title="UK WSR QC Blinded Review", version="1")
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(
            static_dir / "qc_review.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "benchmark_id": BENCHMARK_ID,
            "reviewer": store.reviewer,
            "stage": store.stage,
        }

    @app.get("/api/review")
    def review_state():
        return store.review_state()

    @app.get("/api/targets/{target_id}")
    def target(target_id: str):
        try:
            return store.target_payload(target_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/targets/{target_id}/fields/{quantity}.png")
    def field(target_id: str, quantity: str):
        try:
            content = store.field_png(target_id, quantity)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.post("/api/targets/{target_id}/annotation")
    def save_annotation(target_id: str, payload: dict[str, Any]):
        try:
            return store.save_annotation(target_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/annotations")
    def annotations():
        return store.annotation

    return app


def render_polar_field_png(
    values: Any,
    *,
    vmin: float,
    vmax: float,
    palette: str,
    size: int = REVIEW_IMAGE_SIZE,
) -> bytes:
    """Render a north-up polar sweep without any QC transformation."""

    np = require_numpy()
    Image = require_pillow()
    from PIL import ImageDraw

    array = np.asarray(values, dtype="float32")
    if array.ndim != 2:
        raise ValueError("review field must be a two-dimensional polar sweep")
    nrays, nbins = array.shape
    coordinate = np.arange(size, dtype="float32")
    x, y = np.meshgrid(coordinate, coordinate)
    centre = (size - 1) / 2.0
    dx = x - centre
    dy = y - centre
    radial = np.sqrt(dx * dx + dy * dy)
    inside = radial <= centre
    gate = np.minimum(
        (radial / max(centre, 1.0) * nbins).astype("int32"),
        nbins - 1,
    )
    azimuth = np.mod(np.arctan2(dx, -dy), 2.0 * np.pi)
    ray = np.minimum(
        (azimuth / (2.0 * np.pi) * nrays).astype("int32"),
        nrays - 1,
    )
    sampled = array[ray, gate]
    valid = inside & np.isfinite(sampled)
    scaled = np.clip(
        (sampled - float(vmin)) / max(float(vmax) - float(vmin), 1.0e-6),
        0.0,
        1.0,
    )
    rgb = apply_palette(
        (np.nan_to_num(scaled) * 255.0).astype("uint8"),
        palette,
    )
    rgba = np.zeros((size, size, 4), dtype="uint8")
    rgba[inside, :3] = (18, 22, 27)
    rgba[inside, 3] = 255
    rgba[valid, :3] = rgb[valid]
    image = Image.fromarray(rgba, mode="RGBA")
    draw = ImageDraw.Draw(image, mode="RGBA")
    for fraction in (0.25, 0.50, 0.75, 1.0):
        radius = centre * fraction
        draw.ellipse(
            (
                centre - radius,
                centre - radius,
                centre + radius,
                centre + radius,
            ),
            outline=(230, 235, 240, 80),
            width=1,
        )
    draw.line((centre, 0, centre, size), fill=(230, 235, 240, 55), width=1)
    draw.line((0, centre, size, centre), fill=(230, 235, 240, 55), width=1)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _validate_geometry(raw: Any, nrays: int, nbins: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("geometry must be an object")
    geometry_type = str(raw.get("type") or "")
    if geometry_type == "full_sweep":
        return {"type": "full_sweep"}
    if geometry_type == "polar_gate_polygon":
        vertices = raw.get("vertices")
        if not isinstance(vertices, list) or len(vertices) < 3:
            raise ValueError("polar polygon requires at least three vertices")
        checked = []
        for vertex in vertices:
            if not isinstance(vertex, list) or len(vertex) != 2:
                raise ValueError("polygon vertex must contain ray and gate")
            ray, gate = (float(value) for value in vertex)
            if not 0.0 <= ray < nrays or not 0.0 <= gate < nbins:
                raise ValueError("polygon vertex is outside the sweep")
            checked.append([round(ray, 4), round(gate, 4)])
        return {"type": geometry_type, "vertices": checked}
    if geometry_type == "row_major_rle":
        runs = raw.get("runs")
        if not isinstance(runs, list):
            raise ValueError("row-major RLE requires a runs array")
        maximum = nrays * nbins
        checked_runs = []
        for run in runs:
            if not isinstance(run, list) or len(run) != 2:
                raise ValueError("RLE run must contain offset and length")
            offset, length = (int(value) for value in run)
            if offset < 0 or length < 1 or offset + length > maximum:
                raise ValueError("RLE run is outside the sweep")
            checked_runs.append([offset, length])
        return {"type": geometry_type, "runs": checked_runs}
    raise ValueError(f"unsupported geometry type: {geometry_type}")


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
