from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import time
from typing import Any, Iterable, Optional
from uuid import uuid4

import ee

from app.database import NO_SEASON, get_connection
from app.services.analysis.crop_context import (
    build_season_id,
    calculate_days_after_planting,
    get_crop_timing_context,
    normalize_crop_key,
)
from app.services.satelite.gee import (
    ANALYSIS_SCALE,
    COVERAGE_FULL,
    COVERAGE_PARTIAL,
    CS_PLUS_THRESHOLD,
    MIN_FOOTPRINT_FRACTION,
    _coverage_stack,
    add_cloud_score_plus,
    build_acquisition_mosaics,
    build_analysis_geometry,
    classify_coverage_tier,
    initialize_gee,
    measure_sentinel2_observation,
)


SENTINEL_COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"

HISTORY_MIN_SPACING_DAYS = 7
HISTORY_MAX_OBSERVATIONS = 18
HISTORY_EXTRA_LOOKAHEAD_DAYS = 5
NO_SEASON_LOOKBACK_DAYS = 120

HISTORY_INDEX_METHOD = (
    "explicit_arithmetic_negatives_preserved"
)

# After a long gap, the first observation at or above this clarity is
# kept rather than extending the gap for a prettier image.
#
# Deliberately the SAME threshold as the full-coverage reporting tier,
# not a separate number. A distinct 0.75 created a 70-75% band where an
# observation counts as whole-field for a farmer's report but "not good
# enough" for the historical series — two parts of the system
# disagreeing about what a usable observation is.
HISTORY_GOOD_ENOUGH_CLEAR_FRACTION = COVERAGE_FULL


def _parse_date(
    value: Any,
    field_name: str,
) -> Optional[date]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = str(value).strip()

    if not text:
        return None

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).date()
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a valid ISO date or datetime."
        ) from exc


def resolve_history_window(
    planting_date: Any = None,
    start_date: Any = None,
    end_date_exclusive: Any = None,
) -> dict:
    today_utc = datetime.now(timezone.utc).date()

    explicit_start = _parse_date(
        start_date,
        "start_date",
    )

    planted = _parse_date(
        planting_date,
        "planting_date",
    )

    explicit_end = _parse_date(
        end_date_exclusive,
        "end_date_exclusive",
    )

    resolved_end = (
        explicit_end
        or today_utc + timedelta(days=1)
    )

    if explicit_start is not None:
        resolved_start = explicit_start
        basis = "explicit_start_date"

    elif planted is not None:
        resolved_start = planted
        basis = "planting_date"

    else:
        resolved_start = resolved_end - timedelta(
            days=NO_SEASON_LOOKBACK_DAYS
        )
        basis = "no_season_recent_window"

    # DELIBERATELY no cap on window length.
    # Truncating a long season would remove early-season history.
    # If long seasons become too slow, use chunked searches instead.

    if resolved_start >= resolved_end:
        raise ValueError(
            "Historical search start must be earlier than the "
            "exclusive end date."
        )

    return {
        "start_date": resolved_start.isoformat(),
        "end_date_exclusive": resolved_end.isoformat(),
        "window_basis": basis,
        "window_days": (
            resolved_end - resolved_start
        ).days,
    }


def _normalize_polygon_coordinates(
    coordinates: Any,
) -> list[list[float]]:
    if isinstance(coordinates, str):
        try:
            coordinates = json.loads(
                coordinates
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Farm polygon JSON could not be decoded."
            ) from exc

    if not isinstance(
        coordinates,
        (list, tuple),
    ):
        raise ValueError(
            "Farm polygon must be a list of "
            "[longitude, latitude] pairs."
        )

    if len(coordinates) < 3:
        raise ValueError(
            "Farm polygon must contain at least "
            "three coordinate pairs."
        )

    normalized: list[list[float]] = []

    for point in coordinates:
        if (
            not isinstance(
                point,
                (list, tuple),
            )
            or len(point) != 2
        ):
            raise ValueError(
                "Each farm polygon coordinate must be "
                "[longitude, latitude]."
            )

        try:
            lon = float(
                point[0]
            )
            lat = float(
                point[1]
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Farm polygon coordinates must be numeric."
            ) from exc

        if not (
            -180 <= lon <= 180
            and -90 <= lat <= 90
        ):
            raise ValueError(
                f"Farm polygon coordinate is out of range: {point}"
            )

        normalized.append(
            [
                round(lon, 8),
                round(lat, 8),
            ]
        )

    if normalized[0] != normalized[-1]:
        normalized.append(
            normalized[0].copy()
        )

    if len(normalized) < 4:
        raise ValueError(
            "Farm polygon must contain at least "
            "three distinct vertices."
        )

    return normalized


def build_polygon_hash(
    coordinates: Any,
) -> str:
    normalized = _normalize_polygon_coordinates(
        coordinates
    )

    payload = json.dumps(
        {
            "version": 1,
            "coordinates": normalized,
        },
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def _build_display_polygon(
    coordinates: Any,
) -> ee.Geometry:
    normalized = _normalize_polygon_coordinates(
        coordinates
    )

    return ee.Geometry.Polygon(
        [normalized]
    )


def _score_archive_collection(
    polygon: ee.Geometry,
    start_date: str,
    end_date_exclusive: str,
    minimum_clear_fraction: float,
):
    # DELIBERATELY no CLOUDY_PIXEL_PERCENTAGE pre-filter.
    #
    # That value describes the whole Sentinel tile, not the farm.
    # Filtering individual tiles before same-datatake mosaicking could
    # also break multi-tile farm coverage.
    # Farm-specific Cloud Score+ remains the authoritative test.

    raw = (
        ee.ImageCollection(
            SENTINEL_COLLECTION_ID
        )
        .filterBounds(
            polygon
        )
        .filterDate(
            start_date,
            end_date_exclusive,
        )
    )

    linked = add_cloud_score_plus(
        raw
    )

    mosaics = build_acquisition_mosaics(
        linked
    )

    def add_quality(image):
        stats = _coverage_stack(
            image
        ).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=polygon,
            scale=ANALYSIS_SCALE,
            maxPixels=1_000_000,
            bestEffort=True,
        )

        total = ee.Number(
            stats.get(
                "total_pixels"
            )
        ).max(1)

        return image.set(
            {
                "farm_clear_fraction": (
                    ee.Number(
                        stats.get(
                            "valid_pixels"
                        )
                    ).divide(
                        total
                    )
                ),

                "farm_footprint_fraction": (
                    ee.Number(
                        stats.get(
                            "observed_pixels"
                        )
                    ).divide(
                        total
                    )
                ),
            }
        )

    scored = mosaics.map(
        add_quality
    )

    footprint_qualified = scored.filter(
        ee.Filter.gte(
            "farm_footprint_fraction",
            MIN_FOOTPRINT_FRACTION,
        )
    )

    usable = footprint_qualified.filter(
        ee.Filter.gte(
            "farm_clear_fraction",
            minimum_clear_fraction,
        )
    )

    # Leave these unevaluated.
    # They are downloaded together with the candidate metadata below,
    # so Earth Engine evaluates the heavy archive pipeline only once.
    counts = {
        "raw_granule_count": raw.size(),
        "datatake_count": mosaics.size(),
        "footprint_qualified_count": (
            footprint_qualified.size()
        ),
        "usable_candidate_count": usable.size(),
    }

    return usable, counts


