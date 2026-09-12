from types import SimpleNamespace

import pytest

from app.ragv2.ingest.indexes.embeddings import (
    OllamaEmbeddingModel,
)


class FakeOllamaClient:
    def __init__(self):
        self.calls = []

    def embed(self, model: str, input: list[str]):
        self.calls.append(
            {
                "model": model,
                "input": input,
            }
        )

        return SimpleNamespace(
            embeddings=[
                [float(index), 0.5, 1.0]
                for index, _ in enumerate(input)
            ]
        )


def test_embeds_documents_in_one_batch():
    client = FakeOllamaClient()
    model = OllamaEmbeddingModel(
        model_name="test-model",
        client=client,
    )

    embeddings = model.embed_documents(
        ["first chunk", "second chunk"]
    )

    assert embeddings == [
        [0.0, 0.5, 1.0],
        [1.0, 0.5, 1.0],
    ]
    assert client.calls == [
        {
            "model": "test-model",
            "input": ["first chunk", "second chunk"],
        }
    ]


def test_embeds_single_query():
    client = FakeOllamaClient()
    model = OllamaEmbeddingModel(client=client)

    embedding = model.embed_query("How does RAG work?")

    assert embedding == [0.0, 0.5, 1.0]


def test_empty_document_batch_skips_model_call():
    client = FakeOllamaClient()
    model = OllamaEmbeddingModel(client=client)

    assert model.embed_documents([]) == []
    assert client.calls == []


def test_rejects_empty_text():
    model = OllamaEmbeddingModel(client=FakeOllamaClient())

    with pytest.raises(ValueError, match="cannot be empty"):
        model.embed_query("   ")

    with pytest.raises(ValueError, match="cannot contain empty"):
        model.embed_documents(["valid", ""])