from app.services.agents.state import FarmWatchState


# Fields a successful report cannot exist without.
#
# FarmWatchState is total=False, so a missing write becomes a silent
# None rather than raising. This agent is the last gate before the
# frontend, so anything whose absence would produce a wrong or
# unrenderable report is checked here.
#
# assessment_scope is in this list deliberately. Without it the frontend
# has nothing telling it to frame the report as partial, and a field 40%
# observed renders identically to one fully assessed. Every agent
# upstream guards it; this is the last chance to catch a gap.
#
# Deliberately NOT required:
#   attention_area         None is a legitimate scientific result
#   possible_causes        an empty list is valid
#   corroborating_signals  an empty list is valid
#   hotspot_summary        absence means silence about the spatial
#                          comparison, not a false claim
#   stress_type            legacy field; condition_signal is what matters
#   crop_context           OPTIONAL BY DESIGN. Requiring it here would
#                          hard-fail every farm that never supplied crop
#                          information — which is every farm currently in
#                          the database. Crop context changes how a
#                          reading is interpreted; it is never a gate on
#                          producing one.
REQUIRED_REPORT_FIELDS = (
    "title",
    "summary",
    "explanation",
    "action",
    "recommendation",
    "condition_signal",
    "severity",
    "urgency",
    "color",
    "assessment_scope",
)

# Spatial fields checked by PRESENCE, not truthiness.
#
# attention_is_distinct=False is a legitimate measured result: the zone
# ranking ran and found nothing meaningfully weaker. `bool(state.get())`
# collapses that with a missing write, which is the silent conversion
# this whole migration exists to eliminate. `key not in state` is the
# only test that separates "detection said no" from "detection said
# nothing".
REQUIRED_SPATIAL_FIELDS = (
    "attention_source",
    "attention_is_distinct",
)

# Metadata blocks that must be present AND dict-shaped. Processing
# guarantees each of them; Report is the last boundary before the
# frontend, so their disappearance should be visible rather than
# rendered as a null.
REQUIRED_REPORT_BLOCKS = (
    "field_coverage",
    "analysis_coverage",
    "analysis_geometry",
)

# Acquisition identity and observation date. Without these a result
# cannot be reproduced in the Earth Engine Code Editor during
# validation, which is the point of carrying them this far.
REQUIRED_PROVENANCE_FIELDS = (
    ("datatake_id", "Final report is missing the Sentinel-2 datatake ID."),
    (
        "observation_datetime_utc",
        "Final report is missing the Sentinel-2 observation time.",
    ),
    ("image_date", "Final report is missing the observation date."),
)

VARIATION_BOUND_KEYS = {"west", "south", "east", "north"}


def _validate_report_contract(state):
    """
    Raises RuntimeError if state is not what the frozen pipeline
    guarantees.

    Split out so it can be exercised directly in a test with a
    hand-built state, without running the whole graph.
    """
    missing_fields = [
        field
        for field in REQUIRED_REPORT_FIELDS
        if state.get(field) is None or state.get(field) == ""
    ]
    if missing_fields:
        raise RuntimeError(
            "Final report is missing required fields: "
            + ", ".join(missing_fields)
        )

    for key in REQUIRED_SPATIAL_FIELDS:
        if key not in state:
            raise RuntimeError(
                f"Final report is missing required spatial field: {key}."
            )

    if not isinstance(state.get("attention_source"), str):
        raise RuntimeError("Final report has an invalid attention_source.")

    if not isinstance(state.get("attention_is_distinct"), bool):
        raise RuntimeError(
            "Final report has an invalid attention_is_distinct value."
        )

    if not state.get("image_info"):
        raise RuntimeError(
            "Final report is missing satellite image metadata."
        )

    for key in REQUIRED_REPORT_BLOCKS:
        if not isinstance(state.get(key), dict):
            raise RuntimeError(
                f"Final report is missing required metadata block: {key}."
            )

    source_image_ids = state.get("source_image_ids")
    if not isinstance(source_image_ids, list) or not source_image_ids:
        raise RuntimeError(
            "Final report is missing Sentinel-2 source image IDs."
        )

    for key, message in REQUIRED_PROVENANCE_FIELDS:
        if not state.get(key):
            raise RuntimeError(message)

    # The variation map is the farmer-facing deliverable. The URL alone
    # is not enough: without bounds Mapbox cannot place the raster, and
    # without info the frontend cannot explain the relative green scale,
    # the two different grays, or that colours do not compare across
    # dates. A map shown without that explanation is worse than no map.
    if not state.get("variation_map_url"):
        raise RuntimeError(
            "Final report is missing the field variation map."
        )

    bounds = state.get("variation_map_bounds")
    if not isinstance(bounds, dict):
        raise RuntimeError("Final report is missing variation-map bounds.")
    if not VARIATION_BOUND_KEYS.issubset(bounds):
        raise RuntimeError("Final report has invalid variation-map bounds.")

    info = state.get("variation_map_info")
    if not isinstance(info, dict) or not info:
        raise RuntimeError(
            "Final report is missing variation-map metadata."
        )

    # Field geometry. Fundamental Farm Watch outputs, and no longer
    # reconstructed from the top-level aliases — a broken contract
    # should be visible, not quietly patched.
    farm_area = state.get("farm_area")
    if not isinstance(farm_area, dict):
        raise RuntimeError("Final report is missing farm area.")
    if farm_area.get("hectares") is None or farm_area.get("acres") is None:
        raise RuntimeError("Final report has incomplete farm area values.")

    center = state.get("center")
    if not isinstance(center, dict):
        raise RuntimeError("Final report is missing the farm centroid.")
    if center.get("lat") is None or center.get("lng") is None:
        raise RuntimeError("Final report has an incomplete farm centroid.")

    # Crop context is OPTIONAL, so its ABSENCE is never an error. Only
    # its shape is checked: detection_agent always writes a dict when it
    # runs, so a non-dict here means something wrote garbage rather than
    # that the farmer skipped the form.
    crop_context = state.get("crop_context")
    if crop_context is not None and not isinstance(crop_context, dict):
        raise RuntimeError("Final report has an invalid crop_context.")


