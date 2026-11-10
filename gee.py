import os
import json
import math
from datetime import datetime, timedelta, timezone

import ee
from dotenv import load_dotenv

load_dotenv()


# ── Constants ─────────────────────────────────────────────────────

# COPERNICUS/S2_SR_HARMONIZED stores reflectance as integers scaled by
# 10000. Indices with additive constants (SAVI's L) MUST use true
# reflectance or the constant has no meaningful effect.
#
# HARMONIZED also shifts scenes acquired from 2022-01-25 onward back by
# the 1000 DN processing-baseline offset, so genuinely NEGATIVE
# reflectance occurs in dark pixels. Every index below is therefore
# computed with explicit arithmetic rather than normalizedDifference(),
# which masks any pixel whose inputs are negative.
S2_SCALE = 0.0001

# Cloud Score+ 'cs_cdf' ranges from 0 (obscured) to 1 (clear).
# Tagintell currently uses 0.60 as a provisional clear-pixel threshold.
CS_PLUS_THRESHOLD = 0.60

# One analysis grid for the whole module. NDRE and NDMI come from 20 m
# bands (B5/B8A/B11) and are the primary indices, so every reduction,
# pixel count and zone statistic uses 20 m. Standardising here means
# coverage counts, zone means and index means all share a denominator
# instead of silently changing with the index.
ANALYSIS_SCALE = 20

# ── Field-level coverage policy ───────────────────────────────────
# Provisional Tagintell engineering thresholds pending field
# validation. NOT universal agronomic constants.
COVERAGE_FULL = 0.70
COVERAGE_PARTIAL = 0.50

# A same-date mosaic must still cover essentially the whole field before
# it is scored. After same-acquisition mosaicking this rejects genuine
# edge-of-swath cases rather than ordinary multi-tile fields.
MIN_FOOTPRINT_FRACTION = 0.90

# ── Field-edge policy ─────────────────────────────────────────────
# A 10-20 m pixel on a field boundary mixes crop with road, tree line,
# ditch and headland. Those pixels read systematically low on EVERY
# observation, which is exactly the signature the future persistent-
# pattern detector looks for. Excluding them keeps that feature from
# firing on every field's own perimeter.
EDGE_BUFFER_M = 5

# If negatively buffering a small or thin field removes too much of it,
# fall back to the full polygon and flag that edge effects are present.
MIN_BUFFERED_AREA_SHARE = 0.35

# Smallest ground area a 3x3 cell must contribute before its mean is
# trusted. Expressed as AREA so the guard means the same thing if the
# analysis scale ever changes.
MIN_ZONE_AREA_M2 = 1600
MIN_PIXELS_PER_ZONE = 4

# Whether the 3x3 grid can work at all is decided by how many cells
# actually hold enough area, NOT by a farm-acreage approximation. An
# irregular 1 ha field may yield five usable cells while a 1.5 ha
# ribbon-shaped one yields three. eligible_zone_count answers the real
# question, so these two constants are the only zone-count rules and
# they are shared by the ranking code and the support test.
MIN_ZONES_FOR_ANALYSIS = 5
MIN_ZONES_FOR_NDRE = 6

# Spatial representativeness is checked separately from whole-field
# percentage. A field can be 60% clear but have almost all clear pixels
# in one corner; that should not support a whole-field conclusion.
MIN_ZONE_CLEAR_FRACTION = 0.25
MIN_SPATIALLY_COVERED_ZONE_SHARE = 0.50

RECENT_SEARCH_DAYS = 10
EXTENDED_SEARCH_DAYS = 30

# ── Variation-map policy ──────────────────────────────────────────
# Phase 1 map is intentionally a RELATIVE, same-date variation map.
# It does NOT claim that light green is unhealthy or dark green healthy.
# It asks only: which parts of THIS field are lower/higher than the
# field's typical NDRE reading on THIS observation date?
VARIATION_LOW_PERCENTILE = 5
VARIATION_MEDIAN_PERCENTILE = 50
VARIATION_HIGH_PERCENTILE = 95

# Guards against stretching sensor noise into a dramatic-looking map.
# A field whose p05..p95 spread is smaller than this is uniform for
# practical purposes; the stretch is clamped AND the caller is told via
# variation_map_info["spread_is_meaningful"], so the report can say the
# field looks uniform instead of rendering noise as a vivid pattern.
VARIATION_MIN_HALF_RANGE = 0.025

# p05 and p95 on a handful of pixels are effectively min and max, which
# are the noisiest statistics available. Below this many valid pixels
# the map is STILL rendered at its measured range, so a small field
# keeps its colours and the farmer can see the pixels that exist. What
# changes is that spread_is_meaningful becomes False, so no directional
# within-field finding may be reported from it. The stretch itself is
# not altered; only the claim is withheld.
MIN_VALID_PIXELS_FOR_VARIATION = 25

VARIATION_PALETTE = [
    "#E8F5E9",  # very light green = lower relative reading
    "#C8E6C9",
    "#81C784",
    "#43A047",
    "#1B5E20",  # dark green = higher relative reading
]

# Pixels Cloud Score+ does not consider reliable are shown as gray.
# They are NOT filled with pixels from another date.
NO_DATA_GRAY = "#9CA3AF"

# The excluded boundary ring uses a lighter gray so the legend can
# distinguish "obscured by cloud" from "field edge, not analysed".
EDGE_EXCLUDED_GRAY = "#D1D5DB"

# The legacy recent-composite block is retained only until state.py,
# processing_agent.py and Results.tsx are migrated to
# historical_service.py. It costs five composites and a reduceRegion on
# every request, so flip this off as soon as downstream is ready.
INCLUDE_LEGACY_RECENT_COMPARISON = True


def initialize_gee():
    project_id = os.getenv("GEE_PROJECT_ID")
    service_account_email = os.getenv("GEE_SERVICE_ACCOUNT_EMAIL")
    private_key_json = os.getenv("GEE_SERVICE_ACCOUNT_KEY_JSON")

    if service_account_email and private_key_json:
        service_account_info = json.loads(private_key_json)

        import tempfile

        key_file_path = os.path.join(
            tempfile.gettempdir(), "gee-service-account.json"
        )
        with open(key_file_path, "w", encoding="utf-8") as f:
            json.dump(service_account_info, f)

        credentials = ee.ServiceAccountCredentials(
            service_account_email,
            key_file_path,
        )
        ee.Initialize(credentials, project=project_id)
        return

    ee.Initialize(project=project_id)


def safe_round(value, digits=3):
    return round(value, digits) if value is not None else None


def min_pixels_for_scale(scale):
    """
    Minimum valid pixels a 3x3 cell needs at a given reduction scale.

    Derived from MIN_ZONE_AREA_M2 so the guard always means the same
    ground area regardless of the scale used.
    """
    by_area = math.ceil(MIN_ZONE_AREA_M2 / float(scale * scale))
    return max(MIN_PIXELS_PER_ZONE, by_area)


def get_search_range(days_back: int):
    """
    Start and end dates for a search window, in UTC.

    days_back counts calendar dates INCLUDING today, so days_back=10
    spans exactly ten dates. The end is tomorrow because Earth Engine's
    filterDate() is exclusive on the end. The exclusive UTC end is
    technical provenance only and should not be shown as a future date
    in the farmer interface.
    """
    today_utc = datetime.now(timezone.utc).date()
    start_date = today_utc - timedelta(days=days_back - 1)
    end_date = today_utc + timedelta(days=1)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def _prop(props, band_name, output_name):
    """
    Reads a reduceRegions output property.

    Earth Engine names multi-output reducer results differently
    depending on band count and on whether setOutputs() was used, so
    both the plain and band-prefixed forms are accepted rather than
    assuming one convention and silently returning None.
    """
    if output_name in props:
        return props.get(output_name)
    return props.get(f"{band_name}_{output_name}")


def _as_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


# ── Cloud, haze and shadow masking ────────────────────────────────

def add_cloud_score_plus(collection):
    """
    Links each Sentinel-2 image to Cloud Score+ 'cs_cdf'.

    Unlike granule-wide CLOUDY_PIXEL_PERCENTAGE, this lets Tagintell
    evaluate clarity over the actual farm polygon, pixel by pixel.
    """
    cs_plus = ee.ImageCollection(
        "GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED"
    )
    return collection.linkCollection(cs_plus, ["cs_cdf"])


def clear_pixel_mask(image):
    """Returns the Boolean Cloud Score+ clear-pixel mask."""
    return image.select("cs_cdf").gte(CS_PLUS_THRESHOLD)


def mask_clouds(image):
    """
    Masks pixels Cloud Score+ flags as obscured by cloud, haze or shadow.

    Applied BEFORE index calculation. A masked pixel stays missing in
    the current observation; Tagintell does not fill it with another
    date in this Phase 1 analysis.
    """
    return image.updateMask(clear_pixel_mask(image))


# ── Denominator-safe coverage layers ──────────────────────────────
# Every helper below MUST use unmask(..., sameFootprint=False).
#
# Image.mask() keeps the footprint of the source image, and unmask()
# defaults to sameFootprint=True, which only fills masked pixels that
# are already INSIDE that footprint. Without sameFootprint=False, area
# outside the Sentinel granule stays absent rather than becoming an
# explicit zero, so reduceRegion silently drops it and every coverage
# percentage is computed against the granule instead of the field.

def _total_pixels_image(image):
    """
    1 everywhere, on the image's own grid.

    This is the correct denominator for coverage: "pixels this zone or
    field should contain", not "pixels the satellite happened to see".
    """
    return (
        image.select("B8")
        .multiply(0)
        .add(1)
        .unmask(1, sameFootprint=False)
        .rename("total_pixels")
    )