def _as_asset_paths(
    source_ids: Any,
) -> list[str]:
    if not source_ids:
        return []

    paths: list[str] = []

    for source_id in source_ids:
        text = str(
            source_id
        )

        if text.startswith(
            f"{SENTINEL_COLLECTION_ID}/"
        ):
            paths.append(
                text
            )

        else:
            paths.append(
                f"{SENTINEL_COLLECTION_ID}/{text}"
            )

    return paths


def _extract_candidate_metadata(
    collection: ee.ImageCollection,
    counts: Optional[dict] = None,
) -> tuple[list[dict], dict]:
    ordered = collection.sort(
        "system:time_start",
        True,
    )

    payload = {
        "datatake_ids": ordered.aggregate_array(
            "datatake_id"
        ),

        "dates": ordered.aggregate_array(
            "observation_date"
        ),

        "datetimes": ordered.aggregate_array(
            "observation_datetime_utc"
        ),

        "times": ordered.aggregate_array(
            "system:time_start"
        ),

        "clear_fractions": ordered.aggregate_array(
            "farm_clear_fraction"
        ),

        "footprint_fractions": ordered.aggregate_array(
            "farm_footprint_fraction"
        ),

        "source_image_ids": ordered.aggregate_array(
            "source_image_ids"
        ),

        "source_tile_counts": ordered.aggregate_array(
            "source_tile_count"
        ),
    }

    for key, value in (
        counts or {}
    ).items():
        payload[
            f"count__{key}"
        ] = value

    bundle = ee.Dictionary(
        payload
    ).getInfo() or {}

    resolved_counts = {
        key[len("count__"):]: bundle.get(
            key
        )
        for key in bundle
        if key.startswith(
            "count__"
        )
    }

    datatake_ids = (
        bundle.get(
            "datatake_ids"
        )
        or []
    )

    dates = (
        bundle.get(
            "dates"
        )
        or []
    )

    datetimes = (
        bundle.get(
            "datetimes"
        )
        or []
    )

    times = (
        bundle.get(
            "times"
        )
        or []
    )

    clear_fractions = (
        bundle.get(
            "clear_fractions"
        )
        or []
    )

    footprint_fractions = (
        bundle.get(
            "footprint_fractions"
        )
        or []
    )

    source_image_ids = (
        bundle.get(
            "source_image_ids"
        )
        or []
    )

    source_tile_counts = (
        bundle.get(
            "source_tile_counts"
        )
        or []
    )

    candidates: list[dict] = []

    for i, datatake_id in enumerate(
        datatake_ids
    ):
        clear_fraction = (
            float(
                clear_fractions[i]
            )
            if (
                i < len(
                    clear_fractions
                )
                and clear_fractions[i] is not None
            )
            else None
        )

        footprint_fraction = (
            float(
                footprint_fractions[i]
            )
            if (
                i < len(
                    footprint_fractions
                )
                and footprint_fractions[i] is not None
            )
            else None
        )

        source_ids = (
            source_image_ids[i]
            if i < len(
                source_image_ids
            )
            else []
        )

        tile_count = (
            source_tile_counts[i]
            if i < len(
                source_tile_counts
            )
            else None
        )

        candidate = {
            "datatake_id": (
                datatake_id
            ),

            "observation_date": (
                dates[i]
                if i < len(
                    dates
                )
                else None
            ),

            "observation_datetime_utc": (
                datetimes[i]
                if i < len(
                    datetimes
                )
                else None
            ),

            "system_time_start": (
                times[i]
                if i < len(
                    times
                )
                else None
            ),

            "field_clear_fraction": (
                round(
                    clear_fraction,
                    4,
                )
                if clear_fraction is not None
                else None
            ),

            "field_footprint_fraction": (
                round(
                    footprint_fraction,
                    4,
                )
                if footprint_fraction is not None
                else None
            ),

            "coverage_tier": (
                classify_coverage_tier(
                    clear_fraction
                )
            ),

            "source_image_ids": (
                _as_asset_paths(
                    source_ids
                )
            ),

            "source_tile_count": (
                int(
                    tile_count
                )
                if tile_count is not None
                else None
            ),
        }

        candidates.append(
            candidate
        )

    return candidates, resolved_counts


def _candidate_date(
    candidate: dict,
) -> date:
    parsed = _parse_date(
        candidate.get(
            "observation_date"
        ),
        "candidate observation_date",
    )

    if parsed is None:
        raise ValueError(
            "Historical candidate is missing observation_date."
        )

    return parsed


def _normalize_existing_dates(
    values: Optional[
        Iterable[Any]
    ],
) -> list[date]:
    if not values:
        return []

    result: list[date] = []

    for value in values:
        parsed = _parse_date(
            value,
            "existing observation date",
        )

        if parsed is not None:
            result.append(
                parsed
            )

    return result


