"""Real-data field semantics audit for public UKMO WSR PVOL files."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .dependencies import require_h5py, require_numpy
from .export_types import FieldSelection
from .geospatial import polar_to_cartesian, read_polar_field_with_companions, scalar
from .preview import apply_palette
from .qc import QCConfig, QCMaskFlag, build_qc_mask, normalized_quantity

PUBLIC_BASE = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"
DEFAULT_SAMPLE_ANCHORS = (
    ("20260115", "0000"),
    ("20260415", "1200"),
    ("20260711", "2100"),
)
AUDIT_FIELDS = (
    "CI",
    "SQIH",
    "VRADH",
    "WRADH",
    "RHOHV",
    "ZDR",
    "PHIDP",
    "LONG_RANGE_NOISE_DBC_H",
    "LONG_RANGE_NOISE_DBC_V",
)
DBZH_HISTOGRAM_EDGES = tuple(float(value) for value in range(-40, 82, 2))
CI_HISTOGRAM_EDGES = tuple(-0.125 + 0.25 * index for index in range(34))


@dataclass(frozen=True)
class SampleAnchor:
    date: str
    time: str


@dataclass
class AuditAccumulator:
    """Streaming aggregate that avoids retaining gate arrays."""

    np: Any
    rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    field_counts: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    sweep_counts: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    aggregate: dict[str, dict[str, Any]] = field(default_factory=dict)
    dbzh_histograms: dict[str, Any] = field(default_factory=dict)
    removed_histograms: dict[str, Any] = field(default_factory=dict)
    ci_dbzh_histograms: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls) -> "AuditAccumulator":
        np = require_numpy()
        instance = cls(np=np)
        for pulse in ("lp", "sp"):
            instance.dbzh_histograms[pulse] = np.zeros(len(DBZH_HISTOGRAM_EDGES) - 1, dtype="int64")
            instance.removed_histograms[pulse] = np.zeros(len(DBZH_HISTOGRAM_EDGES) - 1, dtype="int64")
            instance.ci_dbzh_histograms[pulse] = np.zeros(
                (len(CI_HISTOGRAM_EDGES) - 1, len(DBZH_HISTOGRAM_EDGES) - 1),
                dtype="int64",
            )
        return instance

    def add(self, row: dict[str, Any], arrays: dict[str, Any]) -> None:
        np = self.np
        self.rows.append(row)
        radar = str(row["radar"])
        pulse = str(row["pulse"])
        self.sweep_counts[(radar, pulse)] += 1
        for quantity in row["companion_quantities"]:
            self.field_counts[(radar, pulse, str(quantity))] += 1

        for key in (pulse, f"{radar}:{pulse}"):
            bucket = self.aggregate.setdefault(key, _empty_bucket())
            bucket["sweep_count"] += 1
            for count_name in (
                "finite_gate_count",
                "receiver_noise_count",
                "receiver_noise_ge_0_dbz",
                "receiver_noise_ge_10_dbz",
                "receiver_noise_ge_20_dbz",
                "ci_finite_count",
                "ci_low_count",
                "ci_high_count",
                "ci_high_receiver_noise_count",
                "near_zero_vrad_count",
                "low_sqi_count",
            ):
                bucket[count_name] += int(row.get(count_name) or 0)
            bucket["receiver_noise_max_dbz"] = _max_optional(
                bucket["receiver_noise_max_dbz"],
                row.get("receiver_noise_max_dbz"),
            )
            bucket["rxnoise_h_values"].append(row.get("receiver_noise_figure_h_db"))
            bucket["rxnoise_v_values"].append(row.get("receiver_noise_figure_v_db"))
            bucket["ambient_noise_h_values"].append(row.get("ambient_noise_h_median"))
            bucket["ambient_noise_v_values"].append(row.get("ambient_noise_v_median"))

        finite = arrays["finite"]
        dbzh = arrays["dbzh"]
        removed = arrays["removed"]
        self.dbzh_histograms[pulse] += np.histogram(
            dbzh[finite],
            bins=np.asarray(DBZH_HISTOGRAM_EDGES),
        )[0]
        self.removed_histograms[pulse] += np.histogram(
            dbzh[finite & removed],
            bins=np.asarray(DBZH_HISTOGRAM_EDGES),
        )[0]
        ci = arrays.get("ci")
        if ci is not None:
            joint = finite & np.isfinite(ci)
            self.ci_dbzh_histograms[pulse] += np.histogram2d(
                ci[joint],
                dbzh[joint],
                bins=(
                    np.asarray(CI_HISTOGRAM_EDGES),
                    np.asarray(DBZH_HISTOGRAM_EDGES),
                ),
            )[0].astype("int64")

    def summary(self, plan: dict[str, Any]) -> dict[str, Any]:
        radars = sorted({str(entry["radar"]) for entry in plan.get("files", [])})
        aggregate = {
            key: _finish_bucket(value)
            for key, value in sorted(self.aggregate.items())
        }
        field_coverage = []
        for radar in radars:
            for pulse in ("lp", "sp"):
                denominator = self.sweep_counts.get((radar, pulse), 0)
                fields = {
                    quantity: {
                        "sweep_count": self.field_counts.get((radar, pulse, quantity), 0),
                        "fraction": (
                            self.field_counts.get((radar, pulse, quantity), 0) / denominator
                            if denominator
                            else 0.0
                        ),
                    }
                    for quantity in AUDIT_FIELDS
                }
                field_coverage.append(
                    {
                        "radar": radar,
                        "pulse": pulse,
                        "sweep_count": denominator,
                        "fields": fields,
                    }
                )
        return {
            "schema": "uk_wsr_field_semantics_audit",
            "schema_version": 1,
            "generated_at": _now_utc(),
            "sample_design": plan.get("sample_design"),
            "planned_file_count": len(plan.get("files", [])),
            "audited_file_count": len({row["local_path"] for row in self.rows}),
            "audited_sweep_count": len(self.rows),
            "radar_count": len({row["radar"] for row in self.rows}),
            "errors": self.errors,
            "aggregate": aggregate,
            "field_coverage": field_coverage,
            "histograms": {
                "dbzh_edges": list(DBZH_HISTOGRAM_EDGES),
                "ci_edges": list(CI_HISTOGRAM_EDGES),
                "dbzh_all": {pulse: values.tolist() for pulse, values in self.dbzh_histograms.items()},
                "dbzh_receiver_noise": {
                    pulse: values.tolist()
                    for pulse, values in self.removed_histograms.items()
                },
                "ci_by_dbzh": {
                    pulse: values.tolist()
                    for pulse, values in self.ci_dbzh_histograms.items()
                },
            },
            "sweeps": self.rows,
        }


def build_sample_plan(
    root_catalog: dict[str, Any],
    fetch_json: Callable[[str], dict[str, Any]],
    *,
    anchors: Iterable[SampleAnchor] | None = None,
    pulses: tuple[str, ...] = ("lp", "sp"),
    public_base: str = PUBLIC_BASE,
) -> dict[str, Any]:
    """Choose one PVOL per radar/pulse at each independent date/time anchor."""

    selected_anchors = tuple(anchors or (SampleAnchor(*value) for value in DEFAULT_SAMPLE_ANCHORS))
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    coverage_cache: dict[str, dict[str, Any]] = {}
    day_cache: dict[str, dict[str, Any]] = {}

    for radar_entry in sorted(root_catalog.get("radars", []), key=lambda value: str(value.get("radar") or "")):
        radar = str(radar_entry.get("radar") or "")
        for anchor in selected_anchors:
            coverage_key = _coverage_key(radar_entry, anchor.date[:4])
            if not coverage_key:
                errors.append({"radar": radar, "anchor": f"{anchor.date}:{anchor.time}", "error": "coverage_missing"})
                continue
            coverage_url = _public_url(public_base, coverage_key)
            if coverage_url not in coverage_cache:
                coverage_cache[coverage_url] = fetch_json(coverage_url)
            coverage = coverage_cache[coverage_url]
            day = _nearest_day(coverage.get("days", []), anchor.date)
            if day is None:
                errors.append({"radar": radar, "anchor": f"{anchor.date}:{anchor.time}", "error": "day_missing"})
                continue
            catalog_url = _public_url(public_base, str(day["catalog_key"]))
            if catalog_url not in day_cache:
                day_cache[catalog_url] = fetch_json(catalog_url)
            catalog = day_cache[catalog_url]
            for pulse in pulses:
                source = _nearest_file(catalog.get("files", []), pulse=pulse, target_time=anchor.time)
                if source is None:
                    errors.append(
                        {
                            "radar": radar,
                            "anchor": f"{anchor.date}:{anchor.time}",
                            "selected_date": day.get("date"),
                            "pulse": pulse,
                            "error": "pulse_file_missing",
                        }
                    )
                    continue
                files.append(
                    {
                        "radar": radar,
                        "radar_num": radar_entry.get("radar_num"),
                        "anchor_date": anchor.date,
                        "anchor_time": anchor.time,
                        "date": str(day["date"]),
                        "time": str(source["time"]),
                        "pulse": pulse,
                        "filename": source["filename"],
                        "object_key": source.get("object_key"),
                        "object_url": source.get("object_url")
                        or _public_url(public_base, str(source.get("object_key") or "")),
                        "size_bytes": int(source.get("size_bytes") or 0),
                        "season": _season(str(day["date"])),
                        "time_bucket": _time_bucket(str(source["time"])),
                    }
                )
    files.sort(key=lambda value: (value["radar"], value["date"], value["pulse"], value["time"]))
    return {
        "schema": "uk_wsr_field_audit_sample_plan",
        "schema_version": 1,
        "generated_at": _now_utc(),
        "sample_design": {
            "description": "one full PVOL per radar and pulse at three independent seasonal/day-night anchors",
            "anchors": [{"date": value.date, "time": value.time} for value in selected_anchors],
            "pulses": list(pulses),
            "all_elevations_per_file": True,
            "selection": "nearest available date and nearest time within pulse",
        },
        "radar_count": len({entry["radar"] for entry in files}),
        "file_count": len(files),
        "errors": errors,
        "files": files,
    }


def audit_plan(plan: dict[str, Any], *, cache_dir: str | Path) -> dict[str, Any]:
    """Audit downloaded files in a sample plan."""

    accumulator = AuditAccumulator.create()
    cache = Path(cache_dir)
    for index, entry in enumerate(plan.get("files", []), start=1):
        source = local_path_for_entry(cache, entry)
        if not source.exists():
            accumulator.errors.append(
                {
                    "radar": entry.get("radar"),
                    "date": entry.get("date"),
                    "pulse": entry.get("pulse"),
                    "error": "source_file_missing",
                    "local_path": str(source),
                }
            )
            continue
        try:
            for target in discover_reflectivity_sweeps(source):
                row, arrays = audit_sweep(source, entry, target)
                accumulator.add(row, arrays)
        except Exception as exc:  # noqa: BLE001 - audit records file-level failures and continues.
            accumulator.errors.append(
                {
                    "radar": entry.get("radar"),
                    "date": entry.get("date"),
                    "pulse": entry.get("pulse"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "local_path": str(source),
                }
            )
        print(
            json.dumps(
                {
                    "audit_progress": f"{index}/{len(plan.get('files', []))}",
                    "radar": entry.get("radar"),
                    "date": entry.get("date"),
                    "pulse": entry.get("pulse"),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    return accumulator.summary(plan)


def discover_reflectivity_sweeps(source: str | Path) -> list[dict[str, Any]]:
    """Return every top-level DBZH sweep represented in one aggregate PVOL."""

    h5py = require_h5py()
    targets: list[dict[str, Any]] = []
    with h5py.File(source, "r") as h5:
        for dataset_name in sorted(
            (name for name in h5 if name.startswith("dataset")),
            key=_dataset_sort_key,
        ):
            dataset = h5[dataset_name]
            quantity = ""
            for name, group in dataset.items():
                if not name.startswith("data") or not isinstance(group, h5py.Group):
                    continue
                candidate = normalized_quantity(_group_quantity(group))
                if candidate == "DBZH":
                    quantity = candidate
                    break
            if not quantity:
                continue
            where = dataset.get("where")
            targets.append(
                {
                    "dataset": dataset_name,
                    "quantity": quantity,
                    "elevation_deg": (
                        float(where.attrs["elangle"])
                        if where is not None and "elangle" in where.attrs
                        else None
                    ),
                }
            )
    return targets


def audit_sweep(
    source: str | Path,
    entry: dict[str, Any],
    target: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Audit one DBZH sweep and return metrics plus transient arrays."""

    np = require_numpy()
    path = Path(source)
    selection = FieldSelection(
        pulse=str(entry["pulse"]),
        time=str(entry["time"]),
        quantity=str(target["quantity"]),
        dataset=str(target["dataset"]),
    )
    values, metadata, companions = read_polar_field_with_companions(
        path,
        str(entry["radar"]),
        str(entry["date"]),
        selection,
    )
    dbzh = np.asarray(values, dtype="float32")
    finite = np.isfinite(dbzh)
    qc = build_qc_mask(
        dbzh,
        metadata=metadata,
        companion_fields=companions,
        config=_audit_qc_config(),
    )
    removed = (qc.mask & int(QCMaskFlag.RECEIVER_NOISE)) != 0
    ci = _first_field(companions, ("CI", "APD", "CLUTTER_INDICATOR"))
    sqi = _first_field(companions, ("SQIH", "SQI", "QIND"))
    vrad = _first_field(companions, ("VRADH", "VRADDH", "VRAD", "VRADV"))
    ambient_h = _first_field(companions, ("LONG_RANGE_NOISE_DBC_H", "AMBIENT_NOISE_DBC_H"))
    ambient_v = _first_field(companions, ("LONG_RANGE_NOISE_DBC_V", "AMBIENT_NOISE_DBC_V"))
    ci_finite = finite & np.isfinite(ci) if ci is not None else np.zeros(dbzh.shape, dtype=bool)
    ci_low = ci_finite & (ci <= 2.0) if ci is not None else np.zeros(dbzh.shape, dtype=bool)
    ci_high = ci_finite & (ci >= 6.0) if ci is not None else np.zeros(dbzh.shape, dtype=bool)
    near_zero_vrad = (
        finite & np.isfinite(vrad) & (np.abs(vrad) <= 0.5)
        if vrad is not None
        else np.zeros(dbzh.shape, dtype=bool)
    )
    low_sqi = (
        finite & np.isfinite(sqi) & (sqi <= 0.05)
        if sqi is not None
        else np.zeros(dbzh.shape, dtype=bool)
    )
    row = {
        "radar": entry["radar"],
        "date": entry["date"],
        "time": entry["time"],
        "pulse": entry["pulse"],
        "season": entry.get("season"),
        "time_bucket": entry.get("time_bucket"),
        "dataset": metadata.dataset,
        "elevation_deg": metadata.elevation_deg,
        "shape": list(dbzh.shape),
        "local_path": str(path),
        "source_url": entry.get("object_url"),
        "companion_quantities": sorted(companions),
        "finite_gate_count": int(finite.sum()),
        "receiver_noise_count": int((finite & removed).sum()),
        "receiver_noise_fraction": _fraction((finite & removed).sum(), finite.sum()),
        "receiver_noise_ge_0_dbz": int((finite & removed & (dbzh >= 0.0)).sum()),
        "receiver_noise_ge_10_dbz": int((finite & removed & (dbzh >= 10.0)).sum()),
        "receiver_noise_ge_20_dbz": int((finite & removed & (dbzh >= 20.0)).sum()),
        "receiver_noise_max_dbz": _finite_max(dbzh[finite & removed]),
        "dbzh": _array_stats(dbzh[finite]),
        "receiver_noise_dbzh": _array_stats(dbzh[finite & removed]),
        "ci": _array_stats(ci[ci_finite]) if ci is not None else _array_stats([]),
        "ci_finite_count": int(ci_finite.sum()),
        "ci_low_count": int(ci_low.sum()),
        "ci_high_count": int(ci_high.sum()),
        "ci_high_receiver_noise_count": int((ci_high & removed).sum()),
        "near_zero_vrad_count": int(near_zero_vrad.sum()),
        "low_sqi_count": int(low_sqi.sum()),
        "near_zero_vrad_with_low_ci_count": int((near_zero_vrad & ci_low).sum()),
        "near_zero_vrad_with_high_ci_count": int((near_zero_vrad & ci_high).sum()),
        "receiver_noise_figure_h_db": metadata.attrs.get("uk_wsr:receiver_noise_figure_h_db"),
        "receiver_noise_figure_v_db": metadata.attrs.get("uk_wsr:receiver_noise_figure_v_db"),
        "receiver_noise_figure_role": metadata.attrs.get("uk_wsr:receiver_noise_figure_role"),
        "ambient_noise_h_median": _finite_percentile(ambient_h, 50),
        "ambient_noise_v_median": _finite_percentile(ambient_v, 50),
        "noise_floor_profile": _array_stats(qc.floor_profile),
        "evidence_counts": qc.evidence_counts,
    }
    return row, {
        "dbzh": dbzh,
        "finite": finite,
        "removed": removed,
        "ci": ci,
    }


