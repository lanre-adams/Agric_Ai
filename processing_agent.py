from app.services.agents.state import FarmWatchState
from app.services.satelite.gee import calculate_all_indices_for_polygon


# ----------------------------------------------------------------------
# Contract maps
# ----------------------------------------------------------------------
# gee.py and state.py deliberately use the SAME name for the same thing,
# so most of this agent is a copy. Doing that copy from an explicit list
# rather than a dozen hand-written assignments means the next contract
# change is a one-line edit here, and a mistyped key fails visibly in the
# guard below instead of becoming a silent None three agents later.

# Top-level gee_result keys that map 1:1 onto state keys.
GEE_PASSTHROUGH_KEYS = (
    # Scope — must reach state or the report can overclaim
    "assessment_scope",
    "assessment_scope_message",

    # Coverage, both geometries
    "field_coverage",
    "analysis_coverage",
    "field_coverage_tier",
    "analysis_coverage_tier",
    "analysis_geometry",

    # Spatial distribution and zone support
    "spatial_coverage",
    "zone_analysis_supported",
    "eligible_zone_count",
    "min_zones_for_analysis",

    # Same-date relative variation map
    "variation_map_url",
    "variation_map_bounds",
    "variation_map_info",

    # Spatial zone analysis
    "attention_area",
    "attention_source",
    "attention_is_distinct",
    "attention_rule",
    "zone_values",
    "zone_pixel_counts",

    # Area and location
    "farm_area",
    "area_ha",
    "area_acres",
    "center",

    # Legacy support block
    "recent_comparison",
)

# Keys that must EXIST in the gee_result, checked by presence rather than
# truthiness. GEE v2 guarantees all of them, and every one has a valid
# falsy value:
#
#   attention_is_distinct = False   a field with no distinct weak zone
#   zone_analysis_supported = False a small field, permanently
#   zone_values = {}                nothing survived the clear-fraction gate
#
# `if not value` would reject all three as failures. `key not in result`
# is the only test that separates "GEE said no" from "GEE said nothing".
#
# There are deliberately NO defaults for these. A default would convert a
# broken Processing/GEE contract into a plausible-looking result: if
# attention_is_distinct went missing, defaulting it to False makes
# detection conclude "no distinct area" when the truth is "the pipeline
# is out of step". That is the exact silent failure this file exists to
# prevent.
REQUIRED_TOP_LEVEL_KEYS = (
    "attention_source",
    "attention_is_distinct",
    "zone_analysis_supported",
    "zone_values",
    "zone_pixel_counts",
    "field_coverage_tier",
    "analysis_coverage_tier",
)

# Closed value sets. These gate downstream behaviour, so an unrecognised
# value is a contract break rather than a variation to tolerate.
# "unknown" is absent on purpose: gee.py raises before returning a
# completed analysis, so it can never reach here.
VALID_ASSESSMENT_SCOPES = {
    "whole_field",
    "partial_field",
    "local_only",
}

VALID_COVERAGE_TIERS = {
    "full",
    "partial",
    "insufficient",
}

COVERAGE_TIER_KEYS = (
    "coverage_tier",
    "field_coverage_tier",
    "analysis_coverage_tier",
)

BOOLEAN_CONTRACT_KEYS = (
    "attention_is_distinct",
    "zone_analysis_supported",
)

MAPPING_CONTRACT_KEYS = (
    "zone_values",
    "zone_pixel_counts",
)

VARIATION_BOUND_KEYS = {"west", "south", "east", "north"}

# state key -> image_info key. These live inside image_info in the gee.py
# payload but are lifted to the top level of state for convenience.
IMAGE_INFO_TO_STATE = {
    "image_date": "date",
    "image_id": "image_id",
    "source_image_ids": "source_image_ids",
    "source_tile_count": "source_tile_count",
    "datatake_id": "datatake_id",
    "observation_datetime_utc": "observation_datetime_utc",
    "source_granule_cloud_percent_mean": "source_granule_cloud_percent_mean",
    "valid_pixel_fraction": "valid_pixel_fraction",
    "valid_pixel_count": "valid_pixel_count",
    "coverage_tier": "coverage_tier",
}

