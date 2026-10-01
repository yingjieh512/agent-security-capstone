from __future__ import annotations

import json

from trajectory_audit.cli import main


def _row(index: int) -> dict:
    unsafe = index % 2
    tool = f"tool_{index % 4}"
    answer = (
        f"The tool returned data and confirms operation {index}."
        if unsafe
        else f"I need to decline operation {index} for security reasons."
    )
    return {
        "id": index,
        "label": unsafe,
        "tool_used": [
            {
                "name": tool,
                "description": f"Handle category {index % 4} records.",
                "parameters": {"type": "object"},
            }
        ],
        "contents": [
            [
                {
                    "role": "user",
                    "content": f"Please process category {index % 4} item {index}.",
                },
                {
                    "role": "agent",
                    "thought": "",
                    "action": json.dumps(
                        {"name": tool, "arguments": {"item": index}}
                    ),
                },
                {
                    "role": "environment",
                    "content": json.dumps({"status": "ok", "item": index}),
                },
                {
                    "role": "agent",
                    "thought": "",
                    "action": "Complete" + json.dumps({"response": answer}),
                },
            ]
        ],
        "risk_source": "must_not_enter_views",
        "failure_mode": "must_not_enter_views",
        "reason": "gold explanation must_not_enter_views",
        "real_world_harm": "must_not_enter_views",
    }


def test_cli_run_writes_complete_artifact_set(tmp_path) -> None:
    source = tmp_path / "records.json"
    output = tmp_path / "result"
    source.write_text(json.dumps([_row(index) for index in range(20)]), encoding="utf-8")

    code = main(
        [
            "run",
            "--input",
            str(source),
            "--output-dir",
            str(output),
            "--folds",
            "2",
            "--groups",
            "4",
            "--bootstrap-resamples",
            "5",
            "--max-features",
            "1000",
        ]
    )

    assert code == 0
    expected = {
        "results.json",
        "predictions.csv",
        "summary.json",
        "run_metadata.json",
        "group_diagnostics.json",
        "group_assignments.csv",
        "report.md",
        "macro_f1.svg",
        "final_answer_diagnostics.json",
        "final_answer_top_features.csv",
        "final_answer_diagnostics.md",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    report = (output / "report.md").read_text(encoding="utf-8")
    assert "Macro-F1" in report
    assert "must_not_enter_views" not in (output / "results.json").read_text(
        encoding="utf-8"
    )