def write_audit_artifacts(summary: dict[str, Any], output_dir: str | Path) -> None:
    """Persist JSON, CSV, Markdown, and diagnostic PNGs."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _write_case_diagnostics(summary, output)
    published = _without_local_paths(summary)
    (output / "summary.json").write_text(
        json.dumps(published, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_sweep_csv(published.get("sweeps", []), output / "sweeps.csv")
    _plot_field_coverage(published, output / "field_coverage.png")
    _plot_receiver_noise_by_radar(published, output / "receiver_noise_by_radar.png")
    _plot_removal_rate_by_dbzh(published, output / "removal_rate_by_dbzh.png")
    _plot_ci_dbzh(published, output / "ci_by_dbzh.png")
    (output / "README.md").write_text(audit_markdown(published), encoding="utf-8")


def audit_markdown(summary: dict[str, Any]) -> str:
    """Render the evidence-led field semantics report."""

    rows = []
    for coverage in summary.get("field_coverage", []):
        radar = coverage["radar"]
        pulse = coverage["pulse"]
        key = f"{radar}:{pulse}"
        aggregate = summary.get("aggregate", {}).get(key, {})
        fields = coverage.get("fields", {})
        rows.append(
            "| {radar} | {pulse} | {sweeps} | {ci:.0f}% | {sqi:.0f}% | {vrad:.0f}% | {removed:.2f}% | {max_dbzh} | {ge10} | {ge20} |".format(
                radar=radar,
                pulse=pulse.upper(),
                sweeps=coverage.get("sweep_count", 0),
                ci=100.0 * fields.get("CI", {}).get("fraction", 0.0),
                sqi=100.0 * fields.get("SQIH", {}).get("fraction", 0.0),
                vrad=100.0 * fields.get("VRADH", {}).get("fraction", 0.0),
                removed=100.0 * float(aggregate.get("receiver_noise_fraction") or 0.0),
                max_dbzh=_format_optional(aggregate.get("receiver_noise_max_dbz"), digits=1),
                ge10=aggregate.get("receiver_noise_ge_10_dbz", 0),
                ge20=aggregate.get("receiver_noise_ge_20_dbz", 0),
            )
        )
    lp = summary.get("aggregate", {}).get("lp", {})
    sp = summary.get("aggregate", {}).get("sp", {})
    sp_removed = int(sp.get("receiver_noise_count") or 0)
    sp_ge_10 = int(sp.get("receiver_noise_ge_10_dbz") or 0)
    sp_ge_10_share = 100.0 * sp_ge_10 / sp_removed if sp_removed else 0.0
    return f"""# UKMO WSR Field Semantics and qc-v2 Receiver-Noise Audit

