from app.services.agents.state import FarmWatchState
from app.services.analysis.crop_context import build_crop_context
from app.services.analysis.stress_classifier import classify_stress


# ----------------------------------------------------------------------
# Spatial availability
# ----------------------------------------------------------------------
# gee.py returns attention_source as either the index that produced a
# ranking, or the REASON no ranking could be reported. The old code
# tested only for the single string "insufficient_data", so every other
# suppression reason fell through to the final else branch and produced
# "Condition looks consistent across the whole field" — a false all-clear
# assembled out of missing data.
#
# Three outcomes, and the difference between the last two is the whole
# point:
#
#   ranked       a zone was ranked; attention_is_distinct decides whether
#                it is worth surfacing
#   uniform      we looked and everything matched. A real finding.
#   unavailable  we could not look. NOT a finding, and must never be
#                worded as one.

SPATIAL_RANKED_SOURCES = frozenset({"ndre", "ndvi_fallback"})

# The field's own spread was inside the noise floor. We measured and
# found nothing, which is a legitimate uniformity claim.
SPATIAL_UNIFORM_SOURCES = frozenset({"field_uniform"})

# Each of these means the comparison could not be made. They need
# different wording because they imply different things about whether a
# later satellite pass would help.
SPATIAL_UNAVAILABLE_MESSAGES = {
    # The 3x3 grid cannot support a reliable comparison at this field
    # size. A later pass does not change the field geometry.
    #
    # This must NOT promise whole-field readings. gee.py checks zone
    # support BEFORE scope, so a small field with only partial coverage
    # arrives here with assessment_scope="partial_field" — the readings
    # cover what was observed, not the whole farm.
    "field_too_small_for_zone_analysis": (
        "This field is too small for Tagintell to reliably compare "
        "different areas within it at the current satellite resolution. "
        "Overall readings are still available for the area that was "
        "reliably observed."
    ),

    # Too few usable pixels to support a within-field variation claim.
    "insufficient_pixels_for_variation": (
        "There were too few usable satellite pixels at this resolution "
        "to reliably compare different areas within this field."
    ),

    # Cloud or other obscuration prevented enough zones from qualifying
    # on this acquisition. A later pass may succeed.
    "insufficient_clear_zones": (
        "There was not enough clear satellite data to reliably compare "
        "conditions across different parts of this field."
    ),

    "insufficient_data": (
        "There was not enough reliable satellite data to compare "
        "conditions across different parts of this field."
    ),
}

# scope_local_only has TWO possible causes and they are not the same
# story for the farmer:
#
#   coverage_tier == "insufficient"  too little of the field was seen
#   otherwise                        enough was seen, but the reliable
#                                    pixels sat in one part of the field
#
# Wording that names only one cause is wrong roughly half the time, so
# detection picks using coverage_tier, which is already in state.
SCOPE_LOCAL_ONLY_MESSAGES = {
    "low_coverage": (
        "Too little of this field was reliably observed to compare "
        "different areas within it."
    ),
    "poor_distribution": (
        "Reliable satellite data were not distributed widely enough "
        "across this field to safely compare different areas."
    ),
}

# An attention_source we do not recognise is treated as unavailable, not
# as a ranking. processing_agent deliberately does not validate this
# value against a closed set, so a future gee.py may add a reason before
# this file knows about it. Falling back to "we could not compare" keeps
# that safe; falling through to "the field is uniform" would not.
SPATIAL_UNAVAILABLE_DEFAULT = SPATIAL_UNAVAILABLE_MESSAGES[
    "insufficient_clear_zones"
]


def _unavailable_message(attention_source, coverage_tier):
    """Wording for a spatial comparison that could not be made."""
    if attention_source == "scope_local_only":
        key = (
            "low_coverage"
            if coverage_tier == "insufficient"
            else "poor_distribution"
        )
        return SCOPE_LOCAL_ONLY_MESSAGES[key]

    return SPATIAL_UNAVAILABLE_MESSAGES.get(
        attention_source, SPATIAL_UNAVAILABLE_DEFAULT
    )

