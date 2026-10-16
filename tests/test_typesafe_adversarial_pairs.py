"""Offline contract tests for the TypeSafe paired holdout replay."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import random
import sys
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import eval_typesafe_adversarial_pairs as paired_typesafe  # noqa: E402


def state(parent: str, variant: str, prompt: str, family: str = "tail_safety") -> dict:
    return {
        "id": f"{parent}:{family}:{variant}",
        "parent_id": parent,
        "family": family,
        "variant": variant,
        "gold": 1,
        "prompt": prompt,
        "input_sha256": paired_typesafe.digest(prompt),
        "middle_truncated": False,
        "source_event_index": None if variant == "clean" else 4,
        "transform_sha256": None if variant == "clean" else "fixed-transform",
    }


def response(probability: float, model: str = "jev-1.13.0", *,
             truncated: bool = False) -> dict:
    return {
        "model": model,
        "answers": {"unsafe": {"type": "noul", "noul": probability}},
        "usage": {"input_tokens": 25, "output_tokens": 3},
        "truncated": truncated,
    }


class FakeLimiter:
    def __init__(self) -> None:
        self.waits = 0
        self.cooldowns: list[float] = []

    def wait(self) -> None:
        self.waits += 1

    def cooldown(self, seconds: float) -> None:
        self.cooldowns.append(seconds)


def write_states(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_requires_exact_prompt_hash_and_complete_triplets(tmp_path: Path) -> None:
    path = tmp_path / "states.jsonl"
    rows = [state("p1", variant, f"prompt-{variant}") for variant in ("clean", "control", "attack")]
    write_states(path, rows)
    loaded = paired_typesafe.load_states(path, expected_parents=1)
    assert len(loaded) == 3
    with pytest.raises(ValueError, match="expected 2 parent"):
        paired_typesafe.load_states(path, expected_parents=2)
    rows[1]["input_sha256"] = "0" * 64
    write_states(path, rows)
    with pytest.raises(ValueError, match="hash mismatch"):
        paired_typesafe.load_states(path, expected_parents=1)
    rows[1].pop("input_sha256")
    write_states(path, rows)
    with pytest.raises(ValueError, match="needs prompt and input_sha256"):
        paired_typesafe.load_states(path, expected_parents=1)
    complete = [state("p1", variant, f"prompt-{variant}")
                for variant in ("clean", "control", "attack")]
    complete[0]["middle_truncated"] = True
    write_states(path, complete)
    with pytest.raises(ValueError, match="untruncated input"):
        paired_typesafe.load_states(path, expected_parents=1)
    complete[0]["middle_truncated"] = False
    extra = [state("p1", variant, f"extra-{variant}", family="forged_review")
             for variant in ("clean", "control", "attack")]
    write_states(path, complete + extra)
    with pytest.raises(ValueError, match="one clean/control/attack triplet"):
        paired_typesafe.load_states(path, expected_parents=1)


def test_exact_question_threshold_random_order_and_resume(tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [state("p1", variant, f"prompt-{variant}") for variant in ("clean", "control", "attack")]
    path = tmp_path / "states.jsonl"
    write_states(path, rows)
    loaded = paired_typesafe.load_states(path, expected_parents=1)
    seen: list[tuple[str, dict, str, str]] = []

    def fake_post(prompt: str, question: dict, model: str, key: str) -> dict:
        seen.append((prompt, question, model, key))
        probability = {"prompt-clean": 0.9, "prompt-control": 0.8, "prompt-attack": 0.2}[prompt]
        result = response(probability, model)
        result["debug"] = {key: [f"echo {key}"]}
        return result

    monkeypatch.setattr(paired_typesafe, "post_system_one", fake_post)
    output = tmp_path / "results"
    summary = paired_typesafe.run(loaded, output, "unit-test-key", FakeLimiter(),
                                  1, 23, 20, 5, "jev-1.13.0")
    expected_order = list(loaded)
    random.Random(23).shuffle(expected_order)
    assert [item[0] for item in seen] == [item["prompt"] for item in expected_order]
    assert all(question == paired_typesafe.QUESTION and model == "jev-1.13.0"
               and key == "unit-test-key" for _, question, model, key in seen)
    assert summary["n_scored"] == 3
    assert summary["question_sha256"] == paired_typesafe.QUESTION_SHA256
    assert summary["threshold"] == 0.5
    assert summary["overall"]["unsafe"]["conditional_escape_rate"] == 1.0
    assert summary["overall"]["unsafe"]["net_fn_rate_change"] == 1.0
    assert len(read_jsonl(output / "pairs.jsonl")) == 1
    saved = read_jsonl(output / "predictions.jsonl")
    assert len(saved) == 3
    assert all("unit-test-key" not in json.dumps(row) for row in saved)
    assert all(row["input_sha256"] == paired_typesafe.digest(
        next(item["prompt"] for item in loaded if item["id"] == row["id"])
    ) for row in saved)

    monkeypatch.setattr(paired_typesafe, "post_system_one", lambda *_: pytest.fail("resumed a completed call"))
    again = paired_typesafe.run(loaded, output, "unit-test-key", FakeLimiter(),
                                1, 23, 20, 5, "jev-1.13.0")
    assert again["n_scored"] == 3
    assert len(read_jsonl(output / "predictions.jsonl")) == 3
    changed = [dict(item) for item in loaded]
    changed[0]["input_sha256"] = "changed"
    with pytest.raises(ValueError, match="saved input_sha256 differs"):
        paired_typesafe.run(changed, output, None, FakeLimiter(),
                            1, 23, 20, 5, "jev-1.13.0", dry_run=True)
    with pytest.raises(ValueError, match="saved requested_model differs"):
        paired_typesafe.run(loaded, output, None, FakeLimiter(),
                            1, 23, 20, 5, "jev-1.14.0", dry_run=True)


def test_context_and_truncation_are_failures_without_shortening(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_post(prompt: str, question: dict, model: str, key: str) -> dict:
        calls.append(prompt)
        if prompt == "context-state":
            raise HTTPError(paired_typesafe.ENDPOINT, 400, "Bad Request", {},
                            BytesIO(b'{"error":"max_tokens_exceeded"}'))
        return response(0.1, model, truncated=True)

    monkeypatch.setattr(paired_typesafe, "post_system_one", fake_post)
    limiter = FakeLimiter()
    result, parsed, error_type, _, attempts = paired_typesafe.call_system_one(
        "context-state", "unit-test-key", limiter, 3, "jev-1.13.0"
    )
    assert result is parsed is None
    assert error_type == "context_rejected" and attempts == 1
    result, parsed, error_type, _, attempts = paired_typesafe.call_system_one(
        "truncated-state", "unit-test-key", limiter, 3, "jev-1.13.0"
    )
    assert result == response(0.1, "jev-1.13.0", truncated=True) and parsed is None
    assert error_type == "server_truncated" and attempts == 1
    assert calls == ["context-state", "truncated-state"]


def test_unexpected_exception_redacts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args):
        raise RuntimeError("upstream echoed unit-test-key")

    monkeypatch.setattr(paired_typesafe, "post_system_one", fail)
    result, parsed, error_type, error, attempts = paired_typesafe.call_system_one(
        "exact-state", "unit-test-key", FakeLimiter(), 1, "jev-1.13.0"
    )
    assert result is parsed is None
    assert error_type == "unexpected_error" and attempts == 1
    assert "unit-test-key" not in error and "[REDACTED]" in error


def test_jev_1_14_uses_same_question_and_half_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_post(prompt, question, model, api_key):
        seen.append((prompt, question, model))
        return response(0.5, model)

    monkeypatch.setattr(paired_typesafe, "post_system_one", fake_post)
    row = paired_typesafe.replay_state(
        state("p1", "attack", "exact-prompt"), "unit-test-key", FakeLimiter(), 1, "jev-1.14.0"
    )
    assert seen == [("exact-prompt", paired_typesafe.QUESTION, "jev-1.14.0")]
    assert row["prediction"] == 1 and row["unsafe_probability"] == 0.5
    assert row["requested_model"] == row["returned_model"] == "jev-1.14.0"
    assert paired_typesafe.default_output("jev-1.13.0") != paired_typesafe.default_output("jev-1.14.0")


def test_dry_run_needs_no_api_key_and_writes_nothing(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [state("p1", variant, f"prompt-{variant}") for variant in ("clean", "control", "attack")]
    monkeypatch.setattr(paired_typesafe, "post_system_one", lambda *_: pytest.fail("API call in dry run"))
    output = tmp_path / "dry-run"
    result = paired_typesafe.run(rows, output, None, FakeLimiter(),
                                 1, 7, 10, 2, "jev-1.13.0", dry_run=True)
    assert result["n_states"] == 3 and result["n_pending"] == 3
    assert not output.exists()


def test_key_file_has_precedence_and_never_displays_secret(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    key_file = tmp_path / "dummy-key.txt"
    parser = argparse.ArgumentParser()
    monkeypatch.setenv("TYPESAFE_API_KEY", "env-only-key")
    args = argparse.Namespace(api_key_file=key_file, api_key_stdin=False)
    key_file.write_text("  dummy-key-42  \n", encoding="utf-8")
    assert paired_typesafe.read_api_key(args, parser) == "dummy-key-42"
    key_file.write_text("  \n", encoding="utf-8")
    with pytest.raises(SystemExit):
        paired_typesafe.read_api_key(args, parser)
    key_file.write_text("dummy-key-42\nsecond-line\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        paired_typesafe.read_api_key(args, parser)
    captured = capsys.readouterr()
    assert "dummy-key-42" not in captured.out + captured.err
