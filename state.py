from typing import Any, Dict, List, Optional, TypedDict


class FarmWatchState(TypedDict, total=False):
    """
    Shared state passed between agents in the Farm Watch pipeline.

    Sections below are grouped by the agent that WRITES the field.

    total=False means every key is optional at the type level. Python does
    not enforce TypedDict at runtime, so downstream agents must still use
    safe reads such as state.get(...). A field declared here will simply be
    absent if no agent writes it, which produces silently wrong output
    rather than an error — hence the migration notes at the end of this
    file.

    This contract carries the Phase 1 GEE v2 outputs:
      - one Sentinel-2 acquisition per report
      - same-datatake mosaicking
      - full-field vs analysis-interior coverage
      - assessment scope
      - same-date relative variation map
      - spatial coverage / zone support
      - edge-exclusion metadata
      - exact acquisition provenance

    Legacy recent-composite fields remain temporarily for compatibility
    until historical_service.py replaces them.
    """

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    # Farm boundary as [longitude, latitude] pairs.
    polygon: List[List[float]]

    # ------------------------------------------------------------------
    # Crop / season context (Step 3) — OPTIONAL
    # ------------------------------------------------------------------
    #
    # All four inputs are optional and user-supplied. A farm with no crop
    # information must still analyse normally: crop context changes how a
    # reading is INTERPRETED, it is never a gate on producing one. When
    # everything here is absent, crop_context comes back with
    # has_crop_context=False and cover_screen_mode="legacy", and the
    # classifier behaves exactly as it did before Step 3.
    #
    # Every existing saved farm has no crop information. Any code that
    # requires this block to produce a report has misread the contract.

    crop_type: Optional[str]
    planting_date: Optional[str]
    irrigation_type: Optional[str]
    season_id: Optional[str]

    # Full output of build_crop_context(), written by detection_agent.
    # processing_agent already knows which Sentinel-2 acquisition was selected
    # and stores its observation date in state. detection_agent uses that
    # observation date when it builds the crop interpretation context.
    #
    # Crop timing must describe the crop on the OBSERVATION date, not the
    # day the farmer pressed Analyze.
    crop_context: Optional[Dict[str, Any]]
    # expected keys:
    # has_crop_context
    # crop_type, crop_key
    # planting_date
    # irrigation_type
    # season_id
    # observation_date
    # days_after_planting
    # crop_timing_context   (nested dict, or None)
    # cover_screen_mode
    # decline_expected
    # context_warnings
    #
    # crop_timing_context, when present, holds:
    #   timing_phase, timing_basis, cover_screen_mode,
    #   decline_expected, profile_available,
    #   canopy_expected_from_dap, late_season_from_dap
    #
    # It is None whenever days_after_planting is None, so reads of the
    # nested value need a guard:
    #   (crop_context.get("crop_timing_context") or {}).get("timing_phase")

    # ---- Lifted from crop_context for convenient downstream access ----

    # Days from planting to the SATELLITE OBSERVATION DATE, not today.
    # The selected acquisition can be several days older than the day the
    # farmer pressed Analyze, and crop timing has to describe the crop as
    # the satellite actually saw it.
    days_after_planting: Optional[int]

    # "pre_planting" | "establishment" | "main_growth" | "late_season"
    # | "unknown"
    #
    # Deliberately broad. Calendar days cannot establish V6, R1 or
    # flowering, and nothing downstream should imply that they can.
    timing_phase: Optional[str]

    # Which cover-screening behaviour the classifier should use:
    #
    # "legacy"                no crop context; behave exactly as before
    # "pre_planting_context"  the observation predates planting
    # "early_stage_context"   before expected canopy closure
    # "standard"              main season
    # "late_season_context"   late-season calendar window where natural
    #                         maturity/senescence may be expected
    cover_screen_mode: Optional[str]

    # True only when the crop calendar places the observation in the
    # late-season window, where natural maturity/senescence may reasonably
    # contribute to declining vegetation indices.
    #
    # This is CONTEXT, not an automatic alert suppressor. A late-season crop
    # can still have a real developing problem, so downstream logic must not
    # treat decline_expected=True as proof that every low or falling signal
    # is normal.
    #
    # None when no crop timing profile exists, which is NOT the same as
    # False. Unknown must never be read as "a decline here would be
    # abnormal", so test explicitly for True rather than truthiness.
    decline_expected: Optional[bool]

    # Whether the farmer supplied any crop information at all.
    has_crop_context: Optional[bool]

    # ------------------------------------------------------------------
    # Intake Agent
    # ------------------------------------------------------------------

    boundary_valid: bool
    boundary_error: Optional[str]
    boundary_point_count: int
    boundary_bbox: Optional[Dict[str, float]]
    # expected bbox keys:
    # min_lon, max_lon, min_lat, max_lat

    # ------------------------------------------------------------------
    # Data Agent
    # ------------------------------------------------------------------

    # Lightweight pass-through gate. Sentinel-2 observation selection now
    # happens inside calculate_all_indices_for_polygon() in gee.py.
    data_error: Optional[str]

    # ------------------------------------------------------------------
    # Assessment scope — READ THIS BEFORE WRITING ANY FARMER-FACING TEXT
    # ------------------------------------------------------------------

    # Controls how broadly downstream agents may describe the observation.
    #
    # "whole_field"    coverage adequate and, where the 3x3 grid exists,
    #                  clear pixels well distributed
    # "partial_field"  50-69% coverage; describe only what was seen
    # "local_only"     coverage or distribution too weak for any
    #                  whole-field claim; report local readings only
    #
    # Interpretation MUST branch on this. Nothing else in state prevents a
    # whole-field sentence being written over a partly-observed field.
    assessment_scope: Optional[str]

    # Farmer-facing caveat generated from the actual coverage/scope, or
    # None at whole_field. Already farmer-facing; do not reword it into
    # something more confident.
    assessment_scope_message: Optional[str]

    # ------------------------------------------------------------------
    # Processing Agent / GEE analysis
    # ------------------------------------------------------------------

    # Complete metadata for the selected Sentinel-2 acquisition.
    image_info: Optional[Dict[str, Any]]
    # Expected Phase 1 GEE v2 keys include:
    #
    # source
    # image_id
    # source_image_ids
    # source_tile_count
    # mosaic_policy
    # date
    # image_age_days
    # selected_is_latest_pass
    # fallback_used
    # no_recent_pass
    # datatake_id
    # observation_datetime_utc
    # latest_pass_date
    # latest_pass_datatake
    # latest_pass_fraction
    # source_granule_cloud_percent_mean
    #
    # valid_pixel_fraction
    # valid_pixel_count
    # coverage_tier
    # coverage_tier_rule
    # field_coverage_tier
    # analysis_coverage_tier
    # field_clear_fraction
    # field_footprint_fraction
    # analysis_clear_fraction
    # analysis_footprint_fraction
    # footprint_fraction_floor
    # coverage_denominator
    #
    # assessment_scope
    # spatially_representative
    # distribution_score
    # observed_zone_count
    # eligible_zone_count
    # zone_analysis_supported
    #
    # analysis_scale_m
    # index_native_scale_m
    # index_method
    # edge_buffer_m
    # edge_excluded
    #
    # cloud_mask_method
    # cloud_mask_threshold
    # cloud_gap_policy
    # map_observation_policy
    #
    # search_window_days
    # search_window_start_utc
    # query_end_date_exclusive_utc
    # selection_mode
    # candidate_count
    # clean_candidate_count
    # recent_candidate_count

    # Basic selected-observation provenance copied out of image_info for
    # convenient downstream access.
    image_date: Optional[str]

    # FIRST contributing Sentinel-2 asset path only, retained for
    # compatibility. A farm spanning two tiles has more assets than this
    # one; prefer source_image_ids for validation and store both.
    image_id: Optional[str]

    # All Sentinel-2 asset paths contributing to the same datatake mosaic.
    # A farm crossing a tile boundary can legitimately have more than one.
    source_image_ids: Optional[List[str]]

    # Number of source granules contributing to the same acquisition
    # mosaic. Always ONE datatake, so this is not a multi-date composite.
    source_tile_count: Optional[int]

    # Sentinel-2 DATATAKE_IDENTIFIER — the identity of the acquisition,
    # more precise than the date. A field in an orbit-overlap zone can be
    # imaged twice in one day, so use this when checking whether two
    # analyses refer to the same observation.
    datatake_id: Optional[str]

    # UTC sensing time for the selected acquisition.
    observation_datetime_utc: Optional[str]

    # Mean CLOUDY_PIXEL_PERCENTAGE across contributing source granules.
    # PROVENANCE ONLY: granule-wide, not area weighted across tiles, and
    # says nothing about this field.
    #
    # Never render it as the field's cloud cover. The farmer-facing number
    # is field_coverage["visible_percent"].
    source_granule_cloud_percent_mean: Optional[float]

    # ------------------------------------------------------------------
    # Coverage — two geometries, two different questions
    # ------------------------------------------------------------------

    # How much of the FULL DRAWN FIELD was clearly usable. Every
    # farmer-facing percentage comes from here.
    field_coverage: Optional[Dict[str, Any]]
    # expected keys:
    # clear_fraction
    # visible_percent
    # footprint_fraction
    # valid_pixel_count
    # total_pixel_count
    # geometry = "full_drawn_field"

    # How much of the geometry actually used for vegetation statistics was
    # clearly usable. This is usually the CLEARER of the two, because the
    # edge buffer removes the perimeter where cloud shadow lands first —
    # which is precisely why scope must never be derived from it alone.
    analysis_coverage: Optional[Dict[str, Any]]
    # expected keys:
    # clear_fraction
    # footprint_fraction
    # valid_pixel_count
    # total_pixel_count
    # geometry = "edge_buffered_interior"

    field_coverage_tier: Optional[str]
    analysis_coverage_tier: Optional[str]

    # The more conservative of the two tiers above.
    #
    # "full"         >= 70% clear on both geometries
    # "partial"      >= 50% on both
    # "insufficient" < 50% on at least one
    # "unknown"      unmeasurable; analysis raises, never reaches state
    #
    # CHANGED FROM THE PREVIOUS CONTRACT: "insufficient" now CAN reach
    # state. gee.py raises only when coverage is insufficient AND no zone
    # is usable at all. An insufficient observation with some usable zones
    # arrives here with real index values and
    # assessment_scope="local_only". Any downstream code still assuming
    # "insufficient never reaches state", or treating the presence of
    # index values as proof of adequate coverage, will present a
    # badly-covered field as a normal one.
    coverage_tier: Optional[str]

    # Backward-compatible coverage values describing the ANALYSIS geometry,
    # not the drawn field. Not farmer-facing.
    valid_pixel_fraction: Optional[float]
    valid_pixel_count: Optional[int]

    # Metadata describing the 15 m edge exclusion, or the reason it could
    # not safely be applied to a small/thin field.
    analysis_geometry: Optional[Dict[str, Any]]
    # expected keys:
    # edge_excluded
    # edge_buffer_m
    # full_area_m2
    # analysed_area_m2
    # analysed_area_share
    # reason
    #
    # edge_excluded=False means the field was too small or thin to buffer,
    # so boundary pixels ARE present in the statistics. Worth surfacing in
    # Technical Details: it changes how much a low reading near the edge
    # should be trusted.

    # ------------------------------------------------------------------
    # Spatial coverage distribution and zone support
    # ------------------------------------------------------------------

    # Coverage distribution across the temporary 3x3 spatial grid.
    spatial_coverage: Optional[Dict[str, Any]]
    # expected keys:
    # spatially_representative
    # distribution_score
    # eligible_zone_count
    # observed_zone_count
    # required_zone_count
    # eligible_row_count
    # observed_row_count
    # required_row_count
    # eligible_column_count
    # observed_column_count
    # required_column_count
    # zone_clear_fraction_floor
    # covered_zone_share_floor
    # min_pixels_per_zone
    # zone_coverage
    #
    # zone_coverage is keyed "row_col" and holds, per zone:
    #   total_pixels, observed_pixels, valid_pixels,
    #   footprint_fraction, clear_fraction, eligible,
    #   observed_for_distribution
    #
    # TRAP: spatially_representative is False for ANY field with no usable
    # 3x3 grid, including a perfectly cloud-free small farm. Read
    # zone_analysis_supported FIRST. Presenting
    # spatially_representative=False as "cloud was unevenly spread" would
    # be wrong for every smallholder field.

    # Whether enough 3x3 cells physically contain enough area for a
    # directional zone comparison. Small fields can still receive overall
    # field readings and a variation map when this is False — and this is
    # a permanent property of the field's size, not a condition the farmer
    # can wait out.
    zone_analysis_supported: Optional[bool]
    eligible_zone_count: Optional[int]
    min_zones_for_analysis: Optional[int]

    # ------------------------------------------------------------------
    # Indices and technical details
    # ------------------------------------------------------------------

    # Created by processing_agent.py with satellite/technical outputs, then
    # EXTENDED by detection_agent.py with classification metadata. Both
    # writes matter.
    technical_details: Optional[Dict[str, Any]]

    # Interior-wide averages returned by gee.py.
    indices: Optional[Dict[str, Optional[float]]]
    # expected keys:
    # ndvi, ndmi, ndre, savi, gndvi
    #
    # Computed at 20 m for every index so they share one grid, even though
    # NDVI/SAVI/GNDVI come from 10 m bands. Only NDRE and NDMI are natively
    # 20 m; check image_info["index_native_scale_m"] before claiming fine
    # spatial detail from any of them.
    #
    # "ndwi" may temporarily remain as a compatibility alias for ndmi.
    # B8A/B11 is the Normalized Difference MOISTURE Index; McFeeters' NDWI
    # uses Green/NIR and detects open water — a different index for a
    # different purpose. Remove the alias once the frontend and database
    # columns have migrated.

    # Temporary legacy comparison block. historical_service.py will replace
    # this with true current-season dated observation history.
    recent_comparison: Optional[Dict[str, Any]]
    # expected keys:
    # comparison_method
    # decision_use
    # enabled
    # recent_ndvi_composite
    # recent_ndre_composite
    # recent_ndmi_composite
    # recent_savi_composite
    # recent_gndvi_composite
    # recent_ndwi_composite
    # ndvi_delta_recent
    # ndre_delta_recent
    # ndmi_delta_recent
    # savi_delta_recent
    # gndvi_delta_recent
    # ndwi_delta_recent
    # recent_condition_status
    #
    # The selected observation may be inside the composite it is compared
    # against, so this cannot be used as historical ground truth — the
    # payload says so in decision_use. Once downstream stops reading it,
    # set INCLUDE_LEGACY_RECENT_COMPARISON=False in gee.py to drop five
    # composites and a reduceRegion from every request.

    # Geodesic field area, over the FULL drawn polygon.
    # analysis_geometry["analysed_area_m2"] is the smaller interior that
    # was actually measured.
    farm_area: Optional[Dict[str, float]]
    # keys: hectares, acres
    area_ha: Optional[float]
    area_acres: Optional[float]

    # True geometric centroid of the farmer-drawn polygon, not the
    # bounding-box centre.
    center: Optional[Dict[str, float]]
    # keys: lat, lng

    # ------------------------------------------------------------------
    # Phase 1 relative variation map
    # ------------------------------------------------------------------

    # Same-date NDRE relative-variation map.
    #
    # Light/dark green means lower/higher relative to THIS field on THIS
    # acquisition. It is not an absolute health map, and its colours are
    # rescaled per observation so they are NOT comparable across dates.
    # The frontend must say so next to the legend, or farmers will read a
    # rescaling as a change in the crop.
    #
    # Three visual states:
    #   green shades  measured
    #   #9CA3AF       inside the analysed area, obscured, not analysed
    #   #D1D5DB       field edge, excluded from analysis
    variation_map_url: Optional[str]
    variation_map_bounds: Optional[Dict[str, float]]
    # expected bounds keys: west, south, east, north

    variation_map_info: Optional[Dict[str, Any]]
    # expected keys:
    # map_type
    # index
    # index_native_scale_m
    # analysis_scale_m
    # field_median
    # p05
    # p95
    # observed_half_range
    # display_half_range
    # spread_floor
    # spread_is_meaningful
    # valid_pixel_count
    # min_pixels_for_variation
    # enough_pixels_for_variation
    # spread_exceeds_noise
    # display_min_delta
    # display_max_delta
    # display_min_absolute
    # display_max_absolute
    # cloud_no_data_color
    # edge_excluded_color
    # legend_low
    # legend_middle
    # legend_high
    # legend_no_data
    # legend_edge
    # comparable_across_dates
    # health_classification
    # uniform_field_message
    #
    # spread_is_meaningful=False has TWO distinct causes, and
    # uniform_field_message already carries the right wording for each:
    #   enough_pixels_for_variation=False -> too few clear pixels to
    #       compare areas reliably (small field)
    #   spread_exceeds_noise=False        -> the field genuinely looks
    #       uniform today
    # Do not collapse these into one message. "Your field is uniform" and
    # "we could not tell" are different statements.

    # TEMPORARY compatibility aliases. These now point at the RELATIVE
    # VARIATION map, not an absolute condition or stress map. Remove once
    # Results.tsx reads variation_map_* directly — and fix the surrounding
    # copy at the same time, because the old names imply a health claim the
    # map no longer makes.
    field_condition_map_url: Optional[str]
    condition_map_bounds: Optional[Dict[str, float]]
    stress_map_url: Optional[str]
    stress_map_bounds: Optional[Dict[str, float]]

    processing_error: Optional[str]

    # "SATELLITE_DATA_UNAVAILABLE" -> expected imagery limitation; the
    #                                 message is already farmer-facing
    # "PROCESSING_ERROR"           -> unexpected software/contract failure;
    #                                 user sees a neutral message, detail
    #                                 stays in errors
    # "BOUNDARY_INVALID"           -> geometry rejected before analysis
    processing_error_code: Optional[str]

    # ------------------------------------------------------------------
    # Spatial zone analysis
    # ------------------------------------------------------------------

    # Directional location such as "northwest area of the farm", or None.
    # It never contains an explanatory sentence — detection and
    # interpretation know how to describe an absent finding, and a
    # placeholder here would become a location the pipeline never actually
    # identified.
    #
    # gee.py applies its OWN suppression before this reaches state, via
    # evaluate_spatial_finding(). A named area is suppressed when:
    #   - zone analysis is unsupported (field too small)
    #   - scope is local_only
    #   - there are too few pixels for reliable variation
    #   - the field is effectively uniform
    #   - the zone difference does not pass the distinctness rule
    #
    # detection_agent.py may additionally set it to None when a difference
    # exists but should not be surfaced as an alert.
    attention_area: Optional[str]

    # Why there is or is not a finding. Two families of value:
    #
    #   ranking succeeded:
    #     "ndre" | "ndvi_fallback"
    #   suppressed or unavailable:
    #     "field_too_small_for_zone_analysis"
    #     "scope_local_only"
    #     "insufficient_pixels_for_variation"
    #     "field_uniform"
    #     "insufficient_clear_zones"
    #     "insufficient_data"
    #
    # These are NOT interchangeable in farmer-facing copy.
    # "field_uniform" means we looked and everything matched.
    # "field_too_small_for_zone_analysis" means we can never look.
    # "insufficient_clear_zones" means cloud prevented it this time and a
    # later pass may succeed — only this one is worth telling a farmer to
    # wait on.
    #
    # NOTE: when a finding is suppressed this value REPLACES the index
    # name, so zone_values arrive with no record of whether they are NDRE
    # or NDVI. See the migration notes at the end of this file.
    attention_source: Optional[str]

    # Whether the weakest zone is meaningfully lower than the rest. False
    # whenever attention_area is None.
    #
    # If this never reaches state, detection_agent reads False and NO
    # attention area is ever reported, however distinct the zone is.
    attention_is_distinct: Optional[bool]

    # Human-readable description of the same-date spatial anomaly rule, so
    # a reviewer can see WHY a zone was flagged, not only which zone.
    attention_rule: Optional[str]

    # Raw per-zone values keyed "row_col" ("0_0" through "2_2"). Zones
    # absent here were dropped for too few valid pixels OR for failing
    # their own clear-fraction gate — a zone that was 90% cloud can no
    # longer be crowned weakest on the strength of four cloud-edge pixels.
    # spatial_coverage["zone_coverage"] says which reason applied.
    zone_values: Optional[Dict[str, float]]

    # Valid index-pixel count per zone, same keys. Present even for zones
    # excluded from zone_values.
    zone_pixel_counts: Optional[Dict[str, int]]

    # ------------------------------------------------------------------
    # Detection Agent
    # ------------------------------------------------------------------

    # Legacy internal code retained for database compatibility. The values
    # imply causes ("water_stress", "nutrient_stress") that a spectral
    # index cannot establish. Frontend and report should use
    # condition_signal instead.
    stress_type: Optional[str]

    # Safe user-facing description of what was observed.
    condition_signal: Optional[str]
    # expected values:
    # "moisture_condition"
    # "chlorophyll_condition"
    # "vegetation_cover"
    # "general_vegetation_condition"
    # "early_signal"
    # "no_warning_signal"
    # "not_assessed"
    #
    # "not_assessed" must never be treated as equivalent to
    # "no_warning_signal" — one means we could not measure, the other
    # means we measured and found nothing concerning.
    #
    # At assessment_scope="local_only", "no_warning_signal" is a claim
    # about the observed portion only and must be worded that way.

    severity: Optional[str]
    # "none" | "mild" | "moderate" | "severe"

    urgency: Optional[str]
    # "low" | "medium" | "high"

    # Hex colour for the frontend indicator. Gray (#94a3b8) when
    # condition_signal is "not_assessed" — severity is "none" in that case,
    # so keying colour on severity alone would show the same green as a
    # genuinely clear field.
    color: Optional[str]

    # Classifier outputs. title and recommendation are written by
    # detection; the interpretation agent READS them to build its
    # plain-language text.
    title: Optional[str]
    recommendation: Optional[str]

    # Hypotheses about what might explain the finding. Never asserted as
    # fact — the index establishes condition, not cause.
    possible_causes: Optional[List[str]]

    # Other indicators also low in the same observation. These are NOT
    # independent: NDMI and NDRE both use B8A, NDRE and GNDVI both track
    # chlorophyll. Agreement is corroborating evidence, not independent
    # confirmation, which is why no branch in the current classifier
    # returns high confidence.
    corroborating_signals: Optional[List[str]]

    # "savi" | "ndvi" | None
    #
    # Which index actually drove the vegetation-cover screening step.
    # From Step 3 this is chosen using cover_screen_mode rather than by
    # whichever index happened to be present.
    #
    # SAVI is still computed by gee.py for every observation at a FIXED
    # L=0.5 and stays in Technical Details regardless. Crop context only
    # decides which index the cover decision reads, never how any index
    # is calculated — a soil-brightness correction that drifted with the
    # calendar would put a step change into the season-long series that
    # historical_service.py is about to build.
    cover_source: Optional[str]

    # The technically weakest distinct zone, DERIVED by detection_agent
    # from attention_area and attention_is_distinct, and kept even when the
    # user-facing attention_area is suppressed BY DETECTION — distinct does
    # not mean unhealthy, so this preserves the finding for technical
    # review without presenting it as an alert.
    #
    # LIMITATION: gee.py now suppresses before detection sees the value, so
    # this can only preserve findings that detection itself suppressed. A
    # finding suppressed inside gee.py is not recoverable here.
    relative_low_area: Optional[str]

    hotspot_summary: Optional[str]
    detection_error: Optional[str]

    # ------------------------------------------------------------------
    # Interpretation Agent
    # ------------------------------------------------------------------

    summary: Optional[str]
    explanation: Optional[str]
    action: Optional[str]
    interpretation_error: Optional[str]

    # ------------------------------------------------------------------
    # Report Agent
    # ------------------------------------------------------------------

    final_response: Optional[Dict[str, Any]]
    report_error: Optional[str]

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------

    # "started" | "ok" | "failed"
    status: Optional[str]

    # Accumulated internal/debug messages across agents.
    errors: Optional[List[str]]