Status: **real-data descriptive audit; not a labelled accuracy result.**

The sample contains {summary.get('audited_file_count', 0)} complete public
PVOL/HDF5 files from {summary.get('radar_count', 0)} radars and
{summary.get('audited_sweep_count', 0)} DBZH sweeps. Each PVOL contributes all
elevations. Dates and times were selected from independent seasonal/day-night
anchors before inspecting field values.

## Immediate Findings

- LP receiver-noise mask share: {100.0 * float(lp.get('receiver_noise_fraction') or 0.0):.2f}%.
- SP receiver-noise mask share: {100.0 * float(sp.get('receiver_noise_fraction') or 0.0):.2f}%.
- Maximum LP DBZH removed: {_format_optional(lp.get('receiver_noise_max_dbz'), digits=1)} dBZ.
- Maximum SP DBZH removed: {_format_optional(sp.get('receiver_noise_max_dbz'), digits=1)} dBZ.
- Gates at or above 10 dBZ removed: LP {lp.get('receiver_noise_ge_10_dbz', 0):,}, SP {sp_ge_10:,} ({sp_ge_10_share:.1f}% of SP removals).
- Gates at or above 20 dBZ removed: LP {lp.get('receiver_noise_ge_20_dbz', 0)}, SP {sp.get('receiver_noise_ge_20_dbz', 0)}.

