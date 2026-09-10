from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from app.llm.models import create_fallback_model, create_primary_model


def invoke_with_fallback(primary_model, fallback_model, messages):
    """Invoke the primary model, then fail over without crashing the graph."""
    try:
        reply = primary_model.invoke(messages)
        finish_reason = reply.response_metadata.get("finish_reason")
        has_tool_calls = bool(getattr(reply, "tool_calls", None))
        content = reply.content if isinstance(reply.content, str) else ""
        if finish_reason == "length" or (not content.strip() and not has_tool_calls):
            raise RuntimeError("Primary model returned an empty or truncated response")
        return reply
    except Exception as primary_error:
        print(f"Primary model unavailable; using fallback: {primary_error}")

    try:
        return fallback_model.invoke(messages)
    except Exception as fallback_error:
        print(f"Fallback model unavailable: {fallback_error}")
        return AIMessage(
            content=(
                "I couldn't complete that request because both reasoning "
                "models encountered an error."
            )
        )

def build_agent(
    system_prompt: str,
    tools: list,
    checkpointer=None,
):
    primary_model = create_primary_model(tools)
    fallback_model = create_fallback_model(tools)

    def call_model(state: MessagesState) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
            *state["messages"],
        ]

        reply = invoke_with_fallback(primary_model, fallback_model, messages)

        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("reason", call_model)
    builder.add_node("tools", ToolNode(tools))

    builder.add_edge(START, "reason")
    builder.add_conditional_edges("reason", tools_condition)
    builder.add_edge("tools","reason")

    return builder.compile(checkpointer=checkpointer)
