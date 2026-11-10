from langgraph.graph import END, START, StateGraph

from app.services.agents.state import FarmWatchState
from app.services.agents.intake_agent import intake_agent
from app.services.agents.data_agent import data_agent
from app.services.agents.processing_agent import processing_agent
from app.services.agents.detection_agent import detection_agent
from app.services.agents.interpretation_agent import interpretation_agent
from app.services.agents.report_agent import report_agent


def _route_on_status(state: FarmWatchState) -> str:
    """
    Routes a failed pipeline straight to the report agent.

    Without this, a linear chain runs every downstream agent regardless
    of failure. A boundary rejected by intake would still trigger a
    Google Earth Engine call in processing — wasted quota and latency
    on geometry already known to be invalid.

    The report agent is always the destination rather than END, because
    it is responsible for building final_response on every path. Jumping
    to END would leave the route with no response object to return.
    """
    return "failed" if state.get("status") == "failed" else "continue"


def build_farm_watch_graph():
    """
    Farm Watch pipeline.

    Happy path:
        intake -> data -> processing -> detection -> interpretation -> report

    Any agent setting status="failed" skips directly to report, which
    packages the failure into final_response.

    Interpretation has no failure branch: it runs after detection, and
    if detection failed the pipeline has already routed around it.
    Report is the terminal node in every case.
    """
    graph = StateGraph(FarmWatchState)

    graph.add_node("intake_agent", intake_agent)
    graph.add_node("data_agent", data_agent)
    graph.add_node("processing_agent", processing_agent)
    graph.add_node("detection_agent", detection_agent)
    graph.add_node("interpretation_agent", interpretation_agent)
    graph.add_node("report_agent", report_agent)

    graph.add_edge(START, "intake_agent")

    # Each stage checks status before advancing. A failure anywhere
    # short-circuits to the report agent.
    graph.add_conditional_edges(
        "intake_agent",
        _route_on_status,
        {
            "continue": "data_agent",
            "failed": "report_agent",
        },
    )

    graph.add_conditional_edges(
        "data_agent",
        _route_on_status,
        {
            "continue": "processing_agent",
            "failed": "report_agent",
        },
    )

    graph.add_conditional_edges(
        "processing_agent",
        _route_on_status,
        {
            "continue": "detection_agent",
            "failed": "report_agent",
        },
    )

    graph.add_conditional_edges(
        "detection_agent",
        _route_on_status,
        {
            "continue": "interpretation_agent",
            "failed": "report_agent",
        },
    )

    graph.add_edge("interpretation_agent", "report_agent")
    graph.add_edge("report_agent", END)

    return graph.compile()


farm_watch_graph = build_farm_watch_graph()