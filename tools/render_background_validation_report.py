#!/usr/bin/env python3
"""Render diagnostic plots from persisted real-data background validation."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from uk_wsr_visualizer.preview import apply_palette


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path(
            "reports/background_validation_v2/validation_results.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "docs/_static/qc_results/background_validation_v2"
        ),
    )
    parser.add_argument("--gallery-cases", type=int, default=6)
    args = parser.parse_args()

    report = json.loads(args.results.read_text(encoding="utf-8"))
    records = list(report.get("records") or [])
    if not records:
        raise SystemExit("validation report has no records")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    written = [
        _plot_elevation_distributions(
            records,
            args.output_dir / "removal_by_elevation.png",
        ),
        _plot_radar_increment(
            records,
            args.output_dir / "learned_increment_by_radar.png",
        ),
        _plot_worst_case_gallery(
            records,
            args.output_dir / "worst_case_exact_masks.png",
            case_count=max(1, args.gallery_cases),
        ),
    ]
    summary_path = args.output_dir / "validation_plot_manifest.json"
    summary_path.write_text(
        json.dumps(
            {
                "schema": "uk_wsr_background_validation_plot_manifest",
                "schema_version": 1,
                "source_results": str(args.results),
                "source_configuration_sha256": report.get(
                    "configuration_sha256"
                ),
                "source_record_count": len(records),
                "source_complete": report.get("complete"),
                "plots": [str(path) for path in written],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)
    print(
        json.dumps(
            {
                "record_count": len(records),
                "source_complete": report.get("complete"),
                "written": [str(path) for path in written],
            },
            sort_keys=True,
        )
    )
    return 0


def _plot_elevation_distributions(
    records: list[dict[str, Any]],
    destination: Path,
) -> Path:
    grouped: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[
            (str(record["pulse"]), round(float(record["elevation_deg"]), 2))
        ].append(record)
    categories = sorted(
        grouped,
        key=lambda item: (
            item[1] >= 80.0,
            item[1],
            item[0],
        ),
    )
    width = max(1500, 95 * len(categories) + 180)
    height = 760
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (35, 20),
        "Real validation removal by pulse and elevation",
        fill="#17212b",
        font=_font(30, bold=True),
    )
    draw.text(
        (35, 60),
        "Points show median; vertical bars show p10-p90 across scans",
        fill="#56616d",
        font=_font(17),
    )
    left, right, top, bottom = 90, width - 35, 115, height - 145
    plot_width = right - left
    plot_height = bottom - top
    for tick in range(0, 101, 10):
        y = bottom - plot_height * tick / 100.0
        draw.line((left, y, right, y), fill="#e1e5e9", width=1)
        draw.text(
            (25, y - 9),
            f"{tick}%",
            fill="#56616d",
            font=_font(14),
        )
    draw.line((left, top, left, bottom), fill="#66717c", width=2)
    draw.line((left, bottom, right, bottom), fill="#66717c", width=2)
    step = plot_width / max(1, len(categories))
    for index, category in enumerate(categories):
        pulse, elevation = category
        selected = grouped[category]
        total = np.asarray(
            [
                float(record["learned"]["removed_fraction"])
                for record in selected
            ],
            dtype="float64",
        )
        increment = np.asarray(
            [
                float(record["delta"]["learned_increment_fraction"])
                for record in selected
            ],
            dtype="float64",
        )
        x = left + (index + 0.5) * step
        color = "#167b78" if pulse == "lp" else "#d05b32"
        _draw_quantile_marker(
            draw,
            x=x - 7,
            values=total,
            top=top,
            bottom=bottom,
            color=color,
        )
        _draw_quantile_marker(
            draw,
            x=x + 7,
            values=increment,
            top=top,
            bottom=bottom,
            color="#7c4d9e",
        )
        label = f"{pulse.upper()}\n{elevation:g}"
        draw.multiline_text(
            (x - 18, bottom + 10),
            label,
            fill="#3e4852",
            font=_font(13),
            align="center",
            spacing=2,
        )
    draw.rectangle((left, height - 52, left + 14, height - 38), fill="#167b78")
    draw.text(
        (left + 20, height - 56),
        "LP total",
        fill="#3e4852",
        font=_font(15),
    )
    draw.rectangle((left + 105, height - 52, left + 119, height - 38), fill="#d05b32")
    draw.text(
        (left + 125, height - 56),
        "SP total",
        fill="#3e4852",
        font=_font(15),
    )
    draw.rectangle((left + 215, height - 52, left + 229, height - 38), fill="#7c4d9e")
    draw.text(
        (left + 235, height - 56),
        "learned-only increment",
        fill="#3e4852",
        font=_font(15),
    )
    canvas.save(destination)
    return destination


def _draw_quantile_marker(
    draw: ImageDraw.ImageDraw,
    *,
    x: float,
    values: np.ndarray,
    top: float,
    bottom: float,
    color: str,
) -> None:
    p10, median, p90 = np.percentile(values, (10, 50, 90))
    height = bottom - top

    def y(value: float) -> float:
        return bottom - height * min(1.0, max(0.0, float(value)))

    draw.line((x, y(p10), x, y(p90)), fill=color, width=4)
    draw.ellipse(
        (x - 5, y(median) - 5, x + 5, y(median) + 5),
        fill=color,
        outline="white",
        width=1,
    )


def _plot_radar_increment(
    records: list[dict[str, Any]],
    destination: Path,
) -> Path:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[(str(record["radar"]), str(record["pulse"]))].append(record)
    radars = sorted({key[0] for key in grouped})
    fractions: dict[tuple[str, str], float] = {}
    for key, selected in grouped.items():
        finite = sum(
            int(record["learned"]["finite_count"])
            for record in selected
        )
        increment = sum(
            int(record["delta"]["learned_increment_count"])
            for record in selected
        )
        fractions[key] = increment / finite if finite else 0.0
    maximum = max(fractions.values(), default=0.01)
    axis_max = max(0.01, np.ceil(maximum * 100.0) / 100.0)
    width = 1300
    row_height = 39
    height = 125 + row_height * len(radars) + 70
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (30, 18),
        "Learned-only validation mask share by radar and pulse",
        fill="#17212b",
        font=_font(28, bold=True),
    )
    draw.text(
        (30, 56),
        "Weighted by finite gates; this is not an accuracy score",
        fill="#56616d",
        font=_font(16),
    )
    left, right, top = 190, width - 45, 100
    plot_width = right - left
    for tick in np.linspace(0.0, axis_max, 6):
        x = left + plot_width * tick / axis_max
        draw.line(
            (x, top, x, top + row_height * len(radars)),
            fill="#e1e5e9",
            width=1,
        )
        draw.text(
            (x - 14, top - 24),
            f"{100 * tick:.1f}%",
            fill="#56616d",
            font=_font(13),
        )
    for row, radar in enumerate(radars):
        y = top + row * row_height
        draw.text(
            (25, y + 7),
            radar,
            fill="#36414b",
            font=_font(14),
        )
        for pulse, offset, color in (
            ("lp", 5, "#167b78"),
            ("sp", 20, "#d05b32"),
        ):
            fraction = fractions.get((radar, pulse), 0.0)
            x1 = left + plot_width * fraction / axis_max
            draw.rectangle(
                (left, y + offset, x1, y + offset + 10),
                fill=color,
            )
    draw.rectangle(
        (left, height - 42, left + 14, height - 28),
        fill="#167b78",
    )
    draw.text(
        (left + 20, height - 46),
        "LP",
        fill="#3e4852",
        font=_font(15),
    )
    draw.rectangle(
        (left + 65, height - 42, left + 79, height - 28),
        fill="#d05b32",
    )
    draw.text(
        (left + 85, height - 46),
        "SP",
        fill="#3e4852",
        font=_font(15),
    )
    canvas.save(destination)
    return destination


def _plot_worst_case_gallery(
    records: list[dict[str, Any]],
    destination: Path,
    *,
    case_count: int,
) -> Path:
    selected = _select_gallery_records(records, case_count)
    panel_size = 260
    panel_width = 280
    header = 105
    row_height = 335
    margin = 20
    width = margin * 2 + panel_width * 4
    height = header + row_height * len(selected) + 35
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (margin, 18),
        "Objective worst-case real validation gallery",
        fill="#17212b",
        font=_font(28, bold=True),
    )
    draw.text(
        (margin, 57),
        "Raw DBZH, baseline mask, learned-only increment, learned cleaned",
        fill="#56616d",
        font=_font(16),
    )
    for row, record in enumerate(selected):
        with np.load(record["artifact_npz"]) as loaded:
            raw = loaded["dbzh_raw"]
            baseline = loaded["baseline_remove_mask"].astype(bool)
            increment = loaded["learned_increment_mask"].astype(bool)
            cleaned = loaded["dbzh_learned_cleaned"]
        top = header + row * row_height
        caption = (
            f"{record['radar']} {record['source']['date']} "
            f"{record['source']['time']} {record['pulse'].upper()} "
            f"{record['elevation_deg']:.2f} deg | "
            f"total {100 * record['learned']['removed_fraction']:.1f}% | "
            f"learned +{100 * record['delta']['learned_increment_fraction']:.1f}% | "
            "max "
            f"{_format_optional(record['learned']['removed_dbzh']['maximum'])} "
            "dBZ"
        )
        draw.text(
            (margin, top),
            caption,
            fill="#26313b",
            font=_font(15, bold=True),
        )
        images = (
            (
                _polar_image(raw, size=panel_size, vmin=-30, vmax=60),
                "raw DBZH",
            ),
            (
                _mask_image(baseline, raw, size=panel_size, color="#c83b33"),
                "baseline nuisance",
            ),
            (
                _mask_image(increment, raw, size=panel_size, color="#9a4ea3"),
                "learned-only increment",
            ),
            (
                _polar_image(
                    cleaned,
                    size=panel_size,
                    vmin=-30,
                    vmax=60,
                ),
                "learned cleaned",
            ),
        )
        for column, (image, title) in enumerate(images):
            x = margin + column * panel_width
            canvas.paste(image, (x, top + 34), image)
            title_box = draw.textbbox((0, 0), title, font=_font(14))
            draw.text(
                (
                    x + (panel_size - (title_box[2] - title_box[0])) / 2,
                    top + 299,
                ),
                title,
                fill="#3e4852",
                font=_font(14),
            )
    canvas.save(destination)
    return destination


def _select_gallery_records(
    records: list[dict[str, Any]],
    case_count: int,
) -> list[dict[str, Any]]:
    rankings = (
        sorted(
            records,
            key=lambda row: float(
                row["delta"]["learned_increment_dbzh"][
                    "linear_reflectivity_fraction"
                ]
            ),
            reverse=True,
        ),
        sorted(
            records,
            key=lambda row: float(row["learned"]["removed_fraction"]),
            reverse=True,
        ),
        sorted(
            records,
            key=lambda row: int(
                row["learned"]["removed_dbzh"][
                    "count_at_or_above_dbzh"
                ]["20"]
            ),
            reverse=True,
        ),
    )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    rank_index = 0
    while len(selected) < case_count:
        added = False
        for ranking in rankings:
            if rank_index >= len(ranking):
                continue
            record = ranking[rank_index]
            if record["job_id"] not in seen:
                selected.append(record)
                seen.add(record["job_id"])
                added = True
                if len(selected) >= case_count:
                    break
        if rank_index >= max(len(ranking) for ranking in rankings):
            break
        rank_index += 1
        if not added and rank_index >= len(records):
            break
    return selected


def _polar_image(
    values: Any,
    *,
    size: int,
    vmin: float,
    vmax: float,
) -> Image.Image:
    array = np.asarray(values, dtype="float32")
    sampled, inside = _polar_sample(array, size=size)
    valid = inside & np.isfinite(sampled)
    scaled = np.clip(
        (sampled - vmin) / max(vmax - vmin, 1.0e-6),
        0.0,
        1.0,
    )
    rgb = apply_palette(
        (np.nan_to_num(scaled) * 255.0).astype("uint8"),
        "homeyer",
    )
    rgba = np.zeros((size, size, 4), dtype="uint8")
    rgba[valid, :3] = rgb[valid]
    rgba[valid, 3] = 255
    image = Image.fromarray(rgba, mode="RGBA")
    _draw_polar_grid(image)
    return image


def _mask_image(
    mask: Any,
    source: Any,
    *,
    size: int,
    color: str,
) -> Image.Image:
    mask_sampled, inside = _polar_sample(
        np.asarray(mask, dtype="float32"),
        size=size,
    )
    source_sampled, _ = _polar_sample(
        np.asarray(source, dtype="float32"),
        size=size,
    )
    rgba = np.zeros((size, size, 4), dtype="uint8")
    valid = inside & np.isfinite(source_sampled)
    rgba[valid, :3] = (226, 231, 235)
    rgba[valid, 3] = 255
    selected = valid & (mask_sampled >= 0.5)
    red, green, blue = _hex_rgb(color)
    rgba[selected, :3] = (red, green, blue)
    image = Image.fromarray(rgba, mode="RGBA")
    _draw_polar_grid(image)
    return image


def _polar_sample(
    array: np.ndarray,
    *,
    size: int,
) -> tuple[np.ndarray, np.ndarray]:
    rows, columns = array.shape
    coordinates = np.arange(size, dtype="float32")
    x, y = np.meshgrid(coordinates, coordinates)
    centre = (size - 1) / 2.0
    dx = x - centre
    dy = y - centre
    radial = np.sqrt(dx * dx + dy * dy)
    inside = radial <= centre
    bins = np.minimum(
        (radial / max(centre, 1.0) * columns).astype("int32"),
        columns - 1,
    )
    azimuth = np.mod(np.arctan2(dx, -dy), 2.0 * np.pi)
    rays = np.minimum(
        (azimuth / (2.0 * np.pi) * rows).astype("int32"),
        rows - 1,
    )
    return array[rays, bins], inside


def _draw_polar_grid(image: Image.Image) -> None:
    draw = ImageDraw.Draw(image, mode="RGBA")
    centre = (image.width - 1) / 2.0
    for fraction in (0.25, 0.5, 0.75, 1.0):
        radius = centre * fraction
        draw.ellipse(
            (
                centre - radius,
                centre - radius,
                centre + radius,
                centre + radius,
            ),
            outline=(35, 45, 55, 70),
            width=1,
        )
    draw.line(
        (centre, 0, centre, image.height),
        fill=(35, 45, 55, 55),
        width=1,
    )
    draw.line(
        (0, centre, image.width, centre),
        fill=(35, 45, 55, 55),
        width=1,
    )


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _hex_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def _format_optional(value: Any) -> str:
    return "none" if value is None else f"{float(value):.1f}"


if __name__ == "__main__":
    raise SystemExit(main())
