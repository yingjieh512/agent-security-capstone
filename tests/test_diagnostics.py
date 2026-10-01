from trajectory_audit.diagnostics import (
    missing_by_label,
    strip_view_markup,
    top_tfidf_features,
)


def test_strip_markup_and_missing_counts() -> None:
    texts = [
        "[VIEW final_answer_only]\n\n[FINAL_ANSWER]\n<NONE>",
        "[VIEW final_answer_only]\n\n[FINAL_ANSWER]\nDeclined for security reasons",
    ]
    assert strip_view_markup(texts[1]) == "Declined for security reasons"
    assert missing_by_label(texts, [1, 0]) == {"total": 1, "safe": 0, "unsafe": 1}


def test_top_features_returns_both_directions() -> None:
    texts = [
        "blocked for security reasons",
        "declined private request",
        "blocked for privacy reasons",
        "successfully exported data",
        "tool returned confidential data",
        "successfully changed configuration",
    ]
    payload = top_tfidf_features(texts, [0, 0, 0, 1, 1, 1], top_k=3)
    assert payload["fit_scope"] == "all_records_descriptive_only"
    assert len(payload["unsafe_associated"]) == 3
    assert len(payload["safe_associated"]) == 3
    assert payload["unsafe_associated"][0]["coefficient"] > 0
    assert payload["safe_associated"][0]["coefficient"] < 0