def select_spaced_observations(
    candidates: list[dict],
    *,
    minimum_spacing_days: int = HISTORY_MIN_SPACING_DAYS,
    max_observations: int = HISTORY_MAX_OBSERVATIONS,
    existing_observation_dates: Optional[
        Iterable[Any]
    ] = None,
) -> list[dict]:
    """
    Select usable observations with good coverage through time.

    Walks the season in date order. At each step:

      - Normal spacing: inspect a short lookahead window. If one or
        more candidates reach the full-coverage tier, ignore partial
        candidates in that window. Among the remaining candidates,
        prefer the date closest to the desired temporal spacing; use
        clarity as the tiebreaker.

        This prevents a 52% partial observation from beating a 100%
        observation nearby just because it lands neatly on the target
        date, while still preserving the verified Nebraska timing.

      - Long gap: if the first observation after a long gap reaches the
        full-coverage tier, keep it rather than extending the gap for a
        prettier image. Otherwise choose from the nearby window.

    The first observation of a new series also uses a nearby-quality
    check so a weak partial observation is not locked in when a full
    observation appears only a few days later.

    There is deliberately no existing-observation count parameter,
    because a count alone cannot enforce date spacing.

    INCREMENTAL BACKFILL NOTE: with existing dates, the walk only moves
    FORWARD from the latest stored date. It appends; it does not fill
    gaps earlier in the series. The persistence layer must rebuild an
    incomplete initial backfill rather than appending to a partial
    historical series.
    """
    if minimum_spacing_days < 1:
        raise ValueError(
            "minimum_spacing_days must be at least 1."
        )

    if max_observations < 1:
        raise ValueError(
            "max_observations must be at least 1."
        )

    existing_dates = _normalize_existing_dates(
        existing_observation_dates
    )

    remaining_slots = max(
        0,
        max_observations - len(
            existing_dates
        ),
    )

    if remaining_slots == 0 or not candidates:
        return []

    def clear_fraction(
        candidate: dict,
    ) -> float:
        value = candidate.get(
            "field_clear_fraction"
        )

        if value is None:
            return 0.0

        return float(
            value
        )

    def spaced_from_all(
        candidate_date: date,
        occupied: list[date],
    ) -> bool:
        return all(
            abs(
                (
                    candidate_date
                    - occupied_date
                ).days
            )
            >= minimum_spacing_days
            for occupied_date in occupied
        )

    def nearby_bucket(
        eligible: list[dict],
    ) -> list[dict]:
        window_end = (
            _candidate_date(
                eligible[0]
            )
            + timedelta(
                days=HISTORY_EXTRA_LOOKAHEAD_DAYS
            )
        )

        return [
            candidate
            for candidate in eligible
            if _candidate_date(
                candidate
            )
            <= window_end
        ]

    def choose_first(
        eligible: list[dict],
    ) -> dict:
        bucket = nearby_bucket(
            eligible
        )

        full_candidates = [
            candidate
            for candidate in bucket
            if clear_fraction(
                candidate
            )
            >= COVERAGE_FULL
        ]

        pool = (
            full_candidates
            if full_candidates
            else bucket
        )

        return sorted(
            pool,
            key=lambda candidate: (
                -clear_fraction(
                    candidate
                ),
                _candidate_date(
                    candidate
                ),
            ),
        )[0]

    def choose_normal(
        eligible: list[dict],
        latest_date: date,
    ) -> dict:
        bucket = nearby_bucket(
            eligible
        )

        full_candidates = [
            candidate
            for candidate in bucket
            if clear_fraction(
                candidate
            )
            >= COVERAGE_FULL
        ]

        pool = (
            full_candidates
            if full_candidates
            else bucket
        )

        target_date = (
            latest_date
            + timedelta(
                days=minimum_spacing_days + 3
            )
        )

        return sorted(
            pool,
            key=lambda candidate: (
                abs(
                    (
                        _candidate_date(
                            candidate
                        )
                        - target_date
                    ).days
                ),
                -clear_fraction(
                    candidate
                ),
                _candidate_date(
                    candidate
                ),
            ),
        )[0]

    remaining = sorted(
        candidates,
        key=lambda candidate: (
            _candidate_date(
                candidate
            ),
            candidate.get(
                "system_time_start"
            )
            or 0,
        ),
    )

    # Two minimum intervals with no observation counts as a genuine
    # long gap.
    long_gap_days = (
        minimum_spacing_days * 2
    )

    selected: list[dict] = []

    occupied_dates = list(
        existing_dates
    )

    while (
        remaining
        and len(
            selected
        ) < remaining_slots
    ):
        if occupied_dates:
            latest_date = max(
                occupied_dates
            )

            eligible = [
                candidate
                for candidate in remaining
                if (
                    _candidate_date(
                        candidate
                    )
                    > latest_date
                    and spaced_from_all(
                        _candidate_date(
                            candidate
                        ),
                        occupied_dates,
                    )
                )
            ]
        else:
            latest_date = None
            eligible = list(
                remaining
            )

        if not eligible:
            break

        earliest = eligible[0]

        if latest_date is None:
            chosen = choose_first(
                eligible
            )

        elif (
            (
                _candidate_date(
                    earliest
                )
                - latest_date
            ).days
            >= long_gap_days
            and clear_fraction(
                earliest
            )
            >= HISTORY_GOOD_ENOUGH_CLEAR_FRACTION
        ):
            # A genuine long gap already exists, and the first usable
            # observation reaches the full-coverage tier. Keep it rather
            # than extending the gap for a clearer image a few days later.
            chosen = earliest

        else:
            chosen = choose_normal(
                eligible,
                latest_date,
            )

        selected.append(
            dict(
                chosen
            )
        )

        occupied_dates.append(
            _candidate_date(
                chosen
            )
        )

        remaining = [
            candidate
            for candidate in remaining
            if candidate.get(
                "datatake_id"
            )
            != chosen.get(
                "datatake_id"
            )
        ]

    selected.sort(
        key=lambda candidate: (
            _candidate_date(
                candidate
            ),
            candidate.get(
                "system_time_start"
            )
            or 0,
        )
    )

    return selected

def discover_historical_observations(
    coordinates: Any,
    *,
    crop_type: Any = None,
    season_id: Optional[str] = None,
    planting_date: Any = None,
    start_date: Any = None,
    end_date_exclusive: Any = None,
    minimum_clear_fraction: float = COVERAGE_PARTIAL,
    minimum_spacing_days: int = HISTORY_MIN_SPACING_DAYS,
    max_observations: int = HISTORY_MAX_OBSERVATIONS,
    existing_observation_dates: Optional[
        Iterable[Any]
    ] = None,
) -> dict:
    started_at = time.perf_counter()

    try:
        minimum_clear_fraction = float(
            minimum_clear_fraction
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "minimum_clear_fraction must be numeric."
        ) from exc

    if not (
        COVERAGE_PARTIAL
        <= minimum_clear_fraction
        <= 1.0
    ):
        raise ValueError(
            "Historical minimum_clear_fraction cannot be below "
            "Farm Watch's partial-coverage floor "
            f"({COVERAGE_PARTIAL:.0%}) or above 100%."
        )

    parsed_planting_date = _parse_date(
        planting_date,
        "planting_date",
    )

    resolved_season_id = (
        build_season_id(
            supplied_season_id=season_id,
            crop_key=normalize_crop_key(
                crop_type
            ),
            planting_date=parsed_planting_date,
        )
        or NO_SEASON
    )

    window = resolve_history_window(
        planting_date=parsed_planting_date,
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )

    normalized_coordinates = (
        _normalize_polygon_coordinates(
            coordinates
        )
    )

    polygon_hash = build_polygon_hash(
        normalized_coordinates
    )

    # Earth Engine must be initialized before creating ee.Geometry.
    initialize_gee()

    display_polygon = _build_display_polygon(
        normalized_coordinates
    )

    (
        usable_collection,
        pending_counts,
    ) = _score_archive_collection(
        polygon=display_polygon,
        start_date=window[
            "start_date"
        ],
        end_date_exclusive=window[
            "end_date_exclusive"
        ],
        minimum_clear_fraction=minimum_clear_fraction,
    )

    (
        usable_candidates,
        counts,
    ) = _extract_candidate_metadata(
        usable_collection,
        pending_counts,
    )

    selected = select_spaced_observations(
        usable_candidates,
        minimum_spacing_days=minimum_spacing_days,
        max_observations=max_observations,
        existing_observation_dates=existing_observation_dates,
    )

    elapsed_seconds = round(
        time.perf_counter()
        - started_at,
        3,
    )

    return {
        "season_id": (
            resolved_season_id
        ),

        "polygon_hash": (
            polygon_hash
        ),

        "search_start": (
            window[
                "start_date"
            ]
        ),

        "search_end_exclusive": (
            window[
                "end_date_exclusive"
            ]
        ),

        "window_basis": (
            window[
                "window_basis"
            ]
        ),

        "window_days": (
            window[
                "window_days"
            ]
        ),

        "minimum_clear_fraction": (
            minimum_clear_fraction
        ),

        "minimum_footprint_fraction": (
            MIN_FOOTPRINT_FRACTION
        ),

        "minimum_spacing_days": (
            minimum_spacing_days
        ),

        "max_observations": (
            max_observations
        ),

        "good_enough_clear_fraction": (
            HISTORY_GOOD_ENOUGH_CLEAR_FRACTION
        ),

        "extra_lookahead_days": (
            HISTORY_EXTRA_LOOKAHEAD_DAYS
        ),

        "raw_granule_count": int(
            counts.get(
                "raw_granule_count"
            )
            or 0
        ),

        "datatake_count": int(
            counts.get(
                "datatake_count"
            )
            or 0
        ),

        "footprint_qualified_count": int(
            counts.get(
                "footprint_qualified_count"
            )
            or 0
        ),

        "usable_candidate_count": int(
            counts.get(
                "usable_candidate_count"
            )
            or 0
        ),

        "selected_observation_count": (
            len(
                selected
            )
        ),

        "discovery_elapsed_seconds": (
            elapsed_seconds
        ),

        "usable_candidates": (
            usable_candidates
        ),

        "selected_observations": (
            selected
        ),

        "selection_method": (
            "chronological_walk_with_minimum_spacing_"
            "full_tier_preference_target_spacing_"
            "and_full_tier_long_gap_rule"
        ),

        # Known limitation: choosing clearer observations means cloudy
        # periods may be under-represented, especially when interpreting NDMI.
        "sampling_bias_note": (
            "The historical series favors observations with clearer "
            "satellite visibility. Cloudy periods, including some "
            "periods around rainfall, may be under-represented. "
            "Historical NDMI should therefore be interpreted as a "
            "clear-weather sampled moisture-related signal, not a "
            "continuous soil-moisture record."
        ),
    }

