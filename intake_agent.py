from typing import Dict, List

from app.services.agents.state import FarmWatchState


def _calculate_bbox(polygon: List[List[float]]) -> Dict[str, float]:
    lons = [point[0] for point in polygon]
    lats = [point[1] for point in polygon]

    return {
        "min_lon": min(lons),
        "max_lon": max(lons),
        "min_lat": min(lats),
        "max_lat": max(lats),
    }


def _has_nonzero_area(ring: List[List[float]]) -> bool:
    """
    Whether the polygon encloses a non-zero area.

    Uses the shoelace formula purely as a geometry-validity test — it
    answers "does this shape enclose anything at all?" and nothing more.
    It is NOT the farm area calculation. Actual hectares and acres are
    computed geodesically on the WGS84 ellipsoid in gee.py.

    This catches the case that distinctness and self-intersection checks
    both miss: three genuinely different points lying on one straight
    line. A—B—C are distinct and do not cross, but enclose no field.

    Ring is expected WITHOUT the duplicate closing point.
    """
    area2 = 0.0
    n = len(ring)

    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area2 += x1 * y2 - x2 * y1

    return abs(area2) > 1e-12


def _segments_intersect(p1, p2, p3, p4) -> bool:
    """
    True when two non-adjacent segments properly cross.

    This check detects ordinary crossing edges. Collinear and touching
    edge cases are intentionally not classified here; the distinct-point
    and non-zero-area checks catch the most important degenerate farm
    boundaries for the current version.
    """
    def orientation(a, b, c):
        val = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        if abs(val) < 1e-12:
            return 0
        return 1 if val > 0 else 2

    o1 = orientation(p1, p2, p3)
    o2 = orientation(p1, p2, p4)
    o3 = orientation(p3, p4, p1)
    o4 = orientation(p3, p4, p2)

    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def _is_self_intersecting(ring: List[List[float]]) -> bool:
    """
    True if any two non-adjacent edges of the ring cross.

    A self-intersecting boundary — a bow-tie or figure-eight — passes
    every coordinate check but produces meaningless area and zone
    results downstream. Earth Engine may also compute a negative or
    doubled area for it. Better to reject it at intake with a message
    the user can act on.

    Ring is expected WITHOUT the duplicate closing point.
    """
    n = len(ring)
    if n < 4:
        return False

    for i in range(n):
        a1, a2 = ring[i], ring[(i + 1) % n]
        for j in range(i + 1, n):
            # Skip adjacent edges — they share a vertex by definition
            if j == i or (j + 1) % n == i or j == (i + 1) % n:
                continue
            b1, b2 = ring[j], ring[(j + 1) % n]
            if _segments_intersect(a1, a2, b1, b2):
                return True

    return False


def intake_agent(state: FarmWatchState) -> FarmWatchState:
    """
    Intake Agent — validates the farm boundary before any satellite work.

    Runs first in the pipeline. Everything downstream assumes a valid,
    closed, non-degenerate, non-self-intersecting ring, so failures
    caught here are far cheaper than failures caught after a Google
    Earth Engine call.

    Validation order:
    1.  Polygon present
    2.  At least 3 coordinate entries (closure added if absent)
    3.  Every entry is a valid [lon, lat] pair
    4.  Values are numeric
    5.  Coordinates within valid geographic range
    6.  Close the ring if the caller did not
    7.  At least 3 genuinely distinct corners
    8.  Outline does not cross itself
    9.  Encloses non-zero area
    10. Bounding box

    Both input formats are accepted — a closed ring [A, B, C, A] or an
    open one [A, B, C]. The normalised, closed polygon is returned in
    state so Processing and Earth Engine receive a clean ring.
    """
    polygon = state.get("polygon", [])
    errors = list(state.get("errors", []))

    def fail(msg: str, point_count: int = None):
        errors.append(msg)
        result = {
            **state,
            "boundary_valid": False,
            "boundary_error": msg,
            "status": "failed",
            "errors": errors,
        }
        if point_count is not None:
            result["boundary_point_count"] = point_count
        return result

    if not polygon:
        return fail("No polygon was provided.")

    # Minimum is 3 because the closing point is added automatically
    # below. Requiring 4 here would reject a valid open triangle before
    # the closure step could handle it.
    if len(polygon) < 3:
        return fail(
            "Polygon needs at least 3 coordinate pairs to form a boundary.",
            len(polygon),
        )

    for idx, point in enumerate(polygon):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return fail(
                f"Invalid coordinate at position {idx}. "
                "Each point must be [lon, lat].",
                len(polygon),
            )

        lon, lat = point

        # Python treats bool as a subclass of int, so [True, False]
        # would otherwise pass the numeric check below.
        if isinstance(lon, bool) or isinstance(lat, bool):
            return fail(
                f"Invalid numeric values at position {idx}.",
                len(polygon),
            )

        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            return fail(
                f"Invalid numeric values at position {idx}.",
                len(polygon),
            )

        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return fail(
                f"Coordinate out of range at position {idx}.",
                len(polygon),
            )

    # Close the ring if the caller did not.
    if polygon[0] != polygon[-1]:
        polygon = list(polygon) + [polygon[0]]

    # The open ring is what matters for geometry checks — the closing
    # point is a duplicate, not a corner.
    open_ring = polygon[:-1]

    # Count actual distinct coordinates, not list entries. A ring like
    # [A, B, B, A] has four entries but only two corners.
    distinct_points = {(point[0], point[1]) for point in open_ring}

    if len(distinct_points) < 3:
        return fail(
            "Polygon needs at least 3 distinct corners to enclose an area.",
            len(polygon),
        )

    # Check crossing before area. A bow-tie polygon can have a shoelace
    # area of zero because its two lobes have opposite winding and
    # cancel out, so checking area first would report "encloses no area"
    # when the real problem is a self-crossing outline.
    if _is_self_intersecting(open_ring):
        return fail(
            "The farm boundary crosses over itself. Redraw the boundary "
            "so the outline does not overlap.",
            len(polygon),
        )

    # A boundary can have three distinct non-crossing points and still
    # enclose nothing if those points lie on one straight line.
    if not _has_nonzero_area(open_ring):
        return fail(
            "The farm boundary does not enclose an area. "
            "Redraw the boundary around the field.",
            len(polygon),
        )

    bbox = _calculate_bbox(polygon)

    return {
        **state,
        "polygon": polygon,
        "boundary_valid": True,
        "boundary_error": None,
        "boundary_point_count": len(polygon),
        "boundary_bbox": bbox,
        "status": "ok",
        "errors": errors,
    }