# Fields that MUST be present. Kept as data rather than a run of ifs so
# the contract is legible in one place and testable without executing the
# agent. Each entry is (state key, message shown in errors).
#
# All of these raise RuntimeError, which the handler turns into a neutral
# "try again" for the user while the detail stays in errors. That is the
# right class: a missing key means gee.py and this agent are out of step,
# which is our problem, not a satellite limitation the farmer can wait out.
REQUIRED_GEE_FIELDS = (
    # Coverage — every claim about "the field" is licensed by these
    (
        "valid_pixel_fraction",
        "GEE result is missing valid-pixel coverage.",
    ),
    (
        "image_date",
        "GEE result is missing the Sentinel-2 observation date.",
    ),
    (
        "assessment_scope",
        "GEE result is missing assessment_scope. Downstream agents "
        "cannot safely describe the field without it.",
    ),

    # Reproducibility identity. image_id is deliberately NOT here: it is
    # only the first contributing asset, kept for compatibility. The
    # identity that lets a reviewer reproduce a result in the Earth
    # Engine Code Editor is the datatake plus the full asset list plus
    # the sensing time.
    (
        "source_image_ids",
        "GEE result is missing Sentinel-2 source image IDs.",
    ),
    (
        "datatake_id",
        "GEE result is missing the Sentinel-2 datatake ID.",
    ),
    (
        "observation_datetime_utc",
        "GEE result is missing the Sentinel-2 observation time.",
    ),

    # The Phase 1 farmer map and the metadata that says whether its
    # within-field differences may be claimed at all.
    (
        "variation_map_url",
        "GEE result is missing the Phase 1 variation map.",
    ),
    (
        "variation_map_bounds",
        "GEE result is missing variation-map bounds.",
    ),
    (
        "variation_map_info",
        "GEE result is missing variation-map metadata.",
    ),
)

# Coverage blocks that must be present AND carry a measured fraction.
# Half the coverage contract is worse than none: downstream would quietly
# compare the farmer-facing percentage against nothing.
REQUIRED_COVERAGE_BLOCKS = (
    (
        "field_coverage",
        "GEE result is missing full-field coverage metadata.",
        "GEE result is missing full-field clear coverage.",
    ),
    (
        "analysis_coverage",
        "GEE result is missing analysis-interior coverage metadata.",
        "GEE result is missing analysis-interior clear coverage.",
    ),
)

# image_info keys copied into technical_details for validation review.
TECHNICAL_PROVENANCE_KEYS = (
    "cloud_mask_method",
    "cloud_mask_threshold",
    "cloud_gap_policy",
    "map_observation_policy",
    "mosaic_policy",
    "coverage_denominator",
    "coverage_tier_rule",
    "footprint_fraction_floor",
    "analysis_scale_m",
    "index_native_scale_m",
    "index_method",
    "edge_buffer_m",
    "edge_excluded",
    "field_clear_fraction",
    "field_footprint_fraction",
    "analysis_clear_fraction",
    "analysis_footprint_fraction",
    "spatially_representative",
    "distribution_score",
    "observed_zone_count",
    "eligible_zone_count",
    "selection_mode",
    "selected_is_latest_pass",
    "fallback_used",
    "no_recent_pass",
    "latest_pass_date",
    "latest_pass_datatake",
    "latest_pass_fraction",
    "image_age_days",
    "search_window_days",
    "candidate_count",
    "clean_candidate_count",
    "recent_candidate_count",
    "source_granule_cloud_percent_mean",
)