# ====================================================================
# MIGRATION NOTES — remove once downstream has caught up
# ====================================================================
#
# REMOVED FIELD
#   cloud_cover -> source_granule_cloud_percent_mean
#
#   gee.py no longer returns cloud_cover_percent, so nothing writes
#   cloud_cover. It is deliberately NOT declared above: a declared field
#   with no writer invites state.get("cloud_cover"), which returns None
#   and renders as a blank or a zero rather than raising. Grep for it in
#   processing_agent.py and Results.tsx before deploying. If a database
#   column of that name must survive, populate it in the persistence
#   layer from source_granule_cloud_percent_mean — not here.
#
# CHANGED SEMANTICS
#   coverage_tier == "insufficient" can now reach state. It previously
#   could not. Anything that treats the presence of index values as proof
#   of adequate coverage is now wrong.
#
#   Step 3 adds OPTIONAL crop context. crop_type, planting_date,
#   irrigation_type and season_id may all be absent, and
#   cover_screen_mode="legacy" then reproduces pre-Step-3 behaviour
#   exactly. Any code that requires crop context to produce a report has
#   misread the contract: every existing saved farm has none.
#
#   decline_expected is a THREE-state value: True (late season, a fall is
#   normal), False (not late season), None (no timing profile for this
#   crop, so we cannot say). Test `is True` / `is False`, never
#   truthiness — None read as False would assert that a decline is
#   abnormal on a crop we have no calendar for.
#
#   field_condition_map_url / stress_map_url now point at a RELATIVE
#   variation map whose colours are rescaled per observation. Any UI text
#   implying the colours mean health, or that they are comparable week to
#   week, is now incorrect.
#
# GEE.PY GAP WORTH CLOSING BEFORE FIELD VALIDATION
#   evaluate_spatial_finding() overwrites attention_source with the
#   suppression reason, discarding whether the ranking used NDRE or NDVI.
#   zone_values then arrive with no record of which index produced them,
#   which makes manual validation in the Earth Engine Code Editor
#   guesswork. Returning the pre-suppression values as raw_attention_area
#   / raw_attention_source / ranking_index would fix it without changing
#   any behaviour, and would give relative_low_area something to preserve
#   again.