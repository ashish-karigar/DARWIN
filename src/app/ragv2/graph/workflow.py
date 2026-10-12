from langgraph.graph import END, START, StateGraph

from app.ragv2.config import RagSettings, settings
from app.ragv2.graph.nodes import RagGraphNodes
from app.ragv2.graph.state import RagState


def build_rag_graph(
    nodes: RagGraphNodes | None = None,
    rag_settings: RagSettings = settings,
):
    """Builds the explicit, bounded online RAG decision graph."""

    graph_nodes = nodes or RagGraphNodes(
        rag_settings=rag_settings
    )
    builder = StateGraph(RagState)

    builder.add_node("retrieve", graph_nodes.retrieve)
    builder.add_node("rewrite", graph_nodes.rewrite)
    builder.add_node(
        "retrieve_correction",
        graph_nodes.retrieve_correction,
    )
    builder.add_node("search_web", graph_nodes.search_web)
    builder.add_node("generate", graph_nodes.generate)
    builder.add_node("regenerate", graph_nodes.regenerate)
    builder.add_node("verify", graph_nodes.verify)
    builder.add_node("abstain", graph_nodes.abstain)
    builder.add_node("finalize", graph_nodes.finalize)

    builder.add_edge(START, "retrieve")
    builder.add_conditional_edges(
        "retrieve",
        graph_nodes.route_after_retrieval,
    )
    builder.add_edge("rewrite", "retrieve_correction")
    builder.add_conditional_edges(
        "retrieve_correction",
        graph_nodes.route_after_retrieval,
    )
    builder.add_conditional_edges(
        "search_web",
        graph_nodes.route_after_retrieval,
    )
    builder.add_conditional_edges(
        "generate",
        graph_nodes.route_after_generation,
    )
    builder.add_conditional_edges(
        "regenerate",
        graph_nodes.route_after_generation,
    )
    builder.add_conditional_edges(
        "verify",
        graph_nodes.route_after_verification,
    )
    builder.add_edge("abstain", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