def _footprint_image(image):
    """1 where the granule has B8 data, explicit 0 everywhere else."""
    return (
        image.select("B8")
        .mask()
        .unmask(0, sameFootprint=False)
        .rename("observed_pixels")
    )


def _observed_clear_image(image):
    """
    1 where the field was both imaged AND judged clear, 0 elsewhere.

    Averaging a masked clear-mask would give the share of OBSERVED
    pixels that were clear, which is a different question: a granule
    clipping 10% of a field with no cloud over that sliver would score
    1.0. Averaging this image gives the share of the WHOLE field that is
    usable, which is what the coverage gate needs.
    """
    footprint = _footprint_image(image)

    clear = (
        clear_pixel_mask(image)
        .unmask(0, sameFootprint=False)
    )

    return (
        clear.multiply(footprint)
        .unmask(0, sameFootprint=False)
        .rename("valid_pixels")
    )


def _coverage_stack(image):
    """total_pixels + observed_pixels + valid_pixels, all unmasked 0/1."""
    return (
        _total_pixels_image(image)
        .addBands(_footprint_image(image))
        .addBands(_observed_clear_image(image))
    )


def get_coverage_stats(image, polygon):
    """
    Coverage of a given geometry by THIS observation, in one call.

    Returns:
      clear_fraction     usable share of the geometry
      observed_fraction  share of the geometry inside the footprint
      valid_pixel_count  clear pixels at ANALYSIS_SCALE
      total_pixel_count  pixels the geometry should contain
    """
    try:
        stats = _coverage_stack(image).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=polygon,
            scale=ANALYSIS_SCALE,
            maxPixels=1_000_000,
            bestEffort=True,
        ).getInfo() or {}

        total = _as_int(stats.get("total_pixels"))
        observed = _as_int(stats.get("observed_pixels"))
        valid = _as_int(stats.get("valid_pixels"))

        if total <= 0:
            return {
                "clear_fraction": None,
                "observed_fraction": None,
                "valid_pixel_count": valid,
                "total_pixel_count": total,
            }

        return {
            "clear_fraction": round(valid / total, 3),
            "observed_fraction": round(observed / total, 3),
            "valid_pixel_count": valid,
            "total_pixel_count": total,
        }

    except Exception:
        return {
            "clear_fraction": None,
            "observed_fraction": None,
            "valid_pixel_count": None,
            "total_pixel_count": None,
        }


def classify_coverage_tier(fraction):
    """
    Field-level coverage tier.

    full         -> >= 70% clear
    partial      -> >= 50% and < 70% clear
    insufficient -> < 50% clear
    unknown      -> coverage could not be measured
    """
    if fraction is None:
        return "unknown"
    if fraction >= COVERAGE_FULL:
        return "full"
    if fraction >= COVERAGE_PARTIAL:
        return "partial"
    return "insufficient"


COVERAGE_TIER_RANK = {
    "insufficient": 1,
    "partial": 2,
    "full": 3,
}


def combine_coverage_tiers(field_tier, analysis_tier):
    """
    Returns the more conservative of full-field coverage and
    analysis-interior coverage.

    The interior is often clearer than the drawn field, because the edge
    buffer removes the perimeter where cloud shadow lands first. Taking
    the interior alone would let a report claim a whole-field assessment
    on the same screen where the farmer is told a large part of their
    farm was not visible.

    Live analysis and archived observations both call this, so one
    Sentinel acquisition cannot end up with two different scopes
    depending on which code path measured it.
    """
    if "unknown" in (field_tier, analysis_tier):
        return "unknown"

    return min(
        field_tier,
        analysis_tier,
        key=lambda tier: COVERAGE_TIER_RANK[tier],
    )


# ── Analysis geometry (edge exclusion) ────────────────────────────

def build_analysis_geometry(polygon):
    """
    Returns the interior geometry used for ALL vegetation statistics.

    The farmer's polygon is kept for display, area reporting and the
    farmer-facing visibility percentage; the negatively buffered
    interior is what gets measured, so boundary pixels contaminated by
    roads, tree lines and headlands never enter a zone mean or a
    persistent-pattern series.

    Thin or small fields where the buffer would remove most of the area
    fall back to the full polygon, with edge_excluded=False recorded so
    reviewers know edge effects are present in those results.
    """
    buffered = polygon.buffer(-EDGE_BUFFER_M, maxError=1)

    try:
        areas = ee.Dictionary({
            "full": polygon.area(maxError=1),
            "buffered": buffered.area(maxError=1),
        }).getInfo() or {}
    except Exception:
        areas = {}

    full_area = areas.get("full")
    buffered_area = areas.get("buffered")

    usable = (
        full_area is not None
        and buffered_area is not None
        and full_area > 0
        and (buffered_area / full_area) >= MIN_BUFFERED_AREA_SHARE
    )

    if usable:
        return buffered, {
            "edge_excluded": True,
            "edge_buffer_m": EDGE_BUFFER_M,
            "full_area_m2": round(float(full_area), 1),
            "analysed_area_m2": round(float(buffered_area), 1),
            "analysed_area_share": round(
                float(buffered_area) / float(full_area), 3
            ),
            "reason": "interior_only",
        }

    return polygon, {
        "edge_excluded": False,
        "edge_buffer_m": 0,
        "full_area_m2": (
            round(float(full_area), 1) if full_area is not None else None
        ),
        "analysed_area_m2": (
            round(float(full_area), 1) if full_area is not None else None
        ),
        "analysed_area_share": 1.0,
        "reason": "field_too_small_or_thin_for_edge_buffer",
    }


# ── 3x3 geometry helpers ──────────────────────────────────────────

def _build_3x3_zone_geometries(polygon):
    """
    Builds the current temporary 3x3 spatial grid and intersects every
    cell with the analysis geometry.

    The 3x3 grid is NOT the final management-zone model. It remains
    useful now for directional summaries and, importantly, for checking
    whether cloud-free pixels are spread across the farm.
    """
    bounds = polygon.bounds(maxError=1).getInfo()["coordinates"][0]
    lons = [p[0] for p in bounds]
    lats = [p[1] for p in bounds]

    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    lon_step = (max_lon - min_lon) / 3
    lat_step = (max_lat - min_lat) / 3

    zones = {}

    for row in range(3):
        for col in range(3):
            zone_rect = ee.Geometry.Rectangle([
                min_lon + col * lon_step,
                max_lat - (row + 1) * lat_step,
                min_lon + (col + 1) * lon_step,
                max_lat - row * lat_step,
            ])

            try:
                zone_geom = zone_rect.intersection(polygon, maxError=10)
                zones[(row, col)] = zone_geom
            except Exception:
                continue

    return zones


def _empty_spatial_coverage(zone_coverage=None):
    return {
        "spatially_representative": False,
        "distribution_score": 0.0,
        "eligible_zone_count": 0,
        "observed_zone_count": 0,
        "required_zone_count": 0,
        "eligible_row_count": 0,
        "observed_row_count": 0,
        "required_row_count": 0,
        "eligible_column_count": 0,
        "observed_column_count": 0,
        "required_column_count": 0,
        "zone_clear_fraction_floor": MIN_ZONE_CLEAR_FRACTION,
        "covered_zone_share_floor": MIN_SPATIALLY_COVERED_ZONE_SHARE,
        "min_pixels_per_zone": min_pixels_for_scale(ANALYSIS_SCALE),
        "zone_coverage": zone_coverage or {},
    }


def get_spatial_coverage_stats(image, polygon):
    """
    Checks WHERE the clear pixels are, not only how many exist.

    Guards against a misleading whole-field conclusion when a seemingly
    acceptable clear percentage is concentrated in one corner.

    Each zone reports THREE counts against the same denominator:
      total_pixels     pixels the zone should contain
      observed_pixels  pixels inside the satellite footprint
      valid_pixels     pixels that were also clear

    footprint_fraction and clear_fraction are therefore both computed
    over total_pixels. Dividing valid by observed would answer "of what
    we saw, how much was clear", which is a different question and
    always flatters the result.
    """
    min_pixels = min_pixels_for_scale(ANALYSIS_SCALE)

    zones = _build_3x3_zone_geometries(polygon)
    if not zones:
        return _empty_spatial_coverage()

    features = [
        ee.Feature(
            geom,
            {
                "row": row,
                "col": col,
                "zone_key": f"{row}_{col}",
            },
        )
        for (row, col), geom in zones.items()
    ]
    zone_fc = ee.FeatureCollection(features)

    # All three bands are unmasked 0/1, so a SUM gives pixel counts.
    counted_fc = _coverage_stack(image).reduceRegions(
        collection=zone_fc,
        reducer=ee.Reducer.sum(),
        scale=ANALYSIS_SCALE,
        tileScale=2,
    )

    try:
        info = counted_fc.getInfo() or {}
        feature_info = info.get("features", [])
    except Exception:
        feature_info = []

    if not feature_info:
        return _empty_spatial_coverage()

    zone_coverage = {}
    eligible_keys = []
    observed_keys = []

    for feature in feature_info:
        props = feature.get("properties", {}) or {}
        row = int(props.get("row", 0))
        col = int(props.get("col", 0))
        key = props.get("zone_key") or f"{row}_{col}"

        total_count = _as_int(props.get("total_pixels"))
        observed_count = _as_int(props.get("observed_pixels"))
        valid_count = _as_int(props.get("valid_pixels"))

        if total_count > 0:
            footprint_fraction = round(observed_count / total_count, 3)
            clear_fraction = round(valid_count / total_count, 3)
        else:
            footprint_fraction = None
            clear_fraction = None

        eligible = total_count >= min_pixels
        observed = bool(
            eligible
            and valid_count >= min_pixels
            and clear_fraction is not None
            and clear_fraction >= MIN_ZONE_CLEAR_FRACTION
        )

        if eligible:
            eligible_keys.append((row, col))
        if observed:
            observed_keys.append((row, col))

        zone_coverage[key] = {
            "total_pixels": total_count,
            "observed_pixels": observed_count,
            "valid_pixels": valid_count,
            "footprint_fraction": footprint_fraction,
            "clear_fraction": clear_fraction,
            "eligible": eligible,
            "observed_for_distribution": observed,
        }

    eligible_count = len(eligible_keys)
    observed_count_total = len(observed_keys)

    eligible_rows = {r for r, _ in eligible_keys}
    eligible_cols = {c for _, c in eligible_keys}
    observed_rows = {r for r, _ in observed_keys}
    observed_cols = {c for _, c in observed_keys}

    if eligible_count == 0:
        return _empty_spatial_coverage(zone_coverage)

    required_zone_count = max(
        1,
        math.ceil(eligible_count * MIN_SPATIALLY_COVERED_ZONE_SHARE),
    )
    required_rows = min(2, len(eligible_rows))
    required_cols = min(2, len(eligible_cols))

    # A diagonal band of clear pixels touches every row and every column
    # while covering only a third of the field, so the zone-share test
    # is the primary gate and the axis tests are secondary.
    distribution_score = round(observed_count_total / eligible_count, 3)

    representative = bool(
        observed_count_total >= required_zone_count
        and len(observed_rows) >= required_rows
        and len(observed_cols) >= required_cols
    )

    return {
        "spatially_representative": representative,
        "distribution_score": distribution_score,
        "eligible_zone_count": eligible_count,
        "observed_zone_count": observed_count_total,
        "required_zone_count": required_zone_count,
        "eligible_row_count": len(eligible_rows),
        "observed_row_count": len(observed_rows),
        "required_row_count": required_rows,
        "eligible_column_count": len(eligible_cols),
        "observed_column_count": len(observed_cols),
        "required_column_count": required_cols,
        "zone_clear_fraction_floor": MIN_ZONE_CLEAR_FRACTION,
        "covered_zone_share_floor": MIN_SPATIALLY_COVERED_ZONE_SHARE,
        "min_pixels_per_zone": min_pixels,
        "zone_coverage": zone_coverage,
    }


