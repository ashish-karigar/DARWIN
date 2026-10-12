from app.ragv2.eval.industry.beir import evaluate_retrieval


def test_beir_metrics_use_fractional_recall_for_multiple_relevant_docs():
    qrels = {"q1": {"d1": 1, "d2": 1}}
    results = {"q1": {"d1": 1.0, "d3": 0.5}}

    metrics = evaluate_retrieval(qrels, results, k_values=(1, 2))

    assert metrics["Recall@1"] == 0.5
    assert metrics["Recall@2"] == 0.5
    assert metrics["P@1"] == 1.0
    assert metrics["MRR@2"] == 1.0
