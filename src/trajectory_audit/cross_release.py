"""Cross-release shortcut audit for the two official ATBench releases.

The experiment deliberately keeps the target release untouched: a word-TF-IDF
classifier and its 0.5 decision threshold are fitted on one release and applied
directly to the other.  This distinguishes in-release separability from a cue
that survives a change in benchmark generation and schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence
from urllib.request import Request, urlopen

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .baseline import classification_metrics
from .data import TrajectoryRecord, load_records
from .download import ATBENCH_REVISION, ATBENCH_SHA256, ATBENCH_URL, sha256_file
from .views import build_view


ATBENCH500_URL = (
    "https://huggingface.co/datasets/AI45Research/ATBench/resolve/"
    f"{ATBENCH_REVISION}/ATBench500/test.json"
)
ATBENCH500_SHA256 = "031285443c6b8ca64fc117bd995a4b4490c340467136506763aeed1b23c8f34c"
ATBENCH500_BYTES = 5_422_164
DATASET_LICENSE = "Apache-2.0"


@dataclass(frozen=True)
class ReleaseSpec:
    """Immutable provenance and schema contract for one benchmark release."""

    name: str
    url: str
    sha256: str
    rows: int
    safe: int
    unsafe: int
    bytes: int | None
    schema: str
    id_field: str
    trajectory_field: str
    license: str = DATASET_LICENSE
    revision: str = ATBENCH_REVISION


ATBENCH_SPEC = ReleaseSpec(
    name="ATBench",
    url=ATBENCH_URL,
    sha256=ATBENCH_SHA256,
    rows=1_000,
    safe=503,
    unsafe=497,
    bytes=18_335_079,
    schema="ATBench v1: id/tool_used/contents/label plus taxonomy fields",
    id_field="id",
    trajectory_field="contents",
)

ATBENCH500_SPEC = ReleaseSpec(
    name="ATBench500",
    url=ATBENCH500_URL,
    sha256=ATBENCH500_SHA256,
    rows=500,
    safe=250,
    unsafe=250,
    bytes=ATBENCH500_BYTES,
    schema="ATBench500 legacy: conv_id/tool_used/content/label plus taxonomy fields",
    id_field="conv_id",
    trajectory_field="content",
)


def validate_release_file(path: str | Path, spec: ReleaseSpec) -> dict[str, Any]:
    """Verify that ``path`` is exactly the official release described by ``spec``."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    actual_hash = sha256_file(source)
    if spec.sha256 and actual_hash != spec.sha256:
        raise ValueError(
            f"SHA-256 mismatch for {spec.name}: expected {spec.sha256}, got {actual_hash}"
        )
    try:
        rows = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{spec.name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(rows, list) or len(rows) != spec.rows:
        observed = len(rows) if isinstance(rows, list) else type(rows).__name__
        raise ValueError(f"Expected {spec.rows} {spec.name} rows, found {observed}")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{spec.name} contains a non-object row")
    identifiers = [row.get(spec.id_field) for row in rows]
    if any(value is None or str(value).strip() == "" for value in identifiers):
        raise ValueError(f"{spec.name} has a missing {spec.id_field}")
    if len(set(map(str, identifiers))) != spec.rows:
        raise ValueError(f"{spec.name} {spec.id_field} values are not unique")
    if any(spec.trajectory_field not in row for row in rows):
        raise ValueError(
            f"{spec.name} has a row without trajectory field {spec.trajectory_field}"
        )
    labels = [row.get("label") for row in rows]
    if any(label not in (0, 1) for label in labels):
        raise ValueError(f"{spec.name} contains a non-binary or missing label")
    if labels.count(0) != spec.safe or labels.count(1) != spec.unsafe:
        raise ValueError(
            f"{spec.name} label counts differ from the release contract: "
            f"safe={labels.count(0)}, unsafe={labels.count(1)}"
        )
    if spec.bytes is not None and source.stat().st_size != spec.bytes:
        raise ValueError(
            f"{spec.name} byte size differs: expected {spec.bytes}, "
            f"got {source.stat().st_size}"
        )
    return {
        **asdict(spec),
        "path": str(source),
        "actual_sha256": actual_hash,
        "actual_bytes": source.stat().st_size,
    }


def download_release(
    destination: str | Path,
    spec: ReleaseSpec,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Download one pinned release atomically and validate it before replacement."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        return validate_release_file(target, spec)

    request = Request(spec.url, headers={"User-Agent": "trajectory-audit/0.1"})
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            with urlopen(request, timeout=60) as response:  # nosec B310: pinned HTTPS
                while chunk := response.read(1024 * 1024):
                    temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path = Path(temporary_name)
        validate_release_file(temporary_path, spec)
        temporary_path.replace(target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return validate_release_file(target, spec)


def ensure_release(
    path: str | Path,
    spec: ReleaseSpec,
    *,
    download_missing: bool = False,
) -> dict[str, Any]:
    """Validate an existing official file, optionally downloading it when absent."""

    source = Path(path)
    if not source.exists():
        if not download_missing:
            raise FileNotFoundError(
                f"{source} does not exist; pass download_missing=True to fetch {spec.name}"
            )
        return download_release(source, spec)
    return validate_release_file(source, spec)


def expected_calibration_error(
    y_true: Sequence[int], probabilities: Sequence[float], *, n_bins: int = 10
) -> dict[str, Any]:
    """Return fixed-width binary ECE and its auditable per-bin components."""

    if len(y_true) != len(probabilities) or not y_true:
        raise ValueError("y_true and probabilities must have equal non-zero length")
    if n_bins < 2:
        raise ValueError("n_bins must be at least 2")
    truth = np.asarray(y_true, dtype=float)
    scores = np.asarray(probabilities, dtype=float)
    if np.any((scores < 0.0) | (scores > 1.0)):
        raise ValueError("probabilities must lie in [0, 1]")
    indices = np.minimum((scores * n_bins).astype(int), n_bins - 1)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(n_bins):
        selected = indices == index
        count = int(selected.sum())
        lower = index / n_bins
        upper = (index + 1) / n_bins
        if count:
            mean_probability = float(scores[selected].mean())
            empirical_rate = float(truth[selected].mean())
            contribution = count / len(truth) * abs(mean_probability - empirical_rate)
            ece += contribution
        else:
            mean_probability = None
            empirical_rate = None
            contribution = 0.0
        bins.append(
            {
                "index": index,
                "lower": lower,
                "upper": upper,
                "count": count,
                "mean_probability": mean_probability,
                "empirical_unsafe_rate": empirical_rate,
                "ece_contribution": contribution,
            }
        )
    return {"ece": float(ece), "n_bins": n_bins, "bins": bins}


def _fit_transfer_model(
    train_texts: Sequence[str],
    train_labels: Sequence[int],
    *,
    max_features: int | None,
    seed: int,
) -> Pipeline:
    if set(train_labels) != {0, 1}:
        raise ValueError("each source release must contain both binary labels")
    model = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=1,
                    max_features=max_features,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1_000,
                    random_state=seed,
                    solver="liblinear",
                ),
            ),
        ]
    )
    model.fit(train_texts, train_labels)
    return model