# ── Same-acquisition mosaicking ───────────────────────────────────

def build_acquisition_mosaics(linked_collection):
    """
    Combines granules from the SAME Sentinel-2 acquisition into one
    image, grouping on DATATAKE_IDENTIFIER rather than calendar date.

    A datatake uniquely identifies one acquisition, including satellite,
    sensing start time and orbit. Same date is not the same thing: a
    field in an orbit-overlap zone can be imaged twice in one day, hours
    apart, under different illumination. Merging those into one "daily"
    mosaic would breach the one-report-one-observation rule as surely as
    mixing two dates would.

    Joining adjacent tiles of a single datatake does NOT breach it. It
    reconstructs the observation Sentinel-2 actually made, so a farm
    straddling a tile boundary is not rejected by the footprint gate
    forever despite being well observed.

    Mosaics carry no system:index, so provenance is preserved as an
    explicit list of contributing asset IDs plus a tile count. Mosaics
    also carry no fixed projection, which makes reduceRegions and
    getThumbURL fail intermittently, so the 20 m B8A grid is set as the
    default projection to match ANALYSIS_SCALE.
    """
    datatakes = ee.List(
        linked_collection.aggregate_array("DATATAKE_IDENTIFIER")
    ).distinct()

    def build_one(datatake_id):
        datatake_id = ee.String(datatake_id)
        subset = linked_collection.filter(
            ee.Filter.eq("DATATAKE_IDENTIFIER", datatake_id)
        )

        reference = ee.Image(subset.first())
        sensing_time = reference.get("system:time_start")

        mosaic = subset.mosaic().setDefaultProjection(
            reference.select("B8A").projection()
        )

        return mosaic.set({
            "system:time_start": sensing_time,
            "datatake_id": datatake_id,
            "observation_date": ee.Date(sensing_time).format("YYYY-MM-dd"),
            "observation_datetime_utc": ee.Date(sensing_time).format(
                "YYYY-MM-dd'T'HH:mm:ss"
            ),
            "source_image_ids": subset.aggregate_array("system:index"),
            "source_tile_count": subset.size(),
            # Granule-wide metadata averaged across contributing tiles.
            # NOT a farm-level figure and not area weighted; kept only
            # for provenance. Farm clarity is field_clear_fraction.
            "source_granule_cloud_percent_mean": subset.aggregate_mean(
                "CLOUDY_PIXEL_PERCENTAGE"
            ),
        })

    return ee.ImageCollection(datatakes.map(build_one))


# ── Image selection ───────────────────────────────────────────────

def _score_collection(polygon, days_back):
    """
    Returns same-date Sentinel-2 mosaics with farm-level footprint and
    clear fractions attached to each one.

    Both fractions use the WHOLE geometry as the denominator, so a
    mosaic that only clips the field cannot score as fully clear.
    """
    start_date, end_date = get_search_range(days_back)

    raw = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(polygon)
        .filterDate(start_date, end_date)
    )

    mosaics = build_acquisition_mosaics(add_cloud_score_plus(raw))

    def add_farm_fractions(img):
        stats = _coverage_stack(img).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=polygon,
            scale=ANALYSIS_SCALE,
            maxPixels=1_000_000,
            bestEffort=True,
        )

        total = ee.Number(stats.get("total_pixels")).max(1)

        return img.set({
            "farm_clear_fraction": ee.Number(
                stats.get("valid_pixels")
            ).divide(total),
            "farm_footprint_fraction": ee.Number(
                stats.get("observed_pixels")
            ).divide(total),
        })

    scored = mosaics.map(add_farm_fractions).filter(
        ee.Filter.gte("farm_footprint_fraction", MIN_FOOTPRINT_FRACTION)
    )

    return scored, start_date, end_date


def _describe_image(img):
    """Fetch observation date and clear fraction in one getInfo call."""
    try:
        return ee.Dictionary({
            "date": img.get("observation_date"),
            "datatake_id": img.get("datatake_id"),
            "fraction": img.get("farm_clear_fraction"),
            "tile_count": img.get("source_tile_count"),
        }).getInfo() or {}
    except Exception:
        return {}


def get_sentinel2_image(polygon):
    """
    Selects ONE Sentinel-2 observation for the report.

    Selection policy:
      1. Look at the newest observation in the recent 10-day window.
      2. If newest is >= 70% clear, use it as full coverage.
      3. If newest is >= 50% and < 70% clear, use it as partial coverage.
      4. If newest is < 50% clear, search backward for the most recent
         observation that reaches the 50% minimum usable threshold.
      5. If none qualifies in the recent window, search the extended
         30-day window.
      6. If nothing reaches 50%, return the clearest available
         observation so the downstream quality gate can explain the
         limitation.

    Candidates whose mosaicked footprint does not cover the field are
    excluded before scoring. Cloudy pixels are never filled from another
    date; masked pixels remain no-data/gray.
    """
    scored_recent, recent_start, recent_end = _score_collection(
        polygon,
        RECENT_SEARCH_DAYS,
    )
    recent_count = scored_recent.size().getInfo()

    latest = {}

    if recent_count > 0:
        latest = _describe_image(
            scored_recent.sort(
                "system:time_start",
                False,
            ).first()
        )

    def result(
        image,
        start,
        end,
        mode,
        count,
        clean_count,
        collection,
        window_days,
        latest_info,
    ):
        return {
            "image": image,
            "search_start": start,
            "search_end": end,
            "search_window_days": window_days,
            "selection_mode": mode,
            "candidate_count": count,
            "clean_candidate_count": clean_count,
            "recent_candidate_count": recent_count,
            "collection": collection,
            "latest_date": latest_info.get("date"),
            "latest_datatake": latest_info.get("datatake_id"),
            "latest_fraction": latest_info.get("fraction"),
        }

    # ── First choice: newest observation in the recent window ──
    if recent_count > 0:
        newest = scored_recent.sort(
            "system:time_start",
            False,
        ).first()

        newest_info = _describe_image(newest)
        newest_fraction = newest_info.get("fraction")

        if newest_fraction is not None:
            if newest_fraction >= COVERAGE_FULL:
                return result(
                    newest,
                    recent_start,
                    recent_end,
                    "recent_full_coverage",
                    recent_count,
                    1,
                    scored_recent,
                    RECENT_SEARCH_DAYS,
                    latest,
                )

            if newest_fraction >= COVERAGE_PARTIAL:
                return result(
                    newest,
                    recent_start,
                    recent_end,
                    "recent_partial_coverage",
                    recent_count,
                    1,
                    scored_recent,
                    RECENT_SEARCH_DAYS,
                    latest,
                )

        # The newest observation is below the usable coverage floor.
        # Search backward within the recent window for the most recent
        # observation that reaches the minimum usable threshold.
        usable_recent = scored_recent.filter(
            ee.Filter.gte(
                "farm_clear_fraction",
                COVERAGE_PARTIAL,
            )
        )

        usable_recent_count = usable_recent.size().getInfo()

        if usable_recent_count > 0:
            best = usable_recent.sort(
                "system:time_start",
                False,
            ).first()

            best_info = _describe_image(best)
            best_fraction = best_info.get("fraction")

            mode = (
                "previous_full_coverage"
                if (
                    best_fraction is not None
                    and best_fraction >= COVERAGE_FULL
                )
                else "previous_partial_coverage"
            )

            return result(
                best,
                recent_start,
                recent_end,
                mode,
                recent_count,
                usable_recent_count,
                scored_recent,
                RECENT_SEARCH_DAYS,
                latest,
            )

    # ── No usable recent observation: search the extended window ──
    scored_wide, wide_start, wide_end = _score_collection(
        polygon,
        EXTENDED_SEARCH_DAYS,
    )
    wide_count = scored_wide.size().getInfo()

    if wide_count == 0:
        raise ValueError(
            f"No Sentinel-2 observation covering this whole field was "
            f"found in the last {EXTENDED_SEARCH_DAYS} days. Try again "
            f"after a later satellite pass."
        )

    if not latest:
        latest = _describe_image(
            scored_wide.sort(
                "system:time_start",
                False,
            ).first()
        )

    usable_wide = scored_wide.filter(
        ee.Filter.gte(
            "farm_clear_fraction",
            COVERAGE_PARTIAL,
        )
    )

    usable_wide_count = usable_wide.size().getInfo()

    if usable_wide_count > 0:
        best = usable_wide.sort(
            "system:time_start",
            False,
        ).first()

        best_info = _describe_image(best)
        best_fraction = best_info.get("fraction")

        mode = (
            "previous_full_coverage"
            if (
                best_fraction is not None
                and best_fraction >= COVERAGE_FULL
            )
            else "previous_partial_coverage"
        )

        return result(
            best,
            wide_start,
            wide_end,
            mode,
            wide_count,
            usable_wide_count,
            scored_wide,
            EXTENDED_SEARCH_DAYS,
            latest,
        )

    # Nothing reaches the minimum clear-coverage threshold.
    # Return the clearest candidate so the downstream quality gate
    # can produce the correct farmer-facing limitation.
    best = scored_wide.sort(
        "farm_clear_fraction",
        False,
    ).first()

    return result(
        best,
        wide_start,
        wide_end,
        "best_available_clear_fraction",
        wide_count,
        0,
        scored_wide,
        EXTENDED_SEARCH_DAYS,
        latest,
    )


