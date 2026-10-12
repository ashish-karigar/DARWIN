from app.ragv2.eval.industry.calibration import stratified_sample, write_review_packet
from app.ragv2.eval.industry.contracts import BenchmarkSample, RetrievedContext


def _sample(dataset: str, number: int, *, grounded: bool) -> BenchmarkSample:
    return BenchmarkSample(
        dataset=dataset,
        query_id=str(number),
        query=f"Question {number}",
        reference_answer=f"Reference {number}",
        response=f"Response {number}",
        retrieved_contexts=(),
        grounded=grounded,
        abstained=not grounded,
        latency_seconds=0.1,
    )


def test_calibration_is_stratified_and_writes_three_formats(tmp_path):
    samples = tuple(
        _sample("alpha" if number % 2 else "beta", number, grounded=number % 3 > 0)
        for number in range(12)
    )

    selected = stratified_sample(samples, size=8)
    artifacts = write_review_packet(selected, tmp_path)

    assert len(selected) == 8
    assert {sample.dataset for sample in selected} == {"alpha", "beta"}
    assert all(path.is_file() for path in artifacts)


def test_review_packet_contains_frozen_evidence(tmp_path):
    sample = _sample("alpha", 1, grounded=True).model_copy(
        update={
            "retrieved_contexts": (
                RetrievedContext(
                    doc_id="doc-1",
                    title="Evidence document",
                    text="Exact evidence used by DARWIN.",
                ),
            )
        }
    )

    json_path, _, markdown_path = write_review_packet((sample,), tmp_path)

    assert "Exact evidence used by DARWIN." in json_path.read_text()
    assert "Evidence used" in markdown_path.read_text()
