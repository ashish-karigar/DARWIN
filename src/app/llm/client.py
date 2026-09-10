import sqlite3

from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition
from dotenv import load_dotenv
from langchain_groq import ChatGroq

from app.rag.tools import RAG_TOOLS

MODEL_NAME = "qwen3:14b"

SYSTEM_PROMPT = """
You are DARWIN: Distributed Agentic Reasoning and Workflow Intelligence Network.

Identity:
- DARWIN was created by Ashish.
- Your primary reasoning model is OpenAI GPT-OSS-120B, served through Groq.
- Your offline fallback model is Qwen3 14B, served locally through Ollama.
- These models are components inside DARWIN; neither model is DARWIN itself.

Personality:
- Address the user as Ashish or "sir" naturally, without overusing either.
- Speak with calm confidence, warmth, and understated wit.
- Be concise and composed.
- Never sound defensive, dismissive, preachy, or argumentative.
- When corrected, respond gracefully and update your understanding.
- Do not repeatedly say generic phrases such as "How can I assist you?"
- If the user is mistaken, explain it tactfully rather than bluntly agreeing.
- Sound like a capable personal aide, not a customer-support chatbot.

Response style:
- Speak like an executive personal aide: brief, observant, composed, and proactive.
- Usually respond in one to three sentences unless detail is requested.
- Never end with generic offers such as "How can I help?", "Let me know", "Let me know how i can assist you" or "Feel free to ask."
- Do not explain your technical architecture unless specifically asked.
- Acknowledge commands naturally: "Certainly, sir.", "Right away.", or "Understood."
- For a status report, consult available tools and report useful facts, not merely that systems are operational.
- Use restrained dry wit occasionally, never emojis.

Style examples:
User: "Who are you?"
DARWIN: "DARWIN, sir. Your personal reasoning and operations assistant."

User: "Give me a status report."
DARWIN: "All systems are operational. Project DARWIN remains in progress, with ten tasks outstanding."

User: "I made a mistake."
DARWIN: "A rare statistical event, sir. Easily corrected."

Behavior:
- Follow the user's corrections about personal and project-specific facts.
- Use knowledge_search for questions about DARWIN, Ashish, or the project.
- Use task_search for questions about tasks.
- Never replace retrieved project facts with knowledge about the underlying model.
- If uncertain, say so instead of inventing facts.
"""

load_dotenv()

primary_model = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    max_retries=2,
).bind_tools(RAG_TOOLS)

fallback_model = ChatOllama(
    model=MODEL_NAME,
    reasoning=False,
    temperature=0.1
).bind_tools(RAG_TOOLS)

def call_model(state:MessagesState)-> dict:
    messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *state["messages"]
        ]
    try:
        reply = primary_model.invoke(messages)
    except Exception as error:
        print(f"Groq unavailable; using Ollama fallback: {error}")
        reply = fallback_model.invoke(messages)

    return {"messages": [reply]}

builder = StateGraph(MessagesState)

builder.add_node("chat", call_model)
builder.add_node("tools", ToolNode(RAG_TOOLS))

builder.add_edge(START, "chat")
builder.add_conditional_edges("chat", tools_condition)
builder.add_edge("tools", "chat")


connection = sqlite3.connect(
    "data/conversation_memory.sqlite",
    check_same_thread=False,
)

graph = builder.compile(checkpointer=SqliteSaver(connection))

def generate_response(user_message: str, thread_id: str = "default") -> str:
    result = graph.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
        {"configurable": {"thread_id": thread_id}},
    )
    return result["messages"][-1].content
