from __future__ import annotations

import json

import pytest

from trajectory_audit.data import DataFormatError
from trajectory_audit.rjudge import (
    build_rjudge_views,
    corpus_diagnostics,
    load_rjudge_directory,
    normalize_rjudge_record,
)


def _row(record_id: int = 1, label: int = 1) -> dict:
    return {
        "id": record_id,
        "scenario": "mail",
        "profile": "You are a mail agent.",
        "goal": "Judge this record.",
        "contents": [
            [
                {"role": "user", "content": "Send the report."},
                {
                    "role": "agent",
                    "thought": "I should check the address.",
                    "action": "MailSend(to='outside@example.com')",
                },
                {"role": "environment", "content": {"status": "sent"}},
                {"role": "agent", "thought": None, "action": "Done."},
                {"role": "environment", "content": None},
            ]
        ],
        "label": label,
        "risk_description": "GOLD-RATIONALE-DO-NOT-RENDER",
        "attack_type": "unintended",
    }


def test_rjudge_parser_preserves_native_turn_semantics_and_label_polarity() -> None:
    record = normalize_rjudge_record(_row(), source_file="Application/mail.json")

    assert record.label == 1
    assert [event.kind for event in record.events] == [
        "message",
        "message",
        "reasoning",
        "agent_action",
        "tool_result",
        "agent_action",
        "tool_result",
    ]
    assert [event.index for event in record.events] == list(range(7))
    assert record.events[-1].content == "<NULL>"
    assert record.metadata["source_file"] == "Application/mail.json"


def test_rjudge_views_are_label_free_and_do_not_invent_final_answer() -> None:
    record = normalize_rjudge_record(_row(), source_file="Application/mail.json")
    views = build_rjudge_views(record)

    assert tuple(views) == (
        "full",
        "user_only",
        "action_only",
        "last_action_only",
    )
    assert "Send the report." in views["user_only"]
    assert "I should check" not in views["user_only"]
    assert "MailSend" in views["action_only"]
    assert "I should check" not in views["action_only"]
    assert views["last_action_only"].endswith("Done.")
    assert "FINAL_ANSWER" not in views["last_action_only"]
    for text in views.values():
        assert "GOLD-RATIONALE-DO-NOT-RENDER" not in text
        assert "unintended" not in text
        assert "Judge this record" not in text


def test_directory_loader_deduplicates_exact_official_inputs(tmp_path) -> None:
    data_dir = tmp_path / "data"
    category = data_dir / "Application"
    category.mkdir(parents=True)
    first = _row(record_id=1, label=1)
    duplicate = _row(record_id=2, label=1)
    profile_variant = _row(record_id=3, label=1)
    profile_variant["profile"] = "You are a different mail agent."
    (category / "mail.json").write_text(
        json.dumps([first, duplicate, profile_variant]), encoding="utf-8"
    )

    loaded = load_rjudge_directory(data_dir)
    diagnostics = corpus_diagnostics(loaded)

    assert loaded.raw_rows == 3
    assert [record.id for record in loaded.records] == ["1", "3"]
    assert loaded.duplicate_input_ids == ("2",)
    assert diagnostics["deduplicated_rows"] == 2
    assert diagnostics["label_counts"] == {"1": 2}


@pytest.mark.parametrize("bad_label", [None, "unsafe", 2, True])
def test_rjudge_parser_rejects_noncanonical_labels(bad_label) -> None:
    row = _row()
    row["label"] = bad_label
    with pytest.raises(DataFormatError, match="invalid label"):
        normalize_rjudge_record(row, source_file="Application/mail.json")