def _validate_gee_contract(gee_result, passthrough):
    """
    Raises RuntimeError if the GEE v2 payload is not what we froze.

    Split out of processing_agent() so it can be exercised directly in a
    test with a hand-built payload, without an Earth Engine round trip.

    Three different kinds of check, because one kind cannot do the job:

      presence   for fields whose valid values include False and {}
      emptiness  for scalars, where None or "" is the only failure
      structure  for containers, where [] and {} pass a None check but
                 carry no information

    Note the scalar check deliberately does NOT use `if not value`.
    valid_pixel_fraction is a float, and a low-but-real coverage figure
    must not be rejected as missing.
    """
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in gee_result:
            raise RuntimeError(
                f"GEE result is missing required field: {key}."
            )

    for key, message in REQUIRED_GEE_FIELDS:
        value = passthrough.get(key)
        if value is None or value == "":
            raise RuntimeError(message)

    for key, missing_msg, empty_msg in REQUIRED_COVERAGE_BLOCKS:
        block = passthrough.get(key)
        if not isinstance(block, dict):
            raise RuntimeError(missing_msg)
        if block.get("clear_fraction") is None:
            raise RuntimeError(empty_msg)

    # Containers: an empty list or dict passes the scalar check above
    # while carrying nothing a reviewer could use.
    source_image_ids = passthrough.get("source_image_ids")
    if not isinstance(source_image_ids, list) or not source_image_ids:
        raise RuntimeError(
            "GEE result is missing Sentinel-2 source image IDs."
        )

    bounds = passthrough.get("variation_map_bounds")
    if (
        not isinstance(bounds, dict)
        or not VARIATION_BOUND_KEYS.issubset(bounds)
    ):
        raise RuntimeError("GEE result has invalid variation-map bounds.")

    info = passthrough.get("variation_map_info")
    if not isinstance(info, dict) or not info:
        raise RuntimeError("GEE result is missing variation-map metadata.")

    for key in MAPPING_CONTRACT_KEYS:
        if not isinstance(passthrough.get(key), dict):
            raise RuntimeError(f"GEE result has an invalid {key}.")

    # Booleans specifically, not merely truthy values. A stray string
    # here would read as True downstream and report a hotspot that the
    # science never established.
    for key in BOOLEAN_CONTRACT_KEYS:
        if not isinstance(passthrough.get(key), bool):
            raise RuntimeError(f"GEE result has a non-boolean {key}.")

    # Closed value sets. Without these, assessment_scope="banana" passes
    # every non-empty check and then silently fails to match any branch
    # in the interpretation layer.
    if passthrough.get("assessment_scope") not in VALID_ASSESSMENT_SCOPES:
        raise RuntimeError(
            "GEE result contains an invalid assessment_scope."
        )

    for key in COVERAGE_TIER_KEYS:
        if passthrough.get(key) not in VALID_COVERAGE_TIERS:
            raise RuntimeError(f"GEE result contains an invalid {key}.")

    # attention_source is deliberately NOT validated against a closed
    # set. It carries a suppression REASON used only for wording; the
    # actual gate on reporting a hotspot is attention_is_distinct, which
    # is type-checked above. If a future gee.py adds a suppression
    # reason, hard-failing here would take every farmer's report offline
    # until this file caught up, to prevent nothing: an unrecognised
    # reason arriving with attention_is_distinct=False is already safe.
    # Detection should handle unknown reasons with generic wording.
    if not isinstance(passthrough.get("attention_source"), str):
        raise RuntimeError("GEE result has a non-string attention_source.")