# ----------------------------------------------------------------------
# Scope-aware wording
# ----------------------------------------------------------------------
# assessment_scope says how far a claim may generalise. Without it every
# sentence below says "the field" and "the rest of the field", which
# describes a 40%-visible field as if it had been fully assessed — the
# exact overclaim assessment_scope exists to prevent.

FIELD_NOUN = {
    "whole_field": "the field",
    "partial_field": "the observed parts of the field",
    "local_only": "the areas that could be observed",
}

REST_NOUN = {
    "whole_field": "the rest of the field",
    "partial_field": "the rest of the observed area",
    "local_only": "the rest of the observed area",
}

# Unknown or missing scope is treated as the most cautious option rather
# than the most flattering one.
DEFAULT_SCOPE = "local_only"


def _spatial_status(attention_source):
    """Classifies attention_source into ranked / uniform / unavailable."""
    if attention_source in SPATIAL_RANKED_SOURCES:
        return "ranked"
    if attention_source in SPATIAL_UNIFORM_SOURCES:
        return "uniform"
    return "unavailable"


def _scope_words(assessment_scope):
    """Returns (field noun, rest-of-field noun) for the given scope."""
    scope = assessment_scope if assessment_scope in FIELD_NOUN else DEFAULT_SCOPE
    return FIELD_NOUN[scope], REST_NOUN[scope]


