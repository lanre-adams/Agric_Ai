from __future__ import annotations

from typing import Any, Optional


# Classifies the latest comparable change from a historical comparison
# (build_historical_comparison) along three separate axes before any
# label is assigned:
#
#   magnitude         - is the latest movement larger than this field's
#                       own recent observation-to-observation movement?
#   continuity        - has the same direction repeated across
#                       consecutive comparable observations?
#   timing certainty  - was the change observed over normal spacing,
#                       or across a long gap where its timing is unknown?
#
# No fixed index threshold is used. "Usual movement" comes from the
# field's own regular-interval changes in the same crop phase. Labels
# describe direction ("lower", "higher"), never value judgments such as
# "worsening": a lower index late in the season can be expected crop
# development. Repeated direction across observations does not prove a
# continuous change between them. "Persistent" is reserved for the
# spatial question (the same area repeatedly differing), not used here.

PATTERN_INDICES = (
    "ndvi",
    "ndmi",
    "ndre",
    "savi",
    "gndvi",
)

# Fewer reference changes than this are not enough to describe usual
# movement for the field.
PATTERN_MIN_REFERENCE_CHANGES = 4

# Only the most recent reference changes are used, so "usual movement"
# reflects the field's recent behavior rather than the whole season, and
# the largest-reference comparison does not drift upward as the stored
# series grows.
PATTERN_MAX_REFERENCE_CHANGES = 6

_ROUND = 3


