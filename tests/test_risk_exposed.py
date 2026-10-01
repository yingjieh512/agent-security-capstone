from __future__ import annotations

import json

from trajectory_audit.data import normalize_record
from trajectory_audit.risk_exposed import (
    RISK_EXPOSED_VIEWS,
    build_risk_exposed_views,
    is_risk_exposed,
    run_risk_exposed_cv,
    write_risk_exposed_outputs,
)


def _row(index: int, *, benign: bool, label: int) -> dict:
    topic = index % 5
    final = (
        "Tool confirms the requested operation completed."
        if label
        else "I decline this request for security reasons."
    )
    return {
        "id": index + 1,
        "tool_used": [
            {
                "name": f"topic_{topic}_tool",
                "description": f"Handle topic {topic}.",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "contents": [
            [
                {
                    "role": "user",
                    "content": f"Handle topic {topic} case {index}.",
                },
                {
                    "role": "agent",
                    "action": json.dumps(
                        {"name": f"topic_{topic}_tool", "arguments": {"case": index}}
                    ),
                },
                {
                    "role": "environment",
                    "content": json.dumps({"status": "returned"}),
                },
                {
                    "role": "agent",
                    "action": f'Complete{{"response":{json.dumps(final)}}}',
                },
            ]
        ],
        "label": label,
        "risk_source": "benign" if benign else "direct_prompt_injection",
        "failure_mode": "benign" if benign else "flawed_planning_or_reasoning",
        "real_world_harm": "benign" if benign else "security_and_system_integrity_harm",
    }


def test_local_views_remove_completion_and_combine_user_final() -> None:
    record = normalize_record(_row(1, benign=False, label=1))
    views = build_risk_exposed_views(record)
    assert tuple(views) == RISK_EXPOSED_VIEWS
    assert "Tool confirms" in views["final_answer_only"]
    assert "Tool confirms" not in views["full_without_final"]
    assert "Handle topic" in views["user_plus_final"]
    assert "Tool confirms" in views["user_plus_final"]
    assert is_risk_exposed(record)
    assert not is_risk_exposed(normalize_record(_row(2, benign=True, label=0)))


def test_risk_exposed_cv_filters_then_reclusters_and_writes_outputs(tmp_path) -> None:
    rows = []
    for index in range(10):
        rows.append(_row(index, benign=True, label=0))
    for index in range(10, 50):
        rows.append(_row(index, benign=False, label=index % 2))
    source = tmp_path / "atbench-fixture.json"
    source.write_text(json.dumps(rows), encoding="utf-8")

    results, bundle, assignments = run_risk_exposed_cv(
        source,
        verify_official=False,
        folds=2,
        requested_groups=5,
        max_features=500,
        bootstrap_resamples=5,
    )

    metadata = bundle["metadata"]
    assert metadata["input_records"] == 50
    assert metadata["excluded_benign_records"] == 10
    assert metadata["risk_exposed_records"] == 40
    assert metadata["safe"] == metadata["unsafe"] == 20
    assert metadata["actual_groups"] == 5
    assert len(assignments) == 40
    assert results["audit_notes"]["grouping_uses_labels"] is False
    views = bundle["summary"]["strategies"]["group"]["views"]
    assert set(views) == set(RISK_EXPOSED_VIEWS)
    assert views["final_answer_only"]["metrics"]["macro_f1"] == 1.0

    paths = write_risk_exposed_outputs(
        tmp_path / "output", results, bundle, assignments
    )
    assert set(paths) == {"results", "predictions", "summary", "assignments", "report"}
    assert all(path.is_file() for path in paths.values())
    report = paths["report"].read_text(encoding="utf-8")
    assert "risk-exposed-only" in report
    assert "full_without_final" in report