# ── Index calculations ────────────────────────────────────────────
# Native band resolution is recorded for provenance. B4/B8/B3 are 10 m;
# B5/B8A/B11 are 20 m. All reductions run at ANALYSIS_SCALE so every
# index shares one grid, but the record of which indices can genuinely
# resolve fine detail is kept for the "where to check" claim.

INDEX_NATIVE_SCALE = {
    "NDVI": 10,
    "NDMI": 20,
    "NDRE": 20,
    "SAVI": 10,
    "GNDVI": 10,
}


def calculate_normalized_difference(image, band_a, band_b, output_name):
    """
    (a - b) / (a + b) with explicit arithmetic.

    ee.Image.normalizedDifference() masks the output pixel whenever
    EITHER input band is negative. S2_SR_HARMONIZED subtracts the 1000
    DN baseline offset from scenes acquired after 2022-01-25, so
    negative reflectance is legitimate in dark pixels. Using the
    shortcut would silently drop those pixels and count them as cloud
    gaps, which conflicts with Tagintell's own rule that negative index
    values are valid data.

    Only a zero denominator is masked, since that is undefined rather
    than merely dark. The result is clamped to the theoretical [-1, 1]
    range so a near-zero denominator cannot produce an absurd value that
    passes the downstream zone validity check.
    """
    a = image.select(band_a).toFloat()
    b = image.select(band_b).toFloat()

    denominator = a.add(b)

    return (
        a.subtract(b)
        .divide(denominator)
        .updateMask(denominator.neq(0))
        .clamp(-1, 1)
        .rename(output_name)
    )


def calculate_ndvi(image):
    """NIR (B8, 10 m) vs Red (B4, 10 m)."""
    return calculate_normalized_difference(image, "B8", "B4", "NDVI")


def calculate_ndmi(image):
    """
    Normalized Difference Moisture Index: NIR (B8A) vs SWIR (B11).

    Both bands are 20 m. This is a vegetation-moisture-related signal,
    not a direct soil moisture measurement and not proof that a crop has
    enough water.
    """
    return calculate_normalized_difference(image, "B8A", "B11", "NDMI")


def calculate_ndre(image):
    """NIR (B8A, 20 m) vs Red Edge (B5, 20 m)."""
    return calculate_normalized_difference(image, "B8A", "B5", "NDRE")


def calculate_gndvi(image):
    """NIR (B8, 10 m) vs Green (B3, 10 m)."""
    return calculate_normalized_difference(image, "B8", "B3", "GNDVI")


def calculate_savi(image, L=0.5):
    """
    Soil-Adjusted Vegetation Index.

    SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)

    L is defined on reflectance 0..1, so B8/B4 are scaled first. The
    denominator is guarded for the same reason as the normalized
    differences above.
    """
    nir = image.select("B8").toFloat().multiply(S2_SCALE)
    red = image.select("B4").toFloat().multiply(S2_SCALE)

    denominator = nir.add(red).add(L)

    return (
        nir.subtract(red)
        .divide(denominator)
        .multiply(1 + L)
        .updateMask(denominator.neq(0))
        .clamp(-1, 1)
        .rename("SAVI")
    )


def build_index_stack(masked_image):
    """Builds the five same-date optical indices used by Farm Watch."""
    ndvi = calculate_ndvi(masked_image)
    ndmi = calculate_ndmi(masked_image)
    ndre = calculate_ndre(masked_image)
    savi = calculate_savi(masked_image)
    gndvi = calculate_gndvi(masked_image)

    stack = ndvi.addBands(ndmi).addBands(ndre).addBands(savi).addBands(gndvi)
    return stack, ndvi, ndmi, ndre, savi, gndvi


def get_index_means(index_stack, polygon):
    """Farm-wide means for the clear pixels of one observation date."""
    return index_stack.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=polygon,
        scale=ANALYSIS_SCALE,
        maxPixels=1_000_000,
        bestEffort=True,
    ).getInfo() or {}


# ── Reusable single-observation measurement foundation ───────────

def measure_sentinel2_observation(
    image,
    analysis_polygon,
    display_polygon=None,
    include_zones=False,
):
    """
    Measures ONE already Cloud-Score+-linked observation (or mosaic).

    Intentionally reusable by the future historical_service.py. It does
    not interpret crop health and does not compare seasons; it returns
    dated measurements from one observation.

    Vegetation statistics use analysis_polygon (edge-buffered) so that
    archive rows and live rows are measured over the same footprint and
    are directly comparable. When display_polygon is supplied, the
    farmer-facing visibility percentage for the FULL drawn field is
    reported alongside it.
    """
    analysis_coverage = get_coverage_stats(image, analysis_polygon)

    # display_polygon SHOULD always be supplied. Without it there is no
    # full-field measurement, combine_coverage_tiers degenerates to the
    # interior alone, and this helper stops agreeing with the live
    # analysis - which is the entire reason it exists. The fallback
    # keeps the function usable but records that the comparison was not
    # actually made.
    field_geometry_supplied = display_polygon is not None

    field_coverage = (
        get_coverage_stats(image, display_polygon)
        if field_geometry_supplied
        else analysis_coverage
    )

    field_coverage_tier = classify_coverage_tier(
        field_coverage["clear_fraction"]
    )
    analysis_coverage_tier = classify_coverage_tier(
        analysis_coverage["clear_fraction"]
    )
    coverage_tier = combine_coverage_tiers(
        field_coverage_tier,
        analysis_coverage_tier,
    )

    if coverage_tier == "unknown":
        raise ValueError(
            "Unable to determine satellite coverage for this "
            "observation."
        )

    masked = mask_clouds(image)
    stack, ndvi, ndmi, ndre, savi, gndvi = build_index_stack(masked)
    means = get_index_means(stack, analysis_polygon)

    try:
        meta = ee.Dictionary({
            "date": image.get("observation_date"),
            "observation_datetime_utc": image.get(
                "observation_datetime_utc"
            ),
            "datatake_id": image.get("datatake_id"),
            "source_image_ids": image.get("source_image_ids"),
            "source_tile_count": image.get("source_tile_count"),
        }).getInfo() or {}
    except Exception:
        meta = {}

    source_ids = meta.get("source_image_ids") or []
    asset_paths = [
        f"COPERNICUS/S2_SR_HARMONIZED/{i}" for i in source_ids
    ]

    result = {
        "date": meta.get("date"),
        "observation_datetime_utc": meta.get(
            "observation_datetime_utc"
        ),
        "datatake_id": meta.get("datatake_id"),
        "image_id": asset_paths[0] if asset_paths else None,
        "source_image_ids": asset_paths,
        "source_tile_count": meta.get("source_tile_count"),
        "valid_pixel_fraction": analysis_coverage["clear_fraction"],
        "valid_pixel_count": analysis_coverage["valid_pixel_count"],
        "field_clear_fraction": field_coverage["clear_fraction"],
        "field_footprint_fraction": field_coverage["observed_fraction"],
        "analysis_clear_fraction": analysis_coverage["clear_fraction"],
        "analysis_footprint_fraction": analysis_coverage[
            "observed_fraction"
        ],
        "coverage_tier": coverage_tier,
        "field_coverage_tier": field_coverage_tier,
        "analysis_coverage_tier": analysis_coverage_tier,
        "field_geometry_supplied": field_geometry_supplied,
        "ndvi": safe_round(means.get("NDVI")),
        "ndmi": safe_round(means.get("NDMI")),
        "ndre": safe_round(means.get("NDRE")),
        "savi": safe_round(means.get("SAVI")),
        "gndvi": safe_round(means.get("GNDVI")),
    }

    if include_zones:
        zone_stats = get_spatial_coverage_stats(image, analysis_polygon)
        ndre_clipped = ndre.clip(analysis_polygon)

        eligible_zone_count = zone_stats.get("eligible_zone_count", 0)
        zone_analysis_supported = (
            eligible_zone_count >= MIN_ZONES_FOR_ANALYSIS
        )
        spatially_representative = zone_stats.get(
            "spatially_representative", False
        )

        if zone_analysis_supported and not spatially_representative:
            observation_scope = "local_only"
        elif coverage_tier == "full":
            observation_scope = "whole_field"
        elif coverage_tier == "partial":
            observation_scope = "partial_field"
        else:
            observation_scope = "local_only"

        try:
            spread = measure_variation_spread(
                ndre_clipped, analysis_polygon
            )
        except ValueError:
            spread = {
                "spread_is_meaningful": False,
                "enough_pixels_for_variation": False,
                "spread_exceeds_noise": False,
            }

        (
            attention_area,
            attention_source,
            zone_values,
            attention_is_distinct,
            zone_counts,
        ) = get_attention_area_from_zones(
            ndre_clipped,
            ndvi.clip(analysis_polygon),
            analysis_polygon,
            zone_coverage=zone_stats.get("zone_coverage"),
        )

        # Same gate as the live master function, so a stored archive row
        # can never claim a finding the live report suppressed.
        (
            attention_area,
            attention_source,
            attention_is_distinct,
        ) = evaluate_spatial_finding(
            attention_area,
            attention_source,
            attention_is_distinct,
            assessment_scope=observation_scope,
            zone_analysis_supported=zone_analysis_supported,
            enough_pixels_for_variation=spread.get(
                "enough_pixels_for_variation",
                False,
            ),
            spread_exceeds_noise=spread.get(
                "spread_exceeds_noise",
                False,
            ),
        )

        result.update({
            "spatial_coverage": zone_stats,
            "assessment_scope": observation_scope,
            "zone_analysis_supported": zone_analysis_supported,
            "eligible_zone_count": eligible_zone_count,
            "variation_spread": spread,
            "attention_area": attention_area,
            "attention_source": attention_source,
            "attention_is_distinct": attention_is_distinct,
            "zone_values": {
                f"{r}_{c}": v for (r, c), v in zone_values.items()
            },
            "zone_pixel_counts": {
                f"{r}_{c}": v for (r, c), v in zone_counts.items()
            },
        })

    return result