def _evaluate_direction(
    source: Sequence[TrajectoryRecord],
    target: Sequence[TrajectoryRecord],
    *,
    views: Sequence[str],
    max_features: int | None,
    seed: int,
    threshold: float,
    ece_bins: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    y_train = [int(record.label) for record in source]
    y_test = [int(record.label) for record in target]
    output: dict[str, Any] = {}
    prediction_rows: list[dict[str, Any]] = []
    for view in views:
        train_texts = [build_view(record, view) for record in source]
        test_texts = [build_view(record, view) for record in target]
        model = _fit_transfer_model(
            train_texts, y_train, max_features=max_features, seed=seed
        )
        class_index = list(model.named_steps["classifier"].classes_).index(1)
        scores = model.predict_proba(test_texts)[:, class_index].astype(float)
        predictions = (scores >= threshold).astype(int)
        metrics = classification_metrics(
            y_test, predictions.tolist(), scores=scores.tolist(), positive_label=1
        )
        metrics["brier_score"] = float(np.mean((scores - np.asarray(y_test)) ** 2))
        calibration = expected_calibration_error(y_test, scores.tolist(), n_bins=ece_bins)
        metrics["expected_calibration_error"] = calibration["ece"]
        output[view] = {
            "metrics": metrics,
            "calibration": calibration,
            "threshold": threshold,
            "vocabulary_size": len(
                model.named_steps["tfidf"].get_feature_names_out()
            ),
        }
        for record, truth, prediction, score in zip(
            target, y_test, predictions.tolist(), scores.tolist()
        ):
            prediction_rows.append(
                {
                    "view": view,
                    "record_id": record.id,
                    "y_true": truth,
                    "y_pred": prediction,
                    "unsafe_probability": score,
                    "correct": truth == prediction,
                }
            )
    return output, prediction_rows


def run_cross_release(
    atbench_path: str | Path,
    atbench500_path: str | Path,
    *,
    atbench_spec: ReleaseSpec = ATBENCH_SPEC,
    atbench500_spec: ReleaseSpec = ATBENCH500_SPEC,
    verify_official: bool = True,
    max_features: int | None = 50_000,
    seed: int = 42,
    threshold: float = 0.5,
    ece_bins: int = 10,
    views: Sequence[str] = ("full", "final_answer_only"),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Train on each release and evaluate on the other without target tuning."""

    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold must lie strictly between 0 and 1")
    paths = {"atbench": Path(atbench_path), "atbench500": Path(atbench500_path)}
    specs = {"atbench": atbench_spec, "atbench500": atbench500_spec}
    provenance = {}
    for key, path in paths.items():
        if verify_official:
            provenance[key] = validate_release_file(path, specs[key])
        else:
            provenance[key] = {
                **asdict(specs[key]),
                "path": str(path),
                "actual_sha256": sha256_file(path),
                "actual_bytes": path.stat().st_size,
                "verification": "shape/hash contract bypassed for caller-supplied fixture",
            }

    releases = {key: load_records(path) for key, path in paths.items()}
    for key, records in releases.items():
        if not records or any(record.label not in (0, 1) for record in records):
            raise ValueError(f"{key} did not normalize to fully labelled binary records")

    direction_specs = (
        ("atbench_to_atbench500", "atbench", "atbench500"),
        ("atbench500_to_atbench", "atbench500", "atbench"),
    )
    directions: dict[str, Any] = {}
    all_predictions: list[dict[str, Any]] = []
    for name, source_key, target_key in direction_specs:
        view_results, predictions = _evaluate_direction(
            releases[source_key],
            releases[target_key],
            views=views,
            max_features=max_features,
            seed=seed,
            threshold=threshold,
            ece_bins=ece_bins,
        )
        directions[name] = {
            "source_release": specs[source_key].name,
            "target_release": specs[target_key].name,
            "source_records": len(releases[source_key]),
            "target_records": len(releases[target_key]),
            "views": view_results,
        }
        for row in predictions:
            row.update(
                {
                    "direction": name,
                    "source_release": specs[source_key].name,
                    "target_release": specs[target_key].name,
                }
            )
        all_predictions.extend(predictions)

    result = {
        "schema_version": 1,
        "experiment": "fixed_threshold_cross_release_transfer",
        "config": {
            "model": "word_tfidf_unigram_bigram_logistic_regression",
            "max_features": max_features,
            "class_weight": "balanced",
            "seed": seed,
            "decision_threshold": threshold,
            "target_threshold_tuning": False,
            "ece_bins": ece_bins,
            "views": list(views),
        },
        "dataset_provenance": provenance,
        "directions": directions,
    }
    return result, all_predictions


def write_cross_release_outputs(
    output_dir: str | Path,
    result: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
) -> dict[str, Path]:
    """Save JSON, per-example CSV, and a compact Markdown interpretation table."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "cross_release_results.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_path = directory / "cross_release_predictions.csv"
    fields = [
        "direction",
        "source_release",
        "target_release",
        "view",
        "record_id",
        "y_true",
        "y_pred",
        "unsafe_probability",
        "correct",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(predictions)

    lines = [
        "# ATBench cross-release transfer",
        "",
        "The classifier and its fixed 0.5 threshold are trained on the source release and",
        "applied to the target release without target-label calibration.",
        "",
        "| Direction | View | Macro-F1 | AUROC | Balanced accuracy | Unsafe FNR | Safe FPR | Brier | ECE |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for direction, payload in result["directions"].items():
        for view, view_payload in payload["views"].items():
            metrics = view_payload["metrics"]
            lines.append(
                "| {direction} | {view} | {macro_f1:.3f} | {auc:.3f} | {balanced:.3f} | "
                "{fnr:.3f} | {fpr:.3f} | {brier:.3f} | {ece:.3f} |".format(
                    direction=direction.replace("_", " "),
                    view=view,
                    macro_f1=metrics["macro_f1"],
                    auc=metrics["roc_auc"],
                    balanced=metrics["balanced_accuracy"],
                    fnr=metrics["false_negative_rate"],
                    fpr=metrics["false_positive_rate"],
                    brier=metrics["brier_score"],
                    ece=metrics["expected_calibration_error"],
                )
            )
    lines.extend(
        [
            "",
            "Brier and ECE use unsafe probabilities. A cross-release F1 drop can reflect both",
            "ranking degradation and threshold/calibration shift; AUROC separates the former.",
            "",
            "## Provenance",
            "",
        ]
    )
    for payload in result["dataset_provenance"].values():
        lines.append(
            f"- {payload['name']}: `{payload['actual_sha256']}`; "
            f"{payload['license']}; {payload['schema']}; {payload['url']}"
        )
    markdown_path = directory / "cross_release_report.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"results": json_path, "predictions": csv_path, "report": markdown_path}


__all__ = [
    "ATBENCH500_BYTES",
    "ATBENCH500_SHA256",
    "ATBENCH500_SPEC",
    "ATBENCH500_URL",
    "ATBENCH_SPEC",
    "ReleaseSpec",
    "download_release",
    "ensure_release",
    "expected_calibration_error",
    "run_cross_release",
    "validate_release_file",
    "write_cross_release_outputs",
]
