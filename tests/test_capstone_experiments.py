from __future__ import annotations

import json

from trajectory_audit.capstone_experiments import (
    MASK_TOKEN,
    STRUCTURE_FEATURE_NAMES,
    build_temporal_views,
    mask_posthoc_cues,
    run_capstone_experiments,
    structure_features,
    train_fold_coefficient_removal_curve,
)
from trajectory_audit.data import normalize_record


def _raw_record(index: int, *, taxonomy_suffix: str = "") -> dict:
    unsafe = index % 2
    category = index % 4
    answer = (
        f"Successfully sent and confirmed item {index}."
        if unsafe
        else f"I cannot do that and decline item {index} for security reasons."
    )
    return {
        "id": f"record-{index}",
        "label": unsafe,
        "tool_used": [
            {
                "name": f"tool_{category}",
                "description": f"TOOL DESCRIPTION {category}",
                "parameters": {"type": "object", "category": category},
            }
        ],
        "contents": [
            [
                {
                    "role": "user",
                    "content": f"USER REQUEST category {category} example {index}",
                },
                {
                    "role": "agent",
                    "thought": "",
                    "action": json.dumps(
                        {"name": f"tool_{category}", "arguments": {"item": index}}
                    ),
                },
                {
                    "role": "environment",
                    "content": f"TOOL RESULT SECRET {index}",
                },
                {
                    "role": "agent",
                    "thought": "",
                    "action": "Complete" + json.dumps({"response": answer}),
                },
            ]
        ],
        "risk_source": f"risk_{category % 2}{taxonomy_suffix}",
        "failure_mode": f"failure_{category}{taxonomy_suffix}",
        "real_world_harm": f"harm_{category % 3}{taxonomy_suffix}",
        "reason": "gold explanation that must not enter a view",
    }


def _records(n: int = 16):
    return [normalize_record(_raw_record(index), index=index) for index in range(n)]


def test_fixed_lexicon_masking_is_case_insensitive_and_uses_one_token():
    masked, counts = mask_posthoc_cues(
        "SUCCESSFULLY sent the file, but I cannot reveal confidential data."
    )

    assert "successfully" not in masked.casefold()
    assert "cannot" not in masked.casefold()
    assert "confidential" not in masked.casefold()
    assert "sent" not in masked.casefold()
    assert masked.count(MASK_TOKEN) == 4
    assert counts["successful_outcome"] == 2
    assert counts["refusal_or_inability"] == 1
    assert counts["authorization_or_policy"] == 1


def test_temporal_and_local_views_respect_normalized_event_boundaries():
    record = normalize_record(_raw_record(1), index=0)
    views = build_temporal_views(record)

    assert views["prefix_25"].count("[EVENT ") == 1
    assert views["prefix_50"].count("[EVENT ") == 2
    assert views["prefix_75"].count("[EVENT ") == 3
    assert views["full"].count("[EVENT ") == 4
    assert "Successfully sent" in views["full"]
    assert "Successfully sent" not in views["full_without_final"]

    assert "USER REQUEST" in views["static_context"]
    assert "TOOL DESCRIPTION" in views["static_context"]
    assert "TOOL RESULT SECRET" not in views["static_context"]
    assert "Successfully sent" not in views["static_context"]

    assert "USER REQUEST" in views["user_plus_final"]
    assert "Successfully sent" in views["user_plus_final"]
    assert "TOOL DESCRIPTION" not in views["user_plus_final"]
    assert "TOOL RESULT SECRET" not in views["user_plus_final"]


def test_structure_features_do_not_read_taxonomy_or_reason_fields():
    first = normalize_record(_raw_record(2, taxonomy_suffix="_first"), index=0)
    second = normalize_record(_raw_record(2, taxonomy_suffix="_second"), index=0)

    assert structure_features(first) == structure_features(second)
    assert tuple(structure_features(first)) == STRUCTURE_FEATURE_NAMES


def test_train_fold_coefficient_removal_has_complete_oof_coverage():
    records = _records()
    final_texts = [build_temporal_views(record)["final_answer_only"] for record in records]
    groups = [f"group-{index // 4}" for index in range(len(records))]

    result = train_fold_coefficient_removal_curve(
        records,
        final_texts,
        groups,
        folds=2,
        seed=3,
        max_features=200,
        k_values=(1, 2),
    )

    assert [row["removed_k"] for row in result["metrics"]] == [1, 2]
    assert len(result["predictions"]) == len(records) * 2
    assert {row["selection_scope"] for row in result["selected_terms"]} == {
        "training_fold_only"
    }
    for k in (1, 2):
        indices = sorted(
            row["record_index"]
            for row in result["predictions"]
            if row["removed_k"] == k
        )
        assert indices == list(range(len(records)))


def test_small_end_to_end_capstone_run_writes_machine_readable_outputs(tmp_path):
    records = _records()
    output = tmp_path / "capstone"

    result = run_capstone_experiments(
        records,
        output,
        folds=2,
        seed=3,
        main_groups=4,
        main_max_features=200,
        capacity_grid=(100, 200, None),
        cluster_ks=(4,),
        cluster_seeds=(3,),
        coefficient_removal_ks=(1, 2),
    )

    expected = {
        "capstone_results.json",
        "run_manifest.json",
        "view_ablation_results.json",
        "main_oof_predictions.csv",
        "trajectory_view_metrics.csv",
        "cue_masking_metrics.csv",
        "cue_masking_coverage.csv",
        "cue_lexicon.json",
        "train_fold_coefficient_removal_metrics.csv",
        "train_fold_selected_terms.csv",
        "train_fold_coefficient_removal_predictions.csv",
        "feature_capacity_sensitivity.csv",
        "cluster_sensitivity.csv",
        "structure_baseline_metrics.csv",
        "structure_oof_predictions.csv",
        "taxonomy_sliced_metrics.csv",
        "experiment_summary.md",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    assert result["cue_masking"]["analysis_status"].startswith("exploratory")
    assert len(result["train_fold_coefficient_removal"]["metrics"]) == 3
    view_names = {
        row["view"] for row in result["trajectory_views"]["metrics"]
    }
    assert {"static_context", "user_plus_final", "prefix_25"}.issubset(view_names)
    assert result["structure_only"]["metrics"]["n"] == len(records)
    assert {row["taxonomy"] for row in result["taxonomy_slices"]} == {
        "risk_source",
        "failure_mode",
        "real_world_harm",
    }

    loaded = json.loads((output / "capstone_results.json").read_text(encoding="utf-8"))
    assert loaded["manifest"]["dataset"]["records"] == len(records)