def _rounded(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None

    return round(float(value), _ROUND) + 0.0


def _reference_changes(
    changes: list[dict],
    latest_change: dict,
) -> tuple[list[dict], Optional[str]]:
    """
    Regular-interval, method-compatible changes that describe usual
    movement before the latest change.

    The reference phase is the phase the field was in BEFORE the latest
    change. Changes across a long gap are excluded because they span an
    unknown amount of time. A change that moves between phases is
    excluded because it mixes two kinds of crop behavior.
    """
    phase = latest_change["timing"]["earlier_phase"]

    reference = [
        change
        for change in changes
        if change is not latest_change
        and change["interval"] == "regular"
        and change["methods_compatible"]
        and (
            phase is None
            or (
                change["timing"]["earlier_phase"] == phase
                and change["timing"]["later_phase"] == phase
            )
        )
    ]

    return reference[-PATTERN_MAX_REFERENCE_CHANGES:], phase


def _magnitude(
    index: str,
    latest_change: dict,
    reference: list[dict],
) -> dict:
    """
    Compare the latest movement with the largest recent reference
    movement for the same index.

    Two comparisons are reported, because across a long gap they can
    disagree:

      total  - absolute change between the two observations
      rate   - change per 10 days, which assumes the change was spread
               evenly across the interval (the most conservative reading
               when the timing within a gap is unknown)
    """
    latest = latest_change["indices"][index]

    if latest["change"] is None:
        return {"status": "unknown"}

    totals = [
        abs(change["indices"][index]["change"])
        for change in reference
        if change["indices"][index]["change"] is not None
    ]
    rates = [
        abs(change["indices"][index]["change_per_10_days"])
        for change in reference
        if change["indices"][index]["change_per_10_days"] is not None
    ]

    if min(len(totals), len(rates)) < PATTERN_MIN_REFERENCE_CHANGES:
        return {
            "status": "insufficient_history",
            "reference_change_count": min(len(totals), len(rates)),
        }

    largest_total = max(totals)
    largest_rate = max(rates)
    latest_total = abs(latest["change"])
    latest_rate = abs(latest["change_per_10_days"])

    exceeds_total = latest_total > largest_total
    exceeds_rate = latest_rate > largest_rate

    if exceeds_rate:
        status = "larger_than_recent_movement"
    elif exceeds_total:
        status = "larger_in_total_not_in_rate"
    else:
        status = "within_recent_movement"

    return {
        "status": status,
        "reference_change_count": len(totals),
        "latest_total": _rounded(latest_total),
        "largest_reference_total": _rounded(largest_total),
        "latest_rate_per_10_days": _rounded(latest_rate),
        "largest_reference_rate_per_10_days": _rounded(largest_rate),
    }


def _continuity(
    index: str,
    changes: list[dict],
) -> dict:
    """
    How many of the newest comparable changes share the latest
    arithmetic direction, and the combined change across that run.
    """
    latest_direction = changes[-1]["indices"][index]["direction"]

    if latest_direction not in ("lower", "higher"):
        return {
            "direction": latest_direction,
            "consecutive_changes": 0,
            "run_total_change": None,
            "run_start_date": None,
            "run_days": None,
            "run_contains_long_gap": False,
            "run_contains_phase_transition": False,
        }

    run = []

    for change in reversed(changes):
        if change["indices"][index]["direction"] != latest_direction:
            break

        timing = change["timing"]

        phase_transition = (
            timing["earlier_phase"] is not None
            and timing["later_phase"] is not None
            and timing["earlier_phase"]
            != timing["later_phase"]
        )

        context_break = (
            change["interval"] == "across_gap"
            or phase_transition
        )

        # Include the latest change itself, but do not carry a
        # directional run backward across a long observation gap
        # or crop-phase transition.
        if run and context_break:
            break

        run.append(change)

        if context_break:
            break

    run.reverse()

    total = sum(change["indices"][index]["change"] for change in run)

    return {
        "direction": latest_direction,
        "consecutive_changes": len(run),
        "run_total_change": _rounded(total),
        "run_start_date": run[0]["earlier_date"],
        "run_days": sum(change["days_between"] for change in run),
        "run_contains_long_gap": any(
            change["interval"] == "across_gap" for change in run
        ),
        "run_contains_phase_transition": any(
            change["timing"]["earlier_phase"] is not None
            and change["timing"]["later_phase"] is not None
            and change["timing"]["earlier_phase"]
            != change["timing"]["later_phase"]
            for change in run
        ),
    }


def _timing_certainty(
    latest_change: dict,
) -> dict:
    across_gap = latest_change["interval"] == "across_gap"
    timing = latest_change["timing"]

    phase_transition = (
        timing["earlier_phase"] is not None
        and timing["later_phase"] is not None
        and timing["earlier_phase"] != timing["later_phase"]
    )

    return {
        "status": (
            "across_long_gap" if across_gap else "regular_spacing"
        ),
        "days_between": latest_change["days_between"],
        "exact_change_time_known": False,
        "timing_resolution": (
            "coarse_due_to_long_gap"
            if across_gap
            else "bounded_by_regular_spacing"
        ),
        "phase_transition": phase_transition,
        "earlier_phase": timing["earlier_phase"],
        "later_phase": timing["later_phase"],
    }


def _pattern_label(
    magnitude: dict,
    continuity: dict,
    timing_certainty: dict,
) -> str:
    """
    Summarize the measured pattern without implying cause or exact
    timing.

    Directional repetition means successive observations moved in the
    same arithmetic direction. It does not prove that change occurred
    continuously between satellite observations.
    """
    if magnitude["status"] in ("unknown", "insufficient_history"):
        return magnitude["status"]

    if continuity["direction"] not in ("lower", "higher"):
        return "unchanged"

    if magnitude["status"] == "within_recent_movement":
        return "within_recent_variation"

    if magnitude["status"] == "larger_in_total_not_in_rate":
        return "larger_total_change_only"

    if timing_certainty["status"] == "across_long_gap":
        return "larger_change_across_gap"

    if continuity["consecutive_changes"] >= 2:
        return "repeated_directional_change"

    return "larger_directional_change"


def analyze_historical_patterns(
    comparison: dict,
) -> dict:
    """
    Classify the latest change in a historical comparison.

    Accepts the result of build_historical_comparison(). Reports, per
    index, magnitude, continuity, and a combined label, plus timing
    certainty for the latest change as a whole. Does not interpret
    causes.
    """
    status = comparison.get("status")
    changes = comparison.get("changes") or []

    if status != "compared" or not changes:
        return {
            "status": (
                status
                if status != "compared"
                else "insufficient_observations"
            ),
            "latest_change": None,
            "timing_certainty": None,
            "indices": {},
            "label_counts": {},
        }

    latest_change = changes[-1]
    reference, reference_phase = _reference_changes(
        changes,
        latest_change,
    )

    timing_certainty = _timing_certainty(latest_change)

    indices: dict[str, Any] = {}

    for index in PATTERN_INDICES:
        magnitude = _magnitude(index, latest_change, reference)
        continuity = _continuity(index, changes)

        indices[index] = {
            "change": latest_change["indices"][index]["change"],
            "direction": continuity["direction"],
            "magnitude": magnitude,
            "continuity": continuity,
            "label": _pattern_label(
                magnitude,
                continuity,
                timing_certainty,
            ),
        }

    labels = [entry["label"] for entry in indices.values()]

    return {
        "status": "analyzed",
        "latest_change": {
            "earlier_date": latest_change["earlier_date"],
            "later_date": latest_change["later_date"],
        },
        "reference": {
            "phase": reference_phase,
            "change_count": len(reference),
            "dates": [
                [change["earlier_date"], change["later_date"]]
                for change in reference
            ],
        },
        "timing_certainty": timing_certainty,
        "indices": indices,
        "label_counts": {
            label: labels.count(label) for label in sorted(set(labels))
        },
    }