def detection_agent(state: FarmWatchState) -> FarmWatchState:
    """
    Detection Agent — classifies condition signal, severity, and location.

    Index roles (signals, not diagnoses):
        1. NDMI   -> moisture-condition signal
        2. NDRE   -> chlorophyll / crop-condition signal
        3. SAVI   -> sparse-canopy / soil-background support
        4. NDVI   -> general vegetation-condition fallback
        5. GNDVI  -> supporting vegetation signal

    These indices describe CONDITION, not CAUSE. A low moisture signal
    may reflect drought, but also recent harvest, senescence or soil
    type. A low chlorophyll signal may reflect nutrient deficiency, but
    also disease, pest pressure or growth stage. Downstream language
    should stay at the level of possible causes and recommend ground
    inspection.

    Four separate questions are combined here:
        1. Is overall field condition concerning?  -> stress_classifier
        2. Is one part meaningfully different?     -> gee.py zones
        3. How far may either claim generalise?    -> assessment_scope
        4. Where in its season is the crop?        -> crop_context

    CROP CONTEXT (Step 3) is built HERE rather than at the API boundary.
    processing_agent has already selected and stored the Sentinel-2
    observation by the time detection runs, so detection is simply the
    right place to combine that observation date with the optional crop
    information.

    The selected acquisition can be several days older than the day the
    farmer pressed Analyze, and crop timing has to describe the crop as
    the satellite saw it, not as it is today. Building crop timing at the
    API boundary would happen before the observation date is known, and
    would compute days-after-planting against the wrong date.

    Crop context is OPTIONAL. Every farm already in the database has
    none, and build_crop_context() returns cover_screen_mode="legacy"
    when the inputs are absent, which reproduces pre-Step-3 behaviour
    exactly. It is never a gate on producing a report.

    A spatially distinct zone is only surfaced as an attention area when
    overall severity is also non-zero. Otherwise the report would say
    "no warning signal" and "area needing attention" simultaneously.

    "Could not assess" and "no warning signal" are kept strictly
    separate throughout — in the summary text, in the colour indicator,
    and in whether any spatial claim is made at all. Treating them alike
    would turn missing data into a false all-clear. The same separation
    now applies to the spatial comparison: "we looked and the field is
    uniform" and "we could not look" are different statements and get
    different wording.
    """
    # `or []` rather than a default argument: state.get("errors", [])
    # returns None when an earlier agent wrote errors=None explicitly,
    # and list(None) raises TypeError here — outside the try block, so
    # it would surface as an unhandled crash rather than a handled one.
    errors = list(state.get("errors") or [])

    # If processing already failed, its message is the one the farmer
    # should see. Running detection anyway would find no indices and
    # overwrite a specific "cloud is blocking your field" message with a
    # generic internal one.
    if state.get("processing_error"):
        return dict(state)

    indices = state.get("indices")

    if not indices:
        msg = "No indices were available for detection."
        errors.append(msg)
        return {
            **state,
            "detection_error": msg,
            "status": "failed",
            "errors": errors,
        }

    try:
        ndvi = indices.get("ndvi")
        ndre = indices.get("ndre")
        savi = indices.get("savi")
        gndvi = indices.get("gndvi")

        # NDMI is the NIR/SWIR vegetation moisture index. Falls back to
        # the legacy "ndwi" key so nothing breaks mid-migration.
        ndmi = indices.get("ndmi")
        if ndmi is None:
            ndmi = indices.get("ndwi")

        # ── Crop / season context ────────────────────────────────
        #
        # Built against the ACTUAL selected observation date. A report
        # describes one acquisition, so crop timing must describe that
        # same acquisition.
        #
        # Crop fields are read with .get() and never with brackets:
        # run_farm_watch_graph omits unsupplied crop keys entirely, so
        # state["crop_type"] would raise KeyError on a polygon-only
        # request — the most common path, and the one every existing
        # saved farm takes. That KeyError would be swallowed by the
        # except-clause below and shown to the farmer as "Field condition
        # could not be assessed" on a perfectly clear image.
        image_info = state.get("image_info") or {}

        observation_date = (
            state.get("image_date")
            or image_info.get("date")
        )

        crop_context = build_crop_context(
            crop_type=state.get("crop_type"),
            planting_date=state.get("planting_date"),
            irrigation_type=state.get("irrigation_type"),
            season_id=state.get("season_id"),
            observation_date=observation_date,
        )

        # crop_timing_context is None whenever days_after_planting is
        # None, which is the case for every farm without a planting
        # date. `or {}` rather than a chained .get() for that reason.
        crop_timing = crop_context.get("crop_timing_context") or {}
        timing_phase = crop_timing.get("timing_phase")
        classification = classify_stress(
            ndvi,
            ndmi,
            ndre,
            savi,
            gndvi,
            crop_context=crop_context,
)

        stress_type = classification["stress_type"]
        severity = classification["severity"]
        recommendation = classification["recommendation"]
        confidence = classification.get("confidence", "medium")
        title = classification["title"]

        # Same enum handling as stress_type and severity. If the
        # classifier returns an Enum, "confidence" would otherwise
        # serialise as "Confidence.MEDIUM" or fail JSON encoding
        # outright at the report boundary.
        confidence_str = (
            confidence.value
            if hasattr(confidence, "value")
            else str(confidence)
            if confidence is not None
            else "medium"
        )

        # condition_signal is the SAFE user-facing label — the report
        # and frontend should use it rather than the legacy stress_type.
        condition_signal = classification.get("condition_signal")
        # `or []` rather than a default argument: the two-argument form
        # only applies when the key is ABSENT, so a classifier returning
        # possible_causes=None would put None into state and break any
        # downstream iteration.
        possible_causes = classification.get("possible_causes") or []
        corroborating_signals = (
            classification.get("corroborating_signals") or []
        )
        cover_source = classification.get("cover_source")

        # Convert enums to plain strings for JSON serialization
        stress_type_str = (
            stress_type.value
            if hasattr(stress_type, "value")
            else str(stress_type)
        )
        severity_str = (
            severity.value if hasattr(severity, "value") else str(severity)
        )

        # A missing condition_signal defaults to "not_assessed", not
        # None. If an older classifier result or an unexpected path
        # omits this field, the safe failure is "we don't know" rather
        # than falling through to a green all-clear.
        condition_signal_str = (
            condition_signal.value
            if hasattr(condition_signal, "value")
            else str(condition_signal)
            if condition_signal is not None
            else "not_assessed"
        )

        classification_not_assessed = condition_signal_str == "not_assessed"

        # ── Colour indicator ─────────────────────────────────────
        # An unassessable field must NOT get the same green as a field
        # with no warning signal. Severity is "none" in both cases, so
        # the colour has to key on condition_signal as well.
        if classification_not_assessed:
            color = "#94a3b8"  # neutral gray — could not assess
        else:
            color_map = {
                "none": "#22c55e",
                "mild": "#facc15",
                "moderate": "#f97316",
                "severe": "#ef4444",
            }
            color = color_map.get(severity_str, "#94a3b8")

        # Severity -> urgency label.
        # Kept to low/medium/high for schema compatibility. For an
        # unassessed field "low" is not ideal, but the title, summary
        # and gray indicator all make the state clear. Revisit if the
        # schema gains an "unknown" value.
        urgency_map = {
            "none": "low",
            "mild": "low",
            "moderate": "medium",
            "severe": "high",
        }
        urgency = urgency_map.get(severity_str, "medium")

        # ── Scope and spatial availability ───────────────────────
        assessment_scope = state.get("assessment_scope")
        field_noun, rest_noun = _scope_words(assessment_scope)

        attention_area_raw = state.get("attention_area")
        attention_is_distinct = bool(state.get("attention_is_distinct"))

        # Default to a value that classifies as "unavailable" rather than
        # "" which would previously classify as uniform.
        attention_source = state.get("attention_source") or "insufficient_data"
        spatial_status = _spatial_status(attention_source)
        coverage_tier = state.get("coverage_tier")

        # The technically lowest / most distinct zone from GEE, kept
        # regardless of whether it is surfaced to the user — it is
        # needed for manual validation against Earth Engine.
        #
        # But it is NOT kept when the field could not be assessed or the
        # spatial comparison could not be made. A stale zone label in
        # those states would be an unsupported spatial claim.
        #
        # NOTE: gee.py now suppresses attention_area BEFORE it reaches
        # state, so this can only preserve findings that detection
        # itself withholds — chiefly the distinct-but-severity-none
        # case below. A finding suppressed inside gee.py is gone.
        relative_low_area = (
            attention_area_raw
            if (
                not classification_not_assessed
                and spatial_status == "ranked"
                and attention_is_distinct
                and isinstance(attention_area_raw, str)
            )
            else None
        )

        if classification_not_assessed:
            attention_area_desc = None
            hotspot_summary = (
                "Field condition could not be assessed reliably from the "
                "available satellite data."
            )

        elif spatial_status == "unavailable":
            # We could not compare areas within the field. This is NOT a
            # uniformity finding and must not be worded as one. The
            # whole-field reading above is still valid.
            attention_area_desc = None
            hotspot_summary = _unavailable_message(
                attention_source, coverage_tier
            )

        elif (
            attention_is_distinct
            and severity_str != "none"
            and isinstance(attention_area_raw, str)
        ):
            # A zone stands out AND overall condition is concerning.
            #
            # At partial coverage the comparison is between observed
            # parts only. Naming the area without that lead-in reads as
            # though the whole of it was measured, when some of it may
            # have been under cloud.
            attention_area_desc = attention_area_raw

            if assessment_scope == "partial_field":
                hotspot_summary = (
                    f"Among the parts of the field that were reliably "
                    f"observed, vegetation condition is comparatively "
                    f"lower in the {attention_area_desc} than across "
                    f"{rest_noun}."
                )
            else:
                hotspot_summary = (
                    f"Vegetation condition is comparatively lower in "
                    f"the {attention_area_desc} than across {rest_noun}."
                )

        elif attention_is_distinct and severity_str == "none":
            # Spatial variation exists, but nothing crosses the concern
            # threshold. Severity "none" means the classifier's
            # thresholds were not crossed — it does not prove every part
            # of the field is objectively healthy.
            attention_area_desc = None
            hotspot_summary = (
                f"Some spatial variation is visible across {field_noun}, "
                f"but no area currently crosses Tagintell's threshold "
                f"for attention."
            )

        else:
            # Measured and uniform — a real finding, distinct from the
            # unavailable branch above.
            attention_area_desc = None

            if severity_str == "none":
                hotspot_summary = (
                    f"Condition looks consistent across {field_noun}. "
                    f"No single area stands out."
                )
            else:
                hotspot_summary = (
                    f"The lower condition appears fairly evenly "
                    f"distributed across {field_noun} rather than "
                    f"concentrated in one particular area."
                )

        # Copy technical details and extend them.
        # Spatial and interpretive fields are carried through for saved
        # reports and for manual validation against Google Earth Engine.
        technical_details = dict(state.get("technical_details") or {})
        technical_details.update({
            "stress_type": stress_type_str,            # legacy / internal
            "condition_signal": condition_signal_str,  # user-facing
            "confidence": confidence_str,
            "possible_causes": possible_causes,
            "corroborating_signals": corroborating_signals,
            "cover_source": cover_source,

            # Crop / season context. Keys match crop_context.py exactly;
            # anything not listed there would silently be None.
            "has_crop_context": crop_context.get("has_crop_context"),
            "crop_type": crop_context.get("crop_type"),
            "crop_key": crop_context.get("crop_key"),
            "planting_date": crop_context.get("planting_date"),
            "irrigation_type": crop_context.get("irrigation_type"),
            "season_id": crop_context.get("season_id"),
            "crop_observation_date": crop_context.get("observation_date"),
            "days_after_planting": crop_context.get("days_after_planting"),
            "timing_phase": timing_phase,
            "timing_basis": crop_timing.get("timing_basis"),
            "crop_profile_available": crop_timing.get("profile_available"),
            "cover_screen_mode": crop_context.get("cover_screen_mode"),
            "decline_expected": crop_context.get("decline_expected"),
            "crop_context_warnings": crop_context.get("context_warnings"),

            "attention_source": attention_source,
            "attention_is_distinct": attention_is_distinct,
            "spatial_status": spatial_status,
            "assessment_scope_applied": (
                assessment_scope
                if assessment_scope in FIELD_NOUN
                else DEFAULT_SCOPE
            ),
            "relative_low_area": relative_low_area,
            "zone_values": state.get("zone_values") or {},
        })

        return {
            **state,

            # ── Crop / season context ────────────────────────────
            #
            # The full dict plus the values state.py lifts to the top
            # level.
            #
            # decline_expected is THREE-state:
            #
            # True  -> the crop is in its broad late-season calendar
            #          window, where natural maturity or senescence may
            #          contribute to declining vegetation signals
            #
            # False -> the crop is not in that late-season window
            #
            # None  -> no usable timing profile exists, so Tagintell
            #          cannot say
            #
            # This is CONTEXT, not an automatic alert suppressor.
            # Downstream logic must test `is True` / `is False`, never
            # truthiness, and must not treat decline_expected=True as
            # proof that a concerning signal is normal. A field can be
            # both in its late-season window and genuinely failing.
            "crop_context": crop_context,
            "has_crop_context": crop_context.get("has_crop_context"),
            "crop_type": crop_context.get("crop_type"),
            "planting_date": crop_context.get("planting_date"),
            "irrigation_type": crop_context.get("irrigation_type"),
            "season_id": crop_context.get("season_id"),
            "days_after_planting": crop_context.get("days_after_planting"),
            "timing_phase": timing_phase,
            "cover_screen_mode": crop_context.get("cover_screen_mode"),
            "decline_expected": crop_context.get("decline_expected"),

            "title": title,
            "stress_type": stress_type_str,
            "condition_signal": condition_signal_str,
            "severity": severity_str,
            "urgency": urgency,
            "color": color,
            "recommendation": recommendation,
            "possible_causes": possible_causes,
            "corroborating_signals": corroborating_signals,
            "cover_source": cover_source,
            "attention_area": attention_area_desc,
            "attention_is_distinct": attention_is_distinct,
            "relative_low_area": relative_low_area,
            "hotspot_summary": hotspot_summary,
            "technical_details": technical_details,
            "detection_error": None,
            "status": "ok",
            "errors": errors,
        }

    except Exception as exc:
        # Internal detail stays in errors; the farmer gets nothing that
        # describes our architecture. Matches processing_agent, which
        # keeps the same separation.
        internal_msg = f"Detection agent failed: {type(exc).__name__}: {exc}"
        errors.append(internal_msg)
        return {
            **state,
            "detection_error": (
                "Field condition could not be assessed. Please try again."
            ),
            "status": "failed",
            "errors": errors,
        }