def processing_agent(state: FarmWatchState) -> FarmWatchState:
    """
    Processing Agent — calls the GEE satellite pipeline for the farm
    polygon and unpacks the result into shared state.

    calculate_all_indices_for_polygon() handles:
    - Connecting to Google Earth Engine
    - Building the edge-buffered analysis interior
    - Mosaicking granules from the SAME datatake, so a farm spanning two
      tiles is one observation rather than a rejected one
    - Prioritised acquisition selection: recent and clear first, recent
      and partial second, older imagery only when nothing recent works
    - Cloud and shadow masking via Cloud Score+ before any index maths
    - Coverage measured over BOTH the drawn field and the interior, with
      scope degraded rather than the analysis refused
    - NDVI, NDMI, NDRE, SAVI and GNDVI by explicit arithmetic, so
      legitimate negative reflectance is not silently masked
    - The same-date relative variation map, with cloud gaps left gray
    - Consistent-index 3x3 zone analysis with a distinctness test
    - Geodesic area and true polygon centroid

    This agent contains no science logic. Its only job is to move every
    field from the GEE result into state without dropping any.

    That matters more than it sounds. Downstream agents read state with
    .get() and safe defaults, so a field not written here does not raise
    — it silently becomes False, None or {}. Two examples that bite:

      attention_is_distinct missing -> detection_agent reads False and
      NO attention area is ever reported, however distinct the zone is.

      assessment_scope missing -> the interpretation layer has nothing
      telling it to withhold whole-field language, so a field that was
      40% visible gets described as if it were fully assessed.

    Since gee.py v2 is frozen, anything it guarantees is treated as
    required here rather than defaulted. See REQUIRED_GEE_FIELDS and
    REQUIRED_COVERAGE_BLOCKS above: coverage, scope, the reproducibility
    identity (datatake, source assets, sensing time) and the variation
    map are all hard failures. Defaulting any of them would either
    overclaim or make every report look cloud-limited, and would send
    you hunting a phantom coverage bug instead of a version mismatch.

    Two failure classes are handled separately:

      ValueError   -> an expected satellite limitation. gee.py has
                      already written a message for the farmer, so it
                      passes through untouched.
      RuntimeError -> a contract violation or unexpected failure. The
                      user gets a neutral message; details stay in
                      errors for debugging.
    """
    # `or []` rather than a default argument: state.get("errors", [])
    # returns None when an earlier agent wrote errors=None explicitly,
    # and list(None) raises TypeError here — outside the try block, so
    # it would surface as an unhandled crash rather than a handled one.
    errors = list(state.get("errors") or [])

    if not state.get("boundary_valid"):
        msg = "Boundary validation failed, so processing was skipped."
        errors.append(msg)
        return {
            **state,
            "processing_error": msg,
            "processing_error_code": "BOUNDARY_INVALID",
            "status": "failed",
            "errors": errors,
        }

    polygon = state.get("polygon")
    if not polygon:
        msg = "No farm boundary was supplied, so processing was skipped."
        errors.append(msg)
        return {
            **state,
            "processing_error": msg,
            "processing_error_code": "BOUNDARY_INVALID",
            "status": "failed",
            "errors": errors,
        }

    try:
        gee_result = calculate_all_indices_for_polygon(polygon)

        # ── Result contract guards ────────────────────────────────
        # RuntimeError, not ValueError. These are code or integration
        # problems, not satellite limitations — a user can do nothing
        # about them, and they must not be shown a message implying
        # they should try again later.
        if not isinstance(gee_result, dict):
            raise RuntimeError("GEE analysis did not return a valid result.")

        image_info = gee_result.get("image_info")
        if not image_info:
            raise RuntimeError("GEE analysis returned no image metadata.")

        # ── Index values ──────────────────────────────────────────
        ndvi = gee_result.get("ndvi")
        ndre = gee_result.get("ndre")
        savi = gee_result.get("savi")
        gndvi = gee_result.get("gndvi")

        # NDMI is the NIR/SWIR moisture index. Falls back to the legacy
        # "ndwi" key so a stale gee.py would not break the pipeline.
        ndmi = gee_result.get("ndmi")
        if ndmi is None:
            ndmi = gee_result.get("ndwi")

        # Values from GEE go to the classifier without any additional
        # rounding here. technical_details uses four decimal places for
        # consistent presentation when more precision is available.
        indices = {
            "ndvi": ndvi,
            "ndmi": ndmi,
            "ndre": ndre,
            "savi": savi,
            "gndvi": gndvi,

            # TEMPORARY compatibility alias. Remove once the frontend
            # and database columns have migrated to ndmi.
            "ndwi": ndmi,
        }

        # ── Bulk pass-through ─────────────────────────────────────
        passthrough = {}
        for key in GEE_PASSTHROUGH_KEYS:
            passthrough[key] = gee_result.get(key)

        for state_key, info_key in IMAGE_INFO_TO_STATE.items():
            passthrough[state_key] = image_info.get(info_key)

        recent_comparison = passthrough.get("recent_comparison") or {}
        passthrough["recent_comparison"] = recent_comparison

        # ── Contract guards on the values that gate claims ────────
        # Deliberately strict, and deliberately WITHOUT fallbacks.
        #
        # There is no fallback from variation_map_url to the legacy
        # field_condition_map_url or stress_map_url. In frozen gee.py
        # those keys are aliases of this same map, so such a fallback
        # could only ever fire against a PRE-FREEZE gee.py — and in
        # exactly that case it would relabel an absolute NDRE condition
        # map as a relative variation map. The two mean different
        # things, the colours are stretched differently, and nothing
        # downstream could tell. Silently swapping the semantics is
        # worse than refusing to produce a report.
        _validate_gee_contract(gee_result, passthrough)

        variation_map_url = passthrough["variation_map_url"]
        variation_map_bounds = passthrough["variation_map_bounds"]

        def r4(v):
            return round(v, 4) if v is not None else None

        technical_details = {
            # Selected-acquisition index values
            "ndvi": r4(ndvi),
            "ndmi": r4(ndmi),
            "ndre": r4(ndre),
            "savi": r4(savi),
            "gndvi": r4(gndvi),

            # TEMPORARY compatibility alias
            "ndwi": r4(ndmi),

            # Spatial zone metadata
            "attention_source": passthrough["attention_source"],
            "attention_is_distinct": passthrough["attention_is_distinct"],
            "attention_rule": passthrough["attention_rule"],
            "zone_values": passthrough["zone_values"],
            "zone_pixel_counts": passthrough["zone_pixel_counts"],
            "zone_analysis_supported": passthrough["zone_analysis_supported"],
            "eligible_zone_count": passthrough["eligible_zone_count"],
            "min_zones_for_analysis": passthrough["min_zones_for_analysis"],

            # Acquisition identity. datatake_id and source_image_ids are
            # what a reviewer needs to reproduce the result in the Earth
            # Engine Code Editor; the date alone is not enough.
            "image_id": passthrough["image_id"],
            "source_image_ids": passthrough["source_image_ids"],
            "source_tile_count": passthrough["source_tile_count"],
            "datatake_id": passthrough["datatake_id"],
            "observation_datetime_utc": passthrough[
                "observation_datetime_utc"
            ],

            # Coverage and scope
            "assessment_scope": passthrough["assessment_scope"],
            "coverage_tier": passthrough["coverage_tier"],
            "field_coverage_tier": passthrough["field_coverage_tier"],
            "analysis_coverage_tier": passthrough["analysis_coverage_tier"],
            "valid_pixel_fraction": passthrough["valid_pixel_fraction"],
            "valid_pixel_count": passthrough["valid_pixel_count"],
            "field_coverage": passthrough["field_coverage"],
            "analysis_coverage": passthrough["analysis_coverage"],
            "analysis_geometry": passthrough["analysis_geometry"],
            "spatial_coverage": passthrough["spatial_coverage"],

            # Map provenance, including why a field may look uniform
            "variation_map_info": passthrough["variation_map_info"],

            # Legacy support layer
            "recent_ndvi_composite": recent_comparison.get(
                "recent_ndvi_composite"
            ),
            "recent_ndre_composite": recent_comparison.get(
                "recent_ndre_composite"
            ),
            "recent_ndmi_composite": recent_comparison.get(
                "recent_ndmi_composite"
            ),
            "recent_savi_composite": recent_comparison.get(
                "recent_savi_composite"
            ),
            "recent_gndvi_composite": recent_comparison.get(
                "recent_gndvi_composite"
            ),

            "ndvi_delta_recent": recent_comparison.get("ndvi_delta_recent"),
            "ndre_delta_recent": recent_comparison.get("ndre_delta_recent"),
            "ndmi_delta_recent": recent_comparison.get("ndmi_delta_recent"),
            "savi_delta_recent": recent_comparison.get("savi_delta_recent"),
            "gndvi_delta_recent": recent_comparison.get(
                "gndvi_delta_recent"
            ),

            # TEMPORARY compatibility aliases
            "recent_ndwi_composite": recent_comparison.get(
                "recent_ndmi_composite"
            ),
            "ndwi_delta_recent": recent_comparison.get("ndmi_delta_recent"),

            "recent_condition_status": recent_comparison.get(
                "recent_condition_status"
            ),
            "recent_comparison_enabled": recent_comparison.get("enabled"),

            "data_source": "Sentinel-2 via Google Earth Engine",
        }

        # NOTE for field validation: the guards above make a missing
        # reproducibility field a full PROCESSING_ERROR, so the farmer
        # sees "try again" rather than a degraded report. That is the
        # right trade while we are validating and need every result to
        # be reproducible. If real-field runs show source_image_ids
        # occasionally absent for a legitimate Earth Engine reason,
        # revisit whether that specific one should degrade instead of
        # fail — but change it deliberately, not by adding a fallback.

        for key in TECHNICAL_PROVENANCE_KEYS:
            technical_details.setdefault(key, image_info.get(key))

        return {
            **state,
            **passthrough,

            # Index values
            "indices": indices,

            # TEMPORARY compatibility aliases for the frontend. All four
            # now point at the RELATIVE VARIATION map, which makes no
            # health claim and whose colours are rescaled per
            # observation. Fix the surrounding copy when Results.tsx
            # migrates to variation_map_*.
            "field_condition_map_url": variation_map_url,
            "condition_map_bounds": variation_map_bounds,
            "stress_map_url": variation_map_url,
            "stress_map_bounds": variation_map_bounds,

            # Full observation metadata
            "image_info": image_info,

            "technical_details": technical_details,

            "processing_error": None,
            "processing_error_code": None,
            "status": "ok",
            "errors": errors,
        }

    except ValueError as exc:
        # An expected satellite limitation — no usable acquisition,
        # cloud cover, no recent pass. gee.py has already written a
        # message for the farmer, so it passes through untouched.
        # Prefixing it with an agent name would tell the user about our
        # architecture instead of their field.
        msg = str(exc)
        errors.append(msg)

        return {
            **state,
            "processing_error": msg,
            "processing_error_code": "SATELLITE_DATA_UNAVAILABLE",
            "status": "failed",
            "errors": errors,
        }

    except Exception as exc:
        # A contract violation or unexpected failure. The user can do
        # nothing about this, so they get a neutral message; the type
        # and detail stay in errors for debugging.
        internal_msg = f"Processing agent failed: {type(exc).__name__}: {exc}"
        errors.append(internal_msg)

        return {
            **state,
            "processing_error": (
                "Satellite analysis could not be completed. "
                "Please try again."
            ),
            "processing_error_code": "PROCESSING_ERROR",
            "status": "failed",
            "errors": errors,
        }