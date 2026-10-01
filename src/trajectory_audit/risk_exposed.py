"""Risk-exposed-only ATBench cross-validation.

ATBench mixes 250 ordinary benign trajectories with 253 safe trajectories that
contain a non-benign risk scenario.  This module removes only the former and
recomputes the same label-free user/tool clusters on the remaining rows.  The
result is a harder safe-vs-unsafe comparison within risk-exposed scenarios.
"""

from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .baseline import (
    evaluate_tfidf_cross_validation,
    save_predictions_csv,
    save_results,
)
from .cross_release import ATBENCH_SPEC, validate_release_file
from .data import TrajectoryRecord, load_records
from .download import sha256_file
from .grouping import derive_semantic_groups, group_diagnostics
from .reporting import aggregate_cross_validation
from .views import build_view


RISK_EXPOSED_VIEWS = (
    "full",
    "full_without_final",
    "user_only",
    "final_answer_only",
    "user_plus_final",
)


def is_risk_exposed(record: TrajectoryRecord) -> bool:
    """Return whether the published risk source is present and non-benign."""

    value = record.raw.get("risk_source")
    return value is not None and str(value).strip().casefold() != "benign"


def build_risk_exposed_views(record: TrajectoryRecord) -> dict[str, str]:
    """Build the five representations used by the risk-exposed experiment."""

    without_final = replace(
        record,
        events=tuple(event for event in record.events if event.kind != "completion"),
    )
    user = build_view(record, "user_only")
    final = build_view(record, "final_answer_only")
    return {
        "full": build_view(record, "full"),
        "full_without_final": build_view(without_final, "full"),
        "user_only": user,
        "final_answer_only": final,
        "user_plus_final": f"{user}\n\n{final}",
    }


