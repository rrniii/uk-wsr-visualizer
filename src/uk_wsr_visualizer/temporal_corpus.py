"""Leakage-controlled consecutive-volume corpus for UK WSR QC."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable

from .background_training import (
    SEASONS,
    SPLITS,
    BackgroundTrainingExclusions,
)
from .background_training_pipeline import (
    VerifiedTrainingSource,
    file_sha256,
)
from .field_audit import PUBLIC_BASE

TEMPORAL_CORPUS_SCHEMA = "uk_wsr_temporal_context_manifest"
TEMPORAL_CORPUS_SCHEMA_VERSION = 1
TEMPORAL_CORPUS_ID = "uk-wsr-temporal-context-v1"
TIME_BUCKETS = ("day", "night")


@dataclass(frozen=True)
class TemporalCorpusSelectionConfig:
    """Consecutive-volume sequence and coverage requirements."""

    pulses: tuple[str, ...] = ("lp", "sp")
    splits: tuple[str, ...] = SPLITS
    seasons: tuple[str, ...] = SEASONS
    time_buckets: tuple[str, ...] = TIME_BUCKETS
    sequences_per_bucket: int = 1
    sequence_length: int = 12
    maximum_gap_minutes: int = 20
    day_start_hour_utc: int = 6
    night_start_hour_utc: int = 19


@dataclass(frozen=True)
class VerifiedTemporalSequence:
    """One verified ordered sequence and its scoring members."""

    sequence_id: str
    radar: str
    pulse: str
    split: str
    season: str
    time_bucket: str
    date: str
    anchor_source_id: str
    source_ids: tuple[str, ...]
    eligible_scoring_source_ids: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedTemporalCorpus:
    """Verified local sources joined to their sequence contract."""

    sources: tuple[VerifiedTrainingSource, ...]
    sequences: tuple[VerifiedTemporalSequence, ...]
    manifest_sha256: str
    ledger_sha256: str
    selected_splits: tuple[str, ...]


def temporal_corpus_local_path(
    root: Path,
    item: dict[str, Any],
) -> Path:
    """Return the stable local path for one unique temporal-corpus PVOL."""

    return (
        root
        / str(item["split"])
        / str(item["radar"])
        / str(item["date"])
        / str(item["pulse"])
        / str(item["filename"])
    )


def build_temporal_context_manifest(
    source_manifest: dict[str, Any],
    fetch_json: Callable[[str], dict[str, Any]],
    *,
    source_manifest_sha256: str,
    config: TemporalCorpusSelectionConfig | None = None,
    exclusions: BackgroundTrainingExclusions | None = None,
    public_base: str = PUBLIC_BASE,
) -> dict[str, Any]:
    """Expand isolated anchors into date-disjoint consecutive sequences."""

    policy = config or TemporalCorpusSelectionConfig()
    blocked = exclusions or BackgroundTrainingExclusions()
    _validate_source_manifest(source_manifest)
    anchors = [
        item
        for item in source_manifest.get("files") or []
        if str(item.get("pulse") or "") in policy.pulses
        and str(item.get("split") or "") in policy.splits
        and str(item.get("season") or "") in policy.seasons
    ]
    radars = sorted({str(item["radar"]) for item in anchors})
    grouped: dict[
        tuple[str, str, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for item in anchors:
        grouped[
            (
                str(item["radar"]),
                str(item["pulse"]),
                str(item["split"]),
                str(item["season"]),
            )
        ].append(item)

    files_by_id: dict[str, dict[str, Any]] = {}
    sequences: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    catalog_cache: dict[str, dict[str, Any]] = {}
    used_sequence_sources: set[str] = set()
    for radar in radars:
        for pulse in policy.pulses:
            for split in policy.splits:
                for season in policy.seasons:
                    for time_bucket in policy.time_buckets:
                        base_key = (
                            radar,
                            pulse,
                            split,
                            season,
                        )
                        base_candidates = grouped.get(base_key, [])
                        bucket_candidates = [
                            item
                            for item in base_candidates
                            if _time_bucket(str(item["time"]), policy)
                            == time_bucket
                        ]
                        candidates = _candidate_order(
                            bucket_candidates or base_candidates
                        )
                        accepted = 0
                        candidate_errors: list[str] = []
                        for anchor in candidates:
                            if accepted >= policy.sequences_per_bucket:
                                break
                            try:
                                sequence, sequence_files = (
                                    _build_sequence_for_anchor(
                                        anchor,
                                        fetch_json=fetch_json,
                                        catalog_cache=catalog_cache,
                                        policy=policy,
                                        exclusions=blocked,
                                        public_base=public_base,
                                        requested_bucket=time_bucket,
                                    )
                                )
                            except (KeyError, TypeError, ValueError) as exc:
                                candidate_errors.append(str(exc))
                                continue
                            source_ids = set(sequence["source_ids"])
                            if source_ids & used_sequence_sources:
                                candidate_errors.append(
                                    f"{anchor['source_id']}: "
                                    "sequence overlaps an accepted sequence"
                                )
                                continue
                            for item in sequence_files:
                                existing = files_by_id.get(item["source_id"])
                                if existing is not None and existing != item:
                                    raise ValueError(
                                        "source ID metadata conflict for "
                                        f"{item['source_id']}"
                                    )
                                files_by_id[item["source_id"]] = item
                            sequences.append(sequence)
                            used_sequence_sources.update(source_ids)
                            accepted += 1
                        if accepted < policy.sequences_per_bucket:
                            errors.append(
                                {
                                    "radar": radar,
                                    "pulse": pulse,
                                    "split": split,
                                    "season": season,
                                    "time_bucket": time_bucket,
                                    "accepted": accepted,
                                    "required": (
                                        policy.sequences_per_bucket
                                    ),
                                    "candidate_errors": candidate_errors,
                                }
                            )

    files = sorted(
        files_by_id.values(),
        key=lambda item: (
            item["radar"],
            policy.splits.index(item["split"]),
            item["date"],
            item["time"],
            item["pulse"],
        ),
    )
    sequences.sort(
        key=lambda item: (
            item["radar"],
            policy.splits.index(item["split"]),
            item["season"],
            item["time_bucket"],
            item["date"],
            item["pulse"],
        )
    )
    manifest = {
        "schema": TEMPORAL_CORPUS_SCHEMA,
        "schema_version": TEMPORAL_CORPUS_SCHEMA_VERSION,
        "manifest_id": TEMPORAL_CORPUS_ID,
        "generated_at": _now_utc(),
        "source_manifest_id": source_manifest.get("manifest_id"),
        "source_manifest_sha256": source_manifest_sha256,
        "selection": {
            **asdict(policy),
            "pulses": list(policy.pulses),
            "splits": list(policy.splits),
            "seasons": list(policy.seasons),
            "time_buckets": list(policy.time_buckets),
            "description": (
                "Date-disjoint, season- and day/night-stratified blocks of "
                "consecutive PVOL volumes. Learned decisions are scored only "
                "on members with both previous and next context."
            ),
            "all_elevations_per_file": True,
            "eligible_scoring_members": "interior_sequence_members_only",
        },
        "leakage_control": {
            "benchmark_urls_excluded": len(blocked.urls),
            "benchmark_radar_dates_excluded": len(blocked.radar_dates),
            "benchmark_source_hashes_excluded": len(
                blocked.source_sha256
            ),
            "exclusion_digest_sha256": blocked.digest(),
            "whole_dates_are_split_exclusive_per_radar": True,
            "sequences_do_not_share_sources": True,
            "source_hashes_must_be_rechecked_after_download": True,
        },
        "radar_count": len(radars),
        "sequence_count": len(sequences),
        "file_count": len(files),
        "errors": errors,
        "counts": _manifest_counts(sequences, files),
        "sequences": sequences,
        "files": files,
    }
    manifest["validation_errors"] = validate_temporal_context_manifest(
        manifest,
        exclusions=blocked,
    )
    return manifest


def validate_temporal_context_manifest(
    manifest: dict[str, Any],
    *,
    exclusions: BackgroundTrainingExclusions | None = None,
) -> list[str]:
    """Return release-blocking temporal corpus errors."""

    blocked = exclusions or BackgroundTrainingExclusions()
    errors: list[str] = []
    files = list(manifest.get("files") or [])
    sequences = list(manifest.get("sequences") or [])
    selection = dict(manifest.get("selection") or {})
    if manifest.get("schema") != TEMPORAL_CORPUS_SCHEMA:
        errors.append("invalid manifest schema")
    if manifest.get("schema_version") != TEMPORAL_CORPUS_SCHEMA_VERSION:
        errors.append("invalid manifest schema version")
    if manifest.get("manifest_id") != TEMPORAL_CORPUS_ID:
        errors.append("invalid manifest id")
    if manifest.get("errors"):
        errors.append(
            f"selection contains {len(manifest['errors'])} errors"
        )
    if int(manifest.get("file_count") or -1) != len(files):
        errors.append("file_count does not match files")
    if int(manifest.get("sequence_count") or -1) != len(sequences):
        errors.append("sequence_count does not match sequences")

    source_ids = [str(item.get("source_id") or "") for item in files]
    urls = [str(item.get("object_url") or "") for item in files]
    if not all(source_ids) or len(source_ids) != len(set(source_ids)):
        errors.append("source IDs must be present and unique")
    if not all(urls) or len(urls) != len(set(urls)):
        errors.append("source URLs must be present and unique")
    file_by_id = {
        str(item["source_id"]): item
        for item in files
        if item.get("source_id")
    }
    sequence_ids = [
        str(sequence.get("sequence_id") or "")
        for sequence in sequences
    ]
    if (
        not all(sequence_ids)
        or len(sequence_ids) != len(set(sequence_ids))
    ):
        errors.append("sequence IDs must be present and unique")

    used_members: list[str] = []
    dates_by_radar_split: dict[tuple[str, str], set[str]] = defaultdict(set)
    grouped: Counter[tuple[str, str, str, str, str]] = Counter()
    expected_length = int(selection.get("sequence_length") or 0)
    maximum_gap = int(selection.get("maximum_gap_minutes") or 0)
    for sequence in sequences:
        sequence_id = str(sequence.get("sequence_id") or "")
        members = list(sequence.get("members") or [])
        member_ids = [str(member.get("source_id") or "") for member in members]
        used_members.extend(member_ids)
        if len(members) != expected_length:
            errors.append(f"{sequence_id}: incorrect sequence length")
            continue
        if member_ids != list(sequence.get("source_ids") or []):
            errors.append(f"{sequence_id}: member/source order mismatch")
        missing = [value for value in member_ids if value not in file_by_id]
        if missing:
            errors.append(f"{sequence_id}: missing source references")
            continue
        anchor_index = int(sequence.get("anchor_index", -1))
        if not 0 < anchor_index < len(members) - 1:
            errors.append(f"{sequence_id}: anchor is not bracketed")
        eligible = list(sequence.get("eligible_scoring_source_ids") or [])
        if eligible != member_ids[1:-1]:
            errors.append(
                f"{sequence_id}: eligible scoring members are not interior"
            )
        rows = [file_by_id[source_id] for source_id in member_ids]
        identity = {
            (
                row.get("radar"),
                row.get("pulse"),
                row.get("split"),
                row.get("season"),
                row.get("date"),
            )
            for row in rows
        }
        if len(identity) != 1:
            errors.append(f"{sequence_id}: source identity changed")
        minutes = [_minutes(str(row["time"])) for row in rows]
        gaps = [
            right - left
            for left, right in zip(minutes, minutes[1:])
        ]
        if any(gap <= 0 or gap > maximum_gap for gap in gaps):
            errors.append(f"{sequence_id}: invalid cadence")
        for index, member in enumerate(members):
            expected_previous = member_ids[index - 1] if index else None
            expected_next = (
                member_ids[index + 1]
                if index + 1 < len(member_ids)
                else None
            )
            if member.get("previous_source_id") != expected_previous:
                errors.append(
                    f"{sequence_id}: incorrect previous source link"
                )
            if member.get("next_source_id") != expected_next:
                errors.append(f"{sequence_id}: incorrect next source link")
        radar = str(sequence.get("radar") or "")
        split = str(sequence.get("split") or "")
        date = str(sequence.get("date") or "")
        dates_by_radar_split[(radar, split)].add(date)
        grouped[
            (
                radar,
                str(sequence.get("pulse") or ""),
                split,
                str(sequence.get("season") or ""),
                str(sequence.get("time_bucket") or ""),
            )
        ] += 1

    if len(used_members) != len(set(used_members)):
        errors.append("sequences share one or more source files")
    for radar in sorted({key[0] for key in dates_by_radar_split}):
        for left_index, left in enumerate(selection.get("splits") or []):
            for right in (selection.get("splits") or [])[left_index + 1 :]:
                overlap = (
                    dates_by_radar_split[(radar, str(left))]
                    & dates_by_radar_split[(radar, str(right))]
                )
                if overlap:
                    errors.append(
                        f"{radar}: {left}/{right} date leakage"
                    )

    radars = sorted({str(item.get("radar") or "") for item in files})
    required = int(selection.get("sequences_per_bucket") or 0)
    for radar in radars:
        for pulse in selection.get("pulses") or []:
            for split in selection.get("splits") or []:
                for season in selection.get("seasons") or []:
                    for time_bucket in selection.get("time_buckets") or []:
                        key = (
                            radar,
                            str(pulse),
                            str(split),
                            str(season),
                            str(time_bucket),
                        )
                        if grouped[key] != required:
                            errors.append(
                                "/".join(key)
                                + f": sequence coverage {grouped[key]}"
                                + f"<>{required}"
                            )

    overlap_urls = set(urls) & set(blocked.urls)
    if overlap_urls:
        errors.append(
            f"benchmark URL leakage: {len(overlap_urls)} source(s)"
        )
    overlap_dates = {
        (str(item.get("radar") or ""), str(item.get("date") or ""))
        for item in files
    } & set(blocked.radar_dates)
    if overlap_dates:
        errors.append(
            f"benchmark date leakage: {len(overlap_dates)} radar/date pair(s)"
        )
    return errors


def load_verified_temporal_context_corpus(
    manifest_path: str | Path,
    ledger_path: str | Path,
    *,
    splits: Iterable[str] = ("training", "validation"),
    radar: Iterable[str] | None = None,
    pulse: Iterable[str] | None = None,
) -> VerifiedTemporalCorpus:
    """Join selected temporal partitions to verified local HDF5 sources."""

    manifest_source = Path(manifest_path)
    ledger_source = Path(ledger_path)
    manifest = json.loads(manifest_source.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_source.read_text(encoding="utf-8"))
    manifest_hash = file_sha256(manifest_source)
    if ledger.get("manifest_sha256") != manifest_hash:
        raise ValueError("download ledger does not match temporal manifest")
    if ledger.get("failures"):
        raise ValueError("download ledger contains failed sources")

    selected_splits = tuple(dict.fromkeys(str(value) for value in splits))
    if not selected_splits:
        raise ValueError("at least one temporal split is required")
    if set(selected_splits) != set(ledger.get("selected_splits") or []):
        raise ValueError("download ledger covers different temporal splits")
    expected_items = [
        item
        for item in manifest.get("files") or []
        if str(item.get("split") or "") in selected_splits
    ]
    expected_ids = {str(item["source_id"]) for item in expected_items}
    expected_ids_hash = sha256(
        "\n".join(sorted(expected_ids)).encode("utf-8")
    ).hexdigest()
    if (
        int(ledger.get("selected_file_count") or -1)
        != len(expected_items)
        or int(ledger.get("validated_file_count") or -1)
        != len(expected_items)
        or ledger.get("selected_source_ids_sha256")
        != expected_ids_hash
    ):
        raise ValueError("download ledger is incomplete for selected splits")

    wanted_radars = {str(value) for value in radar or ()}
    wanted_pulses = {str(value).lower() for value in pulse or ()}
    ledger_files = ledger.get("files")
    if not isinstance(ledger_files, dict):
        raise ValueError("download ledger has no source file map")
    sources: list[VerifiedTrainingSource] = []
    available_ids: set[str] = set()
    for item in expected_items:
        if wanted_radars and str(item["radar"]) not in wanted_radars:
            continue
        if (
            wanted_pulses
            and str(item["pulse"]).lower() not in wanted_pulses
        ):
            continue
        source_id = str(item["source_id"])
        verified = ledger_files.get(source_id)
        if not isinstance(verified, dict):
            raise ValueError(
                f"source {source_id} is missing from temporal ledger"
            )
        local_path = Path(str(verified.get("local_path") or ""))
        digest = str(verified.get("sha256") or "")
        if (
            verified.get("hdf5_valid") is not True
            or verified.get("benchmark_hash_exclusion_checked") is not True
            or len(digest) != 64
            or not local_path.is_file()
            or local_path.stat().st_size
            != int(verified.get("size_bytes") or -1)
            or file_sha256(local_path) != digest
        ):
            raise ValueError(
                f"source {source_id} is not a verified local HDF5 file"
            )
        available_ids.add(source_id)
        sources.append(
            VerifiedTrainingSource(
                source_id=source_id,
                radar=str(item["radar"]),
                pulse=str(item["pulse"]).lower(),
                split=str(item["split"]),
                date=str(item["date"]),
                time=str(item["time"]),
                local_path=str(local_path),
                object_url=str(item["object_url"]),
                object_key=(
                    str(item["object_key"])
                    if item.get("object_key")
                    else None
                ),
                sha256=digest,
                size_bytes=int(verified["size_bytes"]),
                season=str(item["season"]),
                utc_slot=str(item["time_bucket"]),
            )
        )

    sequences: list[VerifiedTemporalSequence] = []
    for sequence in manifest.get("sequences") or []:
        if str(sequence.get("split") or "") not in selected_splits:
            continue
        if (
            wanted_radars
            and str(sequence.get("radar") or "") not in wanted_radars
        ):
            continue
        if (
            wanted_pulses
            and str(sequence.get("pulse") or "").lower()
            not in wanted_pulses
        ):
            continue
        source_ids = tuple(
            str(value) for value in sequence["source_ids"]
        )
        if not set(source_ids) <= available_ids:
            raise ValueError(
                f"sequence {sequence['sequence_id']} lacks local sources"
            )
        sequences.append(
            VerifiedTemporalSequence(
                sequence_id=str(sequence["sequence_id"]),
                radar=str(sequence["radar"]),
                pulse=str(sequence["pulse"]).lower(),
                split=str(sequence["split"]),
                season=str(sequence["season"]),
                time_bucket=str(sequence["time_bucket"]),
                date=str(sequence["date"]),
                anchor_source_id=str(sequence["anchor_source_id"]),
                source_ids=source_ids,
                eligible_scoring_source_ids=tuple(
                    str(value)
                    for value in sequence["eligible_scoring_source_ids"]
                ),
            )
        )
    return VerifiedTemporalCorpus(
        sources=tuple(
            sorted(
                sources,
                key=lambda source: (
                    source.radar,
                    source.pulse,
                    source.split,
                    source.date,
                    source.time,
                ),
            )
        ),
        sequences=tuple(
            sorted(
                sequences,
                key=lambda sequence: sequence.sequence_id,
            )
        ),
        manifest_sha256=manifest_hash,
        ledger_sha256=file_sha256(ledger_source),
        selected_splits=selected_splits,
    )


def _build_sequence_for_anchor(
    anchor: dict[str, Any],
    *,
    fetch_json: Callable[[str], dict[str, Any]],
    catalog_cache: dict[str, dict[str, Any]],
    policy: TemporalCorpusSelectionConfig,
    exclusions: BackgroundTrainingExclusions,
    public_base: str,
    requested_bucket: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    radar = str(anchor["radar"])
    pulse = str(anchor["pulse"])
    date = str(anchor["date"])
    catalog_key = str(anchor.get("catalog_key") or "")
    if not catalog_key:
        raise ValueError(f"{anchor['source_id']}: catalog key missing")
    catalog_url = _public_url(public_base, catalog_key)
    if catalog_url not in catalog_cache:
        catalog_cache[catalog_url] = fetch_json(catalog_url)
    catalog = catalog_cache[catalog_url]
    candidates = [
        item
        for item in catalog.get("files") or []
        if str(item.get("pulse") or "").lower() == pulse
        and _valid_time(str(item.get("time") or ""))
    ]
    candidates.sort(
        key=lambda item: (
            _minutes(str(item["time"])),
            str(item.get("filename") or ""),
        )
    )
    if len(candidates) < policy.sequence_length:
        raise ValueError(
            f"{anchor['source_id']}: only {len(candidates)} same-pulse files"
        )
    source_anchor_time = str(anchor["time"]).zfill(4)
    requested_time = (
        source_anchor_time
        if _time_bucket(source_anchor_time, policy) == requested_bucket
        else _canonical_bucket_time(requested_bucket)
    )
    selected, relative_anchor = _select_bracketed_window(
        candidates,
        requested_time=requested_time,
        requested_bucket=requested_bucket,
        policy=policy,
    )
    times = [str(item["time"]).zfill(4) for item in selected]
    minutes = [_minutes(value) for value in times]
    gaps = [
        right - left
        for left, right in zip(minutes, minutes[1:])
    ]
    if any(
        gap <= 0 or gap > policy.maximum_gap_minutes
        for gap in gaps
    ):
        raise ValueError(
            f"{anchor['source_id']}: cadence outside 1-"
            f"{policy.maximum_gap_minutes} minutes"
        )

    files: list[dict[str, Any]] = []
    for source in selected:
        time = str(source["time"]).zfill(4)
        filename = str(source.get("filename") or "")
        object_key = str(source.get("object_key") or "")
        object_url = str(
            source.get("object_url")
            or _public_url(public_base, object_key)
        )
        if (
            not object_url
            or object_url in exclusions.urls
            or (radar, date) in exclusions.radar_dates
        ):
            raise ValueError(
                f"{anchor['source_id']}: benchmark-excluded source"
            )
        files.append(
            {
                "source_id": _source_id(
                    radar,
                    date,
                    time,
                    pulse,
                    filename,
                ),
                "split": str(anchor["split"]),
                "season": str(anchor["season"]),
                "time_bucket": requested_bucket,
                "date": date,
                "time": time,
                "radar": radar,
                "radar_num": str(anchor.get("radar_num") or ""),
                "pulse": pulse,
                "quantity": "DBZH",
                "all_elevations": True,
                "joint_companion_fields": list(
                    anchor.get("joint_companion_fields") or []
                ),
                "filename": filename,
                "object_key": object_key or None,
                "object_url": object_url,
                "size_bytes": int(source.get("size_bytes") or 0),
                "catalog_key": catalog_key,
                "benchmark_exclusion_checked": True,
                "source_sha256_required_after_download": True,
            }
        )
    source_ids = [item["source_id"] for item in files]
    sequence_digest = sha256(
        "|".join(
            [
                radar,
                date,
                pulse,
                source_ids[0],
                source_ids[-1],
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    members = [
        {
            "sequence_index": index,
            "source_id": source_id,
            "role": "anchor" if index == relative_anchor else "context",
            "previous_source_id": (
                source_ids[index - 1] if index else None
            ),
            "next_source_id": (
                source_ids[index + 1]
                if index + 1 < len(source_ids)
                else None
            ),
        }
        for index, source_id in enumerate(source_ids)
    ]
    return (
        {
            "sequence_id": (
                f"{radar}-{date}-{pulse}-{times[0]}-{times[-1]}-"
                f"{sequence_digest}"
            ),
            "split": str(anchor["split"]),
            "season": str(anchor["season"]),
            "time_bucket": requested_bucket,
            "radar": radar,
            "pulse": pulse,
            "date": date,
            "anchor_source_id": source_ids[relative_anchor],
            "anchor_index": relative_anchor,
            "requested_anchor_source_id": str(anchor["source_id"]),
            "source_manifest_anchor_time": source_anchor_time,
            "requested_anchor_time": requested_time,
            "anchor_time_offset_minutes": _time_distance(
                times[relative_anchor],
                requested_time,
            ),
            "start_time": times[0],
            "end_time": times[-1],
            "sequence_length": len(source_ids),
            "minimum_gap_minutes": min(gaps),
            "median_gap_minutes": float(median(gaps)),
            "maximum_gap_minutes": max(gaps),
            "source_ids": source_ids,
            "eligible_scoring_source_ids": source_ids[1:-1],
            "members": members,
        },
        files,
    )


def _validate_source_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("validation_errors"):
        raise ValueError("source manifest has validation errors")
    if manifest.get("errors"):
        raise ValueError("source manifest has selection errors")
    if not manifest.get("files"):
        raise ValueError("source manifest contains no files")


def _select_bracketed_window(
    candidates: list[dict[str, Any]],
    *,
    requested_time: str,
    requested_bucket: str,
    policy: TemporalCorpusSelectionConfig,
) -> tuple[list[dict[str, Any]], int]:
    length = policy.sequence_length
    maximum_start = len(candidates) - length
    anchor_indices = [
        index
        for index, candidate in enumerate(candidates)
        if 0 < index < len(candidates) - 1
        and _time_bucket(str(candidate["time"]), policy)
        == requested_bucket
    ]
    anchor_indices.sort(
        key=lambda index: (
            _time_distance(
                str(candidates[index]["time"]),
                requested_time,
            ),
            str(candidates[index]["time"]),
        )
    )
    for anchor_index in anchor_indices:
        minimum_start = max(0, anchor_index - (length - 2))
        maximum_anchor_start = min(anchor_index - 1, maximum_start)
        if minimum_start > maximum_anchor_start:
            continue
        preferred_start = max(
            minimum_start,
            min(
                anchor_index - length // 2,
                maximum_anchor_start,
            ),
        )
        starts = sorted(
            range(minimum_start, maximum_anchor_start + 1),
            key=lambda start: (
                abs(start - preferred_start),
                start,
            ),
        )
        for start in starts:
            selected = candidates[start : start + length]
            minutes = [
                _minutes(str(candidate["time"]))
                for candidate in selected
            ]
            gaps = [
                right - left
                for left, right in zip(minutes, minutes[1:])
            ]
            if all(
                0 < gap <= policy.maximum_gap_minutes
                for gap in gaps
            ):
                return selected, anchor_index - start
    raise ValueError(
        f"no bracketed {requested_bucket} sequence of {length} volumes "
        f"within {policy.maximum_gap_minutes}-minute cadence"
    )


def _candidate_order(
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("time") or ""),
            str(item.get("source_id") or ""),
        ),
    )
    if not ordered:
        return []
    centre = (len(ordered) - 1) / 2
    return sorted(
        ordered,
        key=lambda item: (
            abs(ordered.index(item) - centre),
            str(item.get("date") or ""),
            str(item.get("time") or ""),
        ),
    )


def _manifest_counts(
    sequences: Iterable[dict[str, Any]],
    files: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    sequence_rows = list(sequences)
    file_rows = list(files)
    return {
        "sequences_by_split": dict(
            sorted(
                Counter(
                    str(item["split"]) for item in sequence_rows
                ).items()
            )
        ),
        "sequences_by_pulse": dict(
            sorted(
                Counter(
                    str(item["pulse"]) for item in sequence_rows
                ).items()
            )
        ),
        "sequences_by_season": dict(
            sorted(
                Counter(
                    str(item["season"]) for item in sequence_rows
                ).items()
            )
        ),
        "sequences_by_time_bucket": dict(
            sorted(
                Counter(
                    str(item["time_bucket"]) for item in sequence_rows
                ).items()
            )
        ),
        "files_by_split": dict(
            sorted(
                Counter(str(item["split"]) for item in file_rows).items()
            )
        ),
    }


def _time_bucket(
    value: str,
    policy: TemporalCorpusSelectionConfig,
) -> str:
    minutes = _minutes(value)
    day_start = policy.day_start_hour_utc * 60
    night_start = policy.night_start_hour_utc * 60
    return "day" if day_start <= minutes < night_start else "night"


def _source_id(
    radar: str,
    date: str,
    time: str,
    pulse: str,
    filename: str,
) -> str:
    digest = sha256(
        f"{radar}|{date}|{time}|{pulse}|{filename}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{radar}-{date}-{time}-{pulse}-{digest}"


def _canonical_bucket_time(time_bucket: str) -> str:
    if time_bucket == "day":
        return "1200"
    if time_bucket == "night":
        return "0000"
    raise ValueError(f"unsupported time bucket {time_bucket!r}")


def _public_url(base: str, key: str) -> str:
    if key.startswith(("http://", "https://")):
        return key
    return f"{base.rstrip('/')}/{key.lstrip('/')}"


def _minutes(value: str) -> int:
    text = str(value).zfill(4)
    if not _valid_time(text):
        raise ValueError(f"invalid HHMM time {value!r}")
    return int(text[:2]) * 60 + int(text[2:])


def _time_distance(first: str, second: str) -> int:
    direct = abs(_minutes(first) - _minutes(second))
    return min(direct, 24 * 60 - direct)


def _valid_time(value: str) -> bool:
    text = str(value).zfill(4)
    return (
        len(text) == 4
        and text.isdigit()
        and 0 <= int(text[:2]) <= 23
        and 0 <= int(text[2:]) <= 59
    )


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_temporal_context_manifest(
    manifest: dict[str, Any],
    output_dir: str | Path,
) -> tuple[Path, str]:
    """Write the manifest and checksum atomically."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    payload = (
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(manifest_path)
    digest = sha256(payload.encode("utf-8")).hexdigest()
    checksum_path = destination / "manifest.sha256"
    checksum_temporary = checksum_path.with_suffix(".sha256.tmp")
    checksum_temporary.write_text(
        f"{digest}  manifest.json\n",
        encoding="ascii",
    )
    checksum_temporary.replace(checksum_path)
    return manifest_path, digest
