"""Leakage-controlled source selection for learned UK WSR background models."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
from typing import Any, Callable, Iterable

from .field_audit import PUBLIC_BASE

BACKGROUND_TRAINING_MANIFEST_SCHEMA = "uk_wsr_background_training_manifest"
BACKGROUND_TRAINING_MANIFEST_SCHEMA_VERSION = 1
BACKGROUND_TRAINING_MANIFEST_ID = "uk-wsr-background-training-v2"

SEASONS = ("winter", "spring", "summer", "autumn")
SPLITS = ("training", "validation", "holdout")
UTC_SLOTS = {
    "0000": "overnight",
    "0400": "pre_dawn",
    "0800": "morning",
    "1200": "midday",
    "1800": "evening_transition",
    "2200": "late_evening",
}
TIME_PAIRS = (
    ("0000", "1200"),
    ("0400", "1800"),
    ("0800", "2200"),
)


@dataclass(frozen=True)
class BackgroundTrainingSelectionConfig:
    """Selection and release requirements for the multi-date source corpus."""

    training_year: str = "2023"
    evaluation_year: str = "2025"
    pulses: tuple[str, ...] = ("lp", "sp")
    training_dates_per_season: int = 6
    evaluation_dates_per_season: int = 2
    times_per_date: int = 2
    minimum_day_coverage_fraction: float = 0.50
    maximum_time_offset_minutes: int = 20
    minimum_training_sources: int = 48
    minimum_training_dates: int = 20
    minimum_training_span_days: int = 180
    minimum_training_dates_per_season: int = 4
    minimum_training_sources_per_utc_slot: int = 4
    minimum_validation_dates: int = 4
    minimum_holdout_dates: int = 4


@dataclass(frozen=True)
class BackgroundTrainingExclusions:
    """Benchmark sources that must never enter model construction or tuning."""

    urls: frozenset[str] = frozenset()
    radar_dates: frozenset[tuple[str, str]] = frozenset()
    source_sha256: frozenset[str] = frozenset()

    def digest(self) -> str:
        payload = "\n".join(
            [
                *(f"url:{value}" for value in sorted(self.urls)),
                *(f"date:{radar}:{date}" for radar, date in sorted(self.radar_dates)),
                *(f"sha256:{value}" for value in sorted(self.source_sha256)),
            ]
        )
        return sha256(payload.encode("utf-8")).hexdigest()


def build_background_training_manifest(
    root_catalog: dict[str, Any],
    fetch_json: Callable[[str], dict[str, Any]],
    *,
    config: BackgroundTrainingSelectionConfig | None = None,
    exclusions: BackgroundTrainingExclusions | None = None,
    public_base: str = PUBLIC_BASE,
) -> dict[str, Any]:
    """Select multi-date training, validation, and holdout PVOL sources."""

    policy = config or BackgroundTrainingSelectionConfig()
    blocked = exclusions or BackgroundTrainingExclusions()
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    coverage_cache: dict[str, dict[str, Any]] = {}
    catalog_cache: dict[str, dict[str, Any]] = {}
    used_urls: set[str] = set()

    radars = sorted(
        root_catalog.get("radars", []),
        key=lambda value: str(value.get("radar") or ""),
    )
    for radar_entry in radars:
        radar = str(radar_entry.get("radar") or "")
        training_days = _load_eligible_days(
            radar_entry,
            year=policy.training_year,
            radar=radar,
            fetch_json=fetch_json,
            public_base=public_base,
            coverage_cache=coverage_cache,
            policy=policy,
            exclusions=blocked,
            errors=errors,
        )
        evaluation_days = _load_eligible_days(
            radar_entry,
            year=policy.evaluation_year,
            radar=radar,
            fetch_json=fetch_json,
            public_base=public_base,
            coverage_cache=coverage_cache,
            policy=policy,
            exclusions=blocked,
            errors=errors,
        )
        if not training_days or not evaluation_days:
            continue

        radar_files, radar_errors, radar_warnings = _select_radar_sources(
            radar_entry,
            training_days=training_days,
            evaluation_days=evaluation_days,
            fetch_json=fetch_json,
            public_base=public_base,
            catalog_cache=catalog_cache,
            used_urls=used_urls,
            policy=policy,
            exclusions=blocked,
        )
        files.extend(radar_files)
        errors.extend(radar_errors)
        warnings.extend(radar_warnings)

    files.sort(
        key=lambda value: (
            value["radar"],
            SPLITS.index(value["split"]),
            value["date"],
            value["target_time"],
            value["pulse"],
        )
    )
    manifest = {
        "schema": BACKGROUND_TRAINING_MANIFEST_SCHEMA,
        "schema_version": BACKGROUND_TRAINING_MANIFEST_SCHEMA_VERSION,
        "manifest_id": BACKGROUND_TRAINING_MANIFEST_ID,
        "generated_at": _now_utc(),
        "selection": {
            **asdict(policy),
            "pulses": list(policy.pulses),
            "description": (
                "Multi-date, season/time-stratified PVOL sources. Model construction uses "
                f"{policy.training_year}; threshold development and final holdout use disjoint "
                f"dates from {policy.evaluation_year}."
            ),
            "all_elevations_per_file": True,
            "joint_field_statistics": True,
            "quantity_contract": (
                "DBZH is the reference gate grid; CI, VRAD, SQI, RHOHV, ZDR, PHIDP, and width "
                "are companion evidence. One artifact decision is shared by aligned quantities."
            ),
        },
        "leakage_control": {
            "benchmark_urls_excluded": len(blocked.urls),
            "benchmark_radar_dates_excluded": len(blocked.radar_dates),
            "benchmark_source_hashes_excluded": len(blocked.source_sha256),
            "exclusion_digest_sha256": blocked.digest(),
            "source_hashes_must_be_rechecked_after_download": True,
            "whole_dates_are_split_exclusive_per_radar": True,
        },
        "radar_count": len(radars),
        "file_count": len(files),
        "errors": errors,
        "warnings": warnings,
        "counts": background_training_counts(files),
        "files": files,
    }
    manifest["validation_errors"] = validate_background_training_manifest(
        manifest,
        exclusions=blocked,
    )
    return manifest


def validate_background_training_manifest(
    manifest: dict[str, Any],
    *,
    exclusions: BackgroundTrainingExclusions | None = None,
) -> list[str]:
    """Return release-blocking errors for a background-training manifest."""

    errors: list[str] = []
    files = list(manifest.get("files", []))
    selection = manifest.get("selection", {})
    blocked = exclusions or BackgroundTrainingExclusions()
    if manifest.get("schema") != BACKGROUND_TRAINING_MANIFEST_SCHEMA:
        errors.append("invalid manifest schema")
    if manifest.get("schema_version") != BACKGROUND_TRAINING_MANIFEST_SCHEMA_VERSION:
        errors.append("invalid manifest schema version")
    if manifest.get("manifest_id") != BACKGROUND_TRAINING_MANIFEST_ID:
        errors.append("invalid manifest id")
    if manifest.get("errors"):
        errors.append(f"selection contains {len(manifest['errors'])} errors")
    if int(manifest.get("file_count") or 0) != len(files):
        errors.append("file_count does not match files")

    urls = [str(item.get("object_url") or "") for item in files]
    source_ids = [str(item.get("source_id") or "") for item in files]
    if not all(urls) or len(urls) != len(set(urls)):
        errors.append("source URLs must be present and unique")
    if not all(source_ids) or len(source_ids) != len(set(source_ids)):
        errors.append("source IDs must be present and unique")

    overlap_urls = sorted(set(urls) & set(blocked.urls))
    if overlap_urls:
        errors.append(f"benchmark URL leakage: {len(overlap_urls)} source(s)")
    overlap_dates = sorted(
        {
            (str(item.get("radar") or ""), str(item.get("date") or ""))
            for item in files
        }
        & set(blocked.radar_dates)
    )
    if overlap_dates:
        errors.append(f"benchmark date leakage: {len(overlap_dates)} radar/date pair(s)")

    dates_by_radar_split: dict[tuple[str, str], set[str]] = defaultdict(set)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in files:
        radar = str(item.get("radar") or "")
        pulse = str(item.get("pulse") or "")
        split = str(item.get("split") or "")
        date = str(item.get("date") or "")
        if split not in SPLITS:
            errors.append(f"{item.get('source_id')}: invalid split")
        if pulse not in selection.get("pulses", []):
            errors.append(f"{item.get('source_id')}: invalid pulse")
        if item.get("quantity") != "DBZH" or item.get("all_elevations") is not True:
            errors.append(f"{item.get('source_id')}: joint-field/all-elevation contract missing")
        if item.get("benchmark_exclusion_checked") is not True:
            errors.append(f"{item.get('source_id')}: benchmark exclusion was not checked")
        dates_by_radar_split[(radar, split)].add(date)
        grouped[(radar, pulse)].append(item)

    for radar in sorted({key[0] for key in dates_by_radar_split}):
        for left_index, left in enumerate(SPLITS):
            for right in SPLITS[left_index + 1 :]:
                overlap = dates_by_radar_split[(radar, left)] & dates_by_radar_split[(radar, right)]
                if overlap:
                    errors.append(
                        f"{radar}: {left}/{right} date leakage: {','.join(sorted(overlap))}"
                    )

    minimum_training_sources = int(selection.get("minimum_training_sources") or 0)
    minimum_training_dates = int(selection.get("minimum_training_dates") or 0)
    minimum_span = int(selection.get("minimum_training_span_days") or 0)
    minimum_dates_per_season = int(selection.get("minimum_training_dates_per_season") or 0)
    minimum_per_slot = int(selection.get("minimum_training_sources_per_utc_slot") or 0)
    minimum_validation_dates = int(selection.get("minimum_validation_dates") or 0)
    minimum_holdout_dates = int(selection.get("minimum_holdout_dates") or 0)
    expected_pulses = set(str(value) for value in selection.get("pulses", []))
    expected_radars = set(str(item.get("radar") or "") for item in files)
    if len(grouped) != len(expected_radars) * len(expected_pulses):
        errors.append("radar/pulse grid is incomplete")

    for (radar, pulse), rows in sorted(grouped.items()):
        training = [row for row in rows if row["split"] == "training"]
        validation = [row for row in rows if row["split"] == "validation"]
        holdout = [row for row in rows if row["split"] == "holdout"]
        training_dates = sorted({row["date"] for row in training})
        if len(training) < minimum_training_sources:
            errors.append(
                f"{radar}/{pulse}: training sources {len(training)}<{minimum_training_sources}"
            )
        if len(training_dates) < minimum_training_dates:
            errors.append(
                f"{radar}/{pulse}: training dates {len(training_dates)}<{minimum_training_dates}"
            )
        span = _date_span_days(training_dates)
        if span < minimum_span:
            errors.append(f"{radar}/{pulse}: training span {span}<{minimum_span}")
        season_dates = {
            season: {row["date"] for row in training if row["season"] == season}
            for season in SEASONS
        }
        for season, dates in season_dates.items():
            if len(dates) < minimum_dates_per_season:
                errors.append(
                    f"{radar}/{pulse}: {season} training dates "
                    f"{len(dates)}<{minimum_dates_per_season}"
                )
        slot_counts = Counter(str(row["utc_slot"]) for row in training)
        for slot in UTC_SLOTS.values():
            if slot_counts[slot] < minimum_per_slot:
                errors.append(
                    f"{radar}/{pulse}: {slot} training sources "
                    f"{slot_counts[slot]}<{minimum_per_slot}"
                )
        validation_dates = {row["date"] for row in validation}
        holdout_dates = {row["date"] for row in holdout}
        if len(validation_dates) < minimum_validation_dates:
            errors.append(
                f"{radar}/{pulse}: validation dates "
                f"{len(validation_dates)}<{minimum_validation_dates}"
            )
        if len(holdout_dates) < minimum_holdout_dates:
            errors.append(
                f"{radar}/{pulse}: holdout dates {len(holdout_dates)}<{minimum_holdout_dates}"
            )
        for split, split_rows in (("validation", validation), ("holdout", holdout)):
            present = {row["season"] for row in split_rows}
            missing = sorted(set(SEASONS) - present)
            if missing:
                errors.append(f"{radar}/{pulse}: {split} missing seasons {','.join(missing)}")
    return errors


def background_training_counts(files: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries = list(files)
    return {
        "by_split": dict(sorted(Counter(str(item["split"]) for item in entries).items())),
        "by_pulse": dict(sorted(Counter(str(item["pulse"]) for item in entries).items())),
        "by_radar": dict(sorted(Counter(str(item["radar"]) for item in entries).items())),
        "by_season": dict(sorted(Counter(str(item["season"]) for item in entries).items())),
        "by_utc_slot": dict(sorted(Counter(str(item["utc_slot"]) for item in entries).items())),
    }


def _select_radar_sources(
    radar_entry: dict[str, Any],
    *,
    training_days: list[dict[str, Any]],
    evaluation_days: list[dict[str, Any]],
    fetch_json: Callable[[str], dict[str, Any]],
    public_base: str,
    catalog_cache: dict[str, dict[str, Any]],
    used_urls: set[str],
    policy: BackgroundTrainingSelectionConfig,
    exclusions: BackgroundTrainingExclusions,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    radar = str(radar_entry.get("radar") or "")
    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    used_dates: set[str] = set()
    target_training_dates = policy.training_dates_per_season * len(SEASONS)

    for season_index, season in enumerate(SEASONS):
        candidates = [day for day in training_days if _season(str(day["date"])) == season]
        preferred = _select_spread(candidates, policy.training_dates_per_season)
        selected_dates = {str(day["date"]) for day in preferred}
        ordered_candidates = preferred + [
            day for day in candidates if str(day["date"]) not in selected_dates
        ]
        accepted = 0
        for day in ordered_candidates:
            if accepted >= policy.training_dates_per_season:
                break
            date_index = accepted
            pair = TIME_PAIRS[(season_index + date_index) % len(TIME_PAIRS)]
            rows, error = _entries_for_day(
                radar_entry,
                day,
                split="training",
                season=season,
                target_times=pair[: policy.times_per_date],
                fetch_json=fetch_json,
                public_base=public_base,
                catalog_cache=catalog_cache,
                used_urls=used_urls,
                policy=policy,
                exclusions=exclusions,
            )
            if error:
                warnings.append(error)
                continue
            files.extend(rows)
            used_dates.add(str(day["date"]))
            accepted += 1

    selected_training_dates = {
        str(item["date"]) for item in files if item["split"] == "training"
    }
    missing_training_dates = target_training_dates - len(selected_training_dates)
    if missing_training_dates > 0:
        remaining = [
            day for day in training_days if str(day["date"]) not in selected_training_dates
        ]
        for extra_index, day in enumerate(_select_spread(remaining, missing_training_dates)):
            season = _season(str(day["date"]))
            pair = TIME_PAIRS[(extra_index + len(selected_training_dates)) % len(TIME_PAIRS)]
            rows, error = _entries_for_day(
                radar_entry,
                day,
                split="training",
                season=season,
                target_times=pair[: policy.times_per_date],
                fetch_json=fetch_json,
                public_base=public_base,
                catalog_cache=catalog_cache,
                used_urls=used_urls,
                policy=policy,
                exclusions=exclusions,
            )
            if error:
                warnings.append(error)
                continue
            files.extend(rows)
            used_dates.add(str(day["date"]))

    for season_index, season in enumerate(SEASONS):
        candidates = [
            day
            for day in evaluation_days
            if _season(str(day["date"])) == season
            and str(day["date"]) not in used_dates
        ]
        preferred = _select_spread(candidates, policy.evaluation_dates_per_season)
        selected_dates = {str(day["date"]) for day in preferred}
        ordered_candidates = preferred + [
            day for day in candidates if str(day["date"]) not in selected_dates
        ]
        accepted = 0
        for day in ordered_candidates:
            if accepted >= policy.evaluation_dates_per_season:
                break
            split_index = accepted
            split = ("validation", "holdout")[split_index]
            pair = TIME_PAIRS[(season_index + split_index) % len(TIME_PAIRS)]
            rows, error = _entries_for_day_with_time_fallback(
                radar_entry,
                day,
                split=split,
                season=season,
                preferred_times=pair[: policy.times_per_date],
                fetch_json=fetch_json,
                public_base=public_base,
                catalog_cache=catalog_cache,
                used_urls=used_urls,
                policy=policy,
                exclusions=exclusions,
            )
            if error:
                warnings.append(error)
                continue
            files.extend(rows)
            used_dates.add(str(day["date"]))
            accepted += 1
        if accepted < policy.evaluation_dates_per_season:
            errors.append(
                {
                    "radar": radar,
                    "split": "evaluation",
                    "season": season,
                    "error": (
                        f"eligible_dates:{accepted}"
                        f"<{policy.evaluation_dates_per_season}"
                    ),
                }
            )

    return files, errors, warnings


def _entries_for_day_with_time_fallback(
    radar_entry: dict[str, Any],
    day: dict[str, Any],
    *,
    split: str,
    season: str,
    preferred_times: tuple[str, ...],
    fetch_json: Callable[[str], dict[str, Any]],
    public_base: str,
    catalog_cache: dict[str, dict[str, Any]],
    used_urls: set[str],
    policy: BackgroundTrainingSelectionConfig,
    exclusions: BackgroundTrainingExclusions,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    errors: list[str] = []
    for target_times in _target_time_candidates(preferred_times):
        rows, error = _entries_for_day(
            radar_entry,
            day,
            split=split,
            season=season,
            target_times=target_times,
            fetch_json=fetch_json,
            public_base=public_base,
            catalog_cache=catalog_cache,
            used_urls=used_urls,
            policy=policy,
            exclusions=exclusions,
        )
        if error is None:
            return rows, None
        errors.append(str(error["error"]))
    radar = str(radar_entry.get("radar") or "")
    date = str(day.get("date") or "")
    return [], _source_error(
        radar,
        split,
        season,
        date,
        "no_common_time_pair:" + "|".join(errors),
    )


def _entries_for_day(
    radar_entry: dict[str, Any],
    day: dict[str, Any],
    *,
    split: str,
    season: str,
    target_times: tuple[str, ...],
    fetch_json: Callable[[str], dict[str, Any]],
    public_base: str,
    catalog_cache: dict[str, dict[str, Any]],
    used_urls: set[str],
    policy: BackgroundTrainingSelectionConfig,
    exclusions: BackgroundTrainingExclusions,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    radar = str(radar_entry.get("radar") or "")
    date = str(day.get("date") or "")
    catalog_key = str(day.get("catalog_key") or "")
    if not catalog_key:
        return [], _source_error(radar, split, season, date, "catalog_key_missing")
    catalog_url = _public_url(public_base, catalog_key)
    try:
        if catalog_url not in catalog_cache:
            catalog_cache[catalog_url] = fetch_json(catalog_url)
        catalog = catalog_cache[catalog_url]
    except Exception as exc:  # noqa: BLE001 - batch selection records source failure.
        return [], _source_error(
            radar,
            split,
            season,
            date,
            f"catalog_fetch_failed:{type(exc).__name__}:{exc}",
        )

    selected: list[tuple[str, str, dict[str, Any], str]] = []
    local_urls: set[str] = set()
    for target_time in target_times:
        for pulse in policy.pulses:
            source = _nearest_file(catalog.get("files", []), pulse=pulse, target_time=target_time)
            if source is None:
                return [], _source_error(
                    radar,
                    split,
                    season,
                    date,
                    f"{pulse}/{target_time}:source_missing",
                )
            actual_time = str(source.get("time") or "").zfill(4)
            offset = _time_distance(actual_time, target_time)
            object_url = str(
                source.get("object_url")
                or _public_url(public_base, str(source.get("object_key") or ""))
            )
            if offset > policy.maximum_time_offset_minutes:
                return [], _source_error(
                    radar,
                    split,
                    season,
                    date,
                    f"{pulse}/{target_time}:time_offset:{offset}",
                )
            if not object_url or object_url in used_urls or object_url in local_urls:
                return [], _source_error(
                    radar,
                    split,
                    season,
                    date,
                    f"{pulse}/{target_time}:source_duplicate",
                )
            if object_url in exclusions.urls or (radar, date) in exclusions.radar_dates:
                return [], _source_error(
                    radar,
                    split,
                    season,
                    date,
                    f"{pulse}/{target_time}:benchmark_excluded",
                )
            local_urls.add(object_url)
            selected.append((target_time, pulse, source, object_url))

    rows: list[dict[str, Any]] = []
    for target_time, pulse, source, object_url in selected:
        actual_time = str(source.get("time") or "").zfill(4)
        source_id = _source_id(
            radar,
            date,
            actual_time,
            pulse,
            str(source.get("filename") or ""),
        )
        rows.append(
            {
                "source_id": source_id,
                "split": split,
                "season": season,
                "utc_slot": UTC_SLOTS[target_time],
                "target_time": target_time,
                "date": date,
                "time": actual_time,
                "time_offset_minutes": _time_distance(actual_time, target_time),
                "radar": radar,
                "radar_num": str(radar_entry.get("radar_num") or ""),
                "pulse": pulse,
                "quantity": "DBZH",
                "all_elevations": True,
                "joint_companion_fields": [
                    "CI",
                    "VRADH",
                    "SQIH",
                    "RHOHV",
                    "ZDR",
                    "PHIDP",
                    "WRADH",
                ],
                "filename": str(source.get("filename") or ""),
                "object_key": source.get("object_key"),
                "object_url": object_url,
                "size_bytes": int(source.get("size_bytes") or 0),
                "catalog_key": catalog_key,
                "benchmark_exclusion_checked": True,
                "source_sha256_required_after_download": True,
            }
        )
    used_urls.update(local_urls)
    return rows, None


def _target_time_candidates(
    preferred_times: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    preferred = tuple(preferred_times)
    if len(preferred) <= 1:
        ordered = [preferred]
        ordered.extend((value,) for value in UTC_SLOTS if (value,) != preferred)
        return tuple(ordered)
    if len(preferred) != 2:
        return (preferred,)
    alternatives = sorted(
        (
            tuple(values)
            for values in combinations(UTC_SLOTS, 2)
            if tuple(values) != preferred
        ),
        key=lambda values: (
            -_time_distance(values[0], values[1]),
            values,
        ),
    )
    return (preferred, *alternatives)


def _load_eligible_days(
    radar_entry: dict[str, Any],
    *,
    year: str,
    radar: str,
    fetch_json: Callable[[str], dict[str, Any]],
    public_base: str,
    coverage_cache: dict[str, dict[str, Any]],
    policy: BackgroundTrainingSelectionConfig,
    exclusions: BackgroundTrainingExclusions,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coverage_key = _coverage_key(radar_entry, year)
    if not coverage_key:
        errors.append({"radar": radar, "year": year, "error": "coverage_missing"})
        return []
    coverage_url = _public_url(public_base, coverage_key)
    try:
        if coverage_url not in coverage_cache:
            coverage_cache[coverage_url] = fetch_json(coverage_url)
        coverage = coverage_cache[coverage_url]
    except Exception as exc:  # noqa: BLE001 - manifest records catalog failures.
        errors.append(
            {
                "radar": radar,
                "year": year,
                "error": f"coverage_fetch_failed:{type(exc).__name__}:{exc}",
            }
        )
        return []
    days = list(coverage.get("days", []))
    maximum_counts = {
        pulse: max(
            (int(day.get("pulse_counts", {}).get(pulse) or 0) for day in days),
            default=0,
        )
        for pulse in policy.pulses
    }
    return sorted(
        (
            day
            for day in days
            if day.get("date")
            and day.get("catalog_key")
            and (radar, str(day["date"])) not in exclusions.radar_dates
            and _day_has_sufficient_coverage(
                day,
                pulses=policy.pulses,
                maximum_counts=maximum_counts,
                minimum_fraction=policy.minimum_day_coverage_fraction,
            )
        ),
        key=lambda value: str(value["date"]),
    )


def _select_spread(days: Iterable[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ordered = sorted(days, key=lambda value: str(value["date"]))
    if count <= 0 or not ordered:
        return []
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[len(ordered) // 2]]
    indices = {
        round(index * (len(ordered) - 1) / (count - 1))
        for index in range(count)
    }
    if len(indices) < count:
        for index in range(len(ordered)):
            indices.add(index)
            if len(indices) == count:
                break
    return [ordered[index] for index in sorted(indices)[:count]]


def _day_has_sufficient_coverage(
    day: dict[str, Any],
    *,
    pulses: tuple[str, ...],
    maximum_counts: dict[str, int],
    minimum_fraction: float,
) -> bool:
    pulse_counts = day.get("pulse_counts")
    if not isinstance(pulse_counts, dict):
        return True
    for pulse in pulses:
        maximum = int(maximum_counts.get(pulse) or 0)
        count = int(pulse_counts.get(pulse) or 0)
        if count <= 0 or (maximum > 0 and count < maximum * minimum_fraction):
            return False
    return True


def _nearest_file(
    files: Iterable[dict[str, Any]],
    *,
    pulse: str,
    target_time: str,
) -> dict[str, Any] | None:
    candidates = [
        entry
        for entry in files
        if str(entry.get("pulse") or "").lower() == pulse.lower()
        and _valid_time(str(entry.get("time") or ""))
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda entry: (
            _time_distance(str(entry.get("time") or ""), target_time),
            str(entry.get("time") or ""),
        ),
    )


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


def _season(date: str) -> str:
    month = int(str(date)[4:6])
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _time_distance(first: str, second: str) -> int:
    direct = abs(_minutes(first) - _minutes(second))
    return min(direct, 24 * 60 - direct)


def _minutes(value: str) -> int:
    text = str(value).zfill(4)
    if not _valid_time(text):
        raise ValueError(f"invalid HHMM time {value!r}")
    return int(text[:2]) * 60 + int(text[2:])


def _valid_time(value: str) -> bool:
    text = str(value).zfill(4)
    return (
        len(text) == 4
        and text.isdigit()
        and 0 <= int(text[:2]) <= 23
        and 0 <= int(text[2:]) <= 59
    )


def _date_span_days(dates: Iterable[str]) -> int:
    parsed = sorted(datetime.strptime(value, "%Y%m%d").date() for value in set(dates))
    return (parsed[-1] - parsed[0]).days if len(parsed) >= 2 else 0


def _source_id(radar: str, date: str, time: str, pulse: str, filename: str) -> str:
    digest = sha256(
        f"{radar}|{date}|{time}|{pulse}|{filename}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{radar}-{date}-{time}-{pulse}-{digest}"


def _source_error(
    radar: str,
    split: str,
    season: str,
    date: str,
    error: str,
) -> dict[str, Any]:
    return {
        "radar": radar,
        "split": split,
        "season": season,
        "date": date,
        "error": error,
    }


def _public_url(base: str, key: str) -> str:
    if key.startswith(("http://", "https://")):
        return key
    return f"{base.rstrip('/')}/{key.lstrip('/')}"


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
