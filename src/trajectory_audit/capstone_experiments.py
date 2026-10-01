"""Reproducible CPU experiments for the ATBench capstone.

This module extends the small partial-view audit with the controls needed for a
capstone report.  Every text model is the same word (1, 2)-gram TF-IDF plus
class-balanced logistic regression baseline used by :mod:`trajectory_audit.baseline`.
The only exception is the explicitly labelled ``structure_only`` control, which
uses numeric, label-free counts from the normalized trajectory.

Run the complete default experiment suite with::

    python -m trajectory_audit.capstone_experiments \
      --input data/raw/atbench/test.json \
      --output-dir outputs/atbench-capstone

The public functions accept smaller grids so the protocol can be tested quickly
without changing the defaults used in the paper.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import csv
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import re
import sys
import time
from typing import Any

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .baseline import (
    classification_metrics,
    evaluate_tfidf_cross_validation,
    flatten_predictions,
)
from .data import DataFormatError, TrajectoryRecord, canonical_text, load_records
from .grouping import derive_semantic_groups
from .reporting import aggregate_cross_validation, view_length_statistics
from .splits import cross_validation_splits
from .views import build_view


DEFAULT_INPUT = Path("data/raw/atbench/test.json")
DEFAULT_OUTPUT = Path("outputs/atbench-capstone")

DEFAULT_CAPACITIES: tuple[int | None, ...] = (5_000, 20_000, 50_000, None)
DEFAULT_CLUSTER_KS = (25, 50, 75, 100)
DEFAULT_CLUSTER_SEEDS = (7, 21, 42)


# This lexicon is deliberately fixed in source rather than learned from ATBench
# labels.  Every matched phrase receives the same token, so the masked text does
# not reveal which cue family matched.  The category is retained only in the
# aggregate coverage audit and the exported lexicon.
CUE_LEXICON: dict[str, tuple[str, ...]] = {
    "refusal_or_inability": (
        "cannot",
        "can't",
        "could not",
        "decline",
        "declined",
        "declining",
        "refuse",
        "refused",
        "refusing",
        "unable",
        "will not",
        "won't",
    ),
    "authorization_or_policy": (
        "not authorized",
        "unauthorized",
        "not permitted",
        "permission",
        "consent",
        "policy",
        "privacy",
        "security reason",
        "security reasons",
        "safety reason",
        "safety reasons",
        "sensitive",
        "confidential",
        "prohibited",
    ),
    "successful_outcome": (
        "success",
        "successful",
        "successfully",
        "completed",
        "confirmed",
        "confirms",
        "created",
        "deleted",
        "downloaded",
        "enabled",
        "exported",
        "retrieved",
        "returned",
        "scheduled",
        "sent",
        "transferred",
        "updated",
        "uploaded",
    ),
}
MASK_TOKEN = "[MASKED_CUE]"


def _compile_cue_pattern() -> tuple[re.Pattern[str], dict[str, str]]:
    alternatives: list[tuple[str, str]] = []
    for category, phrases in CUE_LEXICON.items():
        for phrase in phrases:
            escaped = re.escape(phrase).replace(r"\ ", r"\s+")
            alternatives.append((category, escaped))
    alternatives.sort(key=lambda item: len(item[1]), reverse=True)
    group_to_category: dict[str, str] = {}
    pieces: list[str] = []
    for index, (category, escaped) in enumerate(alternatives):
        group = f"cue_{index}"
        group_to_category[group] = category
        pieces.append(f"(?P<{group}>(?<!\\w){escaped}(?!\\w))")
    return re.compile("|".join(pieces), flags=re.IGNORECASE), group_to_category


_CUE_PATTERN, _CUE_GROUP_TO_CATEGORY = _compile_cue_pattern()


def mask_posthoc_cues(text: str) -> tuple[str, dict[str, int]]:
    """Replace every predefined outcome/refusal cue with one neutral token.

    The returned counts are diagnostic only.  They are never appended to the
    masked model input, because doing so would reintroduce the removed cue type.
    """

    counts = {category: 0 for category in CUE_LEXICON}

    def replacement(match: re.Match[str]) -> str:
        category = _CUE_GROUP_TO_CATEGORY[str(match.lastgroup)]
        counts[category] += 1
        return MASK_TOKEN

    return _CUE_PATTERN.sub(replacement, str(text)), counts


TEMPORAL_VIEW_NAMES = (
    "full",
    "static_context",
    "user_plus_final",
    "full_without_final",
    "prefix_25",
    "prefix_50",
    "prefix_75",
    "final_answer_only",
    "final_answer_masked",
)

VIEW_DEFINITIONS = {
    "full": "Tool schemas plus every normalized event.",
    "static_context": "User messages plus tool schemas; no agent or environment events.",
    "user_plus_final": "User messages plus the terminal final answer; no tools or intermediate events.",
    "full_without_final": "Tool schemas plus all events except completion events.",
    "prefix_25": "Tool schemas plus the first floor(25% of events), minimum one.",
    "prefix_50": "Tool schemas plus the first floor(50% of events), minimum one.",
    "prefix_75": "Tool schemas plus the first floor(75% of events), minimum one.",
    "final_answer_only": "The terminal completion, or the last assistant message fallback.",
    "final_answer_masked": "Final answer with the fixed cue lexicon replaced by one token.",
}


def _render_full_with_events(
    record: TrajectoryRecord, events: Sequence[Any], view_name: str
) -> str:
    rendered = build_view(replace(record, events=tuple(events)), "full")
    return rendered.replace("[VIEW full]", f"[VIEW {view_name}]", 1)


def build_temporal_views(record: TrajectoryRecord) -> dict[str, str]:
    """Create full, event-boundary prefixes, and final-answer controls.

    Prefixes slice the normalized event tuple before rendering; no message,
    action, tool result, or completion is cut in the middle.  Tool schemas are
    available at every prefix because an agent receives them before acting.
    """

    events = tuple(record.events)
    output = {
        "full": build_view(record, "full"),
        "static_context": "\n\n".join(
            (
                "[VIEW static_context]",
                build_view(record, "user_only"),
                build_view(record, "tool_schema_only"),
            )
        ),
        "user_plus_final": "\n\n".join(
            (
                "[VIEW user_plus_final]",
                build_view(record, "user_only"),
                build_view(record, "final_answer_only"),
            )
        ),
        "full_without_final": _render_full_with_events(
            record,
            tuple(event for event in events if event.kind != "completion"),
            "full_without_final",
        ),
        "final_answer_only": build_view(record, "final_answer_only"),
    }
    for percent in (25, 50, 75):
        count = math.floor(len(events) * percent / 100)
        if events:
            count = max(1, count)
        name = f"prefix_{percent}"
        output[name] = _render_full_with_events(record, events[:count], name)

    masked, _ = mask_posthoc_cues(output["final_answer_only"])
    output["final_answer_masked"] = masked.replace(
        "[VIEW final_answer_only]", "[VIEW final_answer_masked]", 1
    )
    return {name: output[name] for name in TEMPORAL_VIEW_NAMES}


DEFAULT_TOP_COEFFICIENT_KS = (5, 10, 25, 50, 100)


def _fit_word_model(
    train_texts: Sequence[str],
    train_labels: Sequence[int],
    *,
    max_features: int | None,
    seed: int,
) -> Any:
    clean = [text if text.strip() else "[EMPTY]" for text in train_texts]
    if len(set(train_labels)) < 2:
        model: Any = DummyClassifier(strategy="most_frequent")
        model.fit(clean, train_labels)
        return model
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
    model.fit(clean, train_labels)
    return model


def _remove_unigram_terms(texts: Sequence[str], terms: Sequence[str]) -> list[str]:
    if not terms:
        return list(texts)
    alternatives = sorted((re.escape(term) for term in terms), key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)",
        flags=re.IGNORECASE,
    )
    return [pattern.sub(" ", text) for text in texts]


def train_fold_coefficient_removal_curve(
    records: Sequence[TrajectoryRecord],
    final_texts: Sequence[str],
    groups: Sequence[str],
    *,
    folds: int,
    seed: int,
    max_features: int | None,
    k_values: Sequence[int] = DEFAULT_TOP_COEFFICIENT_KS,
) -> dict[str, Any]:
    """Evaluate train-fold-only top-|coefficient| unigram removal.

    For every group fold, the ranking is learned solely from that fold's
    training records.  The selected tokens are deleted from both train and test
    text for that fold, and a fresh TF-IDF/logistic model is fitted.  Therefore
    held-out labels and held-out token coefficients never influence selection.
    """

    if len(records) != len(final_texts) or len(records) != len(groups):
        raise ValueError("records, final_texts, and groups must have equal length")
    if not k_values or any(int(value) < 1 for value in k_values):
        raise ValueError("k_values must contain positive integers")
    labels = [int(record.label) for record in records]
    splits = cross_validation_splits(
        records,
        strategy="group",
        n_splits=folds,
        seed=seed,
        group_values=groups,
    )
    predictions_by_k: dict[int, list[dict[str, Any]]] = {
        int(k): [] for k in k_values
    }
    selected_rows: list[dict[str, Any]] = []
    for split in splits:
        train_indices = list(split.train_indices)
        test_indices = list(split.test_indices)
        train_texts = [final_texts[index] for index in train_indices]
        y_train = [labels[index] for index in train_indices]
        ranking_model = _fit_word_model(
            train_texts,
            y_train,
            max_features=max_features,
            seed=seed,
        )
        if not isinstance(ranking_model, Pipeline):
            raise ValueError("a training fold has only one label; cannot rank coefficients")
        vectorizer = ranking_model.named_steps["tfidf"]
        classifier = ranking_model.named_steps["classifier"]
        feature_names = vectorizer.get_feature_names_out()
        coefficients = classifier.coef_[0]
        candidates = [
            (str(feature_names[index]), float(coefficients[index]))
            for index in range(len(feature_names))
            if " " not in str(feature_names[index])
        ]
        candidates.sort(key=lambda pair: (-abs(pair[1]), pair[0]))
        maximum = max(int(k) for k in k_values)
        ranked = candidates[:maximum]
        for rank, (term, coefficient) in enumerate(ranked, start=1):
            selected_rows.append(
                {
                    "fold": int(split.fold_index),
                    "rank": rank,
                    "term": term,
                    "coefficient": coefficient,
                    "absolute_coefficient": abs(coefficient),
                    "selection_scope": "training_fold_only",
                }
            )

        for k in k_values:
            numeric_k = int(k)
            selected_terms = [term for term, _ in ranked[:numeric_k]]
            masked_train = _remove_unigram_terms(train_texts, selected_terms)
            masked_test = _remove_unigram_terms(
                [final_texts[index] for index in test_indices], selected_terms
            )
            model = _fit_word_model(
                masked_train,
                y_train,
                max_features=max_features,
                seed=seed,
            )
            y_pred = model.predict(masked_test).astype(int).tolist()
            probabilities = model.predict_proba(masked_test)
            classes = list(model.classes_)
            positive_scores = (
                probabilities[:, classes.index(1)].astype(float).tolist()
                if 1 in classes
                else [0.0] * len(test_indices)
            )
            for position, record_index in enumerate(test_indices):
                predictions_by_k[numeric_k].append(
                    {
                        "removed_k": numeric_k,
                        "split": f"group_fold_{split.fold_index}",
                        "view": "final_answer_train_fold_token_removal",
                        "record_index": record_index,
                        "record_id": records[record_index].id,
                        "group": groups[record_index],
                        "y_true": labels[record_index],
                        "y_pred": y_pred[position],
                        "positive_score": positive_scores[position],
                        "correct": labels[record_index] == y_pred[position],
                    }
                )

    metric_rows: list[dict[str, Any]] = []
    all_predictions: list[dict[str, Any]] = []
    for k in sorted(predictions_by_k):
        predictions = sorted(
            predictions_by_k[k], key=lambda row: int(row["record_index"])
        )
        if [int(row["record_index"]) for row in predictions] != list(range(len(records))):
            raise ValueError(f"incomplete OOF coverage for coefficient removal k={k}")
        metrics = classification_metrics(
            [row["y_true"] for row in predictions],
            [row["y_pred"] for row in predictions],
            scores=[row["positive_score"] for row in predictions],
            positive_label=1,
        )
        metric_rows.append(
            _metric_row(
                metrics,
                experiment="train_fold_coefficient_removal",
                strategy="group",
                view="final_answer_only",
                removed_k=k,
                selection_scope="training_fold_only",
            )
        )
        all_predictions.extend(predictions)
    return {
        "k_values": sorted(int(k) for k in k_values),
        "selection_scope": "training_fold_only",
        "metrics": metric_rows,
        "selected_terms": selected_rows,
        "predictions": all_predictions,
    }


STRUCTURE_FEATURE_NAMES = (
    "available_tools",
    "events",
    "distinct_event_kinds",
    "distinct_roles",
    "message_events",
    "user_messages",
    "assistant_messages",
    "reasoning_events",
    "tool_calls",
    "tool_results",
    "completion_events",
    "other_events",
    "content_characters",
    "argument_characters",
    "tool_schema_characters",
    "mean_content_characters",
    "max_content_characters",
    "empty_content_events",
    "named_tool_calls",
    "unique_called_tools",
    "unmatched_tool_call_count",
    "event_kind_transitions",
    "completion_position_fraction",
)


def structure_features(record: TrajectoryRecord) -> dict[str, float]:
    """Return label-free numeric counts from one normalized trajectory."""

    kind_counts = Counter(event.kind for event in record.events)
    role_counts = Counter(event.role for event in record.events)
    content_lengths = [len(event.content or "") for event in record.events]
    argument_lengths = [len(event.arguments or "") for event in record.events]
    called_names = [event.name for event in record.events if event.kind == "tool_call" and event.name]
    completion_positions = [
        index for index, event in enumerate(record.events) if event.kind == "completion"
    ]
    event_count = len(record.events)
    completion_fraction = (
        completion_positions[-1] / max(1, event_count - 1)
        if completion_positions
        else -1.0
    )
    transitions = sum(
        first.kind != second.kind
        for first, second in zip(record.events, record.events[1:])
    )
    tool_schema_characters = sum(
        len(tool.name)
        + len(tool.description)
        + len(canonical_text(tool.parameters))
        for tool in record.tools
    )
    tool_calls = kind_counts.get("tool_call", 0)
    tool_results = kind_counts.get("tool_result", 0)
    values = {
        "available_tools": len(record.tools),
        "events": event_count,
        "distinct_event_kinds": len(kind_counts),
        "distinct_roles": len(role_counts),
        "message_events": kind_counts.get("message", 0),
        "user_messages": sum(
            event.kind == "message" and event.role == "user" for event in record.events
        ),
        "assistant_messages": sum(
            event.kind == "message" and event.role == "assistant"
            for event in record.events
        ),
        "reasoning_events": kind_counts.get("reasoning", 0),
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "completion_events": kind_counts.get("completion", 0),
        "other_events": kind_counts.get("other", 0),
        "content_characters": sum(content_lengths),
        "argument_characters": sum(argument_lengths),
        "tool_schema_characters": tool_schema_characters,
        "mean_content_characters": (
            sum(content_lengths) / event_count if event_count else 0.0
        ),
        "max_content_characters": max(content_lengths, default=0),
        "empty_content_events": sum(length == 0 for length in content_lengths),
        "named_tool_calls": len(called_names),
        "unique_called_tools": len(set(called_names)),
        "unmatched_tool_call_count": max(0, tool_calls - tool_results),
        "event_kind_transitions": transitions,
        "completion_position_fraction": completion_fraction,
    }
    return {name: float(values[name]) for name in STRUCTURE_FEATURE_NAMES}


def _structure_cross_validation(
    records: Sequence[TrajectoryRecord],
    groups: Sequence[str],
    *,
    folds: int,
    seed: int,
) -> dict[str, Any]:
    matrix = np.asarray(
        [[structure_features(record)[name] for name in STRUCTURE_FEATURE_NAMES] for record in records],
        dtype=float,
    )
    labels = np.asarray([int(record.label) for record in records], dtype=int)
    splits = cross_validation_splits(
        records,
        strategy="group",
        n_splits=folds,
        seed=seed,
        group_values=groups,
    )
    prediction_rows: list[dict[str, Any]] = []
    fold_metrics: list[dict[str, Any]] = []
    for split in splits:
        train_indices = np.asarray(split.train_indices, dtype=int)
        test_indices = np.asarray(split.test_indices, dtype=int)
        y_train = labels[train_indices]
        if len(set(y_train.tolist())) < 2:
            model: Any = DummyClassifier(strategy="most_frequent")
        else:
            model = Pipeline(
                [
                    ("scale", StandardScaler()),
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
        model.fit(matrix[train_indices], y_train)
        predictions = model.predict(matrix[test_indices]).astype(int)
        probabilities = model.predict_proba(matrix[test_indices])
        classes = list(model.classes_)
        positive_scores = (
            probabilities[:, classes.index(1)].astype(float)
            if 1 in classes
            else np.zeros(len(test_indices), dtype=float)
        )
        fold_metric = classification_metrics(
            labels[test_indices].tolist(),
            predictions.tolist(),
            scores=positive_scores.tolist(),
            positive_label=1,
        )
        fold_metric["fold"] = split.fold_index
        fold_metrics.append(fold_metric)
        for position, record_index in enumerate(test_indices.tolist()):
            prediction_rows.append(
                {
                    "split": f"group_fold_{split.fold_index}",
                    "view": "structure_only",
                    "record_index": record_index,
                    "record_id": records[record_index].id,
                    "group": groups[record_index],
                    "y_true": int(labels[record_index]),
                    "y_pred": int(predictions[position]),
                    "positive_score": float(positive_scores[position]),
                    "correct": bool(labels[record_index] == predictions[position]),
                }
            )
    prediction_rows.sort(key=lambda row: int(row["record_index"]))
    pooled = classification_metrics(
        [row["y_true"] for row in prediction_rows],
        [row["y_pred"] for row in prediction_rows],
        scores=[row["positive_score"] for row in prediction_rows],
        positive_label=1,
    )
    return {
        "model": "standardized_numeric_logistic_regression",
        "features": list(STRUCTURE_FEATURE_NAMES),
        "metrics": pooled,
        "fold_metrics": fold_metrics,
        "predictions": prediction_rows,
    }


def _version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    fields = sorted({str(key) for row in materialized for key in row})
    preferred = [
        "experiment",
        "strategy",
        "view",
        "max_features",
        "n_groups",
        "clustering_seed",
        "taxonomy",
        "category",
        "record_index",
        "record_id",
        "label",
    ]
    fieldnames = [field for field in preferred if field in fields]
    fieldnames.extend(field for field in fields if field not in fieldnames)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            serialized = {
                key: (
                    json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list, tuple))
                    else value
                )
                for key, value in row.items()
            }
            writer.writerow(serialized)
    return path


def _metric_row(
    metrics: Mapping[str, Any],
    **identifiers: Any,
) -> dict[str, Any]:
    return {
        **identifiers,
        "n": metrics.get("n"),
        "accuracy": metrics.get("accuracy"),
        "balanced_accuracy": metrics.get("balanced_accuracy"),
        "macro_f1": metrics.get("macro_f1"),
        "weighted_f1": metrics.get("weighted_f1"),
        "roc_auc": metrics.get("roc_auc"),
        "average_precision": metrics.get("average_precision"),
        "false_negative_rate": metrics.get("false_negative_rate"),
        "false_positive_rate": metrics.get("false_positive_rate"),
    }


def _taxonomy_value(value: Any) -> str:
    if value is None or value == "":
        return "<missing>"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _group_predictions(
    results: Mapping[str, Any], view: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split_name, split in results.get("splits", {}).items():
        if not str(split_name).startswith("group_fold_"):
            continue
        rows.extend(split["views"][view]["predictions"])
    return sorted(rows, key=lambda row: int(row["record_index"]))


def taxonomy_sliced_metrics(
    records: Sequence[TrajectoryRecord],
    results: Mapping[str, Any],
    *,
    views: Sequence[str] = ("full", "final_answer_only"),
    taxonomies: Sequence[str] = (
        "risk_source",
        "failure_mode",
        "real_world_harm",
    ),
) -> list[dict[str, Any]]:
    """Compute pooled group-OOF metrics inside each published taxonomy slice."""

    output: list[dict[str, Any]] = []
    for view in views:
        predictions = _group_predictions(results, view)
        by_index = {int(row["record_index"]): row for row in predictions}
        if set(by_index) != set(range(len(records))):
            raise ValueError(f"group OOF coverage is incomplete for {view}")
        for taxonomy in taxonomies:
            members: dict[str, list[int]] = defaultdict(list)
            for index, record in enumerate(records):
                members[_taxonomy_value(record.raw.get(taxonomy))].append(index)
            for category, indices in sorted(members.items()):
                rows = [by_index[index] for index in indices]
                scores = [row.get("positive_score") for row in rows]
                metrics = classification_metrics(
                    [row["y_true"] for row in rows],
                    [row["y_pred"] for row in rows],
                    scores=None if any(score is None for score in scores) else scores,
                    positive_label=1,
                )
                output.append(
                    _metric_row(
                        metrics,
                        experiment="taxonomy_slice",
                        strategy="group",
                        view=view,
                        taxonomy=taxonomy,
                        category=category,
                        safe=sum(int(row["y_true"]) == 0 for row in rows),
                        unsafe=sum(int(row["y_true"]) == 1 for row in rows),
                    )
                )
    return output


def _extract_view_metrics(
    summary: Mapping[str, Any], strategies: Sequence[str], views: Sequence[str]
) -> list[dict[str, Any]]:
    rows = []
    for strategy in strategies:
        for view in views:
            metrics = summary["strategies"][strategy]["views"][view]["metrics"]
            rows.append(
                _metric_row(
                    metrics,
                    experiment="trajectory_view",
                    strategy=strategy,
                    view=view,
                )
            )
    return rows


def _masking_coverage(
    records: Sequence[TrajectoryRecord], final_texts: Sequence[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    masked_texts: list[str] = []
    rows: list[dict[str, Any]] = []
    for index, (record, text) in enumerate(zip(records, final_texts)):
        masked, counts = mask_posthoc_cues(text)
        masked = masked.replace(
            "[VIEW final_answer_only]", "[VIEW final_answer_masked]", 1
        )
        masked_texts.append(masked)
        rows.append(
            {
                "record_index": index,
                "record_id": record.id,
                "label": int(record.label),
                "matches": sum(counts.values()),
                **counts,
                "original_characters": len(text),
                "masked_characters": len(masked),
            }
        )
    return masked_texts, rows


def _write_summary_markdown(
    path: Path,
    view_rows: Sequence[Mapping[str, Any]],
    capacity_rows: Sequence[Mapping[str, Any]],
    cluster_rows: Sequence[Mapping[str, Any]],
    structure_row: Mapping[str, Any],
) -> Path:
    lines = [
        "# ATBench capstone experiment summary",
        "",
        "All scores are pooled out-of-fold metrics. Group splits hold out label-free",
        "TF-IDF/KMeans clusters derived from user requests and tool names.",
        "",
        "## Trajectory and cue views",
        "",
        "| strategy | view | Macro-F1 | AUROC | unsafe FNR |",
        "|---|---|---:|---:|---:|",
    ]
    for row in view_rows:
        lines.append(
            f"| {row['strategy']} | {row['view']} | {row['macro_f1']:.3f} | "
            f"{row['roc_auc']:.3f} | {row['false_negative_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Feature capacity sensitivity (group OOF)",
            "",
            "| max features | view | Macro-F1 | AUROC |",
            "|---:|---|---:|---:|",
        ]
    )
    for row in capacity_rows:
        lines.append(
            f"| {row['max_features']} | {row['view']} | {row['macro_f1']:.3f} | "
            f"{row['roc_auc']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Cluster sensitivity (group OOF)",
            "",
            "| K | clustering seed | view | Macro-F1 | AUROC |",
            "|---:|---:|---|---:|---:|",
        ]
    )
    for row in cluster_rows:
        lines.append(
            f"| {row['n_groups']} | {row['clustering_seed']} | {row['view']} | "
            f"{row['macro_f1']:.3f} | {row['roc_auc']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Structure-only control",
            "",
            f"Group OOF Macro-F1: **{structure_row['macro_f1']:.3f}**; "
            f"AUROC: **{structure_row['roc_auc']:.3f}**; "
            f"unsafe FNR: **{structure_row['false_negative_rate']:.3f}**.",
            "",
            "See the CSV files for per-taxonomy slices and the JSON result for the",
            "complete protocol, lexicon, view definitions, and configuration.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_capstone_experiments(
    records: Sequence[TrajectoryRecord],
    output_dir: str | Path,
    *,
    folds: int = 5,
    seed: int = 42,
    main_groups: int = 50,
    main_max_features: int | None = 50_000,
    capacity_grid: Sequence[int | None] = DEFAULT_CAPACITIES,
    cluster_ks: Sequence[int] = DEFAULT_CLUSTER_KS,
    cluster_seeds: Sequence[int] = DEFAULT_CLUSTER_SEEDS,
    coefficient_removal_ks: Sequence[int] = DEFAULT_TOP_COEFFICIENT_KS,
    input_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run every capstone experiment and write JSON/CSV artifacts.

    ``records`` must contain binary labels.  ``capacity_grid``, ``cluster_ks``,
    and ``cluster_seeds`` are arguments primarily so CI can exercise the same
    protocol on a small fixture; the command-line defaults are the paper grid.
    """

    started = time.perf_counter()
    rows = list(records)
    if len(rows) < folds * 2:
        raise ValueError("too few records for the requested cross-validation folds")
    if any(record.label not in (0, 1) for record in rows):
        raise ValueError("every record must have a binary label")
    if not folds <= main_groups <= len(rows):
        raise ValueError("main_groups must be between folds and the record count")
    if any(not folds <= int(k) <= len(rows) for k in cluster_ks):
        raise ValueError("every cluster K must be between folds and the record count")
    if not capacity_grid:
        raise ValueError("capacity_grid must not be empty")
    if not cluster_ks or not cluster_seeds:
        raise ValueError("cluster sensitivity grids must not be empty")
    if not coefficient_removal_ks:
        raise ValueError("coefficient_removal_ks must not be empty")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_records = [dict(record.raw) for record in rows]

    print(f"Deriving main K={main_groups} label-free clusters ...", flush=True)
    main_group_values, _, _ = derive_semantic_groups(
        raw_records, n_groups=main_groups, random_state=seed
    )

    rendered = [build_temporal_views(record) for record in rows]
    view_texts = {
        name: [item[name] for item in rendered] for name in TEMPORAL_VIEW_NAMES
    }
    masked_texts, masking_coverage = _masking_coverage(
        rows, view_texts["final_answer_only"]
    )
    # Use the separately audited masking pass as the canonical masked input.
    view_texts["final_answer_masked"] = masked_texts

    print("Running trajectory, prefix, and cue-masking OOF experiments ...", flush=True)
    main_results = evaluate_tfidf_cross_validation(
        rows,
        n_splits=folds,
        split_strategies=("random", "group"),
        group_values=main_group_values,
        seed=seed,
        view_names=TEMPORAL_VIEW_NAMES,
        view_texts=view_texts,
        max_features=main_max_features,
        bootstrap_resamples=0,
    )
    main_summary = aggregate_cross_validation(
        main_results,
        semantic_groups=main_group_values,
        bootstrap_resamples=0,
        seed=seed,
    )
    view_metrics = _extract_view_metrics(
        main_summary, ("random", "group"), TEMPORAL_VIEW_NAMES
    )
    cue_metrics = [
        dict(
            row,
            experiment="cue_masking",
            analysis_status="exploratory_post_hoc_fixed_lexicon",
        )
        for row in view_metrics
        if row["view"] in {"final_answer_only", "final_answer_masked"}
    ]
    for strategy in ("random", "group"):
        unmasked = next(
            row for row in cue_metrics if row["strategy"] == strategy and row["view"] == "final_answer_only"
        )
        for row in cue_metrics:
            if row["strategy"] == strategy:
                row["delta_macro_f1_vs_unmasked"] = row["macro_f1"] - unmasked["macro_f1"]

    print("Running leakage-controlled train-fold token-removal curve ...", flush=True)
    coefficient_removal = train_fold_coefficient_removal_curve(
        rows,
        view_texts["final_answer_only"],
        main_group_values,
        folds=folds,
        seed=seed,
        max_features=main_max_features,
        k_values=coefficient_removal_ks,
    )
    unremoved_metrics = main_summary["strategies"]["group"]["views"][
        "final_answer_only"
    ]["metrics"]
    coefficient_curve_rows = [
        _metric_row(
            unremoved_metrics,
            experiment="train_fold_coefficient_removal",
            strategy="group",
            view="final_answer_only",
            removed_k=0,
            selection_scope="none_baseline",
        ),
        *coefficient_removal["metrics"],
    ]
    baseline_curve_f1 = coefficient_curve_rows[0]["macro_f1"]
    for row in coefficient_curve_rows:
        row["delta_macro_f1_vs_k0"] = row["macro_f1"] - baseline_curve_f1

    print("Running feature-capacity sensitivity ...", flush=True)
    capacity_rows: list[dict[str, Any]] = []
    for max_features in capacity_grid:
        if max_features == main_max_features:
            capacity_summary = main_summary
        else:
            result = evaluate_tfidf_cross_validation(
                rows,
                n_splits=folds,
                split_strategies=("group",),
                group_values=main_group_values,
                seed=seed,
                view_names=("full", "final_answer_only"),
                view_texts={
                    "full": view_texts["full"],
                    "final_answer_only": view_texts["final_answer_only"],
                },
                max_features=max_features,
                bootstrap_resamples=0,
            )
            capacity_summary = aggregate_cross_validation(
                result,
                semantic_groups=main_group_values,
                bootstrap_resamples=0,
                seed=seed,
            )
        for view in ("full", "final_answer_only"):
            metrics = capacity_summary["strategies"]["group"]["views"][view]["metrics"]
            capacity_rows.append(
                _metric_row(
                    metrics,
                    experiment="feature_capacity",
                    strategy="group",
                    view=view,
                    max_features="all" if max_features is None else int(max_features),
                )
            )

    print("Running cluster K/seed sensitivity ...", flush=True)
    cluster_rows: list[dict[str, Any]] = []
    for n_groups in cluster_ks:
        for clustering_seed in cluster_seeds:
            if n_groups == main_groups and clustering_seed == seed:
                group_values = main_group_values
                cluster_summary = main_summary
            else:
                group_values, _, _ = derive_semantic_groups(
                    raw_records,
                    n_groups=int(n_groups),
                    random_state=int(clustering_seed),
                )
                result = evaluate_tfidf_cross_validation(
                    rows,
                    n_splits=folds,
                    split_strategies=("group",),
                    group_values=group_values,
                    seed=seed,
                    view_names=("full", "final_answer_only"),
                    view_texts={
                        "full": view_texts["full"],
                        "final_answer_only": view_texts["final_answer_only"],
                    },
                    max_features=main_max_features,
                    bootstrap_resamples=0,
                )
                cluster_summary = aggregate_cross_validation(
                    result,
                    semantic_groups=group_values,
                    bootstrap_resamples=0,
                    seed=seed,
                )
            for view in ("full", "final_answer_only"):
                metrics = cluster_summary["strategies"]["group"]["views"][view]["metrics"]
                cluster_rows.append(
                    _metric_row(
                        metrics,
                        experiment="cluster_sensitivity",
                        strategy="group",
                        view=view,
                        n_groups=int(n_groups),
                        clustering_seed=int(clustering_seed),
                        cv_seed=seed,
                    )
                )

    print("Running structure-only control and taxonomy slices ...", flush=True)
    structure_result = _structure_cross_validation(
        rows, main_group_values, folds=folds, seed=seed
    )
    structure_metric_row = _metric_row(
        structure_result["metrics"],
        experiment="structure_only",
        strategy="group",
        view="structure_only",
    )
    taxonomy_rows = taxonomy_sliced_metrics(rows, main_results)

    source = Path(input_path) if input_path is not None else None
    manifest = {
        "schema_version": 1,
        "dataset": {
            "records": len(rows),
            "safe": sum(record.label == 0 for record in rows),
            "unsafe": sum(record.label == 1 for record in rows),
            "input": str(source) if source is not None else None,
            "sha256": _sha256_file(source) if source is not None and source.exists() else None,
        },
        "config": {
            "folds": folds,
            "cv_seed": seed,
            "main_groups": main_groups,
            "main_max_features": main_max_features,
            "capacity_grid": ["all" if value is None else value for value in capacity_grid],
            "cluster_ks": list(cluster_ks),
            "cluster_seeds": list(cluster_seeds),
            "coefficient_removal_ks": list(coefficient_removal_ks),
            "grouping": "label-free TF-IDF/KMeans over user requests and tool names",
            "taxonomy_fields_are_outputs_only": True,
        },
        "software": {
            "python": platform.python_version(),
            "numpy": _version("numpy"),
            "scikit_learn": _version("scikit-learn"),
            "trajectory_audit": _version("trajectory-audit"),
        },
        "elapsed_seconds": time.perf_counter() - started,
    }
    result_payload = {
        "schema_version": 1,
        "manifest": manifest,
        "cue_masking": {
            "mask_token": MASK_TOKEN,
            "lexicon": CUE_LEXICON,
            "analysis_status": "exploratory_post_hoc_fixed_lexicon",
            "input_to_model_includes_match_categories": False,
            "metrics": cue_metrics,
        },
        "train_fold_coefficient_removal": {
            "selection_scope": "training_fold_only",
            "metrics": coefficient_curve_rows,
            "selected_terms": coefficient_removal["selected_terms"],
        },
        "view_definitions": VIEW_DEFINITIONS,
        "trajectory_views": {
            "length_statistics": view_length_statistics(view_texts),
            "metrics": view_metrics,
        },
        "feature_capacity": capacity_rows,
        "cluster_sensitivity": cluster_rows,
        "structure_only": {
            "features": list(STRUCTURE_FEATURE_NAMES),
            "metrics": structure_metric_row,
        },
        "taxonomy_slices": taxonomy_rows,
    }

    _write_json(output / "run_manifest.json", manifest)
    _write_json(output / "capstone_results.json", result_payload)
    _write_json(output / "view_ablation_results.json", main_results)
    _write_json(
        output / "cue_lexicon.json",
        {
            "mask_token": MASK_TOKEN,
            "lexicon": CUE_LEXICON,
            "note": "Fixed in source; not selected using ATBench labels. All matches use one model-input token.",
            "analysis_status": "exploratory_post_hoc_fixed_lexicon",
        },
    )
    _write_csv(output / "main_oof_predictions.csv", flatten_predictions(main_results))
    _write_csv(output / "trajectory_view_metrics.csv", view_metrics)
    _write_csv(output / "cue_masking_metrics.csv", cue_metrics)
    _write_csv(output / "cue_masking_coverage.csv", masking_coverage)
    _write_csv(
        output / "train_fold_coefficient_removal_metrics.csv",
        coefficient_curve_rows,
    )
    _write_csv(
        output / "train_fold_selected_terms.csv",
        coefficient_removal["selected_terms"],
    )
    _write_csv(
        output / "train_fold_coefficient_removal_predictions.csv",
        coefficient_removal["predictions"],
    )
    _write_csv(output / "feature_capacity_sensitivity.csv", capacity_rows)
    _write_csv(output / "cluster_sensitivity.csv", cluster_rows)
    _write_csv(output / "structure_baseline_metrics.csv", [structure_metric_row])
    _write_csv(output / "structure_oof_predictions.csv", structure_result["predictions"])
    _write_csv(output / "taxonomy_sliced_metrics.csv", taxonomy_rows)
    _write_summary_markdown(
        output / "experiment_summary.md",
        view_metrics,
        capacity_rows,
        cluster_rows,
        structure_metric_row,
    )
    return result_payload


