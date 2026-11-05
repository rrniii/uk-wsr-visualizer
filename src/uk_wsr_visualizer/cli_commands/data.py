"""Catalogue, visualisation and export commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from ..animation import AnimationRequest, run_animation
from ..catalog import (
    build_catalog,
    build_raw_volume_catalog,
    filter_catalog,
    load_catalog,
)
from ..citations import citation_payload, format_citation_text
from ..config import Settings
from ..export import ExportRequest, run_export
from ..math_ops import MathOperand, MathRequest, run_math
from ..object_store import DEFAULT_OBJECT_PREFIX
from ..preview import PreviewRequest, generate_preview
from ..stac import (
    AGGREGATE_COLLECTION_ID,
    collection_to_stac,
    item_to_stac,
    root_catalog_to_stac,
)
from ..tiles import TileRequest, generate_tile_pyramid, tile_manifest
from .common import _add_filter_arguments, _filter_args, _settings, _split_csv


def cmd_citation(args: argparse.Namespace) -> int:
    """Print citation guidance for research users."""

    payload = citation_payload()
    print(
        json.dumps(payload, indent=2, sort_keys=True)
        if args.json
        else format_citation_text()
    )
    return 0


def cmd_catalog_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = build_catalog(
        aggregate_base=settings.aggregate_base,
        output=settings.catalog_path,
        radar=args.radar,
        year=args.year,
        date=args.date,
        max_files=args.max_files,
        object_store_base=settings.object_store_external_base,
        metadata_mode=args.metadata_mode,
    )
    print(f"wrote {len(items)} catalog items to {settings.catalog_path}")
    return 0


def cmd_catalog_build_raw_volume(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = build_raw_volume_catalog(
        raw_volume_base=Path(args.raw_volume_base),
        output=settings.catalog_path,
        radar=args.radar,
        year=args.year,
        date=args.date,
        max_files=args.max_files,
        object_store_base=settings.object_store_external_base,
        metadata_mode=args.metadata_mode,
    )
    volume_count = sum(len(item.raw_volumes) for item in items)
    print(
        f"wrote {len(items)} raw-volume catalog item(s), {volume_count} volume file(s), to {settings.catalog_path}"
    )
    return 0


def cmd_catalog_stac(args: argparse.Namespace) -> int:
    settings = _settings(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    items = load_catalog(settings.catalog_path)
    (output_dir / "catalog.json").write_text(
        json.dumps(
            root_catalog_to_stac(
                items,
                public_base_url=settings.object_store_external_base,
                object_prefix=args.object_prefix,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    collection_dir = output_dir / AGGREGATE_COLLECTION_ID
    collection_dir.mkdir(parents=True, exist_ok=True)
    (collection_dir / "collection.json").write_text(
        json.dumps(
            collection_to_stac(
                items,
                public_base_url=settings.object_store_external_base,
                object_prefix=args.object_prefix,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    count = 0
    for item in items:
        path = collection_dir / f"{item.item_id}.json"
        path.write_text(
            json.dumps(
                item_to_stac(
                    item,
                    public_base_url=settings.object_store_external_base,
                    object_prefix=args.object_prefix,
                ),
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        count += 1
    print(f"wrote STAC catalog, collection, and {count} item files to {output_dir}")
    return 0


def cmd_preview_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
    if not items:
        raise SystemExit("no matching catalog item")
    item = items[0]
    request = PreviewRequest(
        aggregate_path=Path(item.path),
        radar=item.radar,
        date=item.date,
        pulse=args.pulse,
        time=args.time,
        quantity=args.quantity,
        dataset=args.dataset,
        palette=args.palette,
        filters=_filter_args(args),
        output_dir=settings.preview_dir / item.radar / item.date,
    )
    output = generate_preview(request)
    print(output)
    return 0


def cmd_preview_batch(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.start,
        end=args.end,
        pulse=args.pulse,
        quantity=args.quantity,
    )
    if args.max_items is not None:
        items = items[: args.max_items]

    built: list[str] = []
    errors: list[dict[str, str]] = []
    for item in items:
        combinations = [
            (record.pulse, record.time, record.quantity, f"dataset{record.dataset}")
            for record in item.quantity_records
            if (args.pulse is None or record.pulse == args.pulse)
            and (args.quantity is None or record.quantity == args.quantity)
        ]
        seen: set[tuple[str, str, str, str]] = set()
        unique = [
            combo for combo in combinations if not (combo in seen or seen.add(combo))
        ]
        if args.max_frames_per_item is not None:
            unique = unique[: args.max_frames_per_item]
        for pulse, time, quantity, dataset in unique:
            try:
                output = generate_preview(
                    PreviewRequest(
                        aggregate_path=Path(item.path),
                        radar=item.radar,
                        date=item.date,
                        pulse=pulse,
                        time=time,
                        quantity=quantity,
                        dataset=dataset,
                        palette=args.palette,
                        filters=_filter_args(args),
                        output_dir=settings.preview_dir / item.radar / item.date,
                    )
                )
                built.append(str(output))
            except Exception as exc:
                errors.append(
                    {
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": pulse,
                        "time": time,
                        "quantity": quantity,
                        "dataset": dataset,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    print(
        json.dumps(
            {"built": built, "built_count": len(built), "errors": errors},
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors and not args.keep_going else 0


def cmd_animation_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
    if not items:
        raise SystemExit("no matching catalog item")
    times = [value.strip() for value in (args.times or "").split(",") if value.strip()]
    product = run_animation(
        AnimationRequest(
            radar=args.radar,
            date=args.date,
            pulse=args.pulse,
            quantity=args.quantity,
            times=times,
            dataset=args.dataset,
            palette=args.palette,
            filters=_filter_args(args),
            frame_delay_ms=args.frame_delay_ms,
        ),
        items[0],
        Path(args.output_dir),
        settings.preview_dir,
    )
    print(
        json.dumps(
            product, default=lambda value: value.__dict__, indent=2, sort_keys=True
        )
    )
    return 0


def cmd_tile_build(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
    if not items:
        raise SystemExit("no matching catalog item")
    product = generate_tile_pyramid(
        TileRequest(
            aggregate_path=Path(items[0].path),
            radar=args.radar,
            date=args.date,
            pulse=args.pulse,
            time=args.time,
            quantity=args.quantity,
            dataset=args.dataset,
            palette=args.palette,
            filters=_filter_args(args),
            tile_size=args.tile_size,
            min_zoom=args.min_zoom,
            max_zoom=args.max_zoom,
            output_dir=settings.tile_dir,
        )
    )
    print(json.dumps(tile_manifest(product), indent=2, sort_keys=True))
    return 0


def cmd_tile_batch(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.start,
        end=args.end,
        pulse=args.pulse,
        quantity=args.quantity,
    )
    if args.max_items is not None:
        items = items[: args.max_items]
    built: list[str] = []
    errors: list[dict[str, str]] = []
    for item in items:
        combinations = [
            (record.pulse, record.time, record.quantity, f"dataset{record.dataset}")
            for record in item.quantity_records
            if (args.pulse is None or record.pulse == args.pulse)
            and (args.quantity is None or record.quantity == args.quantity)
        ]
        seen: set[tuple[str, str, str, str]] = set()
        unique = [
            combo for combo in combinations if not (combo in seen or seen.add(combo))
        ]
        if args.max_fields_per_item is not None:
            unique = unique[: args.max_fields_per_item]
        for pulse, time, quantity, dataset in unique:
            try:
                product = generate_tile_pyramid(
                    TileRequest(
                        aggregate_path=Path(item.path),
                        radar=item.radar,
                        date=item.date,
                        pulse=pulse,
                        time=time,
                        quantity=quantity,
                        dataset=dataset,
                        palette=args.palette,
                        filters=_filter_args(args),
                        tile_size=args.tile_size,
                        min_zoom=args.min_zoom,
                        max_zoom=args.max_zoom,
                        output_dir=settings.tile_dir,
                    )
                )
                built.append(product.manifest_path)
            except Exception as exc:
                errors.append(
                    {
                        "radar": item.radar,
                        "date": item.date,
                        "pulse": pulse,
                        "time": time,
                        "quantity": quantity,
                        "dataset": dataset,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    print(
        json.dumps(
            {"built": built, "built_count": len(built), "errors": errors},
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if errors and not args.keep_going else 0


def cmd_export(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
    if not items:
        raise SystemExit("no matching catalog item")
    job = run_export(
        ExportRequest(
            radar=args.radar,
            date=args.date,
            format=args.format,
            pulse=args.pulse,
            time=args.time,
            quantity=args.quantity,
            dataset=args.dataset,
            times=_split_csv(args.times, []),
            frame_delay_ms=args.frame_delay_ms,
            palette=args.palette,
            filters=_filter_args(args),
        ),
        items[0],
        settings.export_dir,
    )
    print(
        json.dumps(
            job.__dict__, default=lambda value: value.__dict__, indent=2, sort_keys=True
        )
    )
    return 0


def cmd_math(args: argparse.Namespace) -> int:
    settings = _settings(args)
    items = filter_catalog(
        load_catalog(settings.catalog_path),
        radar=args.radar,
        start=args.date,
        end=args.date,
    )
    if not items:
        raise SystemExit("no matching catalog item")
    product = run_math(
        MathRequest(
            radar=args.radar,
            date=args.date,
            operation=args.operation,
            left=MathOperand(
                pulse=args.left_pulse,
                time=args.left_time,
                quantity=args.left_quantity,
                dataset=args.left_dataset,
            ),
            right=MathOperand(
                pulse=args.right_pulse,
                time=args.right_time,
                quantity=args.right_quantity,
                dataset=args.right_dataset,
            ),
            format=args.format,
            filters=_filter_args(args),
            palette=args.palette,
        ),
        items[0],
        Path(args.output_dir),
    )
    print(
        json.dumps(
            product, default=lambda value: value.__dict__, indent=2, sort_keys=True
        )
    )
    return 0


def register_catalog_commands(subparsers):
    citation_parser = subparsers.add_parser(
        "citation", help="Print citation and provenance guidance."
    )
    citation_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable citation metadata."
    )
    citation_parser.set_defaults(func=cmd_citation)

    catalog_parser = subparsers.add_parser("catalog")
    catalog_sub = catalog_parser.add_subparsers(required=True)
    catalog_build = catalog_sub.add_parser("build")
    catalog_build.add_argument("--aggregate-base", type=Path, required=True)
    catalog_build.add_argument("--output", "--catalog", dest="catalog", required=True)
    catalog_build.add_argument("--radar")
    catalog_build.add_argument("--year")
    catalog_build.add_argument("--date")
    catalog_build.add_argument("--max-files", type=int)
    catalog_build.add_argument("--object-store-base", default="")
    catalog_build.add_argument(
        "--metadata-mode", choices=["deep", "fast"], default="deep"
    )
    catalog_build.set_defaults(func=cmd_catalog_build)

    catalog_build_raw = catalog_sub.add_parser("build-raw-volume")
    catalog_build_raw.add_argument("--raw-volume-base", type=Path, required=True)
    catalog_build_raw.add_argument(
        "--output", "--catalog", dest="catalog", required=True
    )
    catalog_build_raw.add_argument("--radar")
    catalog_build_raw.add_argument("--year")
    catalog_build_raw.add_argument("--date")
    catalog_build_raw.add_argument("--max-files", type=int)
    catalog_build_raw.add_argument("--object-store-base", default="")
    catalog_build_raw.add_argument(
        "--metadata-mode", choices=["deep", "fast"], default="deep"
    )
    catalog_build_raw.set_defaults(func=cmd_catalog_build_raw_volume)

    catalog_stac = catalog_sub.add_parser("stac")
    catalog_stac.add_argument("--output-dir", required=True)
    catalog_stac.add_argument("--object-store-base", default="")
    catalog_stac.add_argument("--object-prefix", default=DEFAULT_OBJECT_PREFIX)
    catalog_stac.set_defaults(func=cmd_catalog_stac)


def register_visualization_commands(subparsers):
    preview_parser = subparsers.add_parser("preview")
    preview_sub = preview_parser.add_subparsers(required=True)
    preview_build = preview_sub.add_parser("build")
    preview_build.add_argument("--catalog")
    preview_build.add_argument("--radar", required=True)
    preview_build.add_argument("--date", required=True)
    preview_build.add_argument("--pulse", required=True)
    preview_build.add_argument("--time", required=True)
    preview_build.add_argument("--quantity", required=True)
    preview_build.add_argument("--dataset")
    preview_build.add_argument("--palette", default="gray")
    _add_filter_arguments(preview_build)
    preview_build.add_argument(
        "--preview-dir", type=Path, default=Settings.from_env().preview_dir
    )
    preview_build.set_defaults(func=cmd_preview_build)

    preview_batch = preview_sub.add_parser("batch")
    preview_batch.add_argument("--catalog")
    preview_batch.add_argument("--radar")
    preview_batch.add_argument("--start")
    preview_batch.add_argument("--end")
    preview_batch.add_argument("--pulse")
    preview_batch.add_argument("--quantity")
    preview_batch.add_argument("--palette", default="gray")
    _add_filter_arguments(preview_batch)
    preview_batch.add_argument("--max-items", type=int)
    preview_batch.add_argument("--max-frames-per-item", type=int)
    preview_batch.add_argument("--keep-going", action="store_true")
    preview_batch.add_argument(
        "--preview-dir", type=Path, default=Settings.from_env().preview_dir
    )
    preview_batch.set_defaults(func=cmd_preview_batch)

    animation_parser = subparsers.add_parser("animation")
    animation_sub = animation_parser.add_subparsers(required=True)
    animation_build = animation_sub.add_parser("build")
    animation_build.add_argument("--catalog")
    animation_build.add_argument("--radar", required=True)
    animation_build.add_argument("--date", required=True)
    animation_build.add_argument("--pulse", required=True)
    animation_build.add_argument("--quantity", required=True)
    animation_build.add_argument(
        "--times", help="Comma-separated frame times. Defaults to every catalog time."
    )
    animation_build.add_argument("--dataset")
    animation_build.add_argument("--palette", default="gray")
    animation_build.add_argument("--frame-delay-ms", type=int, default=600)
    _add_filter_arguments(animation_build)
    animation_build.add_argument(
        "--preview-dir", type=Path, default=Settings.from_env().preview_dir
    )
    animation_build.add_argument("--output-dir", required=True)
    animation_build.set_defaults(func=cmd_animation_build)

    tile_parser = subparsers.add_parser("tile")
    tile_sub = tile_parser.add_subparsers(required=True)
    tile_build = tile_sub.add_parser("build")
    tile_build.add_argument("--catalog")
    tile_build.add_argument("--radar", required=True)
    tile_build.add_argument("--date", required=True)
    tile_build.add_argument("--pulse", required=True)
    tile_build.add_argument("--time", required=True)
    tile_build.add_argument("--quantity", required=True)
    tile_build.add_argument("--dataset")
    tile_build.add_argument("--palette", default="gray")
    tile_build.add_argument("--tile-size", type=int, default=256)
    tile_build.add_argument("--min-zoom", type=int, default=0)
    tile_build.add_argument("--max-zoom", type=int, default=2)
    _add_filter_arguments(tile_build)
    tile_build.add_argument("--tile-dir", required=True)
    tile_build.set_defaults(func=cmd_tile_build)

    tile_batch = tile_sub.add_parser("batch")
    tile_batch.add_argument("--catalog")
    tile_batch.add_argument("--radar")
    tile_batch.add_argument("--start")
    tile_batch.add_argument("--end")
    tile_batch.add_argument("--pulse")
    tile_batch.add_argument("--quantity")
    tile_batch.add_argument("--palette", default="gray")
    tile_batch.add_argument("--tile-size", type=int, default=256)
    tile_batch.add_argument("--min-zoom", type=int, default=0)
    tile_batch.add_argument("--max-zoom", type=int, default=2)
    _add_filter_arguments(tile_batch)
    tile_batch.add_argument("--max-items", type=int)
    tile_batch.add_argument("--max-fields-per-item", type=int)
    tile_batch.add_argument("--keep-going", action="store_true")
    tile_batch.add_argument("--tile-dir", required=True)
    tile_batch.set_defaults(func=cmd_tile_batch)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--radar", required=True)
    export_parser.add_argument("--date", required=True)
    export_parser.add_argument("--format", required=True)
    export_parser.add_argument("--pulse")
    export_parser.add_argument("--time")
    export_parser.add_argument(
        "--times", help="Comma-separated frame times for MP4 export."
    )
    export_parser.add_argument("--quantity")
    export_parser.add_argument("--dataset")
    export_parser.add_argument("--palette", default="gray")
    export_parser.add_argument("--frame-delay-ms", type=int, default=600)
    _add_filter_arguments(export_parser)
    export_parser.add_argument(
        "--export-dir", type=Path, default=Settings.from_env().export_dir
    )
    export_parser.set_defaults(func=cmd_export)

    math_parser = subparsers.add_parser("math")
    math_parser.add_argument("--catalog")
    math_parser.add_argument("--radar", required=True)
    math_parser.add_argument("--date", required=True)
    math_parser.add_argument("--operation", required=True)
    math_parser.add_argument("--format", default="png")
    math_parser.add_argument("--palette", default="thermal")
    math_parser.add_argument("--left-pulse", required=True)
    math_parser.add_argument("--left-time", required=True)
    math_parser.add_argument("--left-quantity", required=True)
    math_parser.add_argument("--left-dataset")
    math_parser.add_argument("--right-pulse", required=True)
    math_parser.add_argument("--right-time", required=True)
    math_parser.add_argument("--right-quantity", required=True)
    math_parser.add_argument("--right-dataset")
    _add_filter_arguments(math_parser)
    math_parser.add_argument("--output-dir", required=True)
    math_parser.set_defaults(func=cmd_math)