# ── Legacy recent composite support ───────────────────────────────
# Retained temporarily so the current processing/state/frontend contract
# does not break mid-migration. These values MUST NOT be treated as the
# new historical engine because the selected observation may be inside
# the comparison composite. historical_service.py will replace this.

def build_recent_composites(collection):
    masked = collection.map(mask_clouds)

    ndvi_mvc = masked.map(calculate_ndvi).max().rename("NDVI")
    ndre_median = masked.map(calculate_ndre).median().rename("NDRE")
    ndmi_median = masked.map(calculate_ndmi).median().rename("NDMI")
    savi_median = masked.map(calculate_savi).median().rename("SAVI")
    gndvi_median = masked.map(calculate_gndvi).median().rename("GNDVI")

    return {
        "ndvi_mvc": ndvi_mvc,
        "ndre_median": ndre_median,
        "ndmi_median": ndmi_median,
        "savi_median": savi_median,
        "gndvi_median": gndvi_median,
    }


def get_recent_composite_stats(composites, polygon):
    recent_stack = (
        composites["ndvi_mvc"]
        .addBands(composites["ndre_median"])
        .addBands(composites["ndmi_median"])
        .addBands(composites["savi_median"])
        .addBands(composites["gndvi_median"])
    )

    return recent_stack.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=polygon,
        scale=ANALYSIS_SCALE,
        maxPixels=1_000_000,
        bestEffort=True,
    ).getInfo() or {}


def classify_recent_condition_status(
    selected_ndre,
    recent_ndre,
    selected_ndmi,
    recent_ndmi,
    selected_gndvi,
    recent_gndvi,
):
    """
    LEGACY support status only.

    Known limitation: the selected observation can be part of the recent
    composite. Do not use this as the future historical trend engine.
    """
    below_signals = 0
    slight_signals = 0

    for selected, recent in (
        (selected_ndre, recent_ndre),
        (selected_ndmi, recent_ndmi),
        (selected_gndvi, recent_gndvi),
    ):
        if selected is not None and recent is not None:
            difference = selected - recent
            if difference <= -0.08:
                below_signals += 1
            elif difference <= -0.04:
                slight_signals += 1

    if below_signals >= 2:
        return "below_recent_pattern"
    if below_signals >= 1 or slight_signals >= 2:
        return "slightly_below_recent"
    return "near_recent_pattern"


# ── Same-date variation map ───────────────────────────────────────

def measure_variation_spread(ndre_image, analysis_polygon):
    """
    Measures within-field NDRE spread WITHOUT rendering anything.

    Split out of build_variation_map so the live master function and the
    reusable single-observation helper judge "is this field uniform?"
    from one identical calculation. Historical processing needs the same
    number anyway, since within-field spread is itself a signal.
    """
    reducer = ee.Reducer.percentile([
        VARIATION_LOW_PERCENTILE,
        VARIATION_MEDIAN_PERCENTILE,
        VARIATION_HIGH_PERCENTILE,
    ]).combine(
        reducer2=ee.Reducer.count(),
        sharedInputs=True,
    )

    stats = ndre_image.reduceRegion(
        reducer=reducer,
        geometry=analysis_polygon,
        scale=ANALYSIS_SCALE,
        maxPixels=1_000_000,
        bestEffort=True,
    ).getInfo() or {}

    p_low = stats.get(f"NDRE_p{VARIATION_LOW_PERCENTILE}")
    median = stats.get(f"NDRE_p{VARIATION_MEDIAN_PERCENTILE}")
    p_high = stats.get(f"NDRE_p{VARIATION_HIGH_PERCENTILE}")
    valid_count = stats.get("NDRE_count")

    if p_low is None or median is None or p_high is None:
        raise ValueError(
            "The visible part of this field did not contain enough "
            "usable NDRE data to measure within-field variation."
        )

    valid_count = _as_int(valid_count)

    low_delta = float(p_low) - float(median)
    high_delta = float(p_high) - float(median)

    observed_half_range = max(abs(low_delta), abs(high_delta))
    enough_pixels = valid_count >= MIN_VALID_PIXELS_FOR_VARIATION
    spread_exceeds_noise = observed_half_range >= VARIATION_MIN_HALF_RANGE

    spread_is_meaningful = bool(enough_pixels and spread_exceeds_noise)
    half_range = max(observed_half_range, VARIATION_MIN_HALF_RANGE)

    if spread_is_meaningful:
        message = None
    elif not enough_pixels:
        message = (
            "This field has too few clear satellite pixels to compare "
            "areas within it reliably. The map shows the readings that "
            "exist, but no within-field difference is claimed."
        )
    else:
        message = (
            "This field looks uniform in this observation. No "
            "meaningful within-field differences were detected, so "
            "the map is shown at its minimum contrast."
        )

    return {
        "field_median": float(median),
        "p05": float(p_low),
        "p95": float(p_high),
        "valid_pixel_count": valid_count,
        "observed_half_range": observed_half_range,
        "display_half_range": half_range,
        "enough_pixels_for_variation": enough_pixels,
        "spread_exceeds_noise": spread_exceeds_noise,
        "spread_is_meaningful": spread_is_meaningful,
        "uniform_field_message": message,
    }


def evaluate_spatial_finding(
    attention_area,
    attention_source,
    attention_is_distinct,
    assessment_scope,
    zone_analysis_supported,
    enough_pixels_for_variation,
    spread_exceeds_noise,
):
    """
    Single gate for whether a directional spatial finding may be reported.

    Used by both the live analysis and historical observation measurement
    so the same Sentinel acquisition cannot receive different spatial
    conclusions depending on the code path.
    """

    if not zone_analysis_supported:
        return None, "field_too_small_for_zone_analysis", False

    if assessment_scope == "local_only":
        return None, "scope_local_only", False

    if not enough_pixels_for_variation:
        return None, "insufficient_pixels_for_variation", False

    if not spread_exceeds_noise:
        return None, "field_uniform", False

    return attention_area, attention_source, attention_is_distinct


