"""Reproducible download of the public ATBench release."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.request import Request, urlopen


ATBENCH_REVISION = "de862a3d5363aa3928f70e2228b275135597226c"
ATBENCH_URL = (
    "https://huggingface.co/datasets/AI45Research/ATBench/resolve/"
    f"{ATBENCH_REVISION}/ATBench/test.json"
)
ATBENCH_SHA256 = "80c534b5f3517c872b528a2e6b64e34495206968edd184f4aed563d39f0cca09"
ATBENCH_BYTES = 18_335_079


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_atbench_file(
    path: str | Path,
    *,
    expected_sha256: str = ATBENCH_SHA256,
    expected_rows: int = 1_000,
) -> dict[str, Any]:
    """Validate hash, shape, IDs, and binary labels for an ATBench JSON file."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    actual_hash = sha256_file(source)
    if expected_sha256 and actual_hash != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {source}: expected {expected_sha256}, got {actual_hash}"
        )
    try:
        rows = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Downloaded ATBench file is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(rows, list) or len(rows) != expected_rows:
        observed = len(rows) if isinstance(rows, list) else type(rows).__name__
        raise ValueError(f"Expected {expected_rows} ATBench rows, found {observed}")
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    labels = [row.get("label") for row in rows if isinstance(row, dict)]
    if len(ids) != expected_rows or len(set(ids)) != expected_rows:
        raise ValueError("ATBench IDs are missing or not unique")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("ATBench contains a non-binary or missing label")
    return {
        "path": str(source),
        "bytes": source.stat().st_size,
        "sha256": actual_hash,
        "rows": len(rows),
        "safe": labels.count(0),
        "unsafe": labels.count(1),
        "revision": ATBENCH_REVISION,
        "source_url": ATBENCH_URL,
    }


def download_atbench(
    destination: str | Path,
    *,
    force: bool = False,
    url: str = ATBENCH_URL,
    expected_sha256: str = ATBENCH_SHA256,
    expected_rows: int = 1_000,
) -> dict[str, Any]:
    """Download ATBench atomically, then verify its pinned content hash."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        return validate_atbench_file(
            target,
            expected_sha256=expected_sha256,
            expected_rows=expected_rows,
        )

    request = Request(url, headers={"User-Agent": "trajectory-audit/0.1"})
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            with urlopen(request, timeout=60) as response:  # nosec B310: pinned HTTPS URL
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path = Path(temporary_name)
        validate_atbench_file(
            temporary_path,
            expected_sha256=expected_sha256,
            expected_rows=expected_rows,
        )
        temporary_path.replace(target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)

    return validate_atbench_file(
        target,
        expected_sha256=expected_sha256,
        expected_rows=expected_rows,
    )


__all__ = [
    "ATBENCH_BYTES",
    "ATBENCH_REVISION",
    "ATBENCH_SHA256",
    "ATBENCH_URL",
    "download_atbench",
    "sha256_file",
    "validate_atbench_file",
]

