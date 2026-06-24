#!/usr/bin/env python3
"""Lecture 6 practical translated to Python for UK Avocet radar aggregates.

This script reconstructs the core R practical workflow:

1. Read a UK aggregate field for radar geometry.
2. Build a radar-centred polar basegrid.
3. Sample ground height from a DEM, if supplied.
4. Compute beam height, terrain clearance, and topographic blockage.
5. Optionally estimate beam propagation from a radiosonde CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avocet_radar_toolkit.export_types import FieldSelection
from avocet_radar_toolkit.geospatial import read_polar_field
from avocet_radar_toolkit.ground_mapping import (
    beam_center_height_m,
    beam_ground_clearance_m,
    classify_refractivity_gradient,
    effective_earth_radius_factor_from_gradient,
    make_radar_sample_grid,
    refractivity_gradient_n_per_km,
    sample_dem_at_grid,
    topographic_blockage_fraction,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", type=Path, required=True, help="Avocet daily aggregate HDF5 file")
    parser.add_argument("--radar", required=True, help="Radar slug, e.g. thurnham")
    parser.add_argument("--date", required=True, help="Radar date as YYYYMMDD")
    parser.add_argument("--pulse", default="lp", help="Pulse group in the aggregate, e.g. lp or sp")
    parser.add_argument("--time", required=True, help="Scan time group, e.g. 2130")
    parser.add_argument("--quantity", default="DBZH", help="ODIM quantity to locate for geometry")
    parser.add_argument("--dataset", default=None, help="Dataset name such as dataset1; default chooses first quantity match")
    parser.add_argument("--dem", type=Path, help="Optional DEM raster readable by rasterio")
    parser.add_argument("--sounding-csv", type=Path, help="Optional radiosonde CSV with height_m, pressure_hpa, temperature_c, dewpoint_c")
    parser.add_argument("--max-range-km", type=float, default=100.0)
    parser.add_argument("--range-step-km", type=float, default=1.0)
    parser.add_argument("--azimuth-step-deg", type=float, default=1.0)
    parser.add_argument("--beam-width-deg", type=float, default=1.0)
    parser.add_argument("--default-terrain-m", type=float, default=0.0, help="Used when --dem is omitted")
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path)
    return parser.parse_args()


def read_sounding(path: Path) -> dict[str, list[float]]:
    columns = {"height_m": [], "pressure_hpa": [], "temperature_c": [], "dewpoint_c": []}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(columns) - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"sounding CSV missing required columns: {', '.join(sorted(missing))}")
        for row in reader:
            for column in columns:
                columns[column].append(float(row[column]))
    return columns


def main() -> int:
    args = parse_args()
    _data, metadata = read_polar_field(
        args.aggregate,
        args.radar,
        args.date,
        FieldSelection(pulse=args.pulse, time=args.time, quantity=args.quantity, dataset=args.dataset),
    )
    if metadata.elevation_deg is None:
        raise SystemExit("selected field has no elevation angle metadata")

    grid = make_radar_sample_grid(
        metadata,
        max_range_km=args.max_range_km,
        range_step_km=args.range_step_km,
        azimuth_step_deg=args.azimuth_step_deg,
    )

    np = __import__("numpy")
    if args.dem:
        terrain_m = sample_dem_at_grid(args.dem, grid)
        terrain_source = str(args.dem)
    else:
        terrain_m = np.full(grid.range_km.shape, args.default_terrain_m, dtype="float64")
        terrain_source = f"constant:{args.default_terrain_m}"

    k_factor = 4.0 / 3.0
    propagation = {
        "source": "standard_4_3_earth_radius",
        "effective_earth_radius_factor": k_factor,
        "classification": "standard_or_normal",
    }
    if args.sounding_csv:
        sounding = read_sounding(args.sounding_csv)
        gradient = refractivity_gradient_n_per_km(**sounding)
        k_factor = effective_earth_radius_factor_from_gradient(gradient)
        propagation = {
            "source": str(args.sounding_csv),
            "gradient_n_per_km": gradient,
            "effective_earth_radius_factor": k_factor,
            "classification": classify_refractivity_gradient(gradient),
        }

    range_m = grid.range_km * 1000.0
    site_height_m = metadata.height_m or 0.0
    beam_height_m_asl = beam_center_height_m(range_m, metadata.elevation_deg, site_height_m, k_factor)
    clearance_m = beam_ground_clearance_m(terrain_m, range_m, metadata.elevation_deg, site_height_m, k_factor)
    blockage = topographic_blockage_fraction(
        terrain_m,
        range_m,
        metadata.elevation_deg,
        site_height_m=site_height_m,
        beam_width_deg=args.beam_width_deg,
        effective_earth_radius_factor=k_factor,
    )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "azimuth_deg",
                "range_km",
                "longitude",
                "latitude",
                "cell_area_ha",
                "terrain_m_asl",
                "beam_center_m_asl",
                "ground_clearance_m",
                "topographic_blockage_fraction",
                "mask_blockage_gt_25pct",
            ]
        )
        rows, cols = grid.range_km.shape
        for row in range(rows):
            for col in range(cols):
                writer.writerow(
                    [
                        float(grid.azimuth_deg[row, col]),
                        float(grid.range_km[row, col]),
                        float(grid.longitude[row, col]),
                        float(grid.latitude[row, col]),
                        float(grid.cell_area_ha[row, col]),
                        float(terrain_m[row, col]),
                        float(beam_height_m_asl[row, col]),
                        float(clearance_m[row, col]),
                        float(blockage[row, col]),
                        bool(blockage[row, col] > 0.25),
                    ]
                )

    summary = {
        "aggregate": str(args.aggregate),
        "radar": metadata.radar,
        "date": metadata.date,
        "pulse": metadata.pulse,
        "time": metadata.time,
        "quantity": metadata.quantity,
        "dataset": metadata.dataset,
        "elevation_deg": metadata.elevation_deg,
        "site_height_m": metadata.height_m,
        "grid_shape": list(grid.range_km.shape),
        "terrain_source": terrain_source,
        "propagation": propagation,
        "output_csv": str(args.output_csv),
        "blocked_gt_25pct_fraction": float(np.nanmean(blockage > 0.25)),
        "median_ground_clearance_m": float(np.nanmedian(clearance_m)),
    }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
