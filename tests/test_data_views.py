from __future__ import annotations

import json

import pytest

from trajectory_audit.data import (
    DataFormatError,
    load_records,
    loads_records,
    normalize_record,
)
from trajectory_audit.views import VIEW_NAMES, build_view, build_views


def _atbench_row() -> dict:
    return {
        "id": 17,
        "tool_used": [
            {
                "name": "lookup_incident",
                "description": "Look up an incident.",
                "parameters": {
                    "required": ["incident_id"],
                    "type": "object",
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "notify_dispatch",
                    "description": "Notify dispatch.",
                    "parameters": {"type": "object"},
                },
            },
        ],
        # The extra list reflects the nesting seen in some dataset exports.
        "contents": [
            [
                {"role": "system", "content": "Follow dispatch policy."},
                {"role": "user", "content": "Check incident A-7."},
                {
                    "role": "agent",
                    "thought": "I will check.",
                    "action": json.dumps(
                        {
                            "name": "lookup_incident",
                            "arguments": {"z": 2, "incident_id": "A-7"},
                        }
                    ),
                },
            ],
            {
                "role": "tool",
                "name": "lookup_incident",
                "tool_call_id": "call-1",
                "content": {"status": "open"},
            },
            {
                "role": "agent",
                "thought": "",
                "action": 'Complete{"response": "Incident A-7 is open."}',
            },
        ],
        "label": 1,
        "risk_source": "tool_output_injection",
        "reason": "LEAK-ME: gold annotation rationale",
    }


def test_load_atbench_shape_preserves_event_order_and_tools(tmp_path) -> None:
    path = tmp_path / "test.json"
    path.write_text(json.dumps([_atbench_row()]), encoding="utf-8")

    records = load_records(path)

    assert len(records) == 1
    record = records[0]
    assert record.record_id == "17"
    assert record.label == 1
    assert [event.kind for event in record.events] == [
        "message",
        "message",
        "reasoning",
        "tool_call",
        "tool_result",
        "completion",
    ]
    assert [event.index for event in record.events] == list(range(6))
    assert record.events[3].name == "lookup_incident"
    assert record.events[3].call_id is None
    assert record.events[3].arguments == '{"incident_id":"A-7","z":2}'
    assert record.events[4].content == '{"status":"open"}'
    assert [tool.name for tool in record.tools] == [
        "lookup_incident",
        "notify_dispatch",
    ]
    assert record.metadata["risk_source"] == "tool_output_injection"


def test_five_views_are_deterministic_separated_and_label_free() -> None:
    record = normalize_record(_atbench_row())

    first = build_views(record)
    second = build_views(record)

    assert tuple(first) == VIEW_NAMES
    assert first == second
    assert "Check incident A-7." in first["user_only"]
    assert "Incident A-7 is open." not in first["user_only"]
    assert "lookup_incident" in first["tool_schema_only"]
    assert "Look up an incident." in first["tool_schema_only"]
    assert "Check incident A-7." not in first["tool_schema_only"]
    assert "lookup_incident" in first["action_only"]
    assert '{"incident_id":"A-7","z":2}' in first["action_only"]
    assert "open" not in first["action_only"]
    assert "Incident A-7 is open." not in first["action_only"]
    assert first["final_answer_only"].endswith("Incident A-7 is open.")
    assert "Follow dispatch policy." in first["full"]
    assert "{\"status\":\"open\"}" in first["full"]

    for rendered in first.values():
        assert "LEAK-ME" not in rendered
        assert "tool_output_injection" not in rendered


def test_anthropic_blocks_and_ordered_step_schema() -> None:
    row = {
        "conv_id": "mixed-1",
        "available_tools": {
            "search": {
                "description": "Search docs",
                "input_schema": {"type": "object", "properties": {}},
            }
        },
        "trajectory": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Find the policy."}],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Searching."},
                    {
                        "type": "tool_use",
                        "id": "anth-1",
                        "name": "search",
                        "input": {"q": "policy"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "anth-1",
                        "content": "Policy text",
                    }
                ],
            },
            {
                "thought": "Need one more lookup.",
                "action": {"tool": "search", "args": {"q": "exceptions"}},
                "observation": "No exceptions.",
                "final_answer": "The policy has no exceptions.",
            },
        ],
        "is_safe": True,
    }

    record = normalize_record(row)

    assert record.label == 0
    assert [event.kind for event in record.events] == [
        "message",
        "message",
        "tool_call",
        "tool_result",
        "reasoning",
        "tool_call",
        "tool_result",
        "completion",
    ]
    assert record.events[2].call_id == "anth-1"
    assert record.events[3].call_id == "anth-1"
    assert record.events[5].name == "search"
    assert record.events[6].name == "search"
    assert record.tools[0].name == "search"
    assert build_view(record, "final").endswith("The policy has no exceptions.")


def test_jsonl_and_split_wrappers_keep_source_order(tmp_path) -> None:
    rows = [
        {"sample_id": "a", "messages": [{"role": "user", "content": "A"}], "label": "safe"},
        {"sample_id": "b", "messages": [{"role": "user", "content": "B"}], "is_safe": False},
    ]
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    records = load_records(path)
    wrapped = loads_records(
        json.dumps({"train": [rows[0]], "test": [rows[1]]})
    )

    assert [(record.id, record.label) for record in records] == [("a", 0), ("b", 1)]
    assert [record.id for record in wrapped] == ["a", "b"]
    assert [record.metadata["_split"] for record in wrapped] == ["train", "test"]


def test_empty_views_have_explicit_sentinel_and_unknown_view_fails() -> None:
    record = normalize_record(
        {"id": "empty", "messages": [{"role": "system", "content": "Policy"}]}
    )

    assert build_view(record, "user_only").endswith("<NONE>")
    assert build_view(record, "tool_schema_only").endswith("<NONE>")
    assert build_view(record, "action_only").endswith("<NONE>")
    assert build_view(record, "final_answer_only").endswith("<NONE>")
    with pytest.raises(ValueError, match="unknown view"):
        build_view(record, "not-a-view")


def test_final_answer_falls_back_to_last_assistant_message() -> None:
    record = normalize_record(
        {
            "id": "openai",
            "messages": [
                {"role": "user", "content": "Do the task"},
                {"role": "assistant", "content": "Task completed."},
            ],
            "label": 0,
        }
    )
    assert build_view(record, "final_answer_only").endswith("Task completed.")


def test_complete_parser_does_not_consume_similarly_named_tools() -> None:
    record = normalize_record(
        {
            "id": "complete-order",
            "trajectory": [
                {"role": "user", "content": "Finish checkout"},
                {"role": "agent", "action": 'CompleteOrder{"id": 7}'},
            ],
            "label": 1,
        }
    )
    assert not any(event.kind == "completion" for event in record.events)
    assert any(event.kind == "tool_call" for event in record.events)


def test_ambiguous_outcome_words_are_not_silently_labels() -> None:
    record = normalize_record(
        {
            "id": "blocked",
            "messages": [{"role": "user", "content": "x"}],
            "label": "blocked",
        }
    )
    assert record.label is None


def test_bad_input_reports_context() -> None:
    with pytest.raises(DataFormatError, match="line 2"):
        loads_records(
            '{"messages": [{"role": "user", "content": "ok"}]}\nnot json',
            format_hint="jsonl",
        )
    with pytest.raises(DataFormatError, match="no trajectory field"):
        normalize_record({"id": "missing", "label": 0})
