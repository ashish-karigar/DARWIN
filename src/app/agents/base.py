from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from app.llm.models import create_fallback_model, create_primary_model
from app.services.ambient_context import ambient_context_prompt
from app.runtime_events import (
    RuntimeEvent,
    RuntimeRequestCancelled,
    current_runtime_request,
    emit_runtime_event,
    raise_if_cancelled,
)


def _validated_reply(reply, provider: str):
    """Reject silent/truncated model output from either provider."""
    metadata = getattr(reply, "response_metadata", {}) or {}
    finish_reason = metadata.get("finish_reason")
    has_tool_calls = bool(getattr(reply, "tool_calls", None))
    content = reply.content if isinstance(getattr(reply, "content", None), str) else ""
    if finish_reason == "length" or (not content.strip() and not has_tool_calls):
        raise RuntimeError(f"{provider} model returned an empty or truncated response")
    return reply


def _model_event(provider: str, phase: str) -> None:
    request_id, session_id = current_runtime_request()
    emit_runtime_event(
        RuntimeEvent(
            kind="skill",
            request_id=request_id,
            session_id=session_id,
            skill=f"model.{provider}",
            phase=phase,
        )
    )


def invoke_with_fallback(primary_model, fallback_model, messages):
    """Invoke the primary model, then fail over without crashing the graph."""
    raise_if_cancelled()
    _model_event("primary", "started")
    try:
        reply = _validated_reply(primary_model.invoke(messages), "Primary")
        raise_if_cancelled()
        _model_event("primary", "completed")
        return reply
    except RuntimeRequestCancelled:
        raise
    except Exception as primary_error:
        _model_event("primary", "failed")
        print(f"Primary model unavailable; using fallback: {primary_error}")

    _model_event("fallback", "started")
    try:
        reply = _validated_reply(fallback_model.invoke(messages), "Fallback")
        raise_if_cancelled()
        _model_event("fallback", "completed")
        return reply
    except RuntimeRequestCancelled:
        raise
    except Exception as fallback_error:
        _model_event("fallback", "failed")
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
            {
                "role": "system",
                "content": f"{system_prompt}\n\n{ambient_context_prompt()}",
            },
            *state["messages"],
        ]

        reply = invoke_with_fallback(primary_model, fallback_model, messages)

        return {"messages": [reply]}

    tool_node = ToolNode(tools)

    def call_tools(state: MessagesState) -> dict:
        raise_if_cancelled()
        request_id, session_id = current_runtime_request()
        calls = getattr(state['messages'][-1], 'tool_calls', [])
        for call in calls:
            emit_runtime_event(RuntimeEvent(
                kind='skill', request_id=request_id, session_id=session_id,
                skill=f"tool.{call['name']}", phase='started',
            ))
        try:
            result = tool_node.invoke(state)
        except Exception:
            for call in calls:
                emit_runtime_event(RuntimeEvent(
                    kind='skill', request_id=request_id, session_id=session_id,
                    skill=f"tool.{call['name']}", phase='failed',
                ))
            raise
        raise_if_cancelled()
        failed_ids = {getattr(message, 'tool_call_id', None) for message in result.get('messages', []) if getattr(message, 'status', None) == 'error'}
        for call in calls:
            emit_runtime_event(RuntimeEvent(
                kind='skill', request_id=request_id, session_id=session_id,
                skill=f"tool.{call['name']}", phase='failed' if call.get('id') in failed_ids else 'completed',
            ))
        return result

    def route_after_reason(state: MessagesState):
        raise_if_cancelled()
        return tools_condition(state)

    builder = StateGraph(MessagesState)
    builder.add_node("reason", call_model)
    builder.add_node("tools", call_tools)

    builder.add_edge(START, "reason")
    builder.add_conditional_edges("reason", route_after_reason)
    builder.add_edge("tools", "reason")

    return builder.compile(checkpointer=checkpointer)
