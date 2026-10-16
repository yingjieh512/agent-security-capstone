"""Offline checks for the paired trajectory replay's denominators and resume key."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import eval_jev_adversarial_pairs as paired  # noqa: E402


def _state(parent: str, variant: str, prompt: str, family: str = "tail_safety") -> dict:
    return {
        "id": f"{parent}:{family}:{variant}",
        "parent_id": parent,
        "family": family,
        "variant": variant,
        "gold": 1,
        "prompt": prompt,
        "input_sha256": paired.digest(prompt),
    }


def test_resume_rejects_changed_input_hash(tmp_path: Path) -> None:
    states_path = tmp_path / "states.jsonl"
    states_path.write_text("\n".join(json.dumps(_state("x", arm, arm)) for arm in paired.VARIANTS) + "\n", encoding="utf-8")
    states = paired.load_states(states_path, None)
    prediction_path = tmp_path / "predictions.jsonl"
    prediction_path.write_text(json.dumps({
        **{key: states[0][key] for key in ("id", "parent_id", "family", "variant", "gold")},
        "endpoint": "https://example.test/predict",
        "input_sha256": paired.digest("changed"),
        "prediction": 1,
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="input hash conflict"):
        paired.load_prior(prediction_path, states, "https://example.test/predict")


def test_unsafe_metrics_keep_escaped_and_newly_detected_cases_paired() -> None:
    pairs = [
        {"parent_id": "a", "family": "tail_safety", "gold": 1,
         "predictions": {"clean": 1, "control": 1, "attack": 0},
         "complete_clean_attack": True, "complete_triplet": True},
        {"parent_id": "b", "family": "tail_safety", "gold": 1,
         "predictions": {"clean": 0, "control": 0, "attack": 1},
         "complete_clean_attack": True, "complete_triplet": True},
        {"parent_id": "c", "family": "tail_safety", "gold": 1,
         "predictions": {"clean": 1, "control": None, "attack": None},
         "complete_clean_attack": False, "complete_triplet": False},
    ]
    metrics = paired.pair_metrics(pairs, 1)
    assert metrics["n_complete_clean_attack"] == 2
    assert metrics["n_incomplete_clean_attack"] == 1
    assert metrics["n_clean_unsafe_eligible"] == 1
    assert metrics["conditional_escape_rate"] == 1.0
    assert metrics["clean_fn"] == metrics["attack_fn"] == 1
    assert metrics["net_fn_rate_change"] == 0.0
    assert metrics["clean_to_attack_table"]["clean_unsafe_attack_safe"] == 1
    assert metrics["clean_to_attack_table"]["clean_safe_attack_unsafe"] == 1


def test_truncated_server_output_is_failure_not_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paired, "predict", lambda *_: {
        "model": paired.EXPECTED_MODEL, "mode": "single", "truncated": True,
        "safety": "safe", "safety_probs": {"unsafe": 0.1, "safe": 0.9},
    })
    response, error_type, _, attempts = paired.call_endpoint("https://example.test/predict", "text", 3)
    assert response is None
    assert error_type == "server_truncated"
    assert attempts == 1
