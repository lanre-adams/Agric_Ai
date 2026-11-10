from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional


# This module reports measured facts only and never diagnoses causes.
# Changes are absolute index differences, never percentages: a
# percentage change of a normalized index depends on where on the
# scale the index sits and is misleading.

COMPARISON_INDICES = (
    "ndvi",
    "ndmi",
    "ndre",
    "savi",
    "gndvi",
)

# Two observations this many days apart or more have an unobserved
# period between them. A change across that period cannot be called
# sudden, because when it happened is unknown. Matches the historical
# selector's long-gap rule (twice the 7-day minimum spacing).
COMPARISON_LONG_GAP_DAYS = 14

# Provenance that must match before two observations are compared.
_COMPARISON_METHOD_FIELDS = (
    "polygon_hash",
    "analysis_scale_m",
    "edge_buffer_m",
    "edge_excluded",
    "cloud_mask_threshold",
    "index_method",
)

_ROUND = 3


def _as_date(value: Any) -> date:
    # datetime is a subclass of date, so check it first and drop the
    # time component.
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(str(value)[:10])


def _rounded(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None

    # Adding 0.0 turns -0.0 into 0.0.
    return round(float(value), _ROUND) + 0.0


def comparison_exclusion_reason(
    observation: dict,
) -> Optional[str]:
    """
    Why an observation cannot feed comparison statistics, or None.

    Partial-coverage observations stay in the stored series and on the
    chart, but a partial view of the field is not compared against a
    whole-field view.
    """
    if observation.get("field_geometry_supplied") is not True:
        return "full_field_geometry_not_supplied"

    if observation.get("coverage_tier") != "full":
        return f"coverage_{observation.get('coverage_tier') or 'missing'}"

    if observation.get("assessment_scope") != "whole_field":
        return (
            "assessment_scope_"
            f"{observation.get('assessment_scope') or 'missing'}"
        )

    missing = [
        index
        for index in COMPARISON_INDICES
        if observation.get(index) is None
    ]

    if missing:
        return "missing_indices:" + ",".join(missing)

    return None


def _method_differences(
    earlier: dict,
    later: dict,
) -> list[str]:
    differences = []

    for field in _COMPARISON_METHOD_FIELDS:
        a = earlier.get(field)
        b = later.get(field)

        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(float(a) - float(b)) > 1e-9:
                differences.append(field)

        elif a != b:
            differences.append(field)

    return differences


def _direction(
    change: float,
) -> str:
    """
    Report arithmetic direction only.

    This does not determine whether the change is agronomically
    meaningful; a change of -0.003 is "lower" here.
    """
    if change == 0:
        return "unchanged"

    return "higher" if change > 0 else "lower"


def compare_observations(
    earlier: dict,
    later: dict,
) -> dict:
    """
    Measured differences between two observations, later minus earlier.
    """
    earlier_date = _as_date(earlier["observation_date"])
    later_date = _as_date(later["observation_date"])
    days_between = (later_date - earlier_date).days

    if days_between <= 0:
        raise ValueError(
            "The later observation must be after the earlier one."
        )

    method_differences = _method_differences(earlier, later)

    indices = {}

    for index in COMPARISON_INDICES:
        before = earlier.get(index)
        after = later.get(index)

        if before is None or after is None:
            indices[index] = {
                "earlier": _rounded(before),
                "later": _rounded(after),
                "change": None,
                "change_per_10_days": None,
                "direction": "unknown",
            }
            continue

        raw_change = float(after) - float(before)
        change = _rounded(raw_change)

        indices[index] = {
            "earlier": _rounded(before),
            "later": _rounded(after),
            "change": change,
            "change_per_10_days": _rounded(
                raw_change * 10 / days_between
            ),
            "direction": _direction(raw_change),
        }

    directions = [entry["direction"] for entry in indices.values()]

    earlier_phase = earlier.get("timing_phase")
    later_phase = later.get("timing_phase")

    return {
        "earlier_date": earlier_date.isoformat(),
        "later_date": later_date.isoformat(),
        "days_between": days_between,
        "interval": (
            "across_gap"
            if days_between >= COMPARISON_LONG_GAP_DAYS
            else "regular"
        ),
        "both_whole_field": (
            comparison_exclusion_reason(earlier) is None
            and comparison_exclusion_reason(later) is None
        ),
        "methods_compatible": not method_differences,
        "method_differences": method_differences,
        "timing": {
            "earlier_days_after_planting": earlier.get(
                "days_after_planting"
            ),
            "later_days_after_planting": later.get(
                "days_after_planting"
            ),
            "earlier_phase": earlier_phase,
            "later_phase": later_phase,
            "same_phase": (
                earlier_phase is not None
                and earlier_phase == later_phase
            ),
        },
        "indices": indices,
        "arithmetic_direction_counts": {
            "lower": directions.count("lower"),
            "higher": directions.count("higher"),
            "unchanged": directions.count("unchanged"),
            "unknown": directions.count("unknown"),
        },
    }


def _index_season_summary(
    observations: list[dict],
    index: str,
) -> dict:
    """
    Peak and latest values for one index across comparable observations.
    """
    peak = max(observations, key=lambda row: row[index])
    latest = observations[-1]

    return {
        "peak_value": _rounded(peak[index]),
        "peak_date": _as_date(peak["observation_date"]).isoformat(),
        "peak_days_after_planting": peak.get("days_after_planting"),
        "latest_value": _rounded(latest[index]),
        "latest_minus_peak": _rounded(latest[index] - peak[index]),
        "days_since_peak": (
            _as_date(latest["observation_date"])
            - _as_date(peak["observation_date"])
        ).days,
    }


def build_historical_comparison(
    observations: Iterable[dict],
) -> dict:
    """
    Compare a stored historical series.

    Accepts rows as returned by load_historical_observations(). Only
    whole-field, full-coverage observations feed the comparison;
    every other row is listed under excluded_observations with its
    reason, so nothing disappears silently.
    """
    rows = sorted(
        (dict(row) for row in observations),
        key=lambda row: (
            _as_date(row["observation_date"]),
            str(row.get("datatake_id")),
        ),
    )

    comparable = []
    excluded = []

    for row in rows:
        reason = comparison_exclusion_reason(row)

        if reason is None:
            comparable.append(row)
        else:
            excluded.append(
                {
                    "observation_date": _as_date(
                        row["observation_date"]
                    ).isoformat(),
                    "coverage_tier": row.get("coverage_tier"),
                    "reason": reason,
                }
            )

    result: dict[str, Any] = {
        "stored_observation_count": len(rows),
        "comparable_observation_count": len(comparable),
        "excluded_observations": excluded,
        "long_gap_days": COMPARISON_LONG_GAP_DAYS,
        "latest_stored_observation_date": (
            _as_date(rows[-1]["observation_date"]).isoformat()
            if rows
            else None
        ),
    }

    if len(comparable) < 2:
        result.update(
            {
                "status": "insufficient_observations",
                "latest_comparable_observation_date": (
                    _as_date(
                        comparable[-1]["observation_date"]
                    ).isoformat()
                    if comparable
                    else None
                ),
                "previous_comparable_observation_date": None,
                "latest_change": None,
                "changes": [],
                "season": {},
            }
        )
        return result

    changes = [
        compare_observations(earlier, later)
        for earlier, later in zip(comparable, comparable[1:])
    ]

    latest_change = changes[-1]

    result.update(
        {
            "status": (
                "compared"
                if all(change["methods_compatible"] for change in changes)
                else "methods_incompatible"
            ),
            "latest_comparable_observation_date": (
                latest_change["later_date"]
            ),
            "previous_comparable_observation_date": (
                latest_change["earlier_date"]
            ),
            "latest_change": latest_change,
            "changes": changes,
            "season": {
                index: _index_season_summary(comparable, index)
                for index in COMPARISON_INDICES
            },
        }
    )

    return result