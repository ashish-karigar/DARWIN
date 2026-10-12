import json

from app.agents import knowledge_agent


class FakeKnowledgeSearch:
    def __init__(self):
        self.calls = []

    def invoke(self, arguments):
        self.calls.append(arguments)
        return json.dumps(
            {
                "answer": "Patrick Lewis and colleagues [S1].",
                "grounded": True,
                "abstained": False,
            }
        )


def test_knowledge_agent_returns_rag_answer_without_llm(monkeypatch):
    search = FakeKnowledgeSearch()
    monkeypatch.setattr(
        knowledge_agent,
        "knowledge_search",
        search,
    )

    answer = knowledge_agent.run_knowledge_agent(
        "Who introduced RAG?"
    )

    assert answer == "Patrick Lewis and colleagues [S1]."
    assert search.calls == [
        {"query": "Who introduced RAG?"}
    ]
