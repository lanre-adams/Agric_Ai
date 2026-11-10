from app.services.agents.state import FarmWatchState


def data_agent(state: FarmWatchState) -> FarmWatchState:
    """
    Data Agent — pass-through gate between intake and processing.

    This agent deliberately contains no data-acquisition logic. Image
    selection, cloud masking and quality gating all happen inside
    calculate_all_indices_for_polygon() in gee.py, which the Processing
    Agent calls. Splitting acquisition across two agents would mean two
    round trips to Earth Engine and two places where the selection
    criteria could drift apart — different date windows, cloud
    thresholds or coverage rules would make results irreproducible.

    Its only job is to stop the pipeline if the boundary failed
    validation, so processing never runs on invalid geometry.

    The node exists so the graph can grow without restructuring. If
    Tagintell later adds weather, forecast, soil, crop records or sensor
    data, this is where that acquisition belongs — Processing would then
    receive an assembled package rather than becoming responsible for
    every external source.
    """
    errors = list(state.get("errors", []))

    if not state.get("boundary_valid"):
        # Preserve the specific reason from intake rather than replacing
        # it with a generic message. Intake already knows whether the
        # boundary crossed itself, enclosed no area, or had bad
        # coordinates — that detail is what makes a failure debuggable.
        msg = (
            state.get("boundary_error")
            or "Boundary validation failed, so data preparation was skipped."
        )

        if msg not in errors:
            errors.append(msg)

        return {
            **state,
            "data_error": msg,
            "status": "failed",
            "errors": errors,
        }

    return {
        **state,
        "data_error": None,
        "status": "ok",
        "errors": errors,
    }