"""Local blinded annotation store for temporal UK WSR review targets."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .export_types import FieldSelection
from .geospatial import read_polar_field_with_companions
from .qc_benchmark import LABEL_TAXONOMY, canonical_json_sha256
from .qc_review_app import (
    FIELD_RENDERING,
    REVIEW_STAGES,
    ReviewStore,
    render_polar_field_png,
)
from .qc_temporal_review import (
    TEMPORAL_REVIEW_ID,
    TEMPORAL_REVIEW_SCHEMA,
)


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class TemporalReviewStore:
    """Validated temporal targets and independent reviewer annotations."""

    def __init__(
        self,
        *,
        targets_path: str | Path,
        temporal_ledger_path: str | Path,
        regression_root: str | Path,
        output_dir: str | Path,
        reviewer: str,
        stage: str,
        radars: set[str] | None = None,
        pulses: set[str] | None = None,
        limit: int | None = None,
    ) -> None:
        self.targets_path = Path(targets_path)
        self.temporal_ledger_path = Path(temporal_ledger_path)
        self.regression_root = Path(regression_root)
        self.output_dir = Path(output_dir)
        self.reviewer = reviewer.strip()
        self.stage = stage.strip().lower()
        self.review_id = TEMPORAL_REVIEW_ID
        if not self.reviewer:
            raise ValueError("reviewer must not be empty")
        if self.stage not in REVIEW_STAGES:
            raise ValueError(f"invalid review stage: {stage}")

        self.review = json.loads(
            self.targets_path.read_text(encoding="utf-8")
        )
        if self.review.get("schema") != TEMPORAL_REVIEW_SCHEMA:
            raise ValueError("temporal review-target schema mismatch")
        if self.review.get("review_id") != TEMPORAL_REVIEW_ID:
            raise ValueError("temporal review id mismatch")
        if self.review.get("selection", {}).get(
            "sealed_holdout_opened"
        ) is not False:
            raise ValueError("temporal review does not prove holdout closure")

        ledger = json.loads(
            self.temporal_ledger_path.read_text(encoding="utf-8")
        )
        if (
            canonical_json_sha256(ledger)
            != self.review.get("download_ledger_sha256")
        ):
            raise ValueError("temporal review download-ledger hash mismatch")
        raw_files = ledger.get("files", {})
        ledger_rows = (
            list(raw_files.values())
            if isinstance(raw_files, dict)
            else list(raw_files)
        )
        self.temporal_sources = {
            str(item["source_id"]): item for item in ledger_rows
        }

        targets = []
        for target in self.review.get("targets", ()):
            if self.stage == "secondary" and not target.get(
                "double_review_required"
            ):
                continue
            if radars and str(target.get("radar")) not in radars:
                continue
            if pulses and str(target.get("pulse")) not in pulses:
                continue
            targets.append(target)
        if limit is not None:
            targets = targets[: max(0, int(limit))]
        if not targets:
            raise ValueError("temporal review selection contains no targets")
        self.targets = targets
        self.targets_by_id = {
            str(target["target_id"]): target for target in targets
        }
        if len(self.targets_by_id) != len(targets):
            raise ValueError("temporal review target ids are not unique")
        self._validate_sources()

        safe_reviewer = (
            SAFE_NAME.sub("-", self.reviewer).strip("-") or "reviewer"
        )
        self.annotation_path = (
            self.output_dir / f"{safe_reviewer}.{self.stage}.json"
        )
        self.annotation = self._load_annotation()

    def review_state(self) -> dict[str, Any]:
        completed = {
            str(item.get("target_id"))
            for item in self.annotation.get("items", ())
        }
        summaries = [
            {
                "target_id": target["target_id"],
                "radar": target["radar"],
                "pulse": target["pulse"],
                "date": target["date"],
                "time": target["time"],
                "dataset": target["dataset"],
                "elevation_deg": target["elevation_deg"],
                "split": target["split"],
                "selection_role": "stratified_case",
                "completed": target["target_id"] in completed,
            }
            for target in self.targets
        ]
        return {
            "review_id": TEMPORAL_REVIEW_ID,
            "reviewer": self.reviewer,
            "stage": self.stage,
            "target_count": len(summaries),
            "completed_count": sum(item["completed"] for item in summaries),
            "blinding": {
                "qc_outputs_visible": False,
                "ci_available_to_reviewer": False,
                "selection_identity_visible": False,
                "reported_failure_visible": False,
                "sealed_holdout_opened": False,
            },
            "taxonomy": LABEL_TAXONOMY,
            "targets": summaries,
        }

    def target_payload(self, target_id: str) -> dict[str, Any]:
        target = self._target(target_id)
        completed = next(
            (
                item
                for item in self.annotation.get("items", ())
                if item.get("target_id") == target_id
            ),
            None,
        )
        visible_fields = []
        for view in target.get("review_views", ()):
            quantity = str(view["quantity"]).upper()
            if quantity not in FIELD_RENDERING:
                continue
            vmin, vmax, _ = FIELD_RENDERING[quantity]
            visible_fields.append(
                {
                    "view_id": view["view_id"],
                    "label": view["label"],
                    "role": view["role"],
                    "quantity": quantity,
                    "annotation_primary": bool(
                        view.get("annotation_primary")
                    ),
                    "image_url": (
                        f"/api/targets/{target_id}/fields/"
                        f"{view['view_id']}.png"
                    ),
                    "scale_min": vmin,
                    "scale_max": vmax,
                }
            )
        return {
            "target_id": target_id,
            "case_id": target["job_id"],
            "radar": target["radar"],
            "pulse": target["pulse"],
            "date": target["date"],
            "time": target["time"],
            "dataset": target["dataset"],
            "elevation_deg": target["elevation_deg"],
            "shape": target["shape"],
            "split": target["split"],
            "season": target["season"],
            "utc_slot": target["utc_slot"],
            "selection_role": "stratified_case",
            "visible_fields": visible_fields,
            "coordinate_contract": {
                "geometry": "polar_gate_polygon",
                "vertex_order": ["ray_index", "gate_index"],
                "ray_origin": "north",
                "ray_direction": "clockwise",
                "gate_origin": "radar",
            },
            "annotation": completed,
        }

    def field_png(self, target_id: str, view_id: str) -> bytes:
        return self._render_view(target_id, view_id)

    def save_annotation(
        self,
        target_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        target = self._target(target_id)
        regions = ReviewStore._validate_regions(
            payload.get("regions"),
            target,
        )
        item = {
            "target_id": target_id,
            "job_id": target["job_id"],
            "geometry_id": target["geometry_id"],
            "dataset": target["dataset"],
            "elevation_deg": target["elevation_deg"],
            "quantity": "DBZH",
            "shape": list(target["shape"]),
            "review_stage": self.stage,
            "qc_outputs_visible": False,
            "ci_used_as_ground_truth": False,
            "selection_identity_visible": False,
            "reported_failure_visible": False,
            "sealed_holdout_opened": False,
            "regions": regions,
            "notes": str(payload.get("notes") or ""),
            "reviewed_at": _now_utc(),
        }
        items = [
            previous
            for previous in self.annotation.get("items", ())
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

    @lru_cache(maxsize=192)
    def _render_view(self, target_id: str, view_id: str) -> bytes:
        target = self._target(target_id)
        view = next(
            (
                item
                for item in target.get("review_views", ())
                if str(item.get("view_id")) == view_id
            ),
            None,
        )
        if view is None:
            raise KeyError(f"unknown temporal review view: {view_id}")
        quantity = str(view["quantity"]).upper()
        if quantity == "CI" or quantity not in FIELD_RENDERING:
            raise KeyError(f"field is not available in blinded review: {quantity}")
        source = view["source"]
        source_path = self._source_path(target, source)
        selection = FieldSelection(
            pulse=str(target["pulse"]),
            time=str(source["time"]),
            quantity="DBZH",
            dataset=str(source["dataset"]),
        )
        dbzh, _, companions = read_polar_field_with_companions(
            source_path,
            str(target["radar"]),
            str(source["date"]),
            selection,
            quantities=() if quantity == "DBZH" else (quantity,),
        )
        values = dbzh if quantity == "DBZH" else companions.get(quantity)
        if values is None:
            raise KeyError(f"source view is missing {quantity}")
        vmin, vmax, palette = FIELD_RENDERING[quantity]
        return render_polar_field_png(
            values,
            vmin=vmin,
            vmax=vmax,
            palette=palette,
        )

    def _target(self, target_id: str) -> dict[str, Any]:
        target = self.targets_by_id.get(str(target_id))
        if target is None:
            raise KeyError(f"unknown temporal review target: {target_id}")
        return target

    def _validate_sources(self) -> None:
        checked: set[tuple[str, str]] = set()
        for target in self.targets:
            for view in target.get("review_views", ()):
                source = view["source"]
                key = (
                    str(source["source_kind"]),
                    str(source["source_id"]),
                )
                if key in checked:
                    continue
                checked.add(key)
                path = self._source_path(target, source)
                if not path.exists():
                    raise FileNotFoundError(
                        f"temporal review source missing: {path}"
                    )
                expected_size = int(source["size_bytes"])
                if path.stat().st_size != expected_size:
                    raise ValueError(
                        f"temporal review source size mismatch: {path}"
                    )
                if source["source_kind"] == "regression":
                    if _file_sha256(path) != str(source["sha256"]):
                        raise ValueError(
                            f"regression source hash mismatch: {path}"
                        )

    def _source_path(
        self,
        target: Mapping[str, Any],
        source: Mapping[str, Any],
    ) -> Path:
        kind = str(source["source_kind"])
        if kind == "temporal":
            ledger = self.temporal_sources.get(str(source["source_id"]))
            if ledger is None:
                raise KeyError(
                    f"unknown temporal source: {source['source_id']}"
                )
            if str(ledger.get("sha256") or "") != str(source["sha256"]):
                raise ValueError(
                    f"temporal source ledger hash mismatch: {source['source_id']}"
                )
            return Path(str(ledger["local_path"]))
        if kind == "regression":
            return (
                self.regression_root
                / str(target["radar"])
                / str(target["date"])
                / str(target["pulse"])
                / str(source["filename"])
            )
        raise KeyError(f"unsupported temporal review source kind: {kind}")

    def _load_annotation(self) -> dict[str, Any]:
        targets_hash = canonical_json_sha256(self.review)
        if self.annotation_path.exists():
            annotation = json.loads(
                self.annotation_path.read_text(encoding="utf-8")
            )
            if annotation.get("review_targets_sha256") != targets_hash:
                raise ValueError(
                    "existing annotations use different temporal targets"
                )
            if annotation.get("reviewer") != self.reviewer:
                raise ValueError("existing annotation reviewer mismatch")
            if annotation.get("review_stage") != self.stage:
                raise ValueError("existing annotation stage mismatch")
            return annotation
        return {
            "schema": "uk_wsr_qc_temporal_annotations",
            "schema_version": 1,
            "review_id": TEMPORAL_REVIEW_ID,
            "review_targets_sha256": targets_hash,
            "reviewer": self.reviewer,
            "review_stage": self.stage,
            "created_at": _now_utc(),
            "review_policy": {
                "qc_outputs_visible": False,
                "ci_used_as_ground_truth": False,
                "selection_identity_visible": False,
                "reported_failure_visible": False,
                "sealed_holdout_opened": False,
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
