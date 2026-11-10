import os
import sqlite3

# Treat as starter storage
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tagit.db")


# ---------------------------------------------------------------------
# Season sentinel
# ---------------------------------------------------------------------
#
# sentinel_history_observations.season_id is NOT NULL on purpose.
#
# SQLite treats every NULL as DISTINCT inside a UNIQUE constraint, so a
# nullable season_id would not block duplicates — it would silently
# allow the same datatake to be inserted on every backfill, for exactly
# the farms most likely to be tested first. NOT NULL fails loudly
# instead, which is the safer failure.
#
# But build_season_id() returns None when a farm has no planting date,
# and that describes every farm currently in the database. Those rows
# get this sentinel rather than a NULL.
#
# CONSEQUENCE worth knowing: when that farmer later adds a planting
# date, their season becomes something like "corn-20260501" and the
# whole "no-season" backfill is orphaned. historical_service.py should
# either re-key those rows or rebuild the series at that point.
NO_SEASON = "no-season"


def get_connection():
    """
    Get a database connection.
    - row_factory returns rows as dicts instead of tuples
    - PRAGMA foreign_keys = ON enforces foreign key constraints
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _get_existing_columns(cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    rows = cursor.fetchall()
    return {row["name"] for row in rows}


def _add_missing_columns(
    cursor,
    table_name: str,
    required_columns: dict[str, str],
):
    existing_columns = _get_existing_columns(cursor, table_name)

    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} {column_type}"
            )


def initialize_database():
    """
    Create all tables on startup if they do not exist.

    Step 3 keeps crop context optional and stores crop/season snapshots
    on individual saved analyses.

    Step 4 adds persistent Sentinel archive observations. Historical
    rows store measurements and provenance only. Satellite imagery
    remains in Google Earth Engine and is not copied into the local
    database.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # -----------------------------------------------------------------
    # Farms
    # -----------------------------------------------------------------
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS farms (
            id          TEXT PRIMARY KEY,
            user_id     TEXT,
            name        TEXT NOT NULL,
            polygon     TEXT NOT NULL,
            center_lat  REAL,
            center_lng  REAL,
            area_ha     REAL,
            area_acres  REAL,

            -- Step 3: the farm's CURRENT crop cycle.
            -- Each saved analysis keeps its own snapshot separately.
            crop_type       TEXT,
            planting_date   TEXT,
            irrigation_type TEXT,
            season_id       TEXT,

            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )

    # -----------------------------------------------------------------
    # Farmer-triggered saved analyses
    # -----------------------------------------------------------------
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS farm_analyses (
            id                      TEXT PRIMARY KEY,
            user_id                 TEXT,
            farm_id                 TEXT NOT NULL,
            analyzed_at             TEXT NOT NULL,

            stress_type             TEXT,
            severity                TEXT,
            attention_area          TEXT,
            attention_source        TEXT,
            confidence              TEXT,

            title                   TEXT,
            summary                 TEXT,
            action                  TEXT,
            recommendation          TEXT,
            hotspot_summary         TEXT,

            ndvi                    REAL,

            -- LEGACY NAME.
            -- Older rows hold the moisture-condition measurement here.
            ndwi                    REAL,

            -- Current authoritative moisture-condition index.
            ndmi                    REAL,

            ndre                    REAL,
            savi                    REAL,
            gndvi                   REAL,

            -- Step 3 crop/season snapshot.
            crop_type               TEXT,
            planting_date           TEXT,
            irrigation_type         TEXT,
            season_id               TEXT,
            days_after_planting     INTEGER,
            timing_phase            TEXT,
            cover_screen_mode       TEXT,

            -- THREE-state:
            --   NULL = timing could not be determined
            --   0    = broad late-season decline not expected
            --   1    = broad late-season decline may be expected
            decline_expected        INTEGER,
            has_crop_context        INTEGER,

            image_date              TEXT,

            -- Legacy orphaned field retained for compatibility.
            -- Do not start writing farm cloud coverage here again.
            cloud_cover             REAL,

            search_window_start     TEXT,
            search_window_end       TEXT,
            selection_mode          TEXT,
            candidate_count         INTEGER,
            clean_candidate_count   INTEGER,

            recent_ndvi_composite   REAL,
            recent_ndre_composite   REAL,
            recent_ndwi_composite   REAL,
            recent_savi_composite   REAL,
            recent_gndvi_composite  REAL,

            ndvi_delta_recent       REAL,
            ndre_delta_recent       REAL,
            ndwi_delta_recent       REAL,
            savi_delta_recent       REAL,
            gndvi_delta_recent      REAL,

            recent_condition_status TEXT,

            FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE CASCADE
        )
        """
    )

    # -----------------------------------------------------------------
    # Step 4A: persistent Sentinel archive observations
    # -----------------------------------------------------------------
    #
    # IMPORTANT:
    #
    # This table stores NUMBERS AND PROVENANCE, not Sentinel imagery.
    #
    # One row represents one Sentinel datatake measured over one saved
    # farm during one crop season. A row is roughly 1-1.5 KB, so a
    # 15-observation season costs about 20 KB per farm.
    #
    # It is NOT the same thing as farm_analyses. That table records
    # reports the farmer asked for — sparse, irregular, driven by when
    # someone happened to click Analyze. This one is the dense, regular
    # archive series the satellite produced whether anyone looked or
    # not. Persistent-pattern detection needs the second kind: "lower in
    # 5 of the last 6 clear observations" means nothing when there are
    # only three observations in total.
    #
    # The combination:
    #
    #     farm_id + season_id + datatake_id
    #
    # is unique, so the same acquisition cannot be inserted twice when
    # historical_service.py runs again.
    #
    # polygon_hash records the exact farm boundary used for the
    # measurement, and is deliberately NOT part of that unique key.
    #
    # That makes rebuild MANDATORY rather than optional. If the boundary
    # changes, re-measuring the same datatake raises IntegrityError, so
    # historical_service.py must DELETE the farm+season rows before
    # inserting. Appending is impossible by construction, which is the
    # intent: the 3x3 zone grid derives from the bounding box, so
    # "northwest" under an old boundary and a new one are different
    # places, and mixing them would corrupt every persistent-pattern
    # result.
    # -----------------------------------------------------------------
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sentinel_history_observations (
            id                          TEXT PRIMARY KEY,
            user_id                     TEXT,
            farm_id                     TEXT NOT NULL,

            -- NOT NULL on purpose. SQLite treats NULLs as distinct in a
            -- UNIQUE constraint, so a nullable season_id would silently
            -- permit duplicate rows instead of blocking them. A farm
            -- with no planting date uses the NO_SEASON sentinel defined
            -- at the top of this module.
            season_id                   TEXT NOT NULL,

            -- Hash of the full farm polygon used for this observation.
            polygon_hash                TEXT NOT NULL,

            -- Sentinel acquisition identity and date.
            datatake_id                 TEXT NOT NULL,
            observation_date            TEXT NOT NULL,
            observation_datetime_utc    TEXT,

            -- Exact source Sentinel assets used by the same-datatake
            -- mosaic. Stored as JSON text.
            source_image_ids            TEXT,
            source_tile_count           INTEGER,

            -- Five same-date index measurements.
            ndvi                        REAL,
            ndmi                        REAL,
            ndre                        REAL,
            savi                        REAL,
            gndvi                       REAL,

            -- Full drawn-field coverage.
            field_clear_fraction        REAL,
            field_footprint_fraction    REAL,
            field_coverage_tier         TEXT,

            -- Edge-buffered analysis-interior coverage.
            analysis_clear_fraction     REAL,
            analysis_footprint_fraction REAL,
            analysis_coverage_tier      TEXT,

            -- Conservative combined coverage result.
            coverage_tier               TEXT,
            assessment_scope            TEXT,

            -- This must be TRUE for rows accepted into historical
            -- analysis. measure_sentinel2_observation() silently falls
            -- back to the interior geometry when display_polygon is
            -- omitted, which makes every coverage figure a tier too
            -- optimistic. historical_service.py must reject such rows:
            -- one optimistic row poisons every z-score computed against
            -- the series.
            field_geometry_supplied     INTEGER NOT NULL,

            valid_pixel_fraction        REAL,
            valid_pixel_count           INTEGER,

            -- Spatial quality / zone support.
            zone_analysis_supported     INTEGER,
            eligible_zone_count         INTEGER,
            spatially_representative    INTEGER,
            distribution_score          REAL,

            -- JSON snapshots used later by persistent-pattern analysis.
            zone_values                 TEXT,
            zone_pixel_counts           TEXT,
            spatial_coverage            TEXT,
            variation_spread            TEXT,

            -- Same-date spatial finding from this observation.
            attention_area              TEXT,
            attention_source            TEXT,
            attention_is_distinct       INTEGER,

            -- Crop timing AT THIS OBSERVATION, not today.
            --
            -- Cannot be recomputed later: the planting date may have
            -- been corrected since, and correcting it must not rewrite
            -- the timing of measurements already taken. Without these
            -- the series can only be plotted against the calendar, and
            -- Step 5 comparisons "at a similar stage" become
            -- impossible.
            days_after_planting         INTEGER,
            timing_phase                TEXT,

            -- Measurement provenance.
            --
            -- If any of these change between versions, older rows stop
            -- being comparable with newer ones — and without recording
            -- them there is no way to detect that retroactively.
            --
            -- edge_excluded matters most: a small or thin field falls
            -- back to the unbuffered polygon, and a series that
            -- silently mixes buffered and unbuffered measurements is
            -- not one series.
            analysis_scale_m            INTEGER,
            edge_buffer_m               INTEGER,
            edge_excluded               INTEGER,
            cloud_mask_threshold        REAL,
            index_method                TEXT,

            -- When Tagintell calculated and stored this row.
            created_at                  TEXT NOT NULL,

            FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE CASCADE,

            UNIQUE (
                farm_id,
                season_id,
                datatake_id
            )
        )
        """
    )

    # -----------------------------------------------------------------
    # Upgrade existing farms table
    # -----------------------------------------------------------------
    required_farm_columns = {
        "user_id": "TEXT",

        # Step 3
        "crop_type": "TEXT",
        "planting_date": "TEXT",
        "irrigation_type": "TEXT",
        "season_id": "TEXT",
    }

    _add_missing_columns(
        cursor,
        "farms",
        required_farm_columns,
    )

    # -----------------------------------------------------------------
    # Upgrade existing farm_analyses table
    # -----------------------------------------------------------------
    required_analysis_columns = {
        "user_id": "TEXT",
        "attention_source": "TEXT",
        "confidence": "TEXT",
        "title": "TEXT",
        "action": "TEXT",
        "recommendation": "TEXT",
        "hotspot_summary": "TEXT",
        "savi": "REAL",
        "gndvi": "REAL",

        # Current moisture-condition index.
        # ndwi remains for older rows.
        "ndmi": "REAL",

        "search_window_start": "TEXT",
        "search_window_end": "TEXT",
        "selection_mode": "TEXT",
        "candidate_count": "INTEGER",
        "clean_candidate_count": "INTEGER",
        "recent_ndvi_composite": "REAL",
        "recent_ndre_composite": "REAL",
        "recent_ndwi_composite": "REAL",
        "recent_savi_composite": "REAL",
        "recent_gndvi_composite": "REAL",
        "ndvi_delta_recent": "REAL",
        "ndre_delta_recent": "REAL",
        "ndwi_delta_recent": "REAL",
        "savi_delta_recent": "REAL",
        "gndvi_delta_recent": "REAL",
        "recent_condition_status": "TEXT",

        # Step 3 crop/season snapshot.
        "crop_type": "TEXT",
        "planting_date": "TEXT",
        "irrigation_type": "TEXT",
        "season_id": "TEXT",
        "days_after_planting": "INTEGER",
        "timing_phase": "TEXT",
        "cover_screen_mode": "TEXT",
        "decline_expected": "INTEGER",
        "has_crop_context": "INTEGER",
    }

    _add_missing_columns(
        cursor,
        "farm_analyses",
        required_analysis_columns,
    )

    # -----------------------------------------------------------------
    # Upgrade existing sentinel_history_observations table
    # -----------------------------------------------------------------
    #
    # The new table needs the same upgrade path as the old two. Without
    # this, a column added in 4B or 4C would never reach a database
    # where the table already exists — CREATE TABLE IF NOT EXISTS sees
    # the table and does nothing, and the missing column surfaces as a
    # runtime error during a backfill rather than at startup.
    #
    # NOT NULL columns cannot be added this way once rows exist, so
    # anything listed here must be nullable.
    required_history_columns = {
        "user_id": "TEXT",

        "days_after_planting": "INTEGER",
        "timing_phase": "TEXT",

        "analysis_scale_m": "INTEGER",
        "edge_buffer_m": "INTEGER",
        "edge_excluded": "INTEGER",
        "cloud_mask_threshold": "REAL",
        "index_method": "TEXT",

        "spatial_coverage": "TEXT",
        "variation_spread": "TEXT",

        "attention_area": "TEXT",
        "attention_source": "TEXT",
        "attention_is_distinct": "INTEGER",
    }

    _add_missing_columns(
        cursor,
        "sentinel_history_observations",
        required_history_columns,
    )

    # -----------------------------------------------------------------
    # Existing analysis indexes
    # -----------------------------------------------------------------
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_farm_analyses_farm_date
        ON farm_analyses (
            farm_id,
            analyzed_at DESC
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_farm_analyses_season
        ON farm_analyses (
            farm_id,
            season_id
        )
        """
    )

    # -----------------------------------------------------------------
    # Step 4 historical indexes
    # -----------------------------------------------------------------

    # Main historical query:
    #
    #   "Give me this farm's observations for this season in date order."
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sentinel_history_farm_season_date
        ON sentinel_history_observations (
            farm_id,
            season_id,
            observation_date
        )
        """
    )

    # Used to quickly check whether the current farm boundary still
    # matches the boundary used to build its historical series.
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sentinel_history_polygon
        ON sentinel_history_observations (
            farm_id,
            season_id,
            polygon_hash
        )
        """
    )

    # Incremental backfill asks "what is the newest observation already
    # stored for this farm and season?" before discovering candidates,
    # so it can measure only what is new.
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sentinel_history_latest
        ON sentinel_history_observations (
            farm_id,
            season_id,
            observation_date DESC
        )
        """
    )

    conn.commit()
    conn.close()