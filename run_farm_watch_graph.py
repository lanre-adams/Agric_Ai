from typing import Optional

from app.services.orchestrator.farm_watch_graph import farm_watch_graph


def run_farm_watch_analysis(
    polygon: list[list[float]],
    crop_type: Optional[str] = None,
    planting_date: Optional[str] = None,
    irrigation_type: Optional[str] = None,
    season_id: Optional[str] = None,
):
    """
    Runs the Farm Watch pipeline and returns the final report.

    The graph short-circuits to the report agent on any failure, and the
    report agent builds final_response on every path — success, upstream
    failure, or report-stage failure. So a well-behaved run always
    produces a response object.

    The guard below covers the case where it does not. Returning None
    would serialise to null, which the frontend cannot distinguish from
    a network failure, so an explicit error object is returned instead.

    CROP CONTEXT (Step 3)
    ---------------------
    Every crop argument defaults to None.

    A caller passing only a polygon gets the same initial state shape
    used before Step 3. Crop fields are added only when they were
    actually supplied.

    These values are seeded as raw INPUT only, unnormalised.
    crop_context.py is the single place that normalises crop and
    irrigation names, so a farm saved as "Maize" and one saved as "corn"
    resolve identically without duplicating those rules here.

    Days after planting and timing phase are NOT calculated here. The
    Sentinel-2 acquisition has not been selected yet: processing chooses
    the observation, and it can be several days older than the day the
    farmer presses Analyze. Crop timing therefore has to describe the
    crop on the satellite OBSERVATION DATE, so build_crop_context() runs
    later in detection_agent, once processing has written the selected
    observation date into state.

    !! CONTRACT FOR EVERY DOWNSTREAM READER !!
    ------------------------------------------
    Because unsupplied crop keys are OMITTED rather than set to None,
    they may be absent from state entirely. Always read them with
    state.get("crop_type"), never state["crop_type"].

    A bracket access raises KeyError on a polygon-only request — which is
    the most common path and the one every existing saved farm takes. In
    detection_agent that KeyError would be swallowed by the agent's
    except-clause and surface to the farmer as "Field condition could not
    be assessed", with nothing to indicate the real cause.
    """

    # --------------------------------------------------------------
    # Existing pre-Step-3 initial state
    # --------------------------------------------------------------

    initial_state = {
        "polygon": polygon,
        "errors": [],
        "status": "started",
    }

    # --------------------------------------------------------------
    # Step 3 — optional crop inputs
    # --------------------------------------------------------------
    #
    # Only fields that were actually supplied are added. This keeps a
    # polygon-only request byte-identical to the pre-Step-3 initial
    # state and prevents optional context from becoming an accidental
    # requirement.
    #
    # The API layer has already coerced blank strings to None, so a
    # value reaching here is one the caller genuinely provided.

    optional_crop_inputs = {
        "crop_type": crop_type,
        "planting_date": planting_date,
        "irrigation_type": irrigation_type,
        "season_id": season_id,
    }

    for key, value in optional_crop_inputs.items():
        if value is not None:
            initial_state[key] = value

    # --------------------------------------------------------------
    # Run Farm Watch graph
    # --------------------------------------------------------------

    result = farm_watch_graph.invoke(initial_state)

    final_response = result.get("final_response")

    if not final_response:
        errors = result.get("errors") or []

        return {
            "error": (
                errors[-1]
                if errors
                else "Analysis did not complete and produced no report."
            ),
            "status": "failed",
        }

    return final_response