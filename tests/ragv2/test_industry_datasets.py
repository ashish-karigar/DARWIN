import json

from app.ragv2.eval.industry.datasets import (
    discover_datasets,
    iter_corpus,
    load_cases,
)


def test_processed_dataset_is_validated_and_loaded(tmp_path):
    dataset = tmp_path / "science"
    dataset.mkdir()
    (dataset / "science_queries.json").write_text(
        json.dumps(
            {
                "input_data": [
                    {
                        "query_id": "q1",
                        "query": "What happened?",
                        "gt_answer": ["First fact", "Second fact"],
                    }
                ]
            }
        )
    )
    (dataset / "corpus.jsonl").write_text(
        json.dumps(
            {
                "doc_id": "d1",
                "title": "Document",
                "text": "Evidence",
            }
        )
        + "\n"
    )

    assert discover_datasets(tmp_path) == ("science",)
    case = load_cases(tmp_path, "science")[0]
    document = tuple(iter_corpus(tmp_path, "science"))[0]

    assert case.query_id == "q1"
    assert case.reference_answer == "First fact\nSecond fact"
    assert document == {
        "doc_id": "d1",
        "title": "Document",
        "text": "Evidence",
    }


def test_empty_official_corpus_records_are_skipped(tmp_path):
    dataset = tmp_path / "fiqa"
    dataset.mkdir()
    (dataset / "corpus.jsonl").write_text(
        "\n".join(
            (
                json.dumps({"doc_id": "empty", "text": ""}),
                json.dumps({"doc_id": "usable", "text": "Evidence"}),
            )
        )
        + "\n"
    )

    assert tuple(iter_corpus(tmp_path, "fiqa")) == (
        {
            "doc_id": "usable",
            "title": "usable",
            "text": "Evidence",
        },
    )