def build_variation_map(
    ndre_image,
    display_polygon,
    analysis_polygon,
    spread=None,
):
    """
    Builds a SAME-DATE relative NDRE variation map.

    Centered on the field median for this observation and stretched
    symmetrically using the 5th/95th percentile deviations. It is
    intentionally NOT comparable by color across different dates.

    Three visual states, each with a distinct meaning:
      green shades  measured, relative to this field today
      NO_DATA_GRAY  inside the analysed area but obscured by cloud
      EDGE_GRAY     boundary ring excluded from analysis

    When the field's p05..p95 spread falls below VARIATION_MIN_HALF_RANGE
    the stretch is clamped and spread_is_meaningful is returned False, so
    the report can state that the field looks uniform rather than
    rendering sensor noise as a vivid pattern.
    """
    if spread is None:
        spread = measure_variation_spread(ndre_image, analysis_polygon)

    median = spread["field_median"]
    p_low = spread["p05"]
    p_high = spread["p95"]
    observed_half_range = spread["observed_half_range"]
    half_range = spread["display_half_range"]
    spread_is_meaningful = spread["spread_is_meaningful"]

    relative = ndre_image.subtract(float(median)).rename("NDRE_relative")

    # Layer order: excluded edge ring, then cloud gray inside the
    # analysed interior, then measured green pixels on top. Because the
    # green layer is still masked wherever Cloud Score+ rejected the
    # pixel, obscured areas fall through to the gray beneath them.
    edge_base = (
        ee.Image.constant(0)
        .clip(display_polygon)
        .visualize(
            min=0,
            max=1,
            palette=[EDGE_EXCLUDED_GRAY, EDGE_EXCLUDED_GRAY],
        )
    )

    nodata_base = (
        ee.Image.constant(0)
        .clip(analysis_polygon)
        .visualize(
            min=0,
            max=1,
            palette=[NO_DATA_GRAY, NO_DATA_GRAY],
        )
    )

    green_variation = relative.clip(analysis_polygon).visualize(
        min=-half_range,
        max=half_range,
        palette=VARIATION_PALETTE,
    )

    rendered = edge_base.blend(nodata_base).blend(green_variation)

    map_url = rendered.getThumbURL({
        "region": display_polygon,
        "dimensions": 512,
        "format": "png",
        "crs": "EPSG:4326",
    })

    return map_url, {
        "map_type": "same_date_relative_ndre_variation",
        "index": "NDRE",
        "index_native_scale_m": INDEX_NATIVE_SCALE["NDRE"],
        "analysis_scale_m": ANALYSIS_SCALE,
        "field_median": safe_round(float(median), 4),
        "p05": safe_round(float(p_low), 4),
        "p95": safe_round(float(p_high), 4),
        "observed_half_range": safe_round(observed_half_range, 4),
        "display_half_range": safe_round(half_range, 4),
        "spread_floor": VARIATION_MIN_HALF_RANGE,
        "spread_is_meaningful": spread_is_meaningful,
        "valid_pixel_count": spread["valid_pixel_count"],
        "min_pixels_for_variation": MIN_VALID_PIXELS_FOR_VARIATION,
        "enough_pixels_for_variation": spread[
            "enough_pixels_for_variation"
        ],
        "spread_exceeds_noise": spread["spread_exceeds_noise"],
        "display_min_delta": safe_round(-half_range, 4),
        "display_max_delta": safe_round(half_range, 4),
        "display_min_absolute": safe_round(float(median) - half_range, 4),
        "display_max_absolute": safe_round(float(median) + half_range, 4),
        "cloud_no_data_color": NO_DATA_GRAY,
        "edge_excluded_color": EDGE_EXCLUDED_GRAY,
        "legend_low": "lower relative reading",
        "legend_middle": "typical for this field on this date",
        "legend_high": "higher relative reading",
        "legend_no_data": "obscured by cloud, haze or shadow",
        "legend_edge": "field edge, not analysed",
        "comparable_across_dates": False,
        "health_classification": False,
        "uniform_field_message": spread["uniform_field_message"],
    }


# ── Zone analysis ─────────────────────────────────────────────────

def _sample_zones(index_image, band_name, polygon):
    """
    Samples all temporary 3x3 zones with ONE index only, at
    ANALYSIS_SCALE.

    Zones below the minimum-pixel guard are omitted from zone_values but
    keep their count in zone_pixel_counts so reviewers can see why they
    were omitted.
    """
    min_pixels = min_pixels_for_scale(ANALYSIS_SCALE)

    zones = _build_3x3_zone_geometries(polygon)
    if not zones:
        return {}, {}, min_pixels

    features = [
        ee.Feature(
            geom,
            {
                "row": row,
                "col": col,
                "zone_key": f"{row}_{col}",
            },
        )
        for (row, col), geom in zones.items()
    ]
    zone_fc = ee.FeatureCollection(features)

    # setOutputs makes the returned property names explicit rather than
    # relying on Earth Engine's band-count-dependent naming.
    reducer = (
        ee.Reducer.mean()
        .setOutputs(["zone_mean"])
        .combine(
            reducer2=ee.Reducer.count().setOutputs(["zone_count"]),
            sharedInputs=True,
        )
    )

    try:
        reduced = index_image.reduceRegions(
            collection=zone_fc,
            reducer=reducer,
            scale=ANALYSIS_SCALE,
            tileScale=2,
        ).getInfo() or {}
        feature_info = reduced.get("features", [])
    except Exception:
        return {}, {}, min_pixels

    values = {}
    counts = {}

    for feature in feature_info:
        props = feature.get("properties", {}) or {}
        row = int(props.get("row", 0))
        col = int(props.get("col", 0))

        val = _prop(props, band_name, "zone_mean")
        cnt = _prop(props, band_name, "zone_count")
        counts[(row, col)] = cnt

        if cnt is None or cnt < min_pixels:
            continue

        if val is not None and -1.0 <= float(val) <= 1.0:
            values[(row, col)] = round(float(val), 4)

    return values, counts, min_pixels


def get_attention_area_from_zones(
    ndre_image,
    ndvi_image,
    polygon,
    zone_coverage=None,
):
    """
    Finds a same-date relative lower zone using the temporary 3x3 grid.

    NDRE is preferred. If too few NDRE zones survive, all zones are
    resampled with NDVI; indices are never mixed in one ranking.

    zone_coverage comes from get_spatial_coverage_stats(). Only zones
    whose observed_for_distribution is True may enter the ranking. A
    valid-pixel count alone is not enough: a zone holding 4 clear pixels
    out of 40 passes the count guard while being 90% cloud. Worse, the
    handful of pixels that survive next to a cloud edge are exactly the
    ones biased low by thin cirrus and shadow penumbra, so the zones
    most likely to be crowned "weakest" would be the ones with the least
    real data behind them. Field-level statements use field coverage;
    zone-level statements use that zone's own data quality.

    A magnitude gate sits alongside the rank test on purpose. With nine
    candidate zones one of them is always the lowest, and because the
    underlying cause is usually persistent (soil, drainage, topography)
    the rank persists too, even when the difference is agronomically
    trivial. The zone must be both the weakest AND meaningfully weaker.

    Provisional spatial anomaly heuristic, not a diagnosis and not a
    formal statistical significance test.
    """
    zone_names = {
        (0, 0): "northwest",
        (0, 1): "north",
        (0, 2): "northeast",
        (1, 0): "west",
        (1, 1): "center",
        (1, 2): "east",
        (2, 0): "southwest",
        (2, 1): "south",
        (2, 2): "southeast",
    }

    MIN_ABSOLUTE_GAP = 0.03
    MIN_SD_MULTIPLE = 1.0

    def _clear_enough(values):
        """Drops zones that were mostly cloud, whatever their pixel count."""
        if not zone_coverage:
            return values
        return {
            key: val
            for key, val in values.items()
            if (
                zone_coverage.get(f"{key[0]}_{key[1]}", {})
                .get("observed_for_distribution")
            )
        }

    try:
        raw_values, zone_counts, _ = _sample_zones(
            ndre_image, "NDRE", polygon
        )
        zone_values = _clear_enough(raw_values)
        index_used = "ndre"

        if len(zone_values) < MIN_ZONES_FOR_NDRE:
            ndvi_raw, ndvi_counts, _ = _sample_zones(
                ndvi_image, "NDVI", polygon
            )
            ndvi_values = _clear_enough(ndvi_raw)

            if len(ndvi_values) > len(zone_values):
                zone_values = ndvi_values
                zone_counts = ndvi_counts
                index_used = "ndvi_fallback"

        if len(zone_values) < MIN_ZONES_FOR_ANALYSIS:
            return (
                None,
                "insufficient_clear_zones",
                zone_values,
                False,
                zone_counts,
            )

        values = list(zone_values.values())
        n = len(values)
        mean_val = sum(values) / n

        # Sample standard deviation (n-1). With five to nine zones the
        # population form understates spread and makes the gate easier
        # to pass than intended.
        if n > 1:
            variance = sum((v - mean_val) ** 2 for v in values) / (n - 1)
        else:
            variance = 0.0
        std_dev = variance ** 0.5

        weakest_zone = min(
            zone_values.items(),
            key=lambda kv: kv[1],
        )[0]
        gap = mean_val - zone_values[weakest_zone]

        is_distinct = bool(
            gap >= MIN_ABSOLUTE_GAP
            and (
                std_dev == 0
                or gap >= MIN_SD_MULTIPLE * std_dev
            )
        )

        if not is_distinct:
            return None, index_used, zone_values, False, zone_counts

        direction = zone_names[weakest_zone]
        label = (
            "central area of the farm"
            if direction == "center"
            else f"{direction} area of the farm"
        )

        return label, index_used, zone_values, True, zone_counts

    except Exception:
        return None, "insufficient_data", {}, False, {}


# ── Master function ───────────────────────────────────────────────

