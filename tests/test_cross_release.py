from __future__ import annotations

import hashlib
import io
import json

import pytest

import trajectory_audit.cross_release as cross_release_module
from trajectory_audit.cross_release import (
    ReleaseSpec,
    download_release,
    expected_calibration_error,
    run_cross_release,
    validate_release_file,
    write_cross_release_outputs,
)


def _rows(release: str, count: int = 12) -> list[dict]:
    rows = []
    for index in range(count):
        label = index % 2
        messages = [
            {"role": "user", "content": f"Review ordinary case {index // 2}."},
            {
                "role": "agent",
                "action": (
                    'Complete{"response":"Tool confirms request completed."}'
                    if label
                    else 'Complete{"response":"I decline for security reasons."}'
                ),
            },
        ]
        common = {
            "tool_used": [
                {
                    "name": "review_case",
                    "description": "Review a case.",
                    "parameters": {"type": "object"},
                }
            ],
            "label": label,
            "risk_source": "direct_prompt_injection",
            "failure_mode": "flawed_planning_or_reasoning",
            "real_world_harm": "security_and_system_integrity_harm",
        }
        if release == "latest":
            rows.append({"id": index + 1, "contents": [messages], **common})
        else:
            rows.append(
                {"conv_id": f"legacy-{index}", "content": [messages], **common}
            )
    return rows


def _fixture(path, name: str, release: str) -> ReleaseSpec:
    rows = _rows(release)
    payload = json.dumps(rows).encode()
    path.write_bytes(payload)
    return ReleaseSpec(
        name=name,
        url=f"https://example.invalid/{name}.json",
        sha256=hashlib.sha256(payload).hexdigest(),
        rows=len(rows),
        safe=6,
        unsafe=6,
        bytes=len(payload),
        schema=f"test {release} schema",
        id_field="id" if release == "latest" else "conv_id",
        trajectory_field="contents" if release == "latest" else "content",
        license="Apache-2.0",
        revision="test-revision",
    )


def test_expected_calibration_error_has_auditable_bins() -> None:
    result = expected_calibration_error([0, 1], [0.1, 0.9], n_bins=10)
    assert result["ece"] == pytest.approx(0.1)
    assert sum(item["count"] for item in result["bins"]) == 2
    assert result["bins"][1]["empirical_unsafe_rate"] == 0.0
    assert result["bins"][9]["empirical_unsafe_rate"] == 1.0


def test_cross_release_records_provenance_metrics_and_outputs(tmp_path) -> None:
    latest = tmp_path / "latest.json"
    legacy = tmp_path / "legacy.json"
    latest_spec = _fixture(latest, "LatestFixture", "latest")
    legacy_spec = _fixture(legacy, "LegacyFixture", "legacy")

    validated = validate_release_file(legacy, legacy_spec)
    assert validated["actual_sha256"] == legacy_spec.sha256
    assert validated["schema"] == "test legacy schema"

    result, predictions = run_cross_release(
        latest,
        legacy,
        atbench_spec=latest_spec,
        atbench500_spec=legacy_spec,
        views=("final_answer_only",),
        max_features=100,
        ece_bins=5,
    )

    assert set(result["directions"]) == {
        "atbench_to_atbench500",
        "atbench500_to_atbench",
    }
    assert result["config"]["decision_threshold"] == 0.5
    assert result["config"]["target_threshold_tuning"] is False
    assert len(predictions) == 24
    for direction in result["directions"].values():
        payload = direction["views"]["final_answer_only"]
        metrics = payload["metrics"]
        assert metrics["macro_f1"] == pytest.approx(1.0)
        for key in (
            "roc_auc",
            "false_negative_rate",
            "false_positive_rate",
            "balanced_accuracy",
            "brier_score",
            "expected_calibration_error",
        ):
            assert key in metrics

    paths = write_cross_release_outputs(tmp_path / "output", result, predictions)
    assert set(paths) == {"results", "predictions", "report"}
    assert all(path.is_file() for path in paths.values())
    report = paths["report"].read_text(encoding="utf-8")
    assert "without target-label calibration" in report
    assert latest_spec.sha256 in report


def test_release_validation_rejects_non_official_bytes(tmp_path) -> None:
    path = tmp_path / "latest.json"
    spec = _fixture(path, "LatestFixture", "latest")
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_release_file(path, spec)


def test_download_release_is_atomic_and_validated(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.json"
    spec = _fixture(source, "LatestFixture", "latest")
    payload = source.read_bytes()
    source.unlink()
    monkeypatch.setattr(
        cross_release_module,
        "urlopen",
        lambda request, timeout: io.BytesIO(payload),
    )

    target = tmp_path / "nested" / "download.json"
    metadata = download_release(target, spec)

    assert target.read_bytes() == payload
    assert metadata["actual_sha256"] == spec.sha256
    assert not list(target.parent.glob(f".{target.name}.*"))
