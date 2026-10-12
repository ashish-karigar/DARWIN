from app.services.task_extraction import normalize_due_date, parse_extraction


def test_parses_bounded_task_result() -> None:
    result = parse_extraction(
        {
            "isTask": True,
            "title": "Submit the signed form",
            "dueDate": "2026-09-18",
            "priority": 1,
            "notes": "Professor Yang requested the signed form.",
            "confidence": 1.5,
            "reason": "The recipient must submit a document.",
        }
    )
    assert result["title"] == "Submit the signed form"
    assert result["dueDate"].startswith("2026-09-18T09:00:00")
    assert result["confidence"] == 1.0


def test_invalid_due_date_is_not_invented() -> None:
    assert normalize_due_date("sometime next week") is None
