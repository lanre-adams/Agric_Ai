from enum import Enum


class StressType(str, Enum):
    """
    Internal condition codes, kept stable for database compatibility.

    The VALUES imply causes (water_stress, nutrient_stress) for legacy
    reasons. Downstream code should prefer condition_signal for anything
    user-facing — a spectral index establishes condition, not cause.
    """

    HEALTHY = "healthy"
    WATER_STRESS = "water_stress"
    NUTRIENT_STRESS = "nutrient_stress"
    GENERAL_STRESS = "general_stress"
    SPARSE_OR_BARE = "sparse_or_bare"
    WATCH = "watch"
    UNKNOWN = "unknown"


class ConditionSignal(str, Enum):
    """
    Safe user-facing description of WHAT was observed.

    Use this for report text and frontend labels. It names the measured
    signal rather than asserting a cause.
    """

    NONE_DETECTED = "no_warning_signal"
    MOISTURE_CONDITION = "moisture_condition"
    CHLOROPHYLL_CONDITION = "chlorophyll_condition"
    VEGETATION_COVER = "vegetation_cover"
    GENERAL_VEGETATION = "general_vegetation_condition"
    EARLY_SIGNAL = "early_signal"
    NOT_ASSESSED = "not_assessed"


class Severity(str, Enum):
    NONE = "none"
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


# ----------------------------------------------------------------------
# Thresholds
# ----------------------------------------------------------------------
#
# PROVISIONAL.
#
# These are absolute cutoffs applied to field-mean index values. They
# are not calibrated by crop, variety, geography or confirmed growth
# stage.
#
# Step 3 deliberately does NOT change these thresholds.
#
# Crop context changes:
#   - which index is used to screen vegetation cover
#   - how findings are explained
#   - which possible causes are most relevant
#   - irrigation-specific scouting advice
#
# It does NOT change the satellite index values themselves.
#
# Because these indices come from one Sentinel-2 observation and share
# spectral information, agreement between them is corroborating evidence,
# not independent confirmation. No branch returns high confidence in the
# current classifier.

SAVI_BARE = 0.20
SAVI_SPARSE = 0.35

NDVI_BARE = 0.25
NDVI_SPARSE = 0.45

NDMI_VERY_LOW = -0.25
NDMI_LOW = -0.10
NDMI_MARGINAL = 0.05

NDRE_VERY_LOW = 0.20
NDRE_LOW = 0.30
NDRE_WATCH = 0.40

NDVI_SATURATION = 0.65
GNDVI_LOW = 0.35
GNDVI_WATCH = 0.45


# Existing classifier behaviour:
#
# Moisture and chlorophyll signals are scored independently and the
# strongest one is reported.
#
# This existed before Step 3 and is NOT being introduced by crop context.
SEVERITY_RANK = {
    None: 0,
    "mild": 1,
    "moderate": 2,
    "severe": 3,
}


# ----------------------------------------------------------------------
# Crop context modes — Step 3
# ----------------------------------------------------------------------
#
# These strings must match crop_context.py exactly.

MODE_LEGACY = "legacy"
MODE_PRE_PLANTING = "pre_planting_context"
MODE_EARLY = "early_stage_context"
MODE_STANDARD = "standard"
MODE_LATE = "late_season_context"

VALID_COVER_MODES = {
    MODE_LEGACY,
    MODE_PRE_PLANTING,
    MODE_EARLY,
    MODE_STANDARD,
    MODE_LATE,
}


# Irrigation keys produced by
# crop_context.normalize_irrigation_type().
IRRIGATED_TYPES = {
    "center_pivot",
    "drip",
    "sprinkler",
    "furrow",
    "flood",
}


# ----------------------------------------------------------------------
# Legacy moisture wording
# ----------------------------------------------------------------------
#
# These helpers preserve the existing pre-Step-3 recommendations and
# possible-cause lists whenever the farmer has NOT supplied relevant
# irrigation/timing context.


