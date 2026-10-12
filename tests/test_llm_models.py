from app.llm.models import (
    create_local_judge_model,
    create_local_verifier_model,
)


def test_verifier_has_a_larger_structured_output_budget():
    judge = create_local_judge_model()
    verifier = create_local_verifier_model()

    assert judge.num_predict == 450
    assert verifier.num_predict == 900
    assert verifier.client_kwargs["timeout"] == 45.0