def run_risk_exposed_cv(
    atbench_path: str | Path,
    *,
    verify_official: bool = True,
    folds: int = 5,
    requested_groups: int = 50,
    seed: int = 42,
    max_features: int | None = 50_000,
    bootstrap_resamples: int = 500,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Run group-disjoint CV after removing only published benign scenarios."""

    source = Path(atbench_path)
    if verify_official:
        provenance = validate_release_file(source, ATBENCH_SPEC)
    else:
        provenance = {
            "name": ATBENCH_SPEC.name,
            "url": ATBENCH_SPEC.url,
            "revision": ATBENCH_SPEC.revision,
            "license": ATBENCH_SPEC.license,
            "schema": ATBENCH_SPEC.schema,
            "path": str(source),
            "actual_sha256": sha256_file(source),
            "actual_bytes": source.stat().st_size,
            "verification": "official shape/hash contract bypassed for caller-supplied fixture",
        }
    all_records = load_records(source)
    if any(record.label not in (0, 1) for record in all_records):
        raise ValueError("risk-exposed CV requires a binary label on every input row")
    records = [record for record in all_records if is_risk_exposed(record)]
    excluded = len(all_records) - len(records)
    if len(records) < folds * 2:
        raise ValueError("too few risk-exposed records for the requested folds")
    labels = [int(record.label) for record in records]
    if min(labels.count(0), labels.count(1)) < folds:
        raise ValueError("each risk-exposed class must have at least one item per fold")

    max_groups_for_size = max(folds, len(records) // 5)
    n_groups = min(requested_groups, max_groups_for_size)
    if n_groups < folds:
        raise ValueError("requested_groups must permit at least one group per fold")
    raw_records = [dict(record.raw) for record in records]
    groups, vectorizer, clusterer = derive_semantic_groups(
        raw_records, n_groups=n_groups, random_state=seed
    )
    cluster_report = group_diagnostics(
        raw_records, groups, vectorizer, clusterer, top_terms=10
    )

    rendered = [build_risk_exposed_views(record) for record in records]
    view_texts = {
        view: [item[view] for item in rendered] for view in RISK_EXPOSED_VIEWS
    }
    results = evaluate_tfidf_cross_validation(
        records,
        n_splits=folds,
        split_strategies=("group",),
        group_values=groups,
        seed=seed,
        view_names=RISK_EXPOSED_VIEWS,
        view_texts=view_texts,
        max_features=max_features,
        bootstrap_resamples=0,
    )
    results["audit_notes"] = {
        "subset_filter": "risk_source != benign",
        "taxonomy_use": "risk_source is used only to define this evaluation subset",
        "grouping": "TF-IDF KMeans over user messages and tool names, recomputed after filtering",
        "grouping_uses_labels": False,
        "excluded_predictive_fields": [
            "label",
            "reason",
            "risk_source",
            "failure_mode",
            "real_world_harm",
        ],
    }
    summary = aggregate_cross_validation(
        results,
        semantic_groups=groups,
        bootstrap_resamples=bootstrap_resamples,
        seed=seed,
    )
    metadata = {
        "experiment": "risk_exposed_only_group_cross_validation",
        "dataset_provenance": provenance,
        "filter": "risk_source != benign",
        "input_records": len(all_records),
        "excluded_benign_records": excluded,
        "risk_exposed_records": len(records),
        "safe": labels.count(0),
        "unsafe": labels.count(1),
        "folds": folds,
        "requested_groups": requested_groups,
        "actual_groups": len(set(groups)),
        "seed": seed,
        "max_features": max_features,
        "bootstrap_resamples": bootstrap_resamples,
        "views": list(RISK_EXPOSED_VIEWS),
    }
    bundle = {"metadata": metadata, "summary": summary}
    assignments = [
        {
            "subset_index": index,
            "record_id": record.id,
            "group": group,
            "label": record.label,
            "risk_source": record.raw.get("risk_source"),
        }
        for index, (record, group) in enumerate(zip(records, groups))
    ]
    bundle["cluster_diagnostics"] = cluster_report
    return results, bundle, assignments


def write_risk_exposed_outputs(
    output_dir: str | Path,
    results: Mapping[str, Any],
    bundle: Mapping[str, Any],
    assignments: Sequence[Mapping[str, Any]],
) -> dict[str, Path]:
    """Write detailed results, summary, assignments, predictions, and Markdown."""

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    results_path = save_results(results, directory / "risk_exposed_results.json")
    predictions_path = save_predictions_csv(
        results, directory / "risk_exposed_predictions.csv"
    )
    summary_path = directory / "risk_exposed_summary.json"
    summary_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assignments_path = directory / "risk_exposed_group_assignments.csv"
    fields = ["subset_index", "record_id", "group", "label", "risk_source"]
    with assignments_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(assignments)

    metadata = bundle["metadata"]
    summary = bundle["summary"]
    lines = [
        "# ATBench risk-exposed-only audit",
        "",
        "This analysis removes the 250 rows whose published `risk_source` is `benign`,",
        "then recomputes label-free user/tool clusters on the remaining rows. Taxonomy",
        "fields are not included in any predictive view.",
        "",
        f"- Records: {metadata['risk_exposed_records']} "
        f"(safe {metadata['safe']}, unsafe {metadata['unsafe']})",
        f"- Group CV: {metadata['folds']} folds over {metadata['actual_groups']} recomputed clusters",
        f"- Dataset SHA-256: `{metadata['dataset_provenance']['actual_sha256']}`",
        "",
        "| View | Macro-F1 | AUROC | Balanced accuracy | Unsafe FNR | Safe FPR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    views = summary["strategies"]["group"]["views"]
    for view in RISK_EXPOSED_VIEWS:
        metrics = views[view]["metrics"]
        lines.append(
            "| {view} | {f1:.3f} | {auc:.3f} | {balanced:.3f} | {fnr:.3f} | {fpr:.3f} |".format(
                view=view,
                f1=metrics["macro_f1"],
                auc=metrics["roc_auc"],
                balanced=metrics["balanced_accuracy"],
                fnr=metrics["false_negative_rate"],
                fpr=metrics["false_positive_rate"],
            )
        )
    lines.extend(
        [
            "",
            "`full_without_final` removes every terminal completion event; `user_plus_final`",
            "combines the user messages with the final answer while excluding tool schemas,",
            "intermediate actions, reasoning, and tool outputs.",
        ]
    )
    report_path = directory / "risk_exposed_report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "results": results_path,
        "predictions": predictions_path,
        "summary": summary_path,
        "assignments": assignments_path,
        "report": report_path,
    }


__all__ = [
    "RISK_EXPOSED_VIEWS",
    "build_risk_exposed_views",
    "is_risk_exposed",
    "run_risk_exposed_cv",
    "write_risk_exposed_outputs",
]