# Coverage, scope and geometry blocks copied straight into the response.
# The frontend needs all of them to describe honestly what was measured:
# the visible percentage comes from field_coverage, the gray-area legend
# from analysis_geometry, and the "colours not comparable across dates"
# note from variation_map_info.
COVERAGE_PASSTHROUGH_KEYS = (
    "assessment_scope",
    "assessment_scope_message",
    "field_coverage",
    "analysis_coverage",
    "analysis_geometry",
    "spatial_coverage",
    "coverage_tier",
    "field_coverage_tier",
    "analysis_coverage_tier",
    "zone_analysis_supported",
    "eligible_zone_count",
    "min_zones_for_analysis",
)

# Crop / season context (Step 3). PASS-THROUGH ONLY — deliberately not
# in REQUIRED_REPORT_BLOCKS.
#
# A polygon-only farm arrives here with has_crop_context=False and
# cover_screen_mode="legacy". Most user-supplied crop values are None,
# while crop_context itself is still a valid dict describing the legacy
# path. That is a valid report, not a broken one.
#
# The frontend needs the whole set, but not all of it is farmer-facing.
#
# Farmer-facing card:
#   crop_type, planting_date, irrigation_type, days_after_planting,
#   timing_phase, and the observation date from crop_context
#
# Technical Details only:
#   cover_screen_mode, decline_expected, season_id, and the nested
#   crop_timing_context (profile_available, context_warnings)
#
# The raw crop_context dict is returned for Step 3 validation. It is
# reference data, not something to render directly.
#
# decline_expected is CONTEXT and three-state (True / False / None). It
# never proves a signal is normal, and None must not be read as False.
CROP_PASSTHROUGH_KEYS = (
    "crop_context",
    "has_crop_context",
    "crop_type",
    "planting_date",
    "irrigation_type",
    "season_id",
    "days_after_planting",
    "timing_phase",
    "cover_screen_mode",
    "decline_expected",
)

# Acquisition identity. datatake_id plus source_image_ids is what lets a
# reviewer reproduce a result in the Earth Engine Code Editor; image_id
# alone is only the first contributing asset.
OBSERVATION_PASSTHROUGH_KEYS = (
    "image_date",
    "image_id",
    "source_image_ids",
    "source_tile_count",
    "datatake_id",
    "observation_datetime_utc",
)