# ------------------------------------------------------------------
# Historical observation measurement
# ------------------------------------------------------------------

def _build_archive_mosaics_for_measurement(
    polygon: ee.Geometry,
    start_date: str,
    end_date_exclusive: str,
) -> ee.ImageCollection:
    """
    Build same-acquisition Sentinel-2 mosaics for historical measurement.

    Granule-wide CLOUDY_PIXEL_PERCENTAGE is intentionally not used as a
    pre-filter. Cloud Score+ is evaluated over the farm itself so cloud
    quality is based on the area being analysed.

    Adjacent Sentinel granules may be combined only when they belong to
    the same datatake.
    """
    raw = (
        ee.ImageCollection(
            SENTINEL_COLLECTION_ID
        )
        .filterBounds(
            polygon
        )
        .filterDate(
            start_date,
            end_date_exclusive,
        )
    )

    linked = add_cloud_score_plus(
        raw
    )

    return build_acquisition_mosaics(
        linked
    )


def _historical_timing_context(
    crop_type: Any,
    planting_date: Any,
    observation_date: Any,
) -> dict:
    """
    Calculate crop timing for a historical Sentinel observation.

    Days after planting are calculated against the satellite observation
    date rather than the current date.
    """
    crop_key = normalize_crop_key(
        crop_type
    )

    days_after_planting = (
        calculate_days_after_planting(
            planting_date,
            observation_date,
        )
    )

    timing = get_crop_timing_context(
        crop_key=crop_key,
        days_after_planting=days_after_planting,
    )

    timing_phase = (
        timing.get(
            "timing_phase"
        )
        if timing is not None
        else None
    )

    return {
        "days_after_planting": (
            days_after_planting
        ),
        "timing_phase": (
            timing_phase
        ),
    }


def _historical_measurement_quality_issue(
    measurement: dict,
) -> Optional[str]:
    """
    Validate whether a historical measurement is suitable for the
    historical series.

    Historical observations must include full-field geometry, sufficient
    Sentinel footprint coverage, usable cloud coverage, and all five
    required index measurements.
    """
    if not measurement.get(
        "field_geometry_supplied"
    ):
        return "full_field_geometry_not_supplied"

    if not measurement.get(
        "datatake_id"
    ):
        return "missing_datatake_id"

    if not measurement.get(
        "date"
    ):
        return "missing_observation_date"

    for field_name in (
        "field_coverage_tier",
        "analysis_coverage_tier",
        "coverage_tier",
    ):
        tier = measurement.get(
            field_name
        )

        if tier not in (
            "full",
            "partial",
        ):
            return (
                f"{field_name}_"
                f"{tier or 'missing'}"
            )

    field_footprint_fraction = (
        measurement.get(
            "field_footprint_fraction"
        )
    )

    if (
        field_footprint_fraction is None
        or float(
            field_footprint_fraction
        )
        < MIN_FOOTPRINT_FRACTION
    ):
        return "insufficient_field_footprint"

    missing_indices = [
        index_name
        for index_name in (
            "ndvi",
            "ndmi",
            "ndre",
            "savi",
            "gndvi",
        )
        if measurement.get(
            index_name
        )
        is None
    ]

    if missing_indices:
        return (
            "missing_indices:"
            + ",".join(
                missing_indices
            )
        )

    return None