def _parse_capacities(values: Sequence[str]) -> tuple[int | None, ...]:
    parsed: list[int | None] = []
    for value in values:
        normalized = value.strip().casefold()
        if normalized in {"all", "none", "unlimited"}:
            parsed.append(None)
        else:
            number = int(value)
            if number < 1:
                raise ValueError("feature capacities must be positive")
            parsed.append(number)
    return tuple(parsed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trajectory-capstone",
        description="Run the complete CPU ATBench capstone experiment suite.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--main-groups", type=int, default=50)
    parser.add_argument("--main-max-features", type=int, default=50_000)
    parser.add_argument(
        "--capacity-grid",
        nargs="+",
        default=["5000", "20000", "50000", "all"],
        metavar="N|all",
    )
    parser.add_argument(
        "--cluster-ks", nargs="+", type=int, default=list(DEFAULT_CLUSTER_KS)
    )
    parser.add_argument(
        "--cluster-seeds", nargs="+", type=int, default=list(DEFAULT_CLUSTER_SEEDS)
    )
    parser.add_argument(
        "--coefficient-removal-ks",
        nargs="+",
        type=int,
        default=list(DEFAULT_TOP_COEFFICIENT_KS),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        records = load_records(args.input)
        payload = run_capstone_experiments(
            records,
            args.output_dir,
            folds=args.folds,
            seed=args.seed,
            main_groups=args.main_groups,
            main_max_features=args.main_max_features,
            capacity_grid=_parse_capacities(args.capacity_grid),
            cluster_ks=tuple(args.cluster_ks),
            cluster_seeds=tuple(args.cluster_seeds),
            coefficient_removal_ks=tuple(args.coefficient_removal_ks),
            input_path=args.input,
        )
    except (DataFormatError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    manifest = payload["manifest"]
    print(
        f"Completed {manifest['dataset']['records']} records in "
        f"{manifest['elapsed_seconds']:.1f}s. Results: {args.output_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CUE_LEXICON",
    "DEFAULT_CAPACITIES",
    "DEFAULT_CLUSTER_KS",
    "DEFAULT_CLUSTER_SEEDS",
    "DEFAULT_TOP_COEFFICIENT_KS",
    "MASK_TOKEN",
    "STRUCTURE_FEATURE_NAMES",
    "TEMPORAL_VIEW_NAMES",
    "VIEW_DEFINITIONS",
    "build_temporal_views",
    "mask_posthoc_cues",
    "run_capstone_experiments",
    "structure_features",
    "taxonomy_sliced_metrics",
    "train_fold_coefficient_removal_curve",
]
