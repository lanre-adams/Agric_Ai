"""
Tagintell Farm Watch — optional crop context.

This module adds agronomic timing context WITHOUT changing the
existing satellite analysis.

Important design rules:
    1. Crop context is optional.
    2. Missing crop information must never block Farm Watch analysis.
    3. gee.py remains responsible only for satellite measurement.
    4. This module does not diagnose crop problems.
    5. Growth timing is calendar context, not confirmed phenology.
    6. Days after planting are calculated against the ACTUAL Sentinel-2
       observation date used for the report, not today's date.
    7. SAVI/NDVI thresholds are NOT changed here. This module only tells
       downstream classification whether the observation is early,
       main-season, late-season, or unknown.
"""

from datetime import date, datetime
import re
from typing import Any, Dict, Optional


# ------------------------------------------------------------------
# Crop aliases
# ------------------------------------------------------------------

# Canonical crop keys are used internally for timing logic.
# The original crop name supplied by the user is still preserved.
CROP_ALIASES = {
    "corn": "corn",
    "maize": "corn",

    "soybean": "soybean",
    "soybeans": "soybean",
    "soy": "soybean",

    "wheat": "wheat",

    "rice": "rice",

    "sorghum": "sorghum",

    "millet": "millet",

    "cotton": "cotton",

    "cowpea": "cowpea",
    "cowpeas": "cowpea",

    "cassava": "cassava",
}


# ------------------------------------------------------------------
# Irrigation aliases
# ------------------------------------------------------------------

IRRIGATION_ALIASES = {
    "rainfed": "rainfed",
    "rain fed": "rainfed",
    "rain-fed": "rainfed",

    "center pivot": "center_pivot",
    "centre pivot": "center_pivot",
    "pivot": "center_pivot",

    "drip": "drip",
    "drip irrigation": "drip",

    "sprinkler": "sprinkler",
    "sprinkler irrigation": "sprinkler",

    "furrow": "furrow",
    "furrow irrigation": "furrow",

    "flood": "flood",
    "flood irrigation": "flood",

    "other": "other",
}


# ------------------------------------------------------------------
# Provisional crop timing profiles
# ------------------------------------------------------------------

# These are deliberately BROAD calendar windows.
#
# They do NOT attempt to assign precise phenological stages such as
# V6, R1, flowering, grain fill, etc. Variety, climate, planting
# conditions, geography and management can shift those stages.
#
# The only purpose here is to answer two safer questions:
#
#   1. Is low vegetation cover reasonably possible because the crop is
#      still establishing?
#
#   2. Is natural seasonal decline/senescence reasonably possible
#      because the crop is late in its normal season?
#
# These values are provisional engineering context and should later be
# validated/calibrated by crop, region and field observations.

CROP_TIMING_PROFILES = {
    "corn": {
        "canopy_expected_from_dap": 50,
        "late_season_from_dap": 125,
    },
    "soybean": {
        "canopy_expected_from_dap": 50,
        "late_season_from_dap": 115,
    },
    "wheat": {
        # Spring wheat. Winter wheat spans dormancy and this calendar
        # model cannot represent it; treat wheat timing as indicative.
        "canopy_expected_from_dap": 60,
        "late_season_from_dap": 200,
    },
    "rice": {
        "canopy_expected_from_dap": 45,
        "late_season_from_dap": 105,
    },
    "sorghum": {
        "canopy_expected_from_dap": 50,
        "late_season_from_dap": 110,
    },
    "millet": {
        "canopy_expected_from_dap": 35,
        "late_season_from_dap": 80,
    },
    "cotton": {
        "canopy_expected_from_dap": 60,
        "late_season_from_dap": 150,
    },
    "cowpea": {
        "canopy_expected_from_dap": 30,
        "late_season_from_dap": 70,
    },
    "cassava": {
        "canopy_expected_from_dap": 90,
        "late_season_from_dap": 280,
    },
}


# ------------------------------------------------------------------
# Basic helpers
# ------------------------------------------------------------------