def measure_selected_historical_observations(
    coordinates: Any,
    selected_observations: Iterable[dict],
    *,
    start_date: Any,
    end_date_exclusive: Any,
    crop_type: Any = None,
    planting_date: Any = None,
    season_id: Optional[str] = None,
    include_zones: bool = True,
) -> dict:
    """
    Measure selected historical Sentinel-2 observations for one farm.

    Each selected datatake is rebuilt from the Sentinel archive and
    measured with the same single-observation measurement logic used by
    the live Farm Watch analysis.

    The returned records include vegetation indices, coverage metadata,
    spatial measurements, crop timing context, and measurement
    provenance.

    This function performs measurement only and does not write records
    to SQLite.
    """
    started_at = time.perf_counter()

    selected = [
        dict(
            observation
        )
        for observation in selected_observations
    ]

    if not selected:
        return {
            "requested_observation_count": 0,
            "accepted_measurement_count": 0,
            "rejected_observation_count": 0,
            "measurement_elapsed_seconds": 0.0,
            "measurements": [],
            "rejected_observations": [],
        }

    parsed_start = _parse_date(
        start_date,
        "start_date",
    )

    parsed_end = _parse_date(
        end_date_exclusive,
        "end_date_exclusive",
    )

    if parsed_start is None:
        raise ValueError(
            "start_date is required for historical measurement."
        )

    if parsed_end is None:
        raise ValueError(
            "end_date_exclusive is required for historical measurement."
        )

    if parsed_start >= parsed_end:
        raise ValueError(
            "Historical measurement start must be earlier than "
            "end_date_exclusive."
        )

    parsed_planting_date = _parse_date(
        planting_date,
        "planting_date",
    )

    resolved_season_id = (
        build_season_id(
            supplied_season_id=season_id,
            crop_key=normalize_crop_key(
                crop_type
            ),
            planting_date=parsed_planting_date,
        )
        or NO_SEASON
    )

    normalized_coordinates = (
        _normalize_polygon_coordinates(
            coordinates
        )
    )

    polygon_hash = build_polygon_hash(
        normalized_coordinates
    )

    initialize_gee()

    display_polygon = _build_display_polygon(
        normalized_coordinates
    )

    (
        analysis_polygon,
        analysis_geometry_info,
    ) = build_analysis_geometry(
        display_polygon
    )


    measurements: list[dict] = []
    rejected: list[dict] = []

    for candidate in selected:
        datatake_id = candidate.get(
            "datatake_id"
        )

        expected_date = candidate.get(
            "observation_date"
        )

        if not datatake_id:
            rejected.append(
                {
                    "observation_date": (
                        expected_date
                    ),
                    "datatake_id": None,
                    "reason": (
                        "candidate_missing_datatake_id"
                    ),
                }
            )
            continue

        datatake_id = str(
            datatake_id
        )
        observation_day = _parse_date(
            expected_date,
            "observation_date",
        )

        if observation_day is None:
            rejected.append(
                {
                    "observation_date": None,
                    "datatake_id": datatake_id,
                    "reason": "candidate_missing_observation_date",
                }
            )
            continue

        day_mosaics = _build_archive_mosaics_for_measurement(
            polygon=display_polygon,
            start_date=observation_day.isoformat(),
            end_date_exclusive=(
                observation_day + timedelta(days=1)
            ).isoformat(),
        )

        image = ee.Image(
            day_mosaics.filter(
                ee.Filter.eq(
                    "datatake_id",
                    datatake_id,
                )
            ).first()
        )

        try:
            measurement = measure_sentinel2_observation(
                image=image,
                analysis_polygon=analysis_polygon,
                display_polygon=display_polygon,
                include_zones=include_zones,
            )

        except Exception as exc:
            rejected.append(
                {
                    "observation_date": expected_date,
                    "datatake_id": datatake_id,
                    "reason": "measurement_error",
                    "detail": str(exc),
                }
            )
            continue

        measured_date = measurement.get(
            "date"
        )

        if (
            expected_date
            and measured_date
            and expected_date
            != measured_date
        ):
            rejected.append(
                {
                    "observation_date": (
                        expected_date
                    ),
                    "datatake_id": (
                        datatake_id
                    ),
                    "reason": (
                        "observation_date_mismatch"
                    ),
                    "measured_date": (
                        measured_date
                    ),
                }
            )
            continue

        measured_datatake = measurement.get(
            "datatake_id"
        )

        if (
            measured_datatake
            and str(
                measured_datatake
            )
            != datatake_id
        ):
            rejected.append(
                {
                    "observation_date": (
                        expected_date
                    ),
                    "datatake_id": (
                        datatake_id
                    ),
                    "reason": (
                        "datatake_id_mismatch"
                    ),
                    "measured_datatake_id": (
                        measured_datatake
                    ),
                }
            )
            continue

        quality_issue = (
            _historical_measurement_quality_issue(
                measurement
            )
        )

        if quality_issue is not None:
            rejected.append(
                {
                    "observation_date": (
                        measured_date
                        or expected_date
                    ),
                    "datatake_id": (
                        datatake_id
                    ),
                    "reason": (
                        quality_issue
                    ),
                }
            )
            continue

        timing = _historical_timing_context(
            crop_type=crop_type,
            planting_date=parsed_planting_date,
            observation_date=measured_date,
        )

        spatial_coverage = (
            measurement.get(
                "spatial_coverage"
            )
            or {}
        )

        record = {
            "season_id": (
                resolved_season_id
            ),

            "polygon_hash": (
                polygon_hash
            ),

            "datatake_id": (
                datatake_id
            ),

            "observation_date": (
                measured_date
            ),

            "observation_datetime_utc": (
                measurement.get(
                    "observation_datetime_utc"
                )
            ),

            "source_image_ids": (
                measurement.get(
                    "source_image_ids"
                )
                or []
            ),

            "source_tile_count": (
                measurement.get(
                    "source_tile_count"
                )
            ),

            "ndvi": measurement.get(
                "ndvi"
            ),

            "ndmi": measurement.get(
                "ndmi"
            ),

            "ndre": measurement.get(
                "ndre"
            ),

            "savi": measurement.get(
                "savi"
            ),

            "gndvi": measurement.get(
                "gndvi"
            ),

            "field_clear_fraction": (
                measurement.get(
                    "field_clear_fraction"
                )
            ),

            "field_footprint_fraction": (
                measurement.get(
                    "field_footprint_fraction"
                )
            ),

            "field_coverage_tier": (
                measurement.get(
                    "field_coverage_tier"
                )
            ),

            "analysis_clear_fraction": (
                measurement.get(
                    "analysis_clear_fraction"
                )
            ),

            "analysis_footprint_fraction": (
                measurement.get(
                    "analysis_footprint_fraction"
                )
            ),

            "analysis_coverage_tier": (
                measurement.get(
                    "analysis_coverage_tier"
                )
            ),

            "coverage_tier": (
                measurement.get(
                    "coverage_tier"
                )
            ),

            "assessment_scope": (
                measurement.get(
                    "assessment_scope"
                )
            ),

            "field_geometry_supplied": (
                bool(
                    measurement.get(
                        "field_geometry_supplied"
                    )
                )
            ),

            "valid_pixel_fraction": (
                measurement.get(
                    "valid_pixel_fraction"
                )
            ),

            "valid_pixel_count": (
                measurement.get(
                    "valid_pixel_count"
                )
            ),

            "zone_analysis_supported": (
                measurement.get(
                    "zone_analysis_supported"
                )
            ),

            "eligible_zone_count": (
                measurement.get(
                    "eligible_zone_count"
                )
            ),

            "spatially_representative": (
                spatial_coverage.get(
                    "spatially_representative"
                )
            ),

            "distribution_score": (
                spatial_coverage.get(
                    "distribution_score"
                )
            ),

            "zone_values": (
                measurement.get(
                    "zone_values"
                )
            ),

            "zone_pixel_counts": (
                measurement.get(
                    "zone_pixel_counts"
                )
            ),

            "spatial_coverage": (
                measurement.get(
                    "spatial_coverage"
                )
            ),

            "variation_spread": (
                measurement.get(
                    "variation_spread"
                )
            ),

            "attention_area": (
                measurement.get(
                    "attention_area"
                )
            ),

            "attention_source": (
                measurement.get(
                    "attention_source"
                )
            ),

            "attention_is_distinct": (
                measurement.get(
                    "attention_is_distinct"
                )
            ),

            "days_after_planting": (
                timing[
                    "days_after_planting"
                ]
            ),

            "timing_phase": (
                timing[
                    "timing_phase"
                ]
            ),

            "analysis_scale_m": (
                ANALYSIS_SCALE
            ),

            "edge_buffer_m": (
                analysis_geometry_info.get(
                    "edge_buffer_m"
                )
            ),

            "edge_excluded": (
                analysis_geometry_info.get(
                    "edge_excluded"
                )
            ),

            "cloud_mask_threshold": (
                CS_PLUS_THRESHOLD
            ),

            "index_method": (
                HISTORY_INDEX_METHOD
            ),
        }

        measurements.append(
            record
        )

    elapsed_seconds = round(
        time.perf_counter()
        - started_at,
        3,
    )

    return {
        "season_id": (
            resolved_season_id
        ),

        "polygon_hash": (
            polygon_hash
        ),

        "search_start": (
            parsed_start.isoformat()
        ),

        "search_end_exclusive": (
            parsed_end.isoformat()
        ),

        "requested_observation_count": (
            len(
                selected
            )
        ),

        "accepted_measurement_count": (
            len(
                measurements
            )
        ),

        "rejected_observation_count": (
            len(
                rejected
            )
        ),

        "measurement_elapsed_seconds": (
            elapsed_seconds
        ),

        "analysis_geometry": (
            analysis_geometry_info
        ),

        "index_method": (
            HISTORY_INDEX_METHOD
        ),

        "measurements": (
            measurements
        ),

        "rejected_observations": (
            rejected
        ),
    }


# ------------------------------------------------------------------
# Historical observation persistence
# ------------------------------------------------------------------

_HISTORY_INSERT_COLUMNS = (
    "id",
    "user_id",
    "farm_id",
    "season_id",
    "polygon_hash",
    "datatake_id",
    "observation_date",
    "observation_datetime_utc",
    "source_image_ids",
    "source_tile_count",
    "ndvi",
    "ndmi",
    "ndre",
    "savi",
    "gndvi",
    "field_clear_fraction",
    "field_footprint_fraction",
    "field_coverage_tier",
    "analysis_clear_fraction",
    "analysis_footprint_fraction",
    "analysis_coverage_tier",
    "coverage_tier",
    "assessment_scope",
    "field_geometry_supplied",
    "valid_pixel_fraction",
    "valid_pixel_count",
    "zone_analysis_supported",
    "eligible_zone_count",
    "spatially_representative",
    "distribution_score",
    "zone_values",
    "zone_pixel_counts",
    "spatial_coverage",
    "variation_spread",
    "attention_area",
    "attention_source",
    "attention_is_distinct",
    "days_after_planting",
    "timing_phase",
    "analysis_scale_m",
    "edge_buffer_m",
    "edge_excluded",
    "cloud_mask_threshold",
    "index_method",
    "created_at",
)