def calculate_all_indices_for_polygon(coordinates):
    """
    Farm Watch Phase 1 optical analysis.

    Pipeline:
      1. build the interior analysis geometry (edge pixels excluded)
      2. mosaic same-acquisition granules, then choose ONE observation
         date whose mosaic covers the field
      3. Cloud Score+ mask cloud/haze/shadow
      4. measure coverage over BOTH the drawn field and the interior
      5. measure spatial distribution of the clear pixels
      6. set assessment_scope from 4 and 5 instead of failing outright
      7. calculate NDVI/NDMI/NDRE/SAVI/GNDVI from the same date
      8. build same-date relative NDRE variation map
      9. run temporary same-date 3x3 spatial comparison
     10. preserve exact source assets/date/coverage/provenance

    IMPORTANT:
    Does NOT fill cloud gaps from other dates and does NOT interpret
    absolute NDRE/NDVI values as crop health. Crop/stage-aware
    interpretation and current-season history come in later phases.
    """
    initialize_gee()

    display_polygon = ee.Geometry.Polygon([coordinates])
    analysis_polygon, edge_info = build_analysis_geometry(display_polygon)

    # Selection is scored against the FULL drawn field: an observation
    # that misses part of the farm is not an observation of the farm,
    # even if it happens to cover the buffered interior.
    sel = get_sentinel2_image(display_polygon)

    image = sel["image"]
    start_date = sel["search_start"]
    end_date = sel["search_end"]
    search_window_days = sel["search_window_days"]
    selection_mode = sel["selection_mode"]
    candidate_count = sel["candidate_count"]
    clean_candidate_count = sel["clean_candidate_count"]
    recent_candidate_count = sel["recent_candidate_count"]
    recent_collection = sel["collection"]

    # Two different questions, two different geometries.
    #   field_coverage    what the farmer is told: how much of the
    #                     boundary they drew was actually visible
    #   analysis_coverage what the numbers describe: how much of the
    #                     edge-buffered interior was usable
    field_coverage = get_coverage_stats(image, display_polygon)
    analysis_coverage = get_coverage_stats(image, analysis_polygon)

    valid_pixel_fraction = analysis_coverage["clear_fraction"]
    valid_pixel_count = analysis_coverage["valid_pixel_count"]

    field_coverage_tier = classify_coverage_tier(
        field_coverage["clear_fraction"]
    )
    analysis_coverage_tier = classify_coverage_tier(
        analysis_coverage["clear_fraction"]
    )

    if "unknown" in (field_coverage_tier, analysis_coverage_tier):
        raise ValueError(
            "Unable to check cloud cover for this field. Please try "
            "again after a later satellite pass."
        )

    coverage_tier = combine_coverage_tiers(
        field_coverage_tier,
        analysis_coverage_tier,
    )

    spatial_coverage = get_spatial_coverage_stats(image, analysis_polygon)
    spatially_representative = spatial_coverage.get(
        "spatially_representative", False
    )

    # Graceful degradation rather than all-or-nothing failure: a field
    # that is only partly visible can still support statements about the
    # parts that WERE seen. Scope is returned so processing_agent.py and
    # the interpretation layer can withhold whole-field language without
    # losing the local reading.
    # Can the 3x3 grid work on this field at all? Decided by how many
    # cells actually hold enough area, independent of cloud.
    eligible_zone_count = spatial_coverage.get("eligible_zone_count", 0)
    zone_analysis_supported = eligible_zone_count >= MIN_ZONES_FOR_ANALYSIS

    # Coverage scope and zone support are SEPARATE questions, and
    # conflating them silently broke small farms. A 0.6 ha field with
    # 95% clear imagery has no usable 3x3 grid, which made
    # spatially_representative False, which forced local_only, which
    # then raised a "cloud is blocking too much of this field" error on
    # a cloudless day. The spatial-distribution test only applies where
    # the spatial grid exists; below that, coverage percentage alone
    # decides scope and the field still gets its full readings.
    if zone_analysis_supported:
        if coverage_tier == "full" and spatially_representative:
            assessment_scope = "whole_field"
        elif coverage_tier == "partial" and spatially_representative:
            assessment_scope = "partial_field"
        else:
            assessment_scope = "local_only"
    else:
        if coverage_tier == "full":
            assessment_scope = "whole_field"
        elif coverage_tier == "partial":
            assessment_scope = "partial_field"
        else:
            assessment_scope = "local_only"

    # The farmer-facing percentage describes the boundary they drew.
    field_visible_percent = (
        round(field_coverage["clear_fraction"] * 100)
        if field_coverage["clear_fraction"] is not None
        else 0
    )

    usable_zones = sum(
        1
        for z in spatial_coverage.get("zone_coverage", {}).values()
        if z.get("observed_for_distribution")
    )

    # Fail ONLY when coverage is genuinely too poor to describe anything.
    # Never because the field is too small for the grid: a small field
    # with clear imagery still gets whole-field indices and a variation
    # map, it just gets no directional finding.
    if coverage_tier == "insufficient":
        if usable_zones == 0:
            raise ValueError(
                f"Cloud, haze or shadow is blocking too much of this "
                f"field in recent satellite imagery. Only "
                f"{field_visible_percent}% of the field was clearly "
                f"visible in the best usable observation from the last "
                f"{EXTENDED_SEARCH_DAYS} days, and the clear pixels were "
                f"not spread widely enough to describe any part of the "
                f"field. Cloud-obscured areas were not filled with older "
                f"imagery."
            )

    if assessment_scope == "whole_field":
        scope_message = None
    elif assessment_scope == "partial_field":
        scope_message = (
            f"About {field_visible_percent}% of this field had a reliable "
            f"satellite observation. Gray areas had no reliable reading "
            f"and were not analysed."
        )
    elif coverage_tier == "insufficient":
        scope_message = (
            f"Only {field_visible_percent}% of this field had a reliable "
            f"satellite observation, so Tagintell did not make a "
            f"whole-field assessment. Readings are reported only for "
            f"areas with reliable satellite data."
        )
    else:
        scope_message = (
            f"About {field_visible_percent}% of this field had a reliable "
            f"satellite observation, but the usable pixels were not "
            f"distributed widely enough for a whole-field assessment. "
            f"Readings are reported only for areas that were reliably "
            f"observed."
        )

    masked_image = mask_clouds(image)
    (
        selected_indices,
        ndvi,
        ndmi,
        ndre,
        savi,
        gndvi,
    ) = build_index_stack(masked_image)

    selected_result = get_index_means(selected_indices, analysis_polygon)

    # LEGACY support comparison only. Flip
    # INCLUDE_LEGACY_RECENT_COMPARISON off to drop five composites and a
    # reduceRegion from every request once downstream is migrated.
    if INCLUDE_LEGACY_RECENT_COMPARISON:
        recent_composites = build_recent_composites(recent_collection)
        recent_result = get_recent_composite_stats(
            recent_composites,
            analysis_polygon,
        )
    else:
        recent_result = {}

    # Observation and geometry metadata batched into two round trips.
    try:
        meta = ee.Dictionary({
            "date": image.get("observation_date"),
            "source_image_ids": image.get("source_image_ids"),
            "source_tile_count": image.get("source_tile_count"),
            "datatake_id": image.get("datatake_id"),
            "observation_datetime_utc": image.get(
                "observation_datetime_utc"
            ),
            "source_granule_cloud_percent_mean": image.get(
                "source_granule_cloud_percent_mean"
            ),
        }).getInfo() or {}
    except Exception:
        meta = {}

    image_date = meta.get("date")
    source_ids = meta.get("source_image_ids") or []
    asset_paths = [
        f"COPERNICUS/S2_SR_HARMONIZED/{i}" for i in source_ids
    ]
    image_id = asset_paths[0] if asset_paths else None
    source_tile_count = meta.get("source_tile_count")

    # Deliberately NOT called cloud_cover_percent. This is the mean of
    # each contributing granule's whole-tile CLOUDY_PIXEL_PERCENTAGE,
    # unweighted by how much of the farm each tile supplied. It says
    # nothing about this field. Farm-level clarity is field_clear_fraction.
    source_granule_cloud_percent = (
        round(float(meta["source_granule_cloud_percent_mean"]), 1)
        if meta.get("source_granule_cloud_percent_mean") is not None
        else None
    )
    datatake_id = meta.get("datatake_id")
    observation_datetime = meta.get("observation_datetime_utc")

    try:
        geom = ee.Dictionary({
            "bounds": display_polygon.bounds(maxError=1).coordinates(),
            "centroid": display_polygon.centroid(
                maxError=1
            ).coordinates(),
        }).getInfo() or {}
    except Exception:
        geom = {}

    bounds_coords = (geom.get("bounds") or [[]])[0]
    b_lons = [p[0] for p in bounds_coords] or [0]
    b_lats = [p[1] for p in bounds_coords] or [0]
    condition_map_bounds = {
        "west": min(b_lons),
        "south": min(b_lats),
        "east": max(b_lons),
        "north": max(b_lats),
    }

    centroid_coords = geom.get("centroid") or [0, 0]
    center_lon, center_lat = centroid_coords[0], centroid_coords[1]

    area_m2 = edge_info.get("full_area_m2") or 0
    area_ha = round(area_m2 / 10000, 2)
    area_acres = round(area_m2 / 4046.8564224, 2)

    latest_date = sel.get("latest_date")
    latest_datatake = sel.get("latest_datatake")

    # Compare acquisitions, not calendar dates: a field imaged twice in
    # one day from overlapping orbits has two distinct observations.
    selected_is_latest = bool(
        datatake_id is not None
        and latest_datatake is not None
        and datatake_id == latest_datatake
    )
    fallback_used = bool(latest_datatake) and not selected_is_latest
    no_recent_pass = recent_candidate_count == 0

    try:
        from datetime import date as _date

        img_d = _date.fromisoformat(image_date)
        image_age_days = (
            datetime.now(timezone.utc).date() - img_d
        ).days
    except Exception:
        image_age_days = None

    ndre_clipped = ndre.clip(analysis_polygon)
    ndvi_clipped = ndvi.clip(analysis_polygon)

    # Phase 1 farmer map: same-date relative variation only. The spread
    # is measured once and reused, so the map and the finding gate can
    # never disagree about whether this field is uniform.
    variation_spread = measure_variation_spread(
        ndre_clipped,
        analysis_polygon,
    )

    variation_map_url, variation_map_info = build_variation_map(
        ndre_clipped,
        display_polygon,
        analysis_polygon,
        spread=variation_spread,
    )

    (
        attention_area,
        attention_source,
        zone_values,
        attention_is_distinct,
        zone_counts,
    ) = get_attention_area_from_zones(
        ndre_clipped,
        ndvi_clipped,
        analysis_polygon,
        zone_coverage=spatial_coverage.get("zone_coverage"),
    )

    # A named area survives at partial_field scope, because each ranked
    # zone has now passed its own clear-fraction gate. What changes with
    # scope is the CLAIM the interpretation layer may attach to it:
    #   whole_field    lowest area of the field
    #   partial_field  lowest among the parts that were clearly observed
    # It is suppressed only when no whole-field ranking is possible at
    # all, or when the field's spread is inside the noise floor, or when
    # the field is too small for the 3x3 grid to mean anything.
    (
        attention_area,
        attention_source,
        attention_is_distinct,
    ) = evaluate_spatial_finding(
        attention_area,
        attention_source,
        attention_is_distinct,
        assessment_scope=assessment_scope,
        zone_analysis_supported=zone_analysis_supported,
        enough_pixels_for_variation=variation_map_info.get(
            "enough_pixels_for_variation",
            False,
        ),
        spread_exceeds_noise=variation_map_info.get(
            "spread_exceeds_noise",
            False,
        ),
    )

    selected_ndvi = safe_round(selected_result.get("NDVI"))
    selected_ndmi = safe_round(selected_result.get("NDMI"))
    selected_ndre = safe_round(selected_result.get("NDRE"))
    selected_savi = safe_round(selected_result.get("SAVI"))
    selected_gndvi = safe_round(selected_result.get("GNDVI"))

    recent_ndvi = safe_round(recent_result.get("NDVI"))
    recent_ndre = safe_round(recent_result.get("NDRE"))
    recent_ndmi = safe_round(recent_result.get("NDMI"))
    recent_savi = safe_round(recent_result.get("SAVI"))
    recent_gndvi = safe_round(recent_result.get("GNDVI"))

    recent_condition_status = classify_recent_condition_status(
        selected_ndre=selected_ndre,
        recent_ndre=recent_ndre,
        selected_ndmi=selected_ndmi,
        recent_ndmi=recent_ndmi,
        selected_gndvi=selected_gndvi,
        recent_gndvi=recent_gndvi,
    )

    def delta(sel_v, rec_v):
        return (
            safe_round(sel_v - rec_v)
            if sel_v is not None and rec_v is not None
            else None
        )

    return {
        "ndvi": selected_ndvi,
        "ndmi": selected_ndmi,
        "ndre": selected_ndre,
        "savi": selected_savi,
        "gndvi": selected_gndvi,

        # TEMPORARY compatibility alias. Remove after frontend/database
        # migration to NDMI is complete.
        "ndwi": selected_ndmi,

        # How far the report is allowed to generalise from this
        # observation. processing_agent.py and the interpretation layer
        # MUST read this before writing whole-field language.
        "assessment_scope": assessment_scope,
        "assessment_scope_message": scope_message,
        "field_coverage_tier": field_coverage_tier,
        "analysis_coverage_tier": analysis_coverage_tier,
        "zone_analysis_supported": zone_analysis_supported,
        "eligible_zone_count": eligible_zone_count,
        "min_zones_for_analysis": MIN_ZONES_FOR_ANALYSIS,

        # New explicit Phase 1 map fields.
        "variation_map_url": variation_map_url,
        "variation_map_bounds": condition_map_bounds,
        "variation_map_info": variation_map_info,

        # TEMPORARY compatibility: current frontend still expects the
        # old field-condition/stress-map keys. They now point to the
        # SAME-DATE RELATIVE VARIATION map, not an absolute health map.
        "field_condition_map_url": variation_map_url,
        "condition_map_bounds": condition_map_bounds,
        "stress_map_url": variation_map_url,
        "stress_map_bounds": condition_map_bounds,

        "center": {
            "lat": round(center_lat, 6),
            "lng": round(center_lon, 6),
        },

        "farm_area": {
            "hectares": area_ha,
            "acres": area_acres,
        },
        "area_ha": area_ha,
        "area_acres": area_acres,

        # Which part of the drawn polygon the numbers actually describe.
        "analysis_geometry": edge_info,

        # Farmer-facing visibility, over the boundary they drew.
        "field_coverage": {
            "clear_fraction": field_coverage["clear_fraction"],
            "visible_percent": field_visible_percent,
            "footprint_fraction": field_coverage["observed_fraction"],
            "valid_pixel_count": field_coverage["valid_pixel_count"],
            "total_pixel_count": field_coverage["total_pixel_count"],
            "geometry": "full_drawn_field",
        },

        # What the vegetation statistics were actually computed over.
        "analysis_coverage": {
            "clear_fraction": analysis_coverage["clear_fraction"],
            "footprint_fraction": analysis_coverage["observed_fraction"],
            "valid_pixel_count": analysis_coverage["valid_pixel_count"],
            "total_pixel_count": analysis_coverage["total_pixel_count"],
            "geometry": "edge_buffered_interior",
        },

        "attention_area": attention_area,
        "attention_source": attention_source,
        "attention_is_distinct": attention_is_distinct,
        "attention_rule": (
            "Tagintell same-date spatial anomaly rule: the weakest "
            "temporary 3x3 zone must be at least 0.03 index units and "
            "at least 1 sample standard deviation below the mean of the "
            "included zones. Each ranked zone must contribute at least "
            f"{MIN_ZONE_AREA_M2} m2 of valid pixels AND meet the "
            f"{MIN_ZONE_CLEAR_FRACTION:.0%} minimum clear-coverage "
            f"requirement for its own area; at least "
            f"{MIN_ZONES_FOR_ANALYSIS} zones must qualify; the "
            "within-field spread must exceed the noise floor on enough "
            "pixels to be measurable; and the assessment scope must not "
            "be local-only. A finding is permitted at partial-field "
            "scope, where it describes only the parts of the field that "
            "were clearly observed. Provisional engineering policy, not "
            "a formal statistical significance test."
        ),
        "zone_values": {
            f"{r}_{c}": v for (r, c), v in zone_values.items()
        },
        "zone_pixel_counts": {
            f"{r}_{c}": v for (r, c), v in zone_counts.items()
        },

        # Cloud-distribution metadata. processing_agent/state should
        # carry these through in the next migration step.
        "spatial_coverage": spatial_coverage,

        "image_info": {
            "source": "Sentinel-2",
            "image_id": image_id,
            "source_image_ids": asset_paths,
            "source_tile_count": source_tile_count,
            "mosaic_policy": "same_datatake_only",
            "date": image_date,
            "image_age_days": image_age_days,
            "selected_is_latest_pass": selected_is_latest,
            "fallback_used": fallback_used,
            "no_recent_pass": no_recent_pass,
            "datatake_id": datatake_id,
            "observation_datetime_utc": observation_datetime,
            "latest_pass_date": latest_date,
            "latest_pass_datatake": latest_datatake,
            "latest_pass_fraction": (
                round(sel["latest_fraction"], 3)
                if sel.get("latest_fraction") is not None
                else None
            ),
            # Provenance only. Granule-wide, not farm-specific, and not
            # area weighted across tiles. Never show this as the field's
            # cloud cover; use field_clear_fraction for that.
            "source_granule_cloud_percent_mean": (
                source_granule_cloud_percent
            ),

            # Kept for backward compatibility; these describe the
            # ANALYSIS interior, not the drawn field.
            "valid_pixel_fraction": valid_pixel_fraction,
            "valid_pixel_count": valid_pixel_count,
            "coverage_tier": coverage_tier,
            "coverage_tier_rule": "worse_of_field_and_analysis",
            "field_coverage_tier": field_coverage_tier,
            "analysis_coverage_tier": analysis_coverage_tier,
            "zone_analysis_supported": zone_analysis_supported,

            "field_clear_fraction": field_coverage["clear_fraction"],
            "field_footprint_fraction": field_coverage[
                "observed_fraction"
            ],
            "analysis_clear_fraction": analysis_coverage[
                "clear_fraction"
            ],
            "analysis_footprint_fraction": analysis_coverage[
                "observed_fraction"
            ],
            "footprint_fraction_floor": MIN_FOOTPRINT_FRACTION,
            "coverage_denominator": "total_pixels_in_geometry",

            "assessment_scope": assessment_scope,
            "spatially_representative": spatially_representative,
            "distribution_score": spatial_coverage.get(
                "distribution_score"
            ),
            "observed_zone_count": spatial_coverage.get(
                "observed_zone_count"
            ),
            "eligible_zone_count": spatial_coverage.get(
                "eligible_zone_count"
            ),
            "analysis_scale_m": ANALYSIS_SCALE,
            "index_native_scale_m": INDEX_NATIVE_SCALE,
            "index_method": "explicit_arithmetic_negatives_preserved",
            "edge_buffer_m": edge_info.get("edge_buffer_m"),
            "edge_excluded": edge_info.get("edge_excluded"),
            "cloud_mask_method": "Cloud Score+ cs_cdf",
            "cloud_mask_threshold": CS_PLUS_THRESHOLD,
            "cloud_gap_policy": "leave_unobserved_pixels_gray",
            "map_observation_policy": "single_observation_date",
            "search_window_days": search_window_days,
            "search_window_start_utc": start_date,
            "query_end_date_exclusive_utc": end_date,
            "selection_mode": selection_mode,
            "candidate_count": candidate_count,
            "clean_candidate_count": clean_candidate_count,
            "recent_candidate_count": recent_candidate_count,
        },

        # Temporary backward-compatible support block. The future
        # historical_service.py will replace this with true dated,
        # current-season archive comparisons using absolute deltas and
        # eventually field/stage-normalized anomalies.
        "recent_comparison": {
            "comparison_method": "legacy_recent_composite_support_only",
            "decision_use": "do_not_use_as_historical_ground_truth",
            "enabled": INCLUDE_LEGACY_RECENT_COMPARISON,
            "recent_ndvi_composite": recent_ndvi,
            "recent_ndre_composite": recent_ndre,
            "recent_ndmi_composite": recent_ndmi,
            "recent_savi_composite": recent_savi,
            "recent_gndvi_composite": recent_gndvi,
            "recent_ndwi_composite": recent_ndmi,
            "ndvi_delta_recent": delta(selected_ndvi, recent_ndvi),
            "ndre_delta_recent": delta(selected_ndre, recent_ndre),
            "ndmi_delta_recent": delta(selected_ndmi, recent_ndmi),
            "savi_delta_recent": delta(selected_savi, recent_savi),
            "gndvi_delta_recent": delta(selected_gndvi, recent_gndvi),
            "ndwi_delta_recent": delta(selected_ndmi, recent_ndmi),
            "recent_condition_status": recent_condition_status,
        },
    }