def report_agent(state: FarmWatchState) -> FarmWatchState:
    """
    Report Agent — assembles the final response dictionary.

    Last agent in the pipeline. Reads state and builds final_response in
    the shape the frontend expects.

    Six rules this agent must not break:

    1. Never substitute a placeholder for a missing value. Upstream
       agents set attention_area to None deliberately when no area was
       flagged. Replacing that with "general area of the farm" would
       manufacture a location that was never identified and would undo
       the false-positive protection built into the zone analysis.

    2. Never recompose the farmer-facing text. summary, explanation,
       action and hotspot_summary are passed through exactly as written.
       Rebuilding a headline from severity and attention_area would
       discard the scope qualifiers that every agent upstream works to
       preserve — this is the last place they can be lost.

    3. Never report success over an upstream failure. If a prior agent
       failed, preserve that status rather than returning "ok" with a
       response full of nulls.

    4. Never report success over a silently missing field. Because
       FarmWatchState is total=False, a field that no agent wrote
       becomes None rather than raising. This agent is the last gate
       before the frontend, so it verifies that the fields a report
       cannot exist without are actually present.

    5. Preserve machine-readable failure codes. Satellite-data
       limitations must remain distinguishable from software failures
       so the frontend can present them differently.

    6. Never make optional context mandatory. Crop information is
       optional at every layer, and this agent is the last place that
       could accidentally turn it into a requirement. A farm with no
       crop data must produce a complete, valid report.

    final_response is returned on EVERY path — success, upstream
    failure, and report-stage failure — so the route can always read it.
    """
    # `or []` rather than a default argument: state.get("errors", [])
    # returns None when an earlier agent wrote errors=None explicitly,
    # and list(None) raises TypeError here — outside the try block, so
    # it would surface as an unhandled crash rather than a handled one.
    errors = list(state.get("errors") or [])

    # ── Upstream failure handling ─────────────────────────────────
    #
    # A prior agent failed. Preserve the failure rather than dressing
    # it up as a successful report.
    boundary_error = state.get("boundary_error")
    data_error = state.get("data_error")
    processing_error = state.get("processing_error")
    detection_error = state.get("detection_error")
    interpretation_error = state.get("interpretation_error")

    upstream_error = (
        boundary_error
        or data_error
        or processing_error
        or detection_error
        or interpretation_error
    )

    if upstream_error or state.get("status") == "failed":

        msg = upstream_error or "Analysis failed before the report stage."

        # Preserve the most useful machine-readable error code.
        #
        # processing_agent already distinguishes expected satellite
        # limitations from actual processing failures. Other upstream
        # agents receive simple codes here so the frontend never needs
        # to inspect human-readable error text.
        if boundary_error:
            error_code = "BOUNDARY_INVALID"

        elif data_error:
            error_code = "DATA_ERROR"

        elif processing_error:
            error_code = (
                state.get("processing_error_code")
                or "PROCESSING_ERROR"
            )

        elif detection_error:
            error_code = "DETECTION_ERROR"

        elif interpretation_error:
            error_code = "INTERPRETATION_ERROR"

        else:
            error_code = "ANALYSIS_FAILED"

        return {
            **state,
            "final_response": {
                "error": msg,
                "error_code": error_code,
                "status": "failed",
            },

            # The Report Agent itself did not fail here. It successfully
            # packaged an upstream failure into the final API response.
            "report_error": None,

            "status": "failed",
            "errors": errors,
        }

    try:
        # ── Final report contract guard ───────────────────────────
        _validate_report_contract(state)

        # None is meaningful — no area was flagged.
        # Do NOT substitute a placeholder.
        attention_area = state.get("attention_area")

        # Direct indexing, not a defaulted get(). The validator has
        # already established both are present and correctly typed, and
        # a default here would reintroduce exactly the silent
        # substitution it exists to prevent.
        attention_source = state["attention_source"]
        attention_is_distinct = state["attention_is_distinct"]

        technical_details = dict(state.get("technical_details") or {})
        technical_details.setdefault("attention_source", attention_source)

        image_info = state["image_info"]
        recent_comparison = state.get("recent_comparison") or {}

        # Built upstream with the correct distinctions.
        # No fallback here that invents a location.
        hotspot_summary = state.get("hotspot_summary")

        # No reconstruction from area_ha/area_acres: the validator
        # guarantees farm_area, and rebuilding it would hide a gap.
        farm_area = state["farm_area"]

        # ── Field map ─────────────────────────────────────────────
        #
        # The Phase 1 farmer map is the same-date RELATIVE VARIATION
        # map: light-to-dark green shows lower-to-higher readings
        # RELATIVE TO THIS FIELD ON THIS DATE. It is not an absolute
        # condition map and its colours are rescaled per observation,
        # so they are not comparable between reports.
        #
        # variation_map_info carries the legend text, the two gray
        # meanings (cloud-obscured vs excluded field edge) and
        # spread_is_meaningful. All three parts are validated above.
        variation_map_url = state["variation_map_url"]
        variation_map_bounds = state["variation_map_bounds"]
        variation_map_info = state["variation_map_info"]

        final_response = {
            # Response status
            "status": "ok",

            # ── Plain-language interpretation ─────────────────────
            #
            # Passed through verbatim. These sentences already carry the
            # scope qualifiers; recomposing them here would drop those.
            "title": state.get("title"),
            "summary": state.get("summary"),
            "explanation": state.get("explanation"),
            "action": state.get("action"),
            "recommendation": state.get("recommendation"),

            # ── Classification ────────────────────────────────────
            "urgency": state.get("urgency"),
            "severity": state.get("severity"),
            "color": state.get("color"),

            # Safe user-facing signal. The frontend should key on this
            # rather than stress_type, whose legacy values can imply
            # causes that spectral measurements cannot establish.
            "condition_signal": state.get("condition_signal"),

            # Legacy internal code kept for database compatibility.
            "stress_type": state.get("stress_type"),

            # Hypotheses only — never asserted as established causes.
            "possible_causes": (
                state.get("possible_causes") or []
            ),

            "corroborating_signals": (
                state.get("corroborating_signals") or []
            ),

            # ── Spatial finding ───────────────────────────────────
            #
            # attention_area may legitimately be None.
            #
            # relative_low_area, zone_values, zone_pixel_counts and
            # attention_rule remain in technical_details rather than
            # being promoted as user-facing findings.
            "attention_area": attention_area,

            # Passed through as measured. False here means the ranking
            # ran and found nothing meaningfully weaker; a missing value
            # would have failed the validator above rather than
            # arriving as False.
            "attention_is_distinct": attention_is_distinct,

            "attention_source": attention_source,

            "hotspot_summary": hotspot_summary,

            # ── Field variation map ───────────────────────────────
            "variation_map_url": variation_map_url,
            "variation_map_bounds": variation_map_bounds,
            "variation_map_info": variation_map_info,

            # TEMPORARY compatibility aliases. All four now point at the
            # RELATIVE VARIATION map, which makes no health claim.
            # Remove after Results.tsx has fully migrated — and fix the
            # surrounding copy at the same time, because the old names
            # imply a health reading the map no longer provides.
            "field_condition_map_url": variation_map_url,
            "condition_map_bounds": variation_map_bounds,
            "stress_map_url": variation_map_url,
            "stress_map_bounds": variation_map_bounds,

            # ── Location and area ─────────────────────────────────
            #
            # farm_area covers the FULL drawn polygon. The smaller
            # interior the indices were computed over is in
            # analysis_geometry["analysed_area_m2"].
            "center": state.get("center"),
            "farm_area": farm_area,
            "area_ha": state.get("area_ha"),
            "area_acres": state.get("area_acres"),

            # ── Observation metadata ──────────────────────────────
            "image_info": image_info,

            # ── Technical / validation layer ──────────────────────
            "technical_details": technical_details,

            # Supporting layer for future trend and historical work.
            "recent_comparison": recent_comparison,
        }

        # ── Coverage, scope and acquisition identity ──────────────
        #
        # Promoted to the top level of the response so the frontend does
        # not have to dig through image_info. field_coverage is the
        # farmer-facing visibility figure; analysis_coverage describes
        # the edge-buffered interior the numbers actually came from.
        for key in COVERAGE_PASSTHROUGH_KEYS:
            final_response[key] = state.get(key)

        for key in OBSERVATION_PASSTHROUGH_KEYS:
            final_response[key] = state.get(key)

        # Crop context last. Every crop-context response key is included
        # so the API shape stays stable. Missing optional values become
        # None. has_crop_context is the explicit field the frontend
        # should use to distinguish a polygon-only analysis from one with
        # crop information — key presence cannot be used, because this
        # loop assigns every key unconditionally.
        #
        # has_crop_context is True if the farmer supplied ANY crop field,
        # so it does NOT imply that timing exists. Irrigation alone gives
        # has_crop_context=True with days_after_planting=None and
        # cover_screen_mode="legacy". Check the specific value being
        # rendered, not the flag.
        for key in CROP_PASSTHROUGH_KEYS:
            final_response[key] = state.get(key)

        return {
            **state,
            "final_response": final_response,
            "report_error": None,
            "status": "ok",
            "errors": errors,
        }

    except Exception as exc:
        # Keep the technical error internally for debugging.
        internal_msg = (
            f"Report agent failed: "
            f"{type(exc).__name__}: {exc}"
        )

        errors.append(internal_msg)

        # Do NOT expose agent names, Python exceptions or architecture
        # details to a farmer/client.
        user_msg = (
            "The analysis was completed, but the report could not be "
            "prepared for display. Please try again."
        )

        return {
            **state,
            "final_response": {
                "error": user_msg,
                "error_code": "REPORT_ERROR",
                "status": "failed",
            },
            "report_error": user_msg,
            "status": "failed",
            "errors": errors,
        }