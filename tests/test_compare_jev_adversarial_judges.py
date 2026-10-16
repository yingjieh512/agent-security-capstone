"""Offline paired comparisons keep failed calls out of false-negative counts."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_jev_adversarial_judges as comparison  # noqa: E402


def _pair(parent: str, predictions: tuple[int | None, int | None, int | None]) -> dict:
    values = dict(zip(comparison.VARIANTS, predictions))
    return {
        "parent_id": parent,
        "family": "tail_safety",
        "gold": 1,
        "ids": {variant: f"{parent}:tail_safety:{variant}" for variant in comparison.VARIANTS},
        "predictions": values,
        "unsafe_probabilities": {variant: None if values[variant] is None else float(values[variant]) for variant in comparison.VARIANTS},
        "errors": {variant: "transport_error" if values[variant] is None else None for variant in comparison.VARIANTS},
        "complete_triplet": all(value in (0, 1) for value in predictions),
        "complete_clean_attack": predictions[0] in (0, 1) and predictions[2] in (0, 1),
    }


def _write_run(path: Path, model: str, rows: list[dict]) -> None:
    path.mkdir()
    (path / "pairs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    n_scored = sum(value in (0, 1) for row in rows for value in row["predictions"].values())
    (path / "summary.json").write_text(json.dumps({
        "model": model,
        "n_pairs": len(rows),
        "n_unique_parents": len(rows),
        "n_states": len(rows) * 3,
        "n_scored": n_scored,
        "n_api_or_protocol_failures": len(rows) * 3 - n_scored,
    }), encoding="utf-8")


def test_parent_matched_did_and_failed_attack_are_separate(tmp_path: Path) -> None:
    guard_path = tmp_path / "guard"
    typesafe_path = tmp_path / "typesafe"
    _write_run(guard_path, comparison.EXPECTED_MODELS["guard"], [
        _pair("a", (1, 1, 0)),
        _pair("b", (1, 1, 1)),
        _pair("c", (1, 1, None)),
    ])
    _write_run(typesafe_path, comparison.EXPECTED_MODELS["typesafe_1_13"], [
        _pair("a", (1, 1, 1)),
        _pair("b", (1, 1, 0)),
        _pair("c", (1, 1, 1)),
    ])
    guard = comparison.read_judge(guard_path, "guard", "tail_safety", 3)
    typesafe = comparison.read_judge(typesafe_path, "typesafe_1_13", "tail_safety", 3)
    parents = comparison.validate_same_holdout(guard, [typesafe])
    guard_stats = comparison.judge_metrics(guard, parents, 100, 17)
    assert guard_stats["arms"]["attack"] == {
        "n_total": 3, "n_scored": 2, "n_failed": 1, "fn": 1, "fn_rate_among_scored": 0.5,
    }
    result, rows = comparison.compare_pair(guard, typesafe, parents, 100, 17)
    assert result["n_same_parents"] == 3
    assert result["n_both_complete_triplets"] == 2
    assert result["n_excluded_from_difference_in_differences"] == 1
    assert result["guard_minus_typesafe_difference_in_differences"] == 0.0
    assert result["shared_clean_unsafe"]["n_parents"] == 3
    assert result["shared_clean_unsafe"]["n_both_attack_scored"] == 2
    assert result["shared_clean_unsafe"]["n_excluded_due_to_attack_failure"] == 1
    assert result["shared_clean_unsafe"]["paired_attack_flip_table"] == {
        "both_detected": 0, "guard_missed_only": 1,
        "typesafe_missed_only": 1, "both_missed": 0,
    }
    assert result["shared_clean_unsafe"]["guard_minus_typesafe_conditional_attack_flip_rate"] == 0.0
    assert next(row for row in rows if row["parent_id"] == "a")["guard_minus_typesafe_difference_in_differences"] == 1
    assert next(row for row in rows if row["parent_id"] == "b")["guard_minus_typesafe_difference_in_differences"] == -1
    assert next(row for row in rows if row["parent_id"] == "c")["guard_minus_typesafe_difference_in_differences"] is None


def test_mismatched_variant_ids_rejected(tmp_path: Path) -> None:
    guard_path = tmp_path / "guard"
    typesafe_path = tmp_path / "typesafe"
    guard_pair = _pair("a", (1, 1, 0))
    other_pair = _pair("a", (1, 1, 1))
    other_pair["ids"]["attack"] = "different-attack"
    _write_run(guard_path, comparison.EXPECTED_MODELS["guard"], [guard_pair])
    _write_run(typesafe_path, comparison.EXPECTED_MODELS["typesafe_1_13"], [other_pair])
    with pytest.raises(ValueError, match="invalid/duplicate state ID"):
        comparison.read_judge(typesafe_path, "typesafe_1_13", "tail_safety", 1)


def test_failure_cannot_have_safe_verdict_or_probability(tmp_path: Path) -> None:
    run_path = tmp_path / "guard"
    pair = _pair("a", (1, 1, 0))
    pair["errors"]["attack"] = "transport_error"
    _write_run(run_path, comparison.EXPECTED_MODELS["guard"], [pair])
    with pytest.raises(ValueError, match="invalid verdict metadata"):
        comparison.read_judge(run_path, "guard", "tail_safety", 1)

    pair = _pair("a", (1, 1, None))
    pair["unsafe_probabilities"]["attack"] = 0.0
    (run_path / "pairs.jsonl").write_text(json.dumps(pair) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid failure metadata"):
        comparison.read_judge(run_path, "guard", "tail_safety", 1)


def test_parent_set_mismatch_rejected(tmp_path: Path) -> None:
    guard_path = tmp_path / "guard"
    typesafe_path = tmp_path / "typesafe"
    _write_run(guard_path, comparison.EXPECTED_MODELS["guard"], [_pair("a", (1, 1, 0))])
    _write_run(typesafe_path, comparison.EXPECTED_MODELS["typesafe_1_13"], [_pair("b", (1, 1, 0))])
    guard = comparison.read_judge(guard_path, "guard", "tail_safety", 1)
    typesafe = comparison.read_judge(typesafe_path, "typesafe_1_13", "tail_safety", 1)
    with pytest.raises(ValueError, match="parent IDs differ"):
        comparison.validate_same_holdout(guard, [typesafe])


def test_shared_clean_subset_uses_both_current_judges(tmp_path: Path) -> None:
    guard_path = tmp_path / "guard"
    typesafe_path = tmp_path / "typesafe"
    _write_run(guard_path, comparison.EXPECTED_MODELS["guard"], [
        _pair("a", (1, 1, 0)), _pair("b", (1, 1, 0)),
    ])
    _write_run(typesafe_path, comparison.EXPECTED_MODELS["typesafe_1_13"], [
        _pair("a", (1, 1, 1)), _pair("b", (0, 1, 1)),
    ])
    guard = comparison.read_judge(guard_path, "guard", "tail_safety", 2)
    typesafe = comparison.read_judge(typesafe_path, "typesafe_1_13", "tail_safety", 2)
    parents = comparison.validate_same_holdout(guard, [typesafe])
    result, _ = comparison.compare_pair(guard, typesafe, parents, 100, 17)
    assert result["shared_clean_unsafe"]["n_parents"] == 1
    assert result["shared_clean_unsafe"]["by_model"]["guard"]["conditional_attack_flip_rate"] == 1.0
    assert result["shared_clean_unsafe"]["by_model"]["typesafe_1_13"]["conditional_attack_flip_rate"] == 0.0
