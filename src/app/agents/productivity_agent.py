from app.agents.base import build_agent
from app.tools.tasks import list_tasks


PRODUCTIVITY_PROMPT = """
You are DARWIN's productivity specialist.

Always use the task tool for task-related questions.
Choose the correct status filter from the user's intent.
Use the exact count and task data returned by the tool.
Never omit, renumber, invent, or reclassify tasks.
Keep the final response concise.
"""

productivity_agent = build_agent(
    system_prompt=PRODUCTIVITY_PROMPT,
    tools=[list_tasks],
)


def run_productivity_agent(query: str) -> str:
    result = productivity_agent.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    return result["messages"][-1].content
