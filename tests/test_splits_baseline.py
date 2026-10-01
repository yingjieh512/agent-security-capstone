from __future__ import annotations

import csv
import json

import pytest

from trajectory_audit.baseline import (
    bootstrap_confidence_interval,
    evaluate_tfidf_baseline,
    evaluate_tfidf_cross_validation,
    save_evaluation_artifacts,
)
from trajectory_audit.splits import (
    cross_validation_splits,
    infer_group_key,
    split_records,
)


def _records() -> list[dict]:
    records = []
    for group_index in range(10):
        for item_index in range(3):
            label = (group_index + item_index) % 2
            records.append(
                {
                    "record_id": f"r-{group_index}-{item_index}",
                    "label": label,
                    "metadata": {
                        "task_id": f"task-{group_index}",
                        "tool_name": f"tool-{group_index % 3}",
                    },
                }
            )
    return records


def test_group_key_uses_metadata_and_has_deterministic_content_fallback():
    assert infer_group_key({"metadata": {"task_id": "Checkout  7"}}) == (
        "field:task_id=checkout 7"
    )
    first = infer_group_key({"prompt": "Send the report", "label": 0})
    second = infer_group_key({"prompt": " Send   the REPORT ", "label": 1})
    assert first == second
    assert first.startswith("content:prompt:")


def test_group_split_is_deterministic_and_never_leaks_groups():
    records = _records()
    first = split_records(records, strategy="group", test_size=0.3, seed=9)
    second = split_records(records, strategy="group", test_size=0.3, seed=9)

    assert first.train_indices == second.train_indices
    assert first.test_indices == second.test_indices
    assert set(first.train_indices).isdisjoint(first.test_indices)
    assert set(first.train_groups).isdisjoint(first.test_groups)
    assert sorted(first.train_indices + first.test_indices) == list(range(len(records)))


def test_random_split_is_deterministic_and_stratified_when_possible():
    records = _records()
    first = split_records(records, strategy="random", test_size=0.2, seed=17)
    second = split_records(records, strategy="random", test_size=0.2, seed=17)

    assert first.test_indices == second.test_indices
    assert {record["label"] for record in first.train} == {0, 1}
    assert {record["label"] for record in first.test} == {0, 1}


def test_group_split_rejects_a_single_group():
    records = [
        {"record_id": str(index), "group_id": "only", "label": index % 2}
        for index in range(6)
    ]
    with pytest.raises(ValueError, match="at least two distinct groups"):
        split_records(records, strategy="group")


def test_group_cross_validation_accepts_external_semantic_clusters():
    records = _records()
    cluster_ids = [f"cluster-{index // 6}" for index in range(len(records))]
    folds = cross_validation_splits(
        records,
        strategy="group",
        n_splits=5,
        seed=11,
        group_values=cluster_ids,
    )
    assert len(folds) == 5
    assert sorted(index for fold in folds for index in fold.test_indices) == list(
        range(len(records))
    )
    for fold_index, fold in enumerate(folds):
        assert fold.fold_index == fold_index
        assert set(fold.train_groups).isdisjoint(fold.test_groups)


def test_tfidf_evaluation_returns_paired_view_metrics_and_predictions(tmp_path):
    records = _records()
    view_texts = {
        "full": [
            "unsafe exfiltrate secret" if record["label"] else "safe summarize local"
            for record in records
        ],
        "user_only": [f"generic request {index % 4}" for index in range(len(records))],
    }
    results = evaluate_tfidf_baseline(
        records,
        view_texts=view_texts,
        split_strategies=("random", "group"),
        test_size=0.3,
        seed=5,
        bootstrap_resamples=20,
    )

    assert set(results["splits"]) == {"random", "group"}
    for split in results["splits"].values():
        assert set(split["views"]) == {"full", "user_only"}
        expected = split["test_size"]
        for view in split["views"].values():
            assert view["metrics"]["n"] == expected
            assert len(view["predictions"]) == expected
            assert all("group" in row and "positive_score" in row for row in view["predictions"])
            assert view["bootstrap"]["macro_f1"]["n_valid_resamples"] == 20

    group_split = results["splits"]["group"]
    train_groups = {
        infer_group_key(records[index]) for index in group_split["train_original_indices"]
    }
    test_groups = {
        infer_group_key(records[index]) for index in group_split["test_original_indices"]
    }
    assert train_groups.isdisjoint(test_groups)

    paths = save_evaluation_artifacts(results, tmp_path / "artifacts")
    with paths["results"].open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert loaded["model"] == "tfidf_logistic_regression"

    with paths["predictions"].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_rows = sum(
        len(view["predictions"])
        for split in results["splits"].values()
        for view in split["views"].values()
    )
    assert len(rows) == expected_rows


def test_bootstrap_is_reproducible_for_group_sampling():
    kwargs = dict(
        y_true=[0, 0, 1, 1, 0, 1],
        y_pred=[0, 1, 1, 1, 0, 0],
        groups=["a", "a", "b", "b", "c", "c"],
        n_resamples=40,
        seed=123,
    )
    first = bootstrap_confidence_interval(**kwargs)
    second = bootstrap_confidence_interval(**kwargs)
    assert first == second
    assert first["sampling_units"] == "groups"
    assert first["lower"] <= first["estimate"] <= first["upper"]


def test_cross_validation_returns_one_out_of_fold_prediction_per_record():
    records = _records()
    clusters = [f"cluster-{index // 6}" for index in range(len(records))]
    view_texts = {
        "full": [
            "unsafe remote action" if record["label"] else "safe local action"
            for record in records
        ]
    }
    results = evaluate_tfidf_cross_validation(
        records,
        n_splits=5,
        split_strategies=("group",),
        group_values=clusters,
        view_texts=view_texts,
    )

    assert set(results["splits"]) == {f"group_fold_{index}" for index in range(5)}
    predicted_indices = sorted(
        prediction["record_index"]
        for split in results["splits"].values()
        for prediction in split["views"]["full"]["predictions"]
    )
    assert predicted_indices == list(range(len(records)))
