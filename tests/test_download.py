from __future__ import annotations

import hashlib
import json

import pytest

from trajectory_audit.download import validate_atbench_file


def test_validate_atbench_file_checks_hash_rows_and_labels(tmp_path) -> None:
    rows = [
        {"id": 1, "label": 0},
        {"id": 2, "label": 1},
    ]
    path = tmp_path / "tiny.json"
    payload = json.dumps(rows).encode()
    path.write_bytes(payload)

    result = validate_atbench_file(
        path,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_rows=2,
    )

    assert result["rows"] == 2
    assert result["safe"] == 1
    assert result["unsafe"] == 1


def test_validate_atbench_file_rejects_bad_hash(tmp_path) -> None:
    path = tmp_path / "tiny.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_atbench_file(path, expected_sha256="0" * 64, expected_rows=0)