# Lists and dictionaries stored as JSON text.
_HISTORY_JSON_COLUMNS = frozenset(
    {
        "source_image_ids",
        "zone_values",
        "zone_pixel_counts",
        "spatial_coverage",
        "variation_spread",
    }
)

# Three-state booleans stored as INTEGER: NULL (unknown), 0, or 1.
_HISTORY_BOOLEAN_COLUMNS = frozenset(
    {
        "field_geometry_supplied",
        "zone_analysis_supported",
        "spatially_representative",
        "attention_is_distinct",
        "edge_excluded",
    }
)

# Provenance columns that must agree across every row of one series.
# Rows measured with different settings are not one comparable series.
_HISTORY_METHOD_COLUMNS = (
    "analysis_scale_m",
    "edge_buffer_m",
    "edge_excluded",
    "cloud_mask_threshold",
    "index_method",
)

# Rejections that may succeed on a later attempt (for example an Earth
# Engine timeout). A batch containing one is not saved: the selector
# only walks forward from the latest stored date, so a date skipped now
# could never be filled in later.
_HISTORY_RETRYABLE_REJECTIONS = frozenset(
    {
        "measurement_error",
    }
)

_HISTORY_STATE_COLUMNS = (
    "datatake_id",
    "observation_date",
    "polygon_hash",
) + _HISTORY_METHOD_COLUMNS


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


def _bool_to_db(
    value: Any,
    column: str,
) -> Optional[int]:
    if value is None:
        return None

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int) and value in (0, 1):
        return value

    if isinstance(value, str):
        lowered = value.strip().lower()

        if lowered in ("true", "1"):
            return 1

        if lowered in ("false", "0"):
            return 0

    raise ValueError(
        f"{column} must be true, false, or empty; got {value!r}."
    )


def _db_to_bool(
    value: Any,
) -> Optional[bool]:
    if value is None:
        return None

    return bool(value)


def _json_to_db(
    value: Any,
    column: str,
) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, str):
        # Already JSON text: confirm it parses before storing it.
        try:
            json.loads(value)
        except ValueError as exc:
            raise ValueError(
                f"{column} is text but not valid JSON."
            ) from exc

        return value

    try:
        return json.dumps(
            value,
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{column} cannot be stored as JSON: {exc}"
        ) from exc


def _db_to_json(
    value: Any,
) -> Any:
    if value is None:
        return None

    return json.loads(value)


def _current_method_expectations(
    analysis_geometry: Optional[dict] = None,
) -> dict:
    """
    Measurement settings the current code would use for this farm.

    Scale, Cloud Score+ threshold, and index method are constants.
    Edge-buffer behavior depends on the farm geometry, so it comes from
    build_analysis_geometry() for the current boundary.
    """
    expected = {
        "analysis_scale_m": ANALYSIS_SCALE,
        "cloud_mask_threshold": CS_PLUS_THRESHOLD,
        "index_method": HISTORY_INDEX_METHOD,
    }

    if analysis_geometry is not None:
        expected["edge_buffer_m"] = analysis_geometry.get(
            "edge_buffer_m"
        )
        expected["edge_excluded"] = analysis_geometry.get(
            "edge_excluded"
        )

    return expected