def _legacy_moisture_recommendation(level: str) -> str:
    """
    Existing pre-Step-3 moisture recommendations.

    Keeping these in one helper makes the backward-compatibility rule
    explicit: no relevant crop context means the old wording remains.
    """

    if level == "severe":
        return (
            "The moisture-related vegetation signal is very low in this "
            "observation. If this field is irrigated, check for blocked "
            "lines, low pressure or uneven coverage. Inspect plant "
            "condition on the ground before deciding on any action."
        )

    if level == "moderate":
        return (
            "The moisture-related vegetation signal is low in this "
            "observation. If this field is irrigated, check coverage. "
            "Inspect plant condition in the field and monitor over the "
            "next few days."
        )

    return (
        "The moisture-related vegetation signal is slightly below "
        "Tagintell's screening threshold. Worth watching on the next "
        "satellite pass rather than acting on now."
    )


def _legacy_moisture_causes(level: str) -> list:
    """
    Existing pre-Step-3 moisture possible-causes lists.
    """

    if level == "severe":
        return [
            "Insufficient irrigation or rainfall",
            "Irrigation system fault or uneven coverage",
            "Crop at a naturally low-moisture growth stage",
            "Senescence approaching harvest",
        ]

    if level == "moderate":
        return [
            "Reduced soil moisture",
            "Uneven irrigation coverage",
            "Recent dry period",
            "Growth stage change",
        ]

    return [
        "Normal moisture variation",
        "Early-stage moisture limitation",
        "Growth stage change",
    ]


# ----------------------------------------------------------------------
# Crop-aware moisture helpers
# ----------------------------------------------------------------------


def _moisture_recommendation(
    irrigation_type,
    level: str,
) -> str:
    """
    Tailor the NEXT CHECK to a recorded irrigation system.

    This does NOT diagnose water stress.

    Irrigation type changes what the farmer should inspect. It does not
    establish why the satellite signal is low.
    """

    signal_text = {
        "severe": "very low",
        "moderate": "low",
        "mild": "slightly low",
    }.get(level, "low")

    opening = (
        f"The moisture-related vegetation signal is {signal_text} in "
        f"this observation."
    )

    if irrigation_type == "rainfed":
        return (
            f"{opening} This field is recorded as rainfed. Review recent "
            "rainfall and inspect plant and soil conditions before "
            "deciding whether the reading represents a meaningful "
            "moisture problem."
        )

    if irrigation_type == "center_pivot":
        return (
            f"{opening} This field is recorded as center-pivot irrigated. "
            "Check that the pivot has been operating as expected and look "
            "for uneven coverage, blocked nozzles or pressure problems. "
            "Confirm conditions in the field before taking action."
        )

    if irrigation_type == "drip":
        return (
            f"{opening} This field is recorded as drip irrigated. Check "
            "system operation, pressure, blocked emitters and uneven "
            "delivery. Confirm conditions in the field before taking "
            "action."
        )

    if irrigation_type == "sprinkler":
        return (
            f"{opening} This field is recorded as sprinkler irrigated. "
            "Check system operation and whether water application has "
            "been uniform. Confirm conditions in the field before taking "
            "action."
        )

    if irrigation_type in ("furrow", "flood"):
        return (
            f"{opening} This field is recorded as furrow or flood "
            "irrigated. Check whether water has reached the field evenly "
            "and whether some areas may have received too little or too "
            "much. Confirm conditions in the field before taking action."
        )

    if irrigation_type == "other":
        return (
            f"{opening} Review how water has recently reached this field "
            "and inspect plant and soil conditions before deciding on any "
            "irrigation or treatment change."
        )

    # Defensive fallback. Normally None/unknown uses the legacy helper
    # instead, but this keeps the function safe if another value arrives.
    return _legacy_moisture_recommendation(level)


def _moisture_possible_causes(
    level: str,
    irrigation_type=None,
    decline_expected=None,
) -> list:
    """
    Start with the existing possible-cause list, then use ONLY context the
    farmer actually supplied to make it more relevant.

    No context -> legacy list remains unchanged.

    decline_expected uses `is True` deliberately because the value is
    three-state:
        True  = broad late-season window
        False = not late season
        None  = Tagintell cannot determine it
    """

    causes = list(_legacy_moisture_causes(level))

    if irrigation_type == "rainfed":
        # Remove irrigation-system explanations that cannot apply to a
        # field explicitly recorded as rainfed.
        causes = [
            cause
            for cause in causes
            if "irrigation" not in cause.lower()
        ]

        if "Limited recent rainfall" not in causes:
            causes.insert(0, "Limited recent rainfall")

    elif irrigation_type in IRRIGATED_TYPES:
        irrigation_cause = (
            "Uneven irrigation delivery or system performance"
        )

        # The severe/moderate legacy lists already contain an irrigation
        # explanation. Mild does not, so add one only when irrigation is
        # actually known.
        if not any(
            "irrigation" in cause.lower()
            for cause in causes
        ):
            causes.insert(1, irrigation_cause)

    if decline_expected is True:
        late_cause = "Natural maturity or senescence near harvest"

        if late_cause not in causes:
            causes.insert(0, late_cause)

    return causes


