import json
import re
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.auth.firebase_auth import get_current_user_id
from app.database import get_connection
from app.services.analysis.crop_context import (
    build_season_id,
    normalize_crop_key,
)

router = APIRouter()


# ── Step 3 helpers ─────────────────────────────────────────────────────────────

def _blank_to_none(value):
    """A browser form submits "" for an untouched field; that means absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_planting_date(value):
    """
    Optional. If supplied, must be exactly YYYY-MM-DD.

    The regex is not redundant with fromisoformat: on Python 3.11+ that
    function also accepts compact dates (20260501) and ISO week dates
    (2026-W18-5), which would make this validator quietly more
    permissive than its own error message. fromisoformat is still needed
    after the regex, because a regex cannot reject 2026-02-30.
    """
    text = _blank_to_none(value)
    if text is None:
        return None

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(
            "planting_date must be a calendar date in YYYY-MM-DD format."
        )

    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "planting_date must be a valid calendar date in YYYY-MM-DD "
            "format."
        ) from exc

    return text


def _bool_to_int(value):
    """
    Three-state boolean to SQLite INTEGER.

    decline_expected is True / False / None, and None means "no timing
    profile exists for this crop" — NOT False. int(value) or bool(value)
    would collapse None into 0, which asserts that a decline would be
    abnormal on a crop Tagintell has no calendar for.
    """
    if value is True:
        return 1
    if value is False:
        return 0
    return None


def _int_to_bool(value):
    """SQLite INTEGER back to three-state boolean, preserving NULL."""
    if value is None:
        return None
    return bool(value)


def _row_crop_fields(row) -> dict:
    """
    Crop snapshot from a farm_analyses row.

    sqlite3.Row raises IndexError on an unknown column rather than
    returning None, so a database that has not yet been migrated would
    crash the history endpoint. keys() is checked first.
    """
    available = set(row.keys())

    def get(name):
        return row[name] if name in available else None

    return {
        "crop_type": get("crop_type"),
        "planting_date": get("planting_date"),
        "irrigation_type": get("irrigation_type"),
        "season_id": get("season_id"),
        "days_after_planting": get("days_after_planting"),
        "timing_phase": get("timing_phase"),
        "cover_screen_mode": get("cover_screen_mode"),
        "decline_expected": _int_to_bool(get("decline_expected")),
        "has_crop_context": _int_to_bool(get("has_crop_context")),
    }


def get_unique_farm_name(conn, user_id: str, requested_name: str) -> str:
    """
    Make farm names unique for each user.

    Example:
    North Farm
    North Farm 1
    North Farm 2
    """
    base_name = requested_name.strip()

    cursor = conn.execute(
        """
        SELECT name
        FROM farms
        WHERE user_id = ?
          AND (name = ? OR name LIKE ?)
        """,
        (user_id, base_name, f"{base_name} %"),
    )

    existing_names = {row["name"] for row in cursor.fetchall()}

    if base_name not in existing_names:
        return base_name

    counter = 1

    while f"{base_name} {counter}" in existing_names:
        counter += 1

    return f"{base_name} {counter}"


# ── Request models ─────────────────────────────────────────────────────────────

class SaveFarmRequest(BaseModel):
    name: str
    polygon: List[List[float]]
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    area_ha: Optional[float] = None
    area_acres: Optional[float] = None

    # Step 3 — the farm's CURRENT crop cycle. All OPTIONAL.
    #
    # Every farm already saved has none of these, and a farmer must be
    # able to save a boundary before knowing what will go in it. Making
    # them required would break both cases.
    crop_type: Optional[str] = None
    planting_date: Optional[str] = None
    irrigation_type: Optional[str] = None
    season_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Farm name cannot be empty.")
        return v.strip()

    @field_validator(
        "crop_type",
        "irrigation_type",
        "season_id",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, v):
        return _blank_to_none(v)

    @field_validator("planting_date", mode="before")
    @classmethod
    def valid_optional_planting_date(cls, v):
        return _validate_planting_date(v)

    @field_validator("polygon")
    @classmethod
    def polygon_must_be_valid(cls, v: List[List[float]]) -> List[List[float]]:
        if len(v) < 4:
            raise ValueError("Polygon must have at least 4 coordinate pairs including the closing point.")

        for point in v:
            if len(point) != 2:
                raise ValueError("Each coordinate must be [longitude, latitude].")

            lon, lat = point

            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError(f"Coordinate out of range: {point}")

        if v[0] != v[-1]:
            v = v + [v[0]]

        return v


class RenameFarmRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Farm name cannot be empty.")
        return v.strip()


class UpdateFarmSeasonRequest(BaseModel):
    """
    Start or correct a crop cycle on an existing farm.

    Needed because a farm outlives its seasons. Without this, changing
    crop meant deleting and recreating the farm, which would take its
    whole analysis history with it.
    """
    crop_type: Optional[str] = None
    planting_date: Optional[str] = None
    irrigation_type: Optional[str] = None
    season_id: Optional[str] = None

    @field_validator("crop_type", "irrigation_type", "season_id", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        return _blank_to_none(v)

    @field_validator("planting_date", mode="before")
    @classmethod
    def valid_optional_planting_date(cls, v):
        return _validate_planting_date(v)


class SaveAnalysisRequest(BaseModel):
    farm_id: str

    # Classification / report
    stress_type: Optional[str] = None
    severity: Optional[str] = None
    attention_area: Optional[str] = None
    attention_source: Optional[str] = None
    confidence: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    action: Optional[str] = None
    recommendation: Optional[str] = None
    hotspot_summary: Optional[str] = None

    # Selected-image values
    ndvi: Optional[float] = None

    # Current moisture-condition index (B8A/B11).
    ndmi: Optional[float] = None

    # LEGACY NAME, accepted so the backend can be deployed before
    # page.tsx is updated. Until the frontend sends ndmi, it sends the
    # moisture value under this key, and ignoring it would leave a NULL
    # in every analysis saved in between — a permanent hole in the
    # history Step 4 is about to be built on.
    ndwi: Optional[float] = None

    ndre: Optional[float] = None
    savi: Optional[float] = None
    gndvi: Optional[float] = None

    # Step 3 — crop/season SNAPSHOT for this analysis.
    #
    # Stored separately from the farm row on purpose. The farm holds the
    # CURRENT season and is overwritten; these record what was true when
    # this analysis ran. A farmer correcting a mistyped planting date
    # must not silently rewrite the context of every past report.
    crop_type: Optional[str] = None
    planting_date: Optional[str] = None
    irrigation_type: Optional[str] = None
    season_id: Optional[str] = None
    days_after_planting: Optional[int] = None
    timing_phase: Optional[str] = None
    cover_screen_mode: Optional[str] = None

    # THREE-state. None means no timing profile for this crop, which is
    # not the same as False.
    decline_expected: Optional[bool] = None
    has_crop_context: Optional[bool] = None

    # Image metadata
    image_date: Optional[str] = None
    cloud_cover: Optional[float] = None
    search_window_start: Optional[str] = None
    search_window_end: Optional[str] = None
    selection_mode: Optional[str] = None
    candidate_count: Optional[int] = None
    clean_candidate_count: Optional[int] = None

    # Recent comparison layer
    recent_ndvi_composite: Optional[float] = None
    recent_ndre_composite: Optional[float] = None
    recent_ndwi_composite: Optional[float] = None
    recent_savi_composite: Optional[float] = None
    recent_gndvi_composite: Optional[float] = None

    ndvi_delta_recent: Optional[float] = None
    ndre_delta_recent: Optional[float] = None
    ndwi_delta_recent: Optional[float] = None
    savi_delta_recent: Optional[float] = None
    gndvi_delta_recent: Optional[float] = None

    recent_condition_status: Optional[str] = None


# ── Trend helpers ──────────────────────────────────────────────────────────────

def _to_float(value) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _moisture_value(analysis: dict):
    """
    Returns (value, source) for the moisture-condition signal.

    NDMI is authoritative. ndwi is read only for analyses saved before
    the ndmi column existed, and the source is returned rather than
    hidden: comparing a value read from one column against a value read
    from the other is the same class of mistake as comparing across
    seasons, so the caller is given what it needs to refuse.
    """
    ndmi = _to_float(analysis.get("ndmi"))
    if ndmi is not None:
        return ndmi, "ndmi"

    return _to_float(analysis.get("ndwi")), "ndwi_legacy"


def _severity_rank(severity: Optional[str]) -> int:
    order = {
        "none": 0,
        "mild": 1,
        "moderate": 2,
        "severe": 3,
    }

    return order.get((severity or "").lower(), 0)


def _compare_saved_analyses(latest: dict, previous: dict) -> dict:
    """
    Compare the newest saved analysis with the previous one and return
    a simple trend result.

    STEP 3 NOTE — decline_expected is carried in the result but is NOT
    used to soften a "weaker" verdict. Late-season timing explains why a
    reading might fall; it does not establish that the fall is harmless.
    A field can be both in its late-season window and genuinely failing.
    The flag is surfaced so the reader has the context, not so the code
    can suppress the finding.
    """
    latest_ndre = _to_float(latest.get("ndre"))
    previous_ndre = _to_float(previous.get("ndre"))

    latest_ndmi, latest_moisture_source = _moisture_value(latest)
    previous_ndmi, previous_moisture_source = _moisture_value(previous)

    # Both values must come from the same column. Today ndwi holds the
    # same measurement as ndmi, so this never fires — but it stops a
    # future change to either column from silently producing a delta
    # between two different indices.
    moisture_comparable = (
        latest_moisture_source == previous_moisture_source
    )

    latest_ndvi = _to_float(latest.get("ndvi"))
    previous_ndvi = _to_float(previous.get("ndvi"))

    latest_savi = _to_float(latest.get("savi"))
    previous_savi = _to_float(previous.get("savi"))

    latest_severity = _severity_rank(latest.get("severity"))
    previous_severity = _severity_rank(previous.get("severity"))

    ndre_change = (
        latest_ndre - previous_ndre
        if latest_ndre is not None and previous_ndre is not None
        else None
    )

    ndmi_change = (
        latest_ndmi - previous_ndmi
        if latest_ndmi is not None
        and previous_ndmi is not None
        and moisture_comparable
        else None
    )

    ndvi_change = (
        latest_ndvi - previous_ndvi
        if latest_ndvi is not None and previous_ndvi is not None
        else None
    )

    savi_change = (
        latest_savi - previous_savi
        if latest_savi is not None and previous_savi is not None
        else None
    )

    notes: List[str] = []
    improving_signals = 0
    worsening_signals = 0

    # NDRE = main crop-condition signal
    if ndre_change is not None:
        if ndre_change >= 0.03:
            improving_signals += 1
            notes.append("crop condition improved slightly")
        elif ndre_change <= -0.03:
            worsening_signals += 1
            notes.append("crop condition looks slightly weaker")

    # NDMI = moisture condition signal
    if ndmi_change is not None:
        if ndmi_change >= 0.05:
            improving_signals += 1
            notes.append("moisture condition improved slightly")
        elif ndmi_change <= -0.05:
            worsening_signals += 1
            notes.append("moisture condition looks slightly weaker")

    # NDVI = broader vegetation signal
    if ndvi_change is not None:
        if ndvi_change >= 0.04:
            improving_signals += 1
        elif ndvi_change <= -0.04:
            worsening_signals += 1

    # SAVI = sparse canopy support
    if savi_change is not None:
        if savi_change >= 0.04:
            improving_signals += 1
        elif savi_change <= -0.04:
            worsening_signals += 1

    # Severity comparison
    if latest_severity > previous_severity:
        worsening_signals += 1
        notes.append("overall concern level increased")
    elif latest_severity < previous_severity:
        improving_signals += 1
        notes.append("overall concern level eased")

    # Persistent hotspot
    if (
        latest.get("attention_area")
        and previous.get("attention_area")
        and latest.get("attention_area") == previous.get("attention_area")
    ):
        notes.append("the same area is still being flagged")

    if worsening_signals >= 2 and improving_signals == 0:
        trend_status = "weaker"
        trend_summary = "Conditions look weaker since the last analysis."
    elif improving_signals >= 2 and worsening_signals == 0:
        trend_status = "improving"
        trend_summary = "Conditions look better since the last analysis."
    elif worsening_signals == 0 and improving_signals == 0:
        trend_status = "stable"
        trend_summary = "Conditions look mostly stable since the last analysis."
    else:
        trend_status = "mixed"
        trend_summary = "Some signals improved while others weakened since the last analysis."

    if notes:
        note_label = "Main change" if len(notes) == 1 else "Main changes"
        trend_summary += f" {note_label}: " + "; ".join(notes) + "."

    # Context, appended after the verdict rather than altering it.
    #
    # Convert FIRST. sqlite3.Row hands back the raw INTEGER, so this
    # value is 1, not True — and `1 is True` is False in Python. Testing
    # identity against the raw column silently disables the whole branch,
    # which is the worst kind of failure: no error, no output, and a
    # helper sitting right there that looks like it was used.
    latest_decline_expected = _int_to_bool(latest.get("decline_expected"))

    if latest_decline_expected is True:
        trend_summary += (
            " This observation falls within the crop's broad late-season "
            "calendar window, so natural maturity may be contributing. "
            "Timing alone does not show that the change is normal."
        )

    return {
        "trend_status": trend_status,
        "trend_summary": trend_summary,
        "latest_analysis_id": latest.get("id"),
        "previous_analysis_id": previous.get("id"),
        "latest_analyzed_at": latest.get("analyzed_at"),
        "previous_analyzed_at": previous.get("analyzed_at"),
        "season_id": latest.get("season_id"),
        "decline_expected": latest_decline_expected,
        "changes": {
            "ndre_change": round(ndre_change, 4) if ndre_change is not None else None,

            # Both keys emitted during the transition. page.tsx may
            # still read the old one, and a silently missing field there
            # renders as a blank rather than raising.
            "ndmi_change": round(ndmi_change, 4) if ndmi_change is not None else None,
            "ndwi_change": round(ndmi_change, 4) if ndmi_change is not None else None,
            "ndvi_change": round(ndvi_change, 4) if ndvi_change is not None else None,
            "savi_change": round(savi_change, 4) if savi_change is not None else None,
            "severity_change": latest_severity - previous_severity,
            "days_after_planting_change": (
                latest.get("days_after_planting") - previous.get("days_after_planting")
                if latest.get("days_after_planting") is not None
                and previous.get("days_after_planting") is not None
                else None
            ),
        },
    }


# ── Farm routes ────────────────────────────────────────────────────────────────

@router.post("/farms")
def save_farm(payload: SaveFarmRequest, request: Request):
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        farm_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        unique_name = get_unique_farm_name(conn, user_id, payload.name)

        center_lat = payload.center_lat
        center_lng = payload.center_lng

        if center_lat is None or center_lng is None:
            lats = [p[1] for p in payload.polygon]
            lngs = [p[0] for p in payload.polygon]
            center_lat = round(sum(lats) / len(lats), 6)
            center_lng = round(sum(lngs) / len(lngs), 6)

        # Generated only when a planting date exists — a season without
        # one has nothing to anchor it. crop_context is the single place
        # that normalises "Maize" and "corn" onto one key, so the same
        # crop always yields the same season id.
        season_id = build_season_id(
            supplied_season_id=payload.season_id,
            crop_key=normalize_crop_key(payload.crop_type),
            planting_date=(
                date.fromisoformat(payload.planting_date)
                if payload.planting_date
                else None
            ),
        )

        conn.execute("""
            INSERT INTO farms
            (
                id, user_id, name, polygon, center_lat, center_lng,
                area_ha, area_acres,
                crop_type, planting_date, irrigation_type, season_id,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            farm_id,
            user_id,
            unique_name,
            json.dumps(payload.polygon),
            center_lat,
            center_lng,
            payload.area_ha,
            payload.area_acres,
            payload.crop_type,
            payload.planting_date,
            payload.irrigation_type,
            season_id,
            now,
            now,
        ))

        conn.commit()

        return {
            "id": farm_id,
            "user_id": user_id,
            "name": unique_name,
            "polygon": payload.polygon,
            "center_lat": center_lat,
            "center_lng": center_lng,
            "area_ha": payload.area_ha,
            "area_acres": payload.area_acres,
            "crop_type": payload.crop_type,
            "planting_date": payload.planting_date,
            "irrigation_type": payload.irrigation_type,
            "season_id": season_id,
            "created_at": now,
            "updated_at": now,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save farm: {str(e)}")
    finally:
        conn.close()


@router.get("/farms")
def list_farms(request: Request):
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id, user_id, name, center_lat, center_lng,
                   area_ha, area_acres,
                   crop_type, planting_date, irrigation_type, season_id,
                   created_at, updated_at
            FROM farms
            WHERE user_id = ? OR user_id IS NULL
            ORDER BY updated_at DESC
        """, (user_id,))

        farms = []

        for row in cursor.fetchall():
            farms.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "name": row["name"],
                "center_lat": row["center_lat"],
                "center_lng": row["center_lng"],
                "area_ha": row["area_ha"],
                "area_acres": row["area_acres"],
                "crop_type": row["crop_type"],
                "planting_date": row["planting_date"],
                "irrigation_type": row["irrigation_type"],
                "season_id": row["season_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })

        return {"farms": farms}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list farms: {str(e)}")
    finally:
        conn.close()


@router.get("/farms/{farm_id}")
def get_farm(farm_id: str, request: Request):
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT *
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Farm not found.")

        available = set(row.keys())

        def crop(name):
            return row[name] if name in available else None

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "name": row["name"],
            "polygon": json.loads(row["polygon"]),
            "center_lat": row["center_lat"],
            "center_lng": row["center_lng"],
            "area_ha": row["area_ha"],
            "area_acres": row["area_acres"],
            "crop_type": crop("crop_type"),
            "planting_date": crop("planting_date"),
            "irrigation_type": crop("irrigation_type"),
            "season_id": crop("season_id"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get farm: {str(e)}")
    finally:
        conn.close()


@router.put("/farms/{farm_id}/season")
def update_farm_season(
    farm_id: str,
    payload: UpdateFarmSeasonRequest,
    request: Request,
):
    """
    Start a new crop cycle on an existing farm, or correct the current
    one.

    Only the farm row changes. Past analyses keep their own snapshot, so
    correcting a mistyped planting date does not retroactively rewrite
    the context of reports that were produced under the old value.
    """
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Farm not found.")

        now = datetime.now(timezone.utc).isoformat()

        season_id = build_season_id(
            supplied_season_id=payload.season_id,
            crop_key=normalize_crop_key(payload.crop_type),
            planting_date=(
                date.fromisoformat(payload.planting_date)
                if payload.planting_date
                else None
            ),
        )

        # Direct assignment, not COALESCE. This endpoint exists to
        # CHANGE the season, and COALESCE would make clearing a field
        # impossible — a farmer who removed a wrong planting date would
        # silently keep it.
        conn.execute("""
            UPDATE farms
            SET crop_type = ?,
                planting_date = ?,
                irrigation_type = ?,
                season_id = ?,
                updated_at = ?,
                user_id = COALESCE(user_id, ?)
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (
            payload.crop_type,
            payload.planting_date,
            payload.irrigation_type,
            season_id,
            now,
            user_id,
            farm_id,
            user_id,
        ))

        conn.commit()

        return {
            "message": "Farm season updated.",
            "crop_type": payload.crop_type,
            "planting_date": payload.planting_date,
            "irrigation_type": payload.irrigation_type,
            "season_id": season_id,
            "updated_at": now,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update season: {str(e)}")
    finally:
        conn.close()


@router.put("/farms/{farm_id}/rename")
def rename_farm(farm_id: str, payload: RenameFarmRequest, request: Request):
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Farm not found.")

        now = datetime.now(timezone.utc).isoformat()
        unique_name = get_unique_farm_name(conn, user_id, payload.name)

        conn.execute("""
            UPDATE farms
            SET name = ?, updated_at = ?, user_id = COALESCE(user_id, ?)
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (
            unique_name,
            now,
            user_id,
            farm_id,
            user_id,
        ))

        conn.commit()

        return {
            "message": "Farm renamed successfully.",
            "name": unique_name,
            "updated_at": now,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename farm: {str(e)}")
    finally:
        conn.close()


@router.delete("/farms/{farm_id}")
def delete_farm(farm_id: str, request: Request):
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Farm not found.")

        conn.execute("""
            DELETE FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        conn.commit()

        return {"message": "Farm deleted successfully."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete farm: {str(e)}")
    finally:
        conn.close()


# ── Analysis history routes ────────────────────────────────────────────────────

@router.post("/farms/analysis/save")
def save_analysis(payload: SaveAnalysisRequest, request: Request):
    """
    Save a comparison-ready analysis result linked to a saved farm.
    """
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (payload.farm_id, user_id))

        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Farm not found. Save the farm first.")

        analysis_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # NDMI is the moisture-condition index. The frontend still sends
        # it under the legacy "ndwi" key, so take whichever arrived and
        # write it to BOTH columns.
        #
        # Writing both is deliberate and temporary. If only ndmi were
        # written, every analysis saved between deploying this backend
        # and updating page.tsx would store NULL for moisture — a
        # permanent gap in the history Step 4 depends on. Once the
        # frontend sends ndmi, stop writing ndwi.
        moisture_value = (
            payload.ndmi if payload.ndmi is not None else payload.ndwi
        )

        # Columns and values as parallel tuples with generated
        # placeholders. The previous version had 37 question marks
        # counted by hand against 37 values; adding nine crop columns to
        # that would be a silent-misalignment waiting to happen, and a
        # mismatch there writes the right values into the wrong columns
        # without raising.
        analysis_columns = (
            "id",
            "user_id",
            "farm_id",
            "analyzed_at",

            "stress_type",
            "severity",
            "attention_area",
            "attention_source",
            "confidence",

            "title",
            "summary",
            "action",
            "recommendation",
            "hotspot_summary",

            "ndvi",
            "ndmi",
            "ndwi",
            "ndre",
            "savi",
            "gndvi",

            "crop_type",
            "planting_date",
            "irrigation_type",
            "season_id",
            "days_after_planting",
            "timing_phase",
            "cover_screen_mode",
            "decline_expected",
            "has_crop_context",

            "image_date",
            "cloud_cover",
            "search_window_start",
            "search_window_end",
            "selection_mode",
            "candidate_count",
            "clean_candidate_count",

            "recent_ndvi_composite",
            "recent_ndre_composite",
            "recent_ndwi_composite",
            "recent_savi_composite",
            "recent_gndvi_composite",

            "ndvi_delta_recent",
            "ndre_delta_recent",
            "ndwi_delta_recent",
            "savi_delta_recent",
            "gndvi_delta_recent",

            "recent_condition_status",
        )

        analysis_values = (
            analysis_id,
            user_id,
            payload.farm_id,
            now,

            payload.stress_type,
            payload.severity,
            payload.attention_area,
            payload.attention_source,
            payload.confidence,

            payload.title,
            payload.summary,
            payload.action,
            payload.recommendation,
            payload.hotspot_summary,

            payload.ndvi,
            moisture_value,
            moisture_value,
            payload.ndre,
            payload.savi,
            payload.gndvi,

            payload.crop_type,
            payload.planting_date,
            payload.irrigation_type,
            payload.season_id,
            payload.days_after_planting,
            payload.timing_phase,
            payload.cover_screen_mode,
            _bool_to_int(payload.decline_expected),
            _bool_to_int(payload.has_crop_context),

            payload.image_date,
            payload.cloud_cover,
            payload.search_window_start,
            payload.search_window_end,
            payload.selection_mode,
            payload.candidate_count,
            payload.clean_candidate_count,

            payload.recent_ndvi_composite,
            payload.recent_ndre_composite,
            payload.recent_ndwi_composite,
            payload.recent_savi_composite,
            payload.recent_gndvi_composite,

            payload.ndvi_delta_recent,
            payload.ndre_delta_recent,
            payload.ndwi_delta_recent,
            payload.savi_delta_recent,
            payload.gndvi_delta_recent,

            payload.recent_condition_status,
        )

        if len(analysis_columns) != len(analysis_values):
            raise RuntimeError(
                "Analysis column/value mismatch: "
                f"{len(analysis_columns)} columns, "
                f"{len(analysis_values)} values."
            )

        placeholders = ", ".join("?" for _ in analysis_values)
        column_sql = ", ".join(analysis_columns)

        conn.execute(
            f"INSERT INTO farm_analyses ({column_sql}) "
            f"VALUES ({placeholders})",
            analysis_values,
        )

        # COALESCE here, unlike the season endpoint. Saving an analysis
        # should backfill crop details onto a farm that has none, but
        # must never overwrite what the farmer set — the analysis may be
        # from an older season.
        conn.execute("""
            UPDATE farms
            SET updated_at = ?,
                user_id = COALESCE(user_id, ?),
                crop_type = COALESCE(crop_type, ?),
                planting_date = COALESCE(planting_date, ?),
                irrigation_type = COALESCE(irrigation_type, ?),
                season_id = COALESCE(season_id, ?)
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (
            now,
            user_id,
            payload.crop_type,
            payload.planting_date,
            payload.irrigation_type,
            payload.season_id,
            payload.farm_id,
            user_id,
        ))

        conn.commit()

        return {
            "id": analysis_id,
            "user_id": user_id,
            "analyzed_at": now,
            "season_id": payload.season_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save analysis: {str(e)}")
    finally:
        conn.close()


@router.get("/farms/{farm_id}/history")
def get_farm_history(farm_id: str, request: Request):
    """
    Get analysis history for one farm — newest first, max 20 records.
    """
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Farm not found.")

        cursor = conn.execute("""
            SELECT *
            FROM farm_analyses
            WHERE farm_id = ?
              AND (user_id = ? OR user_id IS NULL)
            ORDER BY analyzed_at DESC
            LIMIT 20
        """, (farm_id, user_id))

        history = []

        for row in cursor.fetchall():
            record = {
                "id": row["id"],
                "user_id": row["user_id"],
                "analyzed_at": row["analyzed_at"],
                "stress_type": row["stress_type"],
                "severity": row["severity"],
                "attention_area": row["attention_area"],
                "attention_source": row["attention_source"],
                "confidence": row["confidence"],
                "title": row["title"],
                "summary": row["summary"],
                "action": row["action"],
                "recommendation": row["recommendation"],
                "hotspot_summary": row["hotspot_summary"],
                "ndvi": row["ndvi"],

                # Resolved through the same helper the trend uses, so a
                # reader never has to know which column a given row
                # happens to have populated.
                "ndmi": _moisture_value(dict(row))[0],
                "moisture_source": _moisture_value(dict(row))[1],

                # Raw legacy column, retained for technical review.
                "ndwi": row["ndwi"],

                "ndre": row["ndre"],
                "savi": row["savi"],
                "gndvi": row["gndvi"],
                "image_date": row["image_date"],
                "cloud_cover": row["cloud_cover"],
                "search_window_start": row["search_window_start"],
                "search_window_end": row["search_window_end"],
                "selection_mode": row["selection_mode"],
                "candidate_count": row["candidate_count"],
                "clean_candidate_count": row["clean_candidate_count"],
                "recent_ndvi_composite": row["recent_ndvi_composite"],
                "recent_ndre_composite": row["recent_ndre_composite"],
                "recent_ndwi_composite": row["recent_ndwi_composite"],
                "recent_savi_composite": row["recent_savi_composite"],
                "recent_gndvi_composite": row["recent_gndvi_composite"],
                "ndvi_delta_recent": row["ndvi_delta_recent"],
                "ndre_delta_recent": row["ndre_delta_recent"],
                "ndwi_delta_recent": row["ndwi_delta_recent"],
                "savi_delta_recent": row["savi_delta_recent"],
                "gndvi_delta_recent": row["gndvi_delta_recent"],
                "recent_condition_status": row["recent_condition_status"],
            }

            record.update(_row_crop_fields(row))
            history.append(record)

        return {
            "farm_id": farm_id,
            "history": history,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get history: {str(e)}")
    finally:
        conn.close()


@router.get("/farms/{farm_id}/trend")
def get_farm_trend(farm_id: str, request: Request):
    """
    Compare the latest saved analysis with the previous saved analysis
    for the same farm and return a simple trend summary.
    """
    user_id = get_current_user_id(request)
    conn = get_connection()

    try:
        cursor = conn.execute("""
            SELECT id, name
            FROM farms
            WHERE id = ?
              AND (user_id = ? OR user_id IS NULL)
        """, (farm_id, user_id))

        farm_row = cursor.fetchone()

        if not farm_row:
            raise HTTPException(status_code=404, detail="Farm not found.")

        cursor = conn.execute("""
            SELECT *
            FROM farm_analyses
            WHERE farm_id = ?
              AND (user_id = ? OR user_id IS NULL)
            ORDER BY analyzed_at DESC
            LIMIT 2
        """, (farm_id, user_id))

        rows = cursor.fetchall()

        if len(rows) == 0:
            return {
                "farm_id": farm_id,
                "farm_name": farm_row["name"],
                "trend_status": "no_history",
                "trend_summary": "No saved analysis history yet for this farm.",
                "changes": {},
            }

        if len(rows) == 1:
            return {
                "farm_id": farm_id,
                "farm_name": farm_row["name"],
                "trend_status": "first_saved_check",
                "trend_summary": "This is your first saved analysis. Run another analysis later on this same farm to compare changes over time.",
                "latest_analysis_id": rows[0]["id"],
                "latest_analyzed_at": rows[0]["analyzed_at"],
                "changes": {},
            }

        latest = dict(rows[0])
        previous = dict(rows[1])

        # STEP 3 GUARD — only compare analyses from the SAME season.
        #
        # This endpoint compares index values directly. Corn in August
        # and soybean the following June sit at completely different
        # points in completely different crops, and the difference
        # between them is not a trend in anything.
        #
        # The test is plain inequality, not `both present and different`.
        # That earlier form had a gap: a pre-Step-3 analysis has
        # season_id NULL, so pairing it with a new crop-aware one made
        # the condition False and the two were compared anyway — despite
        # there being no evidence they belong to the same crop cycle.
        #
        # Four cases, and inequality handles all of them:
        #   same id            -> compare
        #   both NULL          -> compare (pre-Step-3 legacy behaviour)
        #   one NULL, one set  -> refuse, season cannot be established
        #   both set, differ   -> refuse, different crop cycles
        latest_season = latest.get("season_id")
        previous_season = previous.get("season_id")

        if latest_season != previous_season:
            return {
                "farm_id": farm_id,
                "farm_name": farm_row["name"],
                "trend_status": "season_mismatch",
                "trend_summary": (
                    "The last two saved analyses do not have matching "
                    "crop-season information, so they cannot be compared "
                    "directly. Run another analysis within the current "
                    "season to track changes over time."
                ),
                "latest_analysis_id": latest.get("id"),
                "previous_analysis_id": previous.get("id"),
                "latest_analyzed_at": latest.get("analyzed_at"),
                "previous_analyzed_at": previous.get("analyzed_at"),
                "latest_season_id": latest_season,
                "previous_season_id": previous_season,
                "changes": {},
            }

        trend_result = _compare_saved_analyses(latest, previous)

        return {
            "farm_id": farm_id,
            "farm_name": farm_row["name"],
            **trend_result,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get trend: {str(e)}")
    finally:
        conn.close()