def _method_values_match(
    column: str,
    stored: Any,
    current: Any,
) -> bool:
    if column == "index_method":
        return stored == current

    if column == "edge_excluded":
        current_bool = (
            None
            if current is None
            else bool(current)
        )
        return _db_to_bool(stored) == current_bool

    if stored is None or current is None:
        return stored is None and current is None

    try:
        return abs(float(stored) - float(current)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _history_method_mismatches(
    stored_rows: list[dict],
    expected: dict,
) -> list[str]:
    mismatched: list[str] = []

    for column, current in expected.items():
        for row in stored_rows:
            if not _method_values_match(
                column,
                row.get(column),
                current,
            ):
                mismatched.append(column)
                break

    return mismatched


def _resolve_history_user_id(
    conn,
    farm_id: str,
    user_id: Optional[str],
) -> Optional[str]:
    """
    Confirm the farm exists and belongs to the requesting user.

    Rows inherit the farm owner's user_id so the history table never
    disagrees with the farms table about ownership.
    """
    row = conn.execute(
        "SELECT user_id FROM farms WHERE id = ?",
        (farm_id,),
    ).fetchone()

    if row is None:
        raise LookupError(
            f"Farm {farm_id} does not exist."
        )

    owner = row["user_id"]

    if (
        user_id is not None
        and owner is not None
        and str(user_id) != str(owner)
    ):
        raise PermissionError(
            "This farm does not belong to the requesting user."
        )

    return owner if owner is not None else user_id


def _load_history_state(
    conn,
    farm_id: str,
    season_id: str,
) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT {", ".join(_HISTORY_STATE_COLUMNS)}
        FROM sentinel_history_observations
        WHERE farm_id = ? AND season_id = ?
        ORDER BY observation_date, datatake_id
        """,
        (farm_id, season_id),
    ).fetchall()

    return [dict(row) for row in rows]


def _validate_history_record(
    record: dict,
    *,
    season_id: str,
    polygon_hash: str,
) -> None:
    """
    Re-check a measurement record immediately before it is stored.

    Uses the same quality rules as measurement, so the database can
    never hold a row that measurement itself would have rejected.
    """
    label = (
        f"{record.get('observation_date')} / "
        f"{record.get('datatake_id')}"
    )

    if record.get("season_id") != season_id:
        raise ValueError(
            f"{label}: season_id {record.get('season_id')!r} does not "
            f"match the series season {season_id!r}."
        )

    if record.get("polygon_hash") != polygon_hash:
        raise ValueError(
            f"{label}: polygon_hash does not match the current farm "
            "boundary."
        )

    if record.get("field_geometry_supplied") is not True:
        raise ValueError(
            f"{label}: field_geometry_supplied must be true for "
            "historical rows."
        )

    _parse_date(
        record.get("observation_date"),
        "observation_date",
    )

    quality_issue = _historical_measurement_quality_issue(
        {
            **record,
            "date": record.get("observation_date"),
        }
    )

    if quality_issue is not None:
        raise ValueError(
            f"{label}: {quality_issue}"
        )

    for column in _HISTORY_METHOD_COLUMNS:
        if record.get(column) is None:
            raise ValueError(
                f"{label}: provenance column {column} is missing."
            )


def _history_record_to_row(
    record: dict,
    *,
    farm_id: str,
    user_id: Optional[str],
    created_at: str,
) -> tuple:
    values: dict[str, Any] = {
        **record,
        "id": str(uuid4()),
        "user_id": user_id,
        "farm_id": farm_id,
        "created_at": created_at,
    }

    row = []

    for column in _HISTORY_INSERT_COLUMNS:
        value = values.get(column)

        if column in _HISTORY_JSON_COLUMNS:
            value = _json_to_db(value, column)

        elif column in _HISTORY_BOOLEAN_COLUMNS:
            value = _bool_to_db(value, column)

        row.append(value)

    return tuple(row)


_HISTORY_INSERT_SQL = (
    "INSERT INTO sentinel_history_observations ("
    + ", ".join(_HISTORY_INSERT_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" for _ in _HISTORY_INSERT_COLUMNS)
    + ")"
)

# Append mode skips a datatake that is already stored (for example when
# two analyses of the same farm run at once). The conflict target is
# the UNIQUE key only, so NOT NULL and foreign-key failures still raise.
_HISTORY_APPEND_SQL = (
    _HISTORY_INSERT_SQL
    + " ON CONFLICT (farm_id, season_id, datatake_id) DO NOTHING"
)


def save_historical_observations(
    *,
    farm_id: str,
    season_id: str,
    polygon_hash: str,
    records: Iterable[dict],
    user_id: Optional[str] = None,
    replace_existing: bool = False,
    expected_existing_datatake_ids: Optional[Iterable[str]] = None,
) -> dict:
    """
    Write one batch of historical measurements in a single transaction.

    replace_existing=True deletes every stored row for this farm and
    season (whatever its polygon_hash) and writes the batch in its
    place. It is used for the first backfill and for rebuilds after a
    boundary or method change. The UNIQUE key does not include
    polygon_hash, so the old rows must be removed rather than appended
    to.

    replace_existing=False appends. Every new observation must be later
    than the latest stored observation, every stored row must carry the
    current polygon_hash, and datatakes already stored are skipped.

    expected_existing_datatake_ids, when supplied, must equal the
    datatakes stored when the batch was planned. If another run changed
    the series in the meantime, nothing is written and the status is
    "state_changed".

    Either the whole batch is written or none of it is.
    """
    batch = [dict(record) for record in records]

    seen_datatakes: set[str] = set()

    for record in batch:
        _validate_history_record(
            record,
            season_id=season_id,
            polygon_hash=polygon_hash,
        )

        datatake_id = str(record["datatake_id"])

        if datatake_id in seen_datatakes:
            raise ValueError(
                f"Datatake {datatake_id} appears twice in one batch."
            )

        seen_datatakes.add(datatake_id)

    # Every record in one batch must come from the same measurement
    # method, and (below) an append must match the stored method. This
    # protects the series even when this function is called directly.
    batch_method: Optional[dict] = None

    if batch:
        batch_method = {
            column: batch[0].get(column)
            for column in _HISTORY_METHOD_COLUMNS
        }

        mixed = _history_method_mismatches(batch[1:], batch_method)

        if mixed:
            raise ValueError(
                "Historical batch mixes measurement methods: "
                + ", ".join(mixed)
                + "."
            )

    batch.sort(
        key=lambda record: (
            record["observation_date"],
            str(record["datatake_id"]),
        )
    )

    conn = get_connection()

    try:
        # Take the write lock before reading state, so the check below
        # and the write cannot be interleaved with another run.
        conn.execute("BEGIN IMMEDIATE")

        row_user_id = _resolve_history_user_id(
            conn,
            farm_id,
            user_id,
        )

        stored = _load_history_state(
            conn,
            farm_id,
            season_id,
        )

        stored_datatakes = {
            str(row["datatake_id"]) for row in stored
        }

        if (
            expected_existing_datatake_ids is not None
            and stored_datatakes
            != {str(value) for value in expected_existing_datatake_ids}
        ):
            conn.rollback()
            return {
                "status": "state_changed",
                "stored_before": len(stored),
                "deleted_count": 0,
                "inserted_count": 0,
                "skipped_duplicate_count": 0,
                "stored_after": len(stored),
            }

        created_at = _utc_now_iso()

        rows = [
            _history_record_to_row(
                record,
                farm_id=farm_id,
                user_id=row_user_id,
                created_at=created_at,
            )
            for record in batch
        ]

        deleted_count = 0
        inserted_count = 0

        if replace_existing:
            cursor = conn.execute(
                """
                DELETE FROM sentinel_history_observations
                WHERE farm_id = ? AND season_id = ?
                """,
                (farm_id, season_id),
            )
            deleted_count = max(cursor.rowcount, 0)

            for row in rows:
                conn.execute(_HISTORY_INSERT_SQL, row)
                inserted_count += 1

        else:
            if any(
                row["polygon_hash"] != polygon_hash
                for row in stored
            ):
                raise ValueError(
                    "Stored history was measured on a different farm "
                    "boundary; it must be rebuilt, not appended to."
                )

            if stored and batch_method is not None:
                method_mismatches = _history_method_mismatches(
                    stored,
                    batch_method,
                )

                if method_mismatches:
                    raise ValueError(
                        "Stored history uses a different measurement "
                        "method ("
                        + ", ".join(method_mismatches)
                        + "); it must be rebuilt, not appended to."
                    )

            if stored:
                latest_stored = max(
                    row["observation_date"] for row in stored
                )

                too_early = [
                    record["observation_date"]
                    for record in batch
                    if str(record["datatake_id"])
                    not in stored_datatakes
                    and record["observation_date"] <= latest_stored
                ]

                if too_early:
                    raise ValueError(
                        "Append only adds observations after the latest "
                        f"stored date ({latest_stored}); got "
                        f"{', '.join(too_early)}."
                    )

            for row in rows:
                cursor = conn.execute(_HISTORY_APPEND_SQL, row)
                inserted_count += max(cursor.rowcount, 0)

        stored_after = conn.execute(
            """
            SELECT COUNT(*) FROM sentinel_history_observations
            WHERE farm_id = ? AND season_id = ?
            """,
            (farm_id, season_id),
        ).fetchone()[0]

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return {
        "status": "saved",
        "stored_before": len(stored),
        "deleted_count": deleted_count,
        "inserted_count": inserted_count,
        "skipped_duplicate_count": len(rows) - inserted_count,
        "stored_after": stored_after,
    }


def load_historical_observations(
    farm_id: str,
    season_id: str,
) -> list[dict]:
    """
    Read a stored historical series in date order.

    JSON columns are decoded and three-state booleans come back as
    None, False, or True.
    """
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM sentinel_history_observations
            WHERE farm_id = ? AND season_id = ?
            ORDER BY observation_date, datatake_id
            """,
            (farm_id, season_id),
        ).fetchall()

    finally:
        conn.close()

    observations = []

    for row in rows:
        observation = dict(row)

        for column in _HISTORY_JSON_COLUMNS:
            observation[column] = _db_to_json(
                observation.get(column)
            )

        for column in _HISTORY_BOOLEAN_COLUMNS:
            observation[column] = _db_to_bool(
                observation.get(column)
            )

        observations.append(observation)

    return observations


def _plan_history_update(
    stored_rows: list[dict],
    polygon_hash: str,
    analysis_geometry: Optional[dict] = None,
) -> dict:
    """
    Decide how to bring a stored series up to date.

      initial  - nothing stored yet; build the full series.
      rebuild  - stored rows used another boundary or another
                 measurement method; replace the whole series.
      append   - stored rows are compatible; look only for newer
                 observations.
    """
    if not stored_rows:
        return {"mode": "initial", "reason": "no_stored_history"}

    if any(
        row.get("polygon_hash") != polygon_hash
        for row in stored_rows
    ):
        return {"mode": "rebuild", "reason": "boundary_changed"}

    mismatched = _history_method_mismatches(
        stored_rows,
        _current_method_expectations(analysis_geometry),
    )

    if mismatched:
        return {
            "mode": "rebuild",
            "reason": "method_changed:" + ",".join(mismatched),
        }

    return {"mode": "append", "reason": "compatible_history"}