# ----------------------------------------------------------------------
# Cover / timing wording
# ----------------------------------------------------------------------


def _cover_context_note(
    cover_screen_mode,
    days_after_planting,
) -> str:
    """
    Add timing context to vegetation-cover findings.

    Calendar timing is broad context, not confirmed phenology.
    """

    if cover_screen_mode == MODE_EARLY:
        dap = (
            f" ({days_after_planting} days after planting for this "
            f"observation)"
            if days_after_planting is not None
            else ""
        )

        return (
            f" This observation falls within the crop's early "
            f"establishment period{dap}, when low or thin vegetation "
            f"cover can be normal while plants are establishing. Check "
            f"emergence and stand uniformity if parts of the field appear "
            f"delayed."
        )

    if cover_screen_mode == MODE_LATE:
        return (
            " This observation falls within the crop's broad late-season "
            "calendar window, when natural maturity, senescence, dry-down "
            "or harvest may reduce vegetation cover. Confirm what has "
            "happened in the field before interpreting reduced cover as "
            "a developing problem."
        )

    return ""


def _late_season_note(decline_expected) -> str:
    """
    Context for a condition signal during the broad late-season window.

    This NEVER suppresses the finding or reduces its severity.
    """

    if decline_expected is True:
        return (
            " This observation falls within the crop's broad late-season "
            "calendar window, so natural maturity or senescence may be "
            "contributing to this reading. This timing context does not "
            "by itself show that the signal is normal."
        )

    return ""


# ----------------------------------------------------------------------
# Classifier
# ----------------------------------------------------------------------


