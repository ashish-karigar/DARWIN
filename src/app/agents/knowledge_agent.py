from app.agents.base import build_agent
from app.rag.tools import knowledge_search

KNOWLEDGE_PROMPT = """
You are an internal knowledge specialist used by DARWIN.

Always search the knowledge base before answering.
Answer only from retrieved evidence.
If the evidence is insufficient, say that clearly.
Keep answers concise and preserve exact names and facts
Write all findings in the third person. Never claim to be DARWIN and never speak directly to the user.
"""

knowledge_agent = build_agent(
    system_prompt=KNOWLEDGE_PROMPT,
    tools=[knowledge_search],
)

def run_knowledge_agent(query: str) -> str:
    result = knowledge_agent.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )

    return result["messages"][-1].content