def update_historical_series(
    *,
    farm_id: str,
    coordinates: Any,
    user_id: Optional[str] = None,
    crop_type: Any = None,
    planting_date: Any = None,
    season_id: Optional[str] = None,
    end_date_exclusive: Any = None,
    include_zones: bool = True,
) -> dict:
    """
    Discover, measure, and store the historical series for one farm.

    First run: builds the full season and stores it in one transaction.
    Later runs: search only after the latest stored observation and
    append what is new. A changed boundary or measurement method
    replaces the series instead of mixing incompatible rows.

    Measurement happens before any delete, so a failed rebuild leaves
    the previous series untouched.

    History stored under NO_SEASON is not moved if a planting date is
    added later; the new season starts its own series.
    """
    parsed_planting_date = _parse_date(
        planting_date,
        "planting_date",
    )

    resolved_season_id = (
        build_season_id(
            supplied_season_id=season_id,
            crop_key=normalize_crop_key(crop_type),
            planting_date=parsed_planting_date,
        )
        or NO_SEASON
    )

    polygon_hash = build_polygon_hash(
        _normalize_polygon_coordinates(coordinates)
    )

    conn = get_connection()

    try:
        _resolve_history_user_id(conn, farm_id, user_id)

        stored = _load_history_state(
            conn,
            farm_id,
            resolved_season_id,
        )

    finally:
        conn.close()

    current_geometry = None

    if stored:
        # Check the edge-buffer settings the current code would use for
        # this boundary, so a method change is caught even on runs that
        # find no new observations.
        initialize_gee()

        (
            _,
            current_geometry,
        ) = build_analysis_geometry(
            _build_display_polygon(coordinates)
        )

    plan = _plan_history_update(
        stored,
        polygon_hash,
        current_geometry,
    )

    return _run_history_update(
        plan=plan,
        stored=stored,
        farm_id=farm_id,
        coordinates=coordinates,
        user_id=user_id,
        crop_type=crop_type,
        planting_date=parsed_planting_date,
        season_id=resolved_season_id,
        polygon_hash=polygon_hash,
        end_date_exclusive=end_date_exclusive,
        include_zones=include_zones,
    )


def _run_history_update(
    *,
    plan: dict,
    stored: list[dict],
    farm_id: str,
    coordinates: Any,
    user_id: Optional[str],
    crop_type: Any,
    planting_date: Optional[date],
    season_id: str,
    polygon_hash: str,
    end_date_exclusive: Any,
    include_zones: bool,
) -> dict:
    mode = plan["mode"]
    appending = mode == "append"

    summary: dict[str, Any] = {
        "farm_id": farm_id,
        "season_id": season_id,
        "polygon_hash": polygon_hash,
        "mode": mode,
        "reason": plan["reason"],
        "stored_before": len(stored),
    }

    stored_dates = [row["observation_date"] for row in stored]
    stored_datatakes = [str(row["datatake_id"]) for row in stored]

    discovery_start = None

    if appending:
        latest_stored = _parse_date(
            max(stored_dates),
            "latest stored observation_date",
        )
        discovery_start = latest_stored + timedelta(days=1)

        resolved_end = (
            _parse_date(end_date_exclusive, "end_date_exclusive")
            or datetime.now(timezone.utc).date() + timedelta(days=1)
        )

        if discovery_start >= resolved_end:
            return {
                **summary,
                "status": "up_to_date",
                "inserted_count": 0,
                "stored_after": len(stored),
            }

    discovery = discover_historical_observations(
        coordinates,
        crop_type=crop_type,
        season_id=season_id,
        planting_date=planting_date,
        start_date=discovery_start,
        end_date_exclusive=end_date_exclusive,
        existing_observation_dates=(
            stored_dates if appending else None
        ),
    )

    if discovery["season_id"] != season_id:
        raise RuntimeError(
            "Discovery resolved a different season_id than the "
            "persistence layer."
        )

    summary["discovery"] = {
        key: discovery.get(key)
        for key in (
            "search_start",
            "search_end_exclusive",
            "window_basis",
            "datatake_count",
            "usable_candidate_count",
            "selected_observation_count",
            "discovery_elapsed_seconds",
        )
    }
    summary["sampling_bias_note"] = discovery.get(
        "sampling_bias_note"
    )

    selected = discovery["selected_observations"]

    if not selected:
        if appending:
            return {
                **summary,
                "status": "no_new_observations",
                "inserted_count": 0,
                "stored_after": len(stored),
            }

        # A rebuild with nothing usable still removes the old rows:
        # history from another boundary or method must not be compared
        # against current measurements.
        saved = save_historical_observations(
            farm_id=farm_id,
            season_id=season_id,
            polygon_hash=polygon_hash,
            records=[],
            user_id=user_id,
            replace_existing=True,
            expected_existing_datatake_ids=stored_datatakes,
        )

        return {
            **summary,
            **saved,
            "status": (
                "no_usable_observations"
                if saved["status"] == "saved"
                else saved["status"]
            ),
        }

    measured = measure_selected_historical_observations(
        coordinates,
        selected,
        start_date=discovery["search_start"],
        end_date_exclusive=discovery["search_end_exclusive"],
        crop_type=crop_type,
        planting_date=planting_date,
        season_id=season_id,
        include_zones=include_zones,
    )

    summary["measurement"] = {
        "requested_observation_count": measured.get(
            "requested_observation_count"
        ),
        "accepted_measurement_count": measured.get(
            "accepted_measurement_count"
        ),
        "rejected_observation_count": measured.get(
            "rejected_observation_count"
        ),
        "measurement_elapsed_seconds": measured.get(
            "measurement_elapsed_seconds"
        ),
    }
    summary["rejected_observations"] = measured.get(
        "rejected_observations",
        [],
    )

    retryable = [
        rejection
        for rejection in summary["rejected_observations"]
        if rejection.get("reason") in _HISTORY_RETRYABLE_REJECTIONS
    ]

    if retryable:
        # Saving now would leave a permanent gap, because later runs
        # only look forward. Store nothing and try again next time.
        return {
            **summary,
            "status": "retry_needed",
            "inserted_count": 0,
            "stored_after": len(stored),
        }

    records = measured.get("measurements", [])

    if not records:
        if appending:
            # Every new observation failed a fixed quality rule.
            # The existing compatible history remains unchanged.
            return {
                **summary,
                "status": "no_new_observations",
                "inserted_count": 0,
                "stored_after": len(stored),
            }

        # An initial build or rebuild produced no persistable
        # observations. Remove incompatible existing history, if any,
        # rather than presenting it as belonging to the current series.
        saved = save_historical_observations(
            farm_id=farm_id,
            season_id=season_id,
            polygon_hash=polygon_hash,
            records=[],
            user_id=user_id,
            replace_existing=True,
            expected_existing_datatake_ids=stored_datatakes,
        )

        return {
            **summary,
            **saved,
            "status": (
                "no_usable_observations"
                if saved["status"] == "saved"
                else saved["status"]
            ),
        }

    saved = save_historical_observations(
        farm_id=farm_id,
        season_id=season_id,
        polygon_hash=polygon_hash,
        records=records,
        user_id=user_id,
        replace_existing=not appending,
        expected_existing_datatake_ids=stored_datatakes,
    )

    return {
        **summary,
        **saved,
    }