def classify_stress(
    ndvi: float,
    ndmi: float,
    ndre: float,
    savi: float = None,
    gndvi: float = None,
    crop_context: dict = None,
):
    """
    Classify field condition using rule-based logic.

    Existing decision structure:
        1. Data sufficiency
        2. Crop timing guard
        3. Bare / no vegetation cover
        4. Sparse vegetation cover
        5. Score moisture and chlorophyll signals independently
        6. Report the strongest signal
        7. NDVI fallback
        8. No warning signal

    ------------------------------------------------------------------
    STEP 3 BACKWARD-COMPATIBILITY CONTRACT
    ------------------------------------------------------------------

    crop_context is OPTIONAL.

    When no crop information exists:
        cover_screen_mode = "legacy"

    The classifier then preserves the existing Farm Watch behaviour:
        - same thresholds
        - same SAVI-first cover screening
        - same strongest-signal logic
        - same severities
        - same titles
        - same legacy recommendations
        - same legacy possible-cause lists

    Step 3 does NOT modify any satellite value or threshold.

    ------------------------------------------------------------------
    WHAT CROP CONTEXT CAN CHANGE
    ------------------------------------------------------------------

    When relevant context exists, it may change:

        1. Which index screens vegetation cover.

           legacy:
               SAVI first, NDVI fallback

           early establishment:
               SAVI first

           main growth:
               NDVI first

           late season:
               NDVI first

        2. The explanation of low vegetation cover.

        3. Moisture scouting advice when irrigation type is known.

        4. Possible causes when late-season timing or irrigation type
           makes some explanations more relevant.

    ------------------------------------------------------------------
    WHAT CROP CONTEXT CANNOT DO
    ------------------------------------------------------------------

    It does NOT:
        - change thresholds
        - change GEE calculations
        - change index values
        - automatically lower severity
        - suppress a warning because decline_expected=True
        - claim calendar timing is a measured crop growth stage

    Every returned dictionary includes:
        possible_causes
        corroborating_signals
        cover_source
        cover_screen_mode_applied
    """

    # ------------------------------------------------------------------
    # Step 1 — data sufficiency
    # ------------------------------------------------------------------

    available = [
        value
        for value in (
            ndvi,
            ndmi,
            ndre,
            savi,
            gndvi,
        )
        if value is not None
    ]

    if len(available) < 2 or (
        ndre is None
        and ndvi is None
    ):
        return {
            "stress_type": StressType.UNKNOWN,
            "condition_signal": ConditionSignal.NOT_ASSESSED,
            "corroborating_signals": [],
            "cover_source": None,
            "cover_screen_mode_applied": None,
            "severity": Severity.NONE,
            "title": "Condition could not be assessed",
            "recommendation": (
                "There was not enough usable satellite data to assess "
                "this field. This usually resolves after the next clear "
                "satellite pass."
            ),
            "possible_causes": [],
            "confidence": "none",
        }

    # ------------------------------------------------------------------
    # Step 2 — crop / season context
    # ------------------------------------------------------------------

    context = crop_context or {}

    cover_screen_mode = (
        context.get("cover_screen_mode")
        or MODE_LEGACY
    )

    # Unexpected future/invalid values fail safely back to the legacy
    # cover-screening path rather than silently inventing new behaviour.
    if cover_screen_mode not in VALID_COVER_MODES:
        cover_screen_mode = MODE_LEGACY

    days_after_planting = context.get(
        "days_after_planting"
    )

    decline_expected = context.get(
        "decline_expected"
    )

    irrigation_type = context.get(
        "irrigation_type"
    )

    # A satellite observation before the farmer's recorded planting date
    # cannot describe the condition of the current crop.
    if cover_screen_mode == MODE_PRE_PLANTING:
        return {
            "stress_type": StressType.UNKNOWN,
            "condition_signal": ConditionSignal.NOT_ASSESSED,
            "corroborating_signals": [],
            "cover_source": None,
            "cover_screen_mode_applied": cover_screen_mode,
            "severity": Severity.NONE,
            "title": "Observation predates planting",
            "recommendation": (
                "The satellite observation used for this analysis was "
                "taken before the recorded planting date, so it cannot "
                "be used to judge the condition of the current crop. "
                "Run the analysis again once a satellite observation "
                "from after planting is available."
            ),
            "possible_causes": [],
            "confidence": "none",
        }

    # ------------------------------------------------------------------
    # Supporting signal checks
    # ------------------------------------------------------------------

    ndvi_saturated = (
        ndvi is not None
        and ndre is not None
        and ndvi > NDVI_SATURATION
        and ndre < NDRE_LOW
    )

    # ------------------------------------------------------------------
    # Step 3 — choose the vegetation-cover screen
    # ------------------------------------------------------------------
    #
    # LEGACY:
    #     Exact pre-Step-3 behaviour:
    #     SAVI when present, otherwise NDVI.
    #
    # EARLY:
    #     SAVI remains preferred because exposed soil still strongly
    #     influences the observation.
    #
    # STANDARD / LATE:
    #     NDVI is used first once the broad crop calendar says canopy
    #     should normally be established.
    #
    # Threshold values themselves are NOT changed.

    if cover_screen_mode in (
        MODE_LEGACY,
        MODE_EARLY,
    ):
        prefer_savi = savi is not None
    else:
        prefer_savi = False

    if prefer_savi and savi is not None:
        cover_source = "savi"
        is_bare = savi < SAVI_BARE
        is_sparse = savi < SAVI_SPARSE

    elif ndvi is not None:
        cover_source = "ndvi"
        is_bare = ndvi < NDVI_BARE
        is_sparse = ndvi < NDVI_SPARSE

    elif savi is not None:
        # Defensive fallback if NDVI alone is unavailable.
        cover_source = "savi"
        is_bare = savi < SAVI_BARE
        is_sparse = savi < SAVI_SPARSE

    else:
        cover_source = None
        is_bare = False
        is_sparse = False

    cover_note = _cover_context_note(
        cover_screen_mode,
        days_after_planting,
    )

    # ------------------------------------------------------------------
    # Corroborating signals
    # ------------------------------------------------------------------
    #
    # These indicators come from the same observation and share spectral
    # information. Agreement supports a finding but does not represent
    # independent confirmation.

    corroborating = []

    if (
        ndmi is not None
        and ndmi < NDMI_MARGINAL
    ):
        corroborating.append(
            "moisture_condition"
        )

    if (
        ndre is not None
        and ndre < 0.25
    ):
        corroborating.append(
            "chlorophyll_condition"
        )

    if (
        gndvi is not None
        and gndvi < GNDVI_LOW
    ):
        corroborating.append(
            "supporting_vegetation_signal"
        )

    if ndvi_saturated:
        corroborating.append(
            "dense_canopy_masking"
        )

    def others(primary):
        """
        Return corroborating signals except the primary one being
        reported.
        """
        return [
            signal
            for signal in corroborating
            if signal != primary
        ]

    # ------------------------------------------------------------------
    # Step 4 — very low vegetation cover
    # ------------------------------------------------------------------

    if is_bare:
        causes = [
            "Field recently harvested",
            "Crop not yet emerged",
            "Field left fallow",
            "Poor establishment or crop failure",
            "Standing water or flooding",
        ]

        if cover_screen_mode == MODE_EARLY:
            causes = [
                "Crop not yet emerged",
                "Poor establishment",
                "Recent replanting",
                "Standing water or flooding",
            ]

        elif cover_screen_mode == MODE_LATE:
            causes = [
                "Field recently harvested",
                "Natural dry-down or senescence near harvest",
                "Crop failure earlier in the season",
                "Standing water or flooding",
            ]

        recommendation = (
            "Very little living vegetation was detected across this "
            "field. If the field has been harvested or is not yet "
            "emerged, this is expected. If a crop should be growing "
            "here, inspect the field to confirm what is happening."
        )

        recommendation += cover_note

        return {
            "stress_type": StressType.SPARSE_OR_BARE,
            "condition_signal": ConditionSignal.VEGETATION_COVER,

            # Deliberately empty. At low cover the crop-condition
            # indices are distorted by soil background, so they cannot
            # corroborate a cover finding — that is the reason this
            # branch runs before them.
            "corroborating_signals": [],

            "cover_source": cover_source,
            "cover_screen_mode_applied": cover_screen_mode,
            "severity": Severity.MILD,
            "title": "Very low vegetation cover",
            "recommendation": recommendation,
            "possible_causes": causes,
            "confidence": "medium",
        }

    # ------------------------------------------------------------------
    # Step 5 — thin / sparse vegetation cover
    # ------------------------------------------------------------------

    if is_sparse:
        causes = [
            "Early growth stage before canopy closure",
            "Uneven stand establishment",
            "Wide row spacing",
            "Recent replanting",
            "Reduced vegetation cover",
        ]

        if cover_screen_mode == MODE_LATE:
            causes = [
                "Natural leaf loss or dry-down near harvest",
                "Partial harvest",
                "Uneven stand establishment",
                "Reduced vegetation cover",
            ]

        recommendation = (
            "Vegetation cover is currently thin, which limits how "
            "confidently crop-condition signals can be interpreted. "
            "This may be normal for an early growth stage or a recently "
            "established crop. Check stand establishment if the crop "
            "should be further along."
        )

        recommendation += cover_note

        return {
            "stress_type": StressType.SPARSE_OR_BARE,
            "condition_signal": ConditionSignal.VEGETATION_COVER,

            # Deliberately empty. At low cover the crop-condition
            # indices are distorted by soil background, so they cannot
            # corroborate a cover finding — that is the reason this
            # branch runs before them.
            "corroborating_signals": [],

            "cover_source": cover_source,
            "cover_screen_mode_applied": cover_screen_mode,
            "severity": Severity.MILD,
            "title": "Vegetation cover is thin",
            "recommendation": recommendation,
            "possible_causes": causes,
            "confidence": "medium",
        }

    # ------------------------------------------------------------------
    # Step 6 — score moisture and chlorophyll independently
    # ------------------------------------------------------------------
    #
    # This strongest-signal behaviour already existed before Step 3.
    # Crop context does not change it.

    moisture_level = None

    if ndmi is not None:
        if ndmi < NDMI_VERY_LOW:
            moisture_level = "severe"

        elif ndmi < NDMI_LOW:
            moisture_level = "moderate"

        elif ndmi < NDMI_MARGINAL:
            moisture_level = "mild"

    chlorophyll_level = None

    if ndre is not None:
        if ndre < NDRE_VERY_LOW:
            chlorophyll_level = "severe"

        elif ndre < NDRE_LOW:
            chlorophyll_level = "moderate"

        elif ndre < NDRE_WATCH:
            chlorophyll_level = "mild"

    moisture_rank = SEVERITY_RANK[
        moisture_level
    ]

    chlorophyll_rank = SEVERITY_RANK[
        chlorophyll_level
    ]

    late_note = _late_season_note(
        decline_expected
    )

    # ------------------------------------------------------------------
    # Step 7 — strongest chlorophyll / crop-condition signal
    # ------------------------------------------------------------------
    #
    # On a tie, chlorophyll keeps the existing priority.

    if (
        chlorophyll_rank > 0
        and chlorophyll_rank >= moisture_rank
    ):

        if chlorophyll_level == "severe":
            causes = [
                "Nutrient deficiency, particularly nitrogen",
                "Disease or pest pressure",
                "Root damage or waterlogging",
                "Early growth stage",
                "Crop variety with naturally lower readings",
            ]

            if decline_expected is True:
                causes.insert(
                    0,
                    "Natural maturity or senescence near harvest",
                )

            recommendation = (
                "The crop condition signal is very low across this "
                "field. Arrange a field inspection soon. Check crop "
                "colour, growth pattern, and recent fertiliser and "
                "irrigation history. Soil or tissue testing may be "
                "needed to identify the cause before any treatment."
            )

            recommendation += late_note

            return {
                "stress_type": StressType.NUTRIENT_STRESS,
                "condition_signal": (
                    ConditionSignal.CHLOROPHYLL_CONDITION
                ),
                "corroborating_signals": others(
                    "chlorophyll_condition"
                ),
                "cover_source": cover_source,
                "cover_screen_mode_applied": cover_screen_mode,
                "severity": Severity.SEVERE,
                "title": "Crop condition signal is very low",
                "recommendation": recommendation,
                "possible_causes": causes,
                "confidence": "medium",
            }

        if chlorophyll_level == "moderate":
            note = (
                " This may not yet be visible in standard crop "
                "greenness views."
                if ndvi_saturated
                else ""
            )

            # Existing pre-Step-3 possible causes.
            causes = [
                "Nutrient limitation",
                "Uneven fertiliser coverage",
                "Early disease or pest pressure",
                "Growth stage variation",
                "Soil variability",
            ]

            if decline_expected is True:
                causes.insert(
                    0,
                    "Natural maturity or senescence near harvest",
                )

            recommendation = (
                f"The crop condition signal is below Tagintell's "
                f"current screening threshold.{note} Inspect the field "
                "and review recent fertiliser, watering and field "
                "conditions. If the signal continues to decline, soil "
                "or tissue testing would help identify the cause."
            )

            recommendation += late_note

            return {
                "stress_type": StressType.NUTRIENT_STRESS,
                "condition_signal": (
                    ConditionSignal.CHLOROPHYLL_CONDITION
                ),
                "corroborating_signals": others(
                    "chlorophyll_condition"
                ),
                "cover_source": cover_source,
                "cover_screen_mode_applied": cover_screen_mode,
                "severity": Severity.MODERATE,
                "title": "Crop condition signal is low",
                "recommendation": recommendation,
                "possible_causes": causes,
                "confidence": "medium",
            }

        # Mild chlorophyll signal.
        causes = [
            "Early-stage condition change",
            "Normal growth stage variation",
            "Minor nutrient or moisture limitation",
        ]

        if decline_expected is True:
            causes.insert(
                0,
                "Natural maturity or senescence near harvest",
            )

        recommendation = (
            "An early signal is present that is worth watching. The "
            "crop may still look normal on the ground. Check the field "
            "when convenient and watch whether this signal holds or "
            "strengthens on the next satellite pass."
        )

        recommendation += late_note

        return {
            "stress_type": StressType.WATCH,
            "condition_signal": ConditionSignal.EARLY_SIGNAL,
            "corroborating_signals": others(
                "chlorophyll_condition"
            ),
            "cover_source": cover_source,
            "cover_screen_mode_applied": cover_screen_mode,
            "severity": Severity.MILD,
            "title": "Early signal worth watching",
            "recommendation": recommendation,
            "possible_causes": causes,
            "confidence": "medium",
        }

    # ------------------------------------------------------------------
    # Step 8 — strongest moisture signal
    # ------------------------------------------------------------------

    if moisture_rank > 0:

        # If the farmer actually supplied irrigation information, the
        # recommendation can safely become irrigation-specific.
        #
        # If irrigation_type is None, keep the existing recommendation
        # exactly rather than changing a legacy farm's wording simply
        # because Step 3 exists.

        if irrigation_type is not None:
            recommendation = _moisture_recommendation(
                irrigation_type,
                moisture_level,
            )

        else:
            recommendation = _legacy_moisture_recommendation(
                moisture_level
            )

        recommendation += late_note

        causes = _moisture_possible_causes(
            level=moisture_level,
            irrigation_type=irrigation_type,
            decline_expected=decline_expected,
        )

        if moisture_level == "severe":
            return {
                "stress_type": StressType.WATER_STRESS,
                "condition_signal": (
                    ConditionSignal.MOISTURE_CONDITION
                ),
                "corroborating_signals": others(
                    "moisture_condition"
                ),
                "cover_source": cover_source,
                "cover_screen_mode_applied": cover_screen_mode,
                "severity": Severity.SEVERE,
                "title": (
                    "Moisture-related vegetation signal is very low"
                ),
                "recommendation": recommendation,
                "possible_causes": causes,
                "confidence": "medium",
            }

        if moisture_level == "moderate":
            return {
                "stress_type": StressType.WATER_STRESS,
                "condition_signal": (
                    ConditionSignal.MOISTURE_CONDITION
                ),
                "corroborating_signals": others(
                    "moisture_condition"
                ),
                "cover_source": cover_source,
                "cover_screen_mode_applied": cover_screen_mode,
                "severity": Severity.MODERATE,
                "title": (
                    "Moisture-related vegetation signal is low"
                ),
                "recommendation": recommendation,
                "possible_causes": causes,
                "confidence": "medium",
            }

        # Mild moisture signal.
        return {
            "stress_type": StressType.WATCH,
            "condition_signal": (
                ConditionSignal.MOISTURE_CONDITION
            ),
            "corroborating_signals": others(
                "moisture_condition"
            ),
            "cover_source": cover_source,
            "cover_screen_mode_applied": cover_screen_mode,
            "severity": Severity.MILD,
            "title": "Moisture signal is slightly low",
            "recommendation": recommendation,
            "possible_causes": causes,
            "confidence": "medium",
        }

    # ------------------------------------------------------------------
    # Step 9 — NDVI fallback
    # ------------------------------------------------------------------

    if (
        ndvi is not None
        and ndvi < NDVI_SPARSE
    ):
        causes = [
            "Pest or disease pressure",
            "Drainage or waterlogging",
            "Soil limitation",
            "Uneven establishment",
            "Growth stage",
        ]

        if decline_expected is True:
            causes.insert(
                0,
                "Natural maturity or senescence near harvest",
            )

        recommendation = (
            "The overall vegetation signal is below Tagintell's "
            "current screening threshold. Inspect for pests, disease, "
            "drainage problems, soil issues or uneven growth."
        )

        recommendation += late_note

        return {
            "stress_type": StressType.GENERAL_STRESS,
            "condition_signal": (
                ConditionSignal.GENERAL_VEGETATION
            ),
            "corroborating_signals": others(
                "general_vegetation_condition"
            ),
            "cover_source": cover_source,
            "cover_screen_mode_applied": cover_screen_mode,
            "severity": Severity.MODERATE,
            "title": "General vegetation signal is low",
            "recommendation": recommendation,
            "possible_causes": causes,
            "confidence": "medium",
        }

    # ------------------------------------------------------------------
    # Step 10 — no warning signal
    # ------------------------------------------------------------------
    #
    # This does not prove the crop is healthy. It means none of the
    # currently screened indicators crossed the concern thresholds.

    return {
        "stress_type": StressType.HEALTHY,
        "condition_signal": ConditionSignal.NONE_DETECTED,
        "corroborating_signals": [],
        "cover_source": cover_source,
        "cover_screen_mode_applied": cover_screen_mode,
        "severity": Severity.NONE,
        "title": "No strong warning signal detected",
        "recommendation": (
            "No strong vegetation-condition warning signal was detected "
            "in this observation. Continue regular monitoring."
        ),
        "possible_causes": [],
        "confidence": "medium",
    }