def _clean_text(value: Any) -> Optional[str]:
    """
    Return a stripped string or None.

    Empty strings from optional frontend fields should behave exactly
    like missing values.
    """
    if value is None:
        return None

    text = str(value).strip()

    return text if text else None


def _slugify(value: str) -> str:
    """
    Safe deterministic identifier component.
    """
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _parse_date(value: Any) -> Optional[date]:
    """
    Accept:
        - datetime.date
        - datetime.datetime
        - YYYY-MM-DD
        - ISO datetime strings

    Returns None rather than raising because optional crop context must
    never crash the existing Farm Watch analysis path.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = _clean_text(value)

    if not text:
        return None

    # Normal YYYY-MM-DD input.
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    # Also tolerate ISO timestamps if one reaches this layer.
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).date()
    except ValueError:
        return None


# ------------------------------------------------------------------
# Normalisation
# ------------------------------------------------------------------

def normalize_crop_key(crop_type: Any) -> Optional[str]:
    """
    Convert known crop names to a stable internal crop key.

    Unknown crops are preserved as a safe slug rather than rejected.
    That means Tagintell can still store/display the user's crop even
    when no timing profile exists yet.
    """
    crop = _clean_text(crop_type)

    if not crop:
        return None

    lookup = crop.lower().strip()

    return CROP_ALIASES.get(lookup, _slugify(lookup))


def normalize_irrigation_type(irrigation_type: Any) -> Optional[str]:
    """
    Normalize common irrigation descriptions.

    Unknown irrigation types are preserved as a slug rather than
    rejected because irrigation context is optional.
    """
    irrigation = _clean_text(irrigation_type)

    if not irrigation:
        return None

    lookup = irrigation.lower().strip()

    return IRRIGATION_ALIASES.get(
        lookup,
        _slugify(lookup).replace("-", "_"),
    )


# ------------------------------------------------------------------
# Season identifier
# ------------------------------------------------------------------

def build_season_id(
    supplied_season_id: Any = None,
    crop_key: Optional[str] = None,
    planting_date: Optional[date] = None,
) -> Optional[str]:
    """
    Preserve a supplied season ID when one exists.

    Otherwise generate a deterministic season ID when planting date is
    available.

    Examples:
        corn-20260420
        soybean-20260503
        season-20260420

    The farm ID will later provide the field-specific scope, so the
    generated season ID does not need to contain a farm identifier.
    """
    supplied = _clean_text(supplied_season_id)

    if supplied:
        return supplied

    if planting_date is None:
        return None

    prefix = crop_key or "season"

    return f"{_slugify(prefix)}-{planting_date.strftime('%Y%m%d')}"


# ------------------------------------------------------------------
# Days after planting
# ------------------------------------------------------------------

def calculate_days_after_planting(
    planting_date: Any,
    observation_date: Any,
) -> Optional[int]:
    """
    Calculate DAP against the satellite observation date.

    IMPORTANT:
        Do not calculate against datetime.now().

    The selected Sentinel-2 observation may be several days older than
    the day the user presses Analyze. Crop timing must describe the crop
    when the satellite actually observed it.
    """
    planted = _parse_date(planting_date)
    observed = _parse_date(observation_date)

    if planted is None or observed is None:
        return None

    return (observed - planted).days


# ------------------------------------------------------------------
# Crop timing
# ------------------------------------------------------------------

def get_crop_timing_context(
    crop_key: Optional[str],
    days_after_planting: Optional[int],
) -> Optional[Dict[str, Any]]:
    """
    Convert crop + DAP into broad timing context.

    This is intentionally NOT a precise crop growth-stage model.

    Returned timing phases:
        pre_planting
        establishment
        main_growth
        late_season
        unknown
    """
    if days_after_planting is None:
        return None

    # Observation occurred before the reported planting date.
    # This is valid context, not an application error.
    if days_after_planting < 0:
        return {
            "timing_phase": "pre_planting",
            "timing_basis": "planting_date_vs_observation_date",
            "cover_screen_mode": "pre_planting_context",
            "decline_expected": False,
            "profile_available": crop_key in CROP_TIMING_PROFILES,
        }

    profile = CROP_TIMING_PROFILES.get(crop_key)

    if profile is None:
        return {
            "timing_phase": "unknown",
            "timing_basis": "planting_date_only",
            "cover_screen_mode": "legacy",
            "decline_expected": None,
            "profile_available": False,
        }

    canopy_from = profile["canopy_expected_from_dap"]
    late_from = profile["late_season_from_dap"]

    if days_after_planting < canopy_from:
        return {
            "timing_phase": "establishment",
            "timing_basis": "crop_calendar_profile",
            "cover_screen_mode": "early_stage_context",
            "decline_expected": False,
            "profile_available": True,
            "canopy_expected_from_dap": canopy_from,
            "late_season_from_dap": late_from,
        }

    if days_after_planting < late_from:
        return {
            "timing_phase": "main_growth",
            "timing_basis": "crop_calendar_profile",
            "cover_screen_mode": "standard",
            "decline_expected": False,
            "profile_available": True,
            "canopy_expected_from_dap": canopy_from,
            "late_season_from_dap": late_from,
        }

    return {
        "timing_phase": "late_season",
        "timing_basis": "crop_calendar_profile",
        "cover_screen_mode": "late_season_context",
        "decline_expected": True,
        "profile_available": True,
        "canopy_expected_from_dap": canopy_from,
        "late_season_from_dap": late_from,
    }


# ------------------------------------------------------------------
# Main public helper
# ------------------------------------------------------------------

def build_crop_context(
    crop_type: Any = None,
    planting_date: Any = None,
    irrigation_type: Any = None,
    season_id: Any = None,
    observation_date: Any = None,
) -> Dict[str, Any]:
    """
    Build optional crop context for one Farm Watch observation.

    When ALL crop fields are absent, this deliberately returns legacy
    mode. Downstream code can therefore leave the existing Farm Watch
    classifier completely unchanged.

    Nothing in this function should prevent satellite analysis from
    completing.
    """
    warnings = []

    crop_type_clean = _clean_text(crop_type)
    crop_key = normalize_crop_key(crop_type_clean)

    irrigation = normalize_irrigation_type(irrigation_type)

    planting = _parse_date(planting_date)
    observation = _parse_date(observation_date)

    if _clean_text(planting_date) and planting is None:
        warnings.append("invalid_planting_date")

    if _clean_text(observation_date) and observation is None:
        warnings.append("invalid_observation_date")

    dap = calculate_days_after_planting(
        planting,
        observation,
    )

    timing = get_crop_timing_context(
        crop_key=crop_key,
        days_after_planting=dap,
    )

    if (
        crop_key is not None
        and crop_key not in CROP_TIMING_PROFILES
        and dap is not None
    ):
        warnings.append("no_timing_profile_for_crop")

    resolved_season_id = build_season_id(
        supplied_season_id=season_id,
        crop_key=crop_key,
        planting_date=planting,
    )

    has_crop_context = any(
        value is not None
        for value in (
            crop_type_clean,
            planting,
            irrigation,
            _clean_text(season_id),
        )
    )

    if timing is None:
        cover_screen_mode = "legacy"
        decline_expected = None
    else:
        cover_screen_mode = timing.get(
            "cover_screen_mode",
            "legacy",
        )
        decline_expected = timing.get("decline_expected")

    return {
        "has_crop_context": has_crop_context,

        # User/context fields
        "crop_type": crop_type_clean,
        "crop_key": crop_key,
        "planting_date": (
            planting.isoformat()
            if planting is not None
            else None
        ),
        "irrigation_type": irrigation,
        "season_id": resolved_season_id,

        # Observation timing
        "observation_date": (
            observation.isoformat()
            if observation is not None
            else None
        ),
        "days_after_planting": dap,

        # Derived agronomic context
        "crop_timing_context": timing,
        "cover_screen_mode": cover_screen_mode,
        "decline_expected": decline_expected,

        # Non-fatal context issues
        "context_warnings": warnings,
    }