The `RXnoiseH` and `RXnoiseV` attributes are reported as calibration metadata,
not as DBZH thresholds. `LONG_RANGE_NOISE_DBC_*` is audited separately because
its validity and scaling differ by pulse and radar. LP has finite receiver-noise
figures and plausible long-range-noise values. SP reports zero receiver-noise
figures and a constant -32 dBc long-range sentinel, so neither provides a
usable SP noise threshold.

CI is present on every audited sweep. Values at or above 6 occur on
{100.0 * float(lp.get('ci_high_fraction') or 0.0):.1f}% of finite LP gates and
{100.0 * float(sp.get('ci_high_fraction') or 0.0):.1f}% of finite SP gates.
That prevalence, plus the absence of a field-level definition in the source
files, means CI is evidence rather than a target label.

## Coverage and Mask Behaviour

| Radar | Pulse | Sweeps | CI | SQI | VRAD | Receiver noise removed | Maximum removed dBZ | Removed >=10 dBZ | Removed >=20 dBZ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

## Plots

![Field coverage](field_coverage.png)

![Receiver-noise fraction by radar](receiver_noise_by_radar.png)

![Removal rate by DBZH](removal_rate_by_dbzh.png)

![CI distribution by DBZH](ci_by_dbzh.png)

## Before, Mask, and Retained Signal

The gallery shows the highest-risk sweep for each SP radar plus eight LP
comparators. Red gates are the exact `RECEIVER_NOISE` bit in the persisted
qc-v2 mask; the right panel is the retained field. Individual full-resolution
cases are in [`cases/`](cases/).

![Worst-case before/mask/after gallery](worst_case_gallery.png)

## Interpretation Limits

This report establishes field availability, scaling, correlations, and the
behaviour of the current conservative mask. It does not establish whether an
individual removed gate is truly receiver noise. That requires independently
labelled weather, biological, clutter, interference, and clear-air objects.
The report is therefore an input to the benchmark corpus, not permission to
increase removal.
"""


def _audit_qc_config() -> QCConfig:
    return QCConfig(
        mode="signal_preserving",
        operation="mask",
        noise_floor_enabled=True,
        noise_floor_hard_mask=False,
        receiver_noise_enabled=True,
        receiver_noise_margin_db=0.25,
        texture_enabled=False,
        companion_qc_enabled=False,
        static_clutter_enabled=False,
        background_model_enabled=False,
    )


def local_path_for_entry(cache_dir: Path, entry: dict[str, Any]) -> Path:
    return (
        cache_dir
        / str(entry["radar"])
        / str(entry["date"])
        / str(entry["pulse"])
        / str(entry["filename"])
    )


def _empty_bucket() -> dict[str, Any]:
    return {
        "sweep_count": 0,
        "finite_gate_count": 0,
        "receiver_noise_count": 0,
        "receiver_noise_ge_0_dbz": 0,
        "receiver_noise_ge_10_dbz": 0,
        "receiver_noise_ge_20_dbz": 0,
        "receiver_noise_max_dbz": None,
        "ci_finite_count": 0,
        "ci_low_count": 0,
        "ci_high_count": 0,
        "ci_high_receiver_noise_count": 0,
        "near_zero_vrad_count": 0,
        "low_sqi_count": 0,
        "rxnoise_h_values": [],
        "rxnoise_v_values": [],
        "ambient_noise_h_values": [],
        "ambient_noise_v_values": [],
    }


def _finish_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    result = dict(bucket)
    result["receiver_noise_fraction"] = _fraction(
        bucket["receiver_noise_count"],
        bucket["finite_gate_count"],
    )
    result["ci_low_fraction"] = _fraction(bucket["ci_low_count"], bucket["ci_finite_count"])
    result["ci_high_fraction"] = _fraction(bucket["ci_high_count"], bucket["ci_finite_count"])
    result["receiver_noise_given_high_ci_fraction"] = _fraction(
        bucket["ci_high_receiver_noise_count"],
        bucket["ci_high_count"],
    )
    for name in (
        "rxnoise_h_values",
        "rxnoise_v_values",
        "ambient_noise_h_values",
        "ambient_noise_v_values",
    ):
        result[name.removesuffix("_values")] = _array_stats(bucket[name])
        del result[name]
    return result


def _coverage_key(radar_entry: dict[str, Any], year: str) -> str | None:
    suffix = f"/{year}/coverage.json"
    return next(
        (
            str(value)
            for value in radar_entry.get("coverage_keys", [])
            if str(value).endswith(suffix)
        ),
        None,
    )


def _nearest_day(days: Iterable[dict[str, Any]], target_date: str) -> dict[str, Any] | None:
    wanted = datetime.strptime(target_date, "%Y%m%d").date()
    candidates = [day for day in days if day.get("date")]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda day: (
            abs((datetime.strptime(str(day["date"]), "%Y%m%d").date() - wanted).days),
            str(day["date"]),
        ),
    )


def _nearest_file(
    files: Iterable[dict[str, Any]],
    *,
    pulse: str,
    target_time: str,
) -> dict[str, Any] | None:
    wanted = _minutes(target_time)
    candidates = [entry for entry in files if str(entry.get("pulse") or "").lower() == pulse.lower()]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda entry: (
            abs(_minutes(str(entry.get("time") or "0000")) - wanted),
            str(entry.get("time") or ""),
        ),
    )


def _minutes(value: str) -> int:
    text = str(value).zfill(4)
    return int(text[:2]) * 60 + int(text[2:4])


def _season(date: str) -> str:
    month = int(date[4:6])
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _time_bucket(time: str) -> str:
    hour = int(str(time).zfill(4)[:2])
    return "day" if 6 <= hour < 18 else "night"


def _public_url(base: str, key: str) -> str:
    if key.startswith(("http://", "https://")):
        return key
    return f"{base.rstrip('/')}/{key.lstrip('/')}"


def _dataset_sort_key(name: str) -> tuple[int, str]:
    suffix = str(name).removeprefix("dataset")
    return (int(suffix) if suffix.isdigit() else 10_000, str(name))


def _group_quantity(group: Any) -> str:
    what = group.get("what")
    if what is None or "quantity" not in what.attrs:
        return ""
    return str(scalar(what.attrs["quantity"]))


def _first_field(fields: dict[str, Any], candidates: tuple[str, ...]) -> Any | None:
    return next((fields[name] for name in candidates if name in fields), None)


def _array_stats(values: Any) -> dict[str, Any]:
    np = require_numpy()
    array = np.asarray(values, dtype="float64").reshape(-1)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return {"count": 0, "min": None, "p10": None, "p50": None, "p90": None, "max": None}
    percentiles = np.percentile(finite, [10, 50, 90])
    return {
        "count": int(finite.size),
        "min": float(finite.min()),
        "p10": float(percentiles[0]),
        "p50": float(percentiles[1]),
        "p90": float(percentiles[2]),
        "max": float(finite.max()),
    }


def _finite_percentile(values: Any | None, percentile: float) -> float | None:
    if values is None:
        return None
    return _array_stats(values)[f"p{int(percentile)}"]


def _finite_max(values: Any) -> float | None:
    return _array_stats(values)["max"]


def _fraction(numerator: Any, denominator: Any) -> float:
    denominator_value = int(denominator or 0)
    return float(numerator or 0) / denominator_value if denominator_value else 0.0


def _max_optional(first: Any, second: Any) -> float | None:
    values = [float(value) for value in (first, second) if value not in (None, "")]
    return max(values) if values else None


def _format_optional(value: Any, *, digits: int) -> str:
    return "none" if value is None else f"{float(value):.{digits}f}"


def _without_local_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_local_paths(item)
            for key, item in value.items()
            if key != "local_path"
        }
    if isinstance(value, list):
        return [_without_local_paths(item) for item in value]
    return value


def _write_sweep_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = (
        "radar",
        "date",
        "time",
        "pulse",
        "dataset",
        "elevation_deg",
        "finite_gate_count",
        "receiver_noise_count",
        "receiver_noise_fraction",
        "receiver_noise_max_dbz",
        "receiver_noise_ge_10_dbz",
        "receiver_noise_ge_20_dbz",
        "ci_finite_count",
        "ci_low_count",
        "ci_high_count",
        "near_zero_vrad_count",
        "low_sqi_count",
        "receiver_noise_figure_h_db",
        "receiver_noise_figure_v_db",
        "ambient_noise_h_median",
        "ambient_noise_v_median",
        "source_url",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _plot_field_coverage(summary: dict[str, Any], path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    rows = summary.get("field_coverage", [])
    cell_w, cell_h = 116, 28
    left, top = 230, 72
    width = left + cell_w * len(AUDIT_FIELDS) + 30
    height = top + cell_h * len(rows) + 45
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((20, 18), "Field availability by radar, pulse, and sweep", fill=(20, 30, 40), font=font)
    for index, field_name in enumerate(AUDIT_FIELDS):
        draw.text((left + index * cell_w + 4, 48), field_name.replace("LONG_RANGE_", "LR_"), fill=(40, 50, 60), font=font)
    for row_index, row in enumerate(rows):
        y = top + row_index * cell_h
        label = f"{row['radar']}  {str(row['pulse']).upper()}"
        draw.text((20, y + 7), label, fill=(30, 40, 50), font=font)
        for column, field_name in enumerate(AUDIT_FIELDS):
            fraction = float(row["fields"][field_name]["fraction"])
            color = _coverage_color(fraction)
            x = left + column * cell_w
            draw.rectangle((x, y, x + cell_w - 2, y + cell_h - 2), fill=color)
            draw.text((x + 42, y + 7), f"{100 * fraction:.0f}%", fill=(20, 30, 40), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _plot_receiver_noise_by_radar(summary: dict[str, Any], path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    radars = sorted(
        {
            key.rsplit(":", 1)[0]
            for key in summary.get("aggregate", {})
            if ":" in key
        }
    )
    width, height = 1500, 760
    left, top, bottom = 250, 70, 70
    plot_w, plot_h = width - left - 60, height - top - bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((20, 18), "qc-v2 receiver-noise mask share", fill=(20, 30, 40), font=font)
    maximum = max(
        [
            float(summary["aggregate"].get(f"{radar}:{pulse}", {}).get("receiver_noise_fraction") or 0.0)
            for radar in radars
            for pulse in ("lp", "sp")
        ]
        + [0.01]
    )
    row_h = plot_h / max(1, len(radars))
    for index, radar in enumerate(radars):
        y = top + index * row_h
        draw.text((20, int(y + row_h * 0.35)), radar, fill=(30, 40, 50), font=font)
        for pulse, offset, color in (("lp", 0.18, (15, 118, 110)), ("sp", 0.55, (221, 112, 44))):
            value = float(summary["aggregate"].get(f"{radar}:{pulse}", {}).get("receiver_noise_fraction") or 0.0)
            bar_y = int(y + row_h * offset)
            bar_h = max(4, int(row_h * 0.25))
            bar_w = int(plot_w * value / maximum)
            draw.rectangle((left, bar_y, left + bar_w, bar_y + bar_h), fill=color)
            draw.text((left + bar_w + 6, bar_y), f"{pulse.upper()} {100 * value:.2f}%", fill=(30, 40, 50), font=font)
    image.save(path)


def _plot_removal_rate_by_dbzh(summary: dict[str, Any], path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1300, 680
    left, top, right, bottom = 90, 60, 45, 75
    plot_w, plot_h = width - left - right, height - top - bottom
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((20, 18), "Receiver-noise removal rate by DBZH bin", fill=(20, 30, 40), font=font)
    edges = summary["histograms"]["dbzh_edges"]
    rate_series: dict[str, list[float]] = {}
    for pulse in ("lp", "sp"):
        all_counts = summary["histograms"]["dbzh_all"][pulse]
        removed = summary["histograms"]["dbzh_receiver_noise"][pulse]
        rate_series[pulse] = [float(r) / a if a else 0.0 for r, a in zip(removed, all_counts)]
    maximum_rate = max((value for values in rate_series.values() for value in values), default=0.0)
    y_max = min(1.0, max(0.05, math.ceil(maximum_rate * 1.1 * 20.0) / 20.0))

    for tick in range(6):
        fraction = y_max * tick / 5.0
        y = top + plot_h * (1.0 - fraction / y_max)
        draw.line((left, int(y), left + plot_w, int(y)), fill=(225, 230, 234), width=1)
        draw.text((25, int(y - 5)), f"{100 * fraction:.0f}%", fill=(50, 60, 70), font=font)
    draw.line((left, top, left, top + plot_h), fill=(90, 100, 110), width=1)
    draw.line((left, top + plot_h, left + plot_w, top + plot_h), fill=(90, 100, 110), width=1)

    for pulse, color in (("lp", (15, 118, 110)), ("sp", (221, 112, 44))):
        rates = rate_series[pulse]
        points = []
        for index, rate in enumerate(rates):
            x = left + plot_w * index / max(1, len(rates) - 1)
            y = top + plot_h * (1.0 - min(y_max, rate) / y_max)
            points.append((int(x), int(y)))
        if len(points) > 1:
            draw.line(points, fill=color, width=4)
    for value in range(-40, 81, 20):
        x = left + plot_w * (value - edges[0]) / (edges[-1] - edges[0])
        draw.text((int(x - 12), top + plot_h + 12), str(value), fill=(50, 60, 70), font=font)
    draw.text((left + plot_w // 2 - 35, top + plot_h + 36), "DBZH (dBZ)", fill=(50, 60, 70), font=font)
    draw.text((left + plot_w - 150, top + 10), "LP", fill=(15, 118, 110), font=font)
    draw.text((left + plot_w - 90, top + 10), "SP", fill=(221, 112, 44), font=font)
    image.save(path)


def _plot_ci_dbzh(summary: dict[str, Any], path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1400, 670
    panel_w, panel_h = 610, 520
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((20, 18), "CI distribution by DBZH", fill=(20, 30, 40), font=font)
    for panel, pulse in enumerate(("lp", "sp")):
        values = require_numpy().asarray(summary["histograms"]["ci_by_dbzh"][pulse], dtype="float64")
        transformed = require_numpy().log1p(values)
        maximum = float(transformed.max()) or 1.0
        x0 = 80 + panel * 670
        y0 = 70
        rows, columns = transformed.shape
        for row in range(rows):
            for column in range(columns):
                fraction = float(transformed[row, column] / maximum)
                color = _heat_color(fraction)
                x1 = x0 + int(panel_w * column / columns)
                x2 = x0 + int(panel_w * (column + 1) / columns)
                y1 = y0 + int(panel_h * (rows - row - 1) / rows)
                y2 = y0 + int(panel_h * (rows - row) / rows)
                draw.rectangle((x1, y1, x2, y2), fill=color)
        draw.text((x0, 48), pulse.upper(), fill=(30, 40, 50), font=font)
        for value in range(-40, 81, 20):
            x = x0 + panel_w * (value - DBZH_HISTOGRAM_EDGES[0]) / (
                DBZH_HISTOGRAM_EDGES[-1] - DBZH_HISTOGRAM_EDGES[0]
            )
            draw.text((int(x - 12), y0 + panel_h + 7), str(value), fill=(50, 60, 70), font=font)
        for value in (0, 2, 4, 6, 8):
            y = y0 + panel_h * (1.0 - (value - CI_HISTOGRAM_EDGES[0]) / (
                CI_HISTOGRAM_EDGES[-1] - CI_HISTOGRAM_EDGES[0]
            ))
            draw.text((x0 - 28, int(y - 5)), str(value), fill=(50, 60, 70), font=font)
        draw.text((x0 + panel_w // 2 - 35, y0 + panel_h + 32), "DBZH (dBZ)", fill=(30, 40, 50), font=font)
        draw.text((x0 - 40, y0 + panel_h // 2), "CI", fill=(30, 40, 50), font=font)
    draw.text((width - 180, 18), "colour = log(gate count)", fill=(70, 80, 90), font=font)
    image.save(path)


def _write_case_diagnostics(summary: dict[str, Any], output_dir: Path) -> None:
    from PIL import Image

    case_dir = output_dir / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    selected = _diagnostic_rows(summary.get("sweeps", []))
    rendered: dict[str, Path] = {}
    errors: list[dict[str, Any]] = []
    for row in selected:
        case_id = _case_id(row)
        path = case_dir / f"{case_id}.png"
        try:
            _render_case_triptych(row, path)
            rendered[case_id] = path
        except Exception as exc:  # noqa: BLE001 - retain the rest of the audit gallery.
            errors.append(
                {
                    "case": case_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    sp = sorted(
        (row for row in selected if row.get("pulse") == "sp"),
        key=_diagnostic_risk,
        reverse=True,
    )[:8]
    lp = sorted(
        (row for row in selected if row.get("pulse") == "lp"),
        key=_diagnostic_risk,
        reverse=True,
    )[:4]
    gallery_rows = [*sp, *lp]
    thumbnails = []
    for row in gallery_rows:
        source = rendered.get(_case_id(row))
        if source is None:
            continue
        with Image.open(source) as image:
            copy = image.convert("RGB")
            copy.thumbnail((710, 270), Image.Resampling.LANCZOS)
            thumbnails.append(copy)
    if thumbnails:
        columns = 2
        cell_w, cell_h = 730, 285
        rows = math.ceil(len(thumbnails) / columns)
        gallery = Image.new("RGB", (columns * cell_w, rows * cell_h), (243, 246, 248))
        for index, thumbnail in enumerate(thumbnails):
            x = (index % columns) * cell_w + (cell_w - thumbnail.width) // 2
            y = (index // columns) * cell_h + (cell_h - thumbnail.height) // 2
            gallery.paste(thumbnail, (x, y))
        gallery.save(output_dir / "worst_case_gallery.png")
    if errors:
        (output_dir / "case_render_errors.json").write_text(
            json.dumps(errors, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _diagnostic_rows(sweeps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_target: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sweeps:
        key = (str(row.get("radar")), str(row.get("pulse")))
        current = by_target.get(key)
        if current is None or _diagnostic_risk(row) > _diagnostic_risk(current):
            by_target[key] = row
    sp = sorted(
        (row for (_, pulse), row in by_target.items() if pulse == "sp"),
        key=lambda row: str(row.get("radar")),
    )
    lp = sorted(
        (row for (_, pulse), row in by_target.items() if pulse == "lp"),
        key=_diagnostic_risk,
        reverse=True,
    )[:8]
    return [*sp, *lp]


def _diagnostic_risk(row: dict[str, Any]) -> tuple[int, int, float, float]:
    return (
        int(row.get("receiver_noise_ge_20_dbz") or 0),
        int(row.get("receiver_noise_ge_10_dbz") or 0),
        float(row.get("receiver_noise_max_dbz") or -999.0),
        float(row.get("receiver_noise_fraction") or 0.0),
    )


def _case_id(row: dict[str, Any]) -> str:
    elevation = _format_optional(row.get("elevation_deg"), digits=2).replace(".", "p")
    return "_".join(
        (
            str(row.get("radar")),
            str(row.get("date")),
            str(row.get("time")),
            str(row.get("pulse")),
            str(row.get("dataset")),
            f"elev-{elevation}",
        )
    )


def _render_case_triptych(row: dict[str, Any], path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    np = require_numpy()
    source = Path(str(row["local_path"]))
    selection = FieldSelection(
        pulse=str(row["pulse"]),
        time=str(row["time"]),
        quantity="DBZH",
        dataset=str(row["dataset"]),
    )
    values, metadata, companions = read_polar_field_with_companions(
        source,
        str(row["radar"]),
        str(row["date"]),
        selection,
    )
    dbzh = np.asarray(values, dtype="float32")
    qc = build_qc_mask(
        dbzh,
        metadata=metadata,
        companion_fields=companions,
        config=_audit_qc_config(),
    )
    removed = (qc.mask & int(QCMaskFlag.RECEIVER_NOISE)) != 0
    pixel_size = max(float(metadata.rscale_m), 2.0 * float(metadata.max_range_m) / 360.0)
    raw_cart = polar_to_cartesian(dbzh, metadata, pixel_size_m=pixel_size).values
    removed_cart = polar_to_cartesian(removed.astype("float32"), metadata, pixel_size_m=pixel_size).values
    outside = ~np.isfinite(raw_cart)
    nodata = getattr(metadata, "nodata", None)
    if nodata is not None and math.isfinite(float(nodata)):
        outside |= np.isclose(raw_cart, float(nodata))
    removed_pixels = np.isfinite(removed_cart) & (removed_cart >= 0.5)
    raw_rgb = _dbzh_rgb(raw_cart, outside)
    mask_rgb = (raw_rgb.astype("float32") * 0.32 + 18.0).clip(0, 255).astype("uint8")
    mask_rgb[removed_pixels] = (220, 46, 54)
    retained_rgb = raw_rgb.copy()
    retained_rgb[removed_pixels] = (242, 245, 247)

    panels = [
        ("Raw DBZH", raw_rgb),
        ("RECEIVER_NOISE mask", mask_rgb),
        ("Retained DBZH", retained_rgb),
    ]
    panel_size = 360
    gap = 20
    header = 72
    width = panel_size * 3 + gap * 4
    height = header + panel_size + 38
    canvas = Image.new("RGB", (width, height), (242, 245, 247))
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(15)
    label_font = _load_font(13)
    title = (
        f"{row['radar']} {str(row['pulse']).upper()} {row['date']} {row['time']} "
        f"{row['dataset']} elev {_format_optional(row.get('elevation_deg'), digits=2)} deg  |  "
        f"removed {100.0 * float(row.get('receiver_noise_fraction') or 0.0):.2f}%  "
        f"max {_format_optional(row.get('receiver_noise_max_dbz'), digits=1)} dBZ  "
        f">=10 dBZ {int(row.get('receiver_noise_ge_10_dbz') or 0):,}"
    )
    draw.text((gap, 18), title, fill=(20, 30, 40), font=title_font)
    for index, (label, array) in enumerate(panels):
        x = gap + index * (panel_size + gap)
        image = Image.fromarray(array, mode="RGB")
        image = image.resize((panel_size, panel_size), Image.Resampling.NEAREST)
        canvas.paste(image, (x, header))
        draw.text((x, header + panel_size + 10), label, fill=(35, 45, 55), font=label_font)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _dbzh_rgb(values: Any, outside: Any) -> Any:
    np = require_numpy()
    array = np.asarray(values, dtype="float32")
    scaled = np.clip((array + 32.0) / 92.0, 0.0, 1.0)
    scaled = np.where(np.isfinite(scaled), scaled, 0.0)
    rgb = apply_palette((scaled * 255.0).astype("uint8"), "homeyer")
    rgb = np.asarray(rgb, dtype="uint8")
    rgb[np.asarray(outside, dtype=bool)] = (242, 245, 247)
    return rgb


def _load_font(size: int) -> Any:
    from PIL import ImageFont

    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _coverage_color(fraction: float) -> tuple[int, int, int]:
    if fraction >= 0.99:
        return (164, 219, 211)
    if fraction > 0.0:
        return (246, 201, 125)
    return (231, 235, 239)


def _heat_color(fraction: float) -> tuple[int, int, int]:
    value = max(0.0, min(1.0, fraction))
    if value < 0.5:
        t = value / 0.5
        return (
            int(245 + (27 - 245) * t),
            int(248 + (133 - 248) * t),
            int(250 + (122 - 250) * t),
        )
    t = (value - 0.5) / 0.5
    return (
        int(27 + (185 - 27) * t),
        int(133 + (45 - 133) * t),
        int(122 + (64 - 122) * t),
    )


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
