"""Command-line interface for the trajectory partial-view audit."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from importlib.metadata import version
import json
from pathlib import Path
import platform
import random
import sys
from typing import Any, Sequence

from .baseline import evaluate_tfidf_cross_validation, save_evaluation_artifacts
from .data import DataFormatError, TrajectoryRecord, load_records
from .diagnostics import (
    missing_by_label,
    save_top_features_csv,
    top_tfidf_features,
    write_final_answer_diagnostics,
)
from .download import download_atbench, sha256_file, validate_atbench_file
from .grouping import derive_semantic_groups, group_diagnostics
from .reporting import (
    aggregate_cross_validation,
    save_summary,
    view_length_statistics,
    write_macro_f1_svg,
    write_markdown_report,
)
from .views import VIEW_NAMES, build_views


DEFAULT_DATA_PATH = Path("data/raw/atbench/test.json")
DEFAULT_OUTPUT_PATH = Path("outputs/atbench-mvp")


def _stratified_subset(
    records: Sequence[TrajectoryRecord], limit: int | None, seed: int
) -> list[TrajectoryRecord]:
    rows = list(records)
    if limit is None or limit >= len(rows):
        return rows
    if limit < 4:
        raise ValueError("--limit must be at least 4")
    by_label: dict[int | None, list[int]] = {}
    for index, record in enumerate(rows):
        by_label.setdefault(record.label, []).append(index)
    rng = random.Random(seed)
    selected: list[int] = []
    remaining = limit
    labels = sorted(by_label, key=lambda value: str(value))
    for position, label in enumerate(labels):
        candidates = list(by_label[label])
        rng.shuffle(candidates)
        if position == len(labels) - 1:
            take = remaining
        else:
            take = round(limit * len(candidates) / len(rows))
            take = min(max(1, take), len(candidates), remaining - (len(labels) - position - 1))
        selected.extend(candidates[:take])
        remaining -= take
    if remaining:
        unused = [index for index in range(len(rows)) if index not in set(selected)]
        rng.shuffle(unused)
        selected.extend(unused[:remaining])
    return [rows[index] for index in sorted(selected)]


def _save_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _save_group_assignments(
    path: Path, records: Sequence[TrajectoryRecord], groups: Sequence[str]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "record_index",
        "record_id",
        "semantic_group",
        "label",
        "risk_source",
        "failure_mode",
        "real_world_harm",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, (record, group) in enumerate(zip(records, groups)):
            writer.writerow(
                {
                    "record_index": index,
                    "record_id": record.id,
                    "semantic_group": group,
                    "label": record.label,
                    "risk_source": record.raw.get("risk_source", ""),
                    "failure_mode": record.raw.get("failure_mode", ""),
                    "real_world_harm": record.raw.get("real_world_harm", ""),
                }
            )
    return path


def _command_download(args: argparse.Namespace) -> int:
    result = download_atbench(args.output, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _command_inspect(args: argparse.Namespace) -> int:
    source = Path(args.input)
    verification = validate_atbench_file(source) if args.verify_atbench else None
    records = load_records(source)
    labels = [record.label for record in records]
    views = [build_views(record) for record in records]
    view_texts = {name: [item[name] for item in views] for name in VIEW_NAMES}
    payload = {
        "path": str(source),
        "sha256": sha256_file(source),
        "records": len(records),
        "safe": labels.count(0),
        "unsafe": labels.count(1),
        "unlabelled": labels.count(None),
        "view_statistics": view_length_statistics(view_texts),
    }
    if verification is not None:
        payload["atbench_verification"] = verification
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _command_run(args: argparse.Namespace) -> int:
    source = Path(args.input)
    output = Path(args.output_dir)
    print(f"Loading {source} ...", flush=True)
    records = _stratified_subset(load_records(source), args.limit, args.seed)
    if any(record.label not in (0, 1) for record in records):
        raise ValueError("run requires a binary label on every selected record")
    if len(records) < args.folds * 2:
        raise ValueError("too few records for the requested number of folds")

    max_groups_for_size = max(args.folds, len(records) // 5)
    n_groups = min(args.groups, max_groups_for_size)
    if n_groups < args.folds:
        raise ValueError("--groups must be at least --folds")
    raw_records = [dict(record.raw) for record in records]
    print(
        f"Deriving {n_groups} label-free user/tool clusters for grouped CV ...",
        flush=True,
    )
    semantic_groups, vectorizer, clusterer = derive_semantic_groups(
        raw_records,
        n_groups=n_groups,
        random_state=args.seed,
    )
    diagnostics = group_diagnostics(
        raw_records, semantic_groups, vectorizer, clusterer, top_terms=10
    )

    selected_views = tuple(args.views or VIEW_NAMES)
    rendered = [build_views(record) for record in records]
    view_texts = {
        name: [item[name] for item in rendered]
        for name in selected_views
    }
    stats = view_length_statistics(view_texts)

    print(
        f"Running {args.folds}-fold random and semantic-group CV across "
        f"{len(selected_views)} views ...",
        flush=True,
    )
    results = evaluate_tfidf_cross_validation(
        records,
        n_splits=args.folds,
        split_strategies=("random", "group"),
        group_values=semantic_groups,
        seed=args.seed,
        view_names=selected_views,
        view_texts=view_texts,
        max_features=args.max_features,
        bootstrap_resamples=0,
    )
    results["audit_notes"] = {
        "official_split": "test only",
        "interpretation": "custom diagnostic cross-validation; not an official leaderboard score",
        "grouping": "unsupervised TF-IDF KMeans over user messages and tool names",
        "grouping_uses_labels": False,
        "excluded_input_fields": [
            "label",
            "reason",
            "risk_source",
            "failure_mode",
            "real_world_harm",
        ],
    }
    summary = aggregate_cross_validation(
        results,
        semantic_groups=semantic_groups,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    labels = [int(record.label) for record in records]

    final_diagnostics: dict[str, Any] | None = None
    if "final_answer_only" in view_texts:
        final_texts = view_texts["final_answer_only"]
        missing = missing_by_label(final_texts, labels)
        top_features = top_tfidf_features(
            final_texts,
            labels,
            top_k=25,
            max_features=min(args.max_features, 20_000),
            seed=args.seed,
        )
        complete_indices = [
            index
            for index, text in enumerate(final_texts)
            if not text.rstrip().endswith("<NONE>")
        ]
        complete_records = [records[index] for index in complete_indices]
        complete_texts = [final_texts[index] for index in complete_indices]
        complete_groups = [semantic_groups[index] for index in complete_indices]
        complete_label_counts = Counter(int(record.label) for record in complete_records)
        if (
            len(complete_records) >= args.folds * 2
            and len(set(complete_groups)) >= args.folds
            and len(complete_label_counts) == 2
            and min(complete_label_counts.values()) >= args.folds
        ):
            complete_results = evaluate_tfidf_cross_validation(
                complete_records,
                n_splits=args.folds,
                split_strategies=("random", "group"),
                group_values=complete_groups,
                seed=args.seed,
                view_names=("final_answer_only",),
                view_texts={"final_answer_only": complete_texts},
                max_features=args.max_features,
                bootstrap_resamples=0,
            )
            complete_summary = aggregate_cross_validation(
                complete_results,
                semantic_groups=complete_groups,
                bootstrap_resamples=args.bootstrap_resamples,
                seed=args.seed,
            )
        else:
            complete_summary = {
                "strategies": {},
                "skipped": "insufficient complete records, labels, or groups for requested folds",
            }
        final_diagnostics = {
            "missing": missing,
            "top_features": top_features,
            "complete_only_summary": complete_summary,
        }
    run_metadata = {
        "input": str(source),
        "input_sha256": sha256_file(source),
        "records": len(records),
        "safe": labels.count(0),
        "unsafe": labels.count(1),
        "seed": args.seed,
        "folds": args.folds,
        "semantic_groups": len(set(semantic_groups)),
        "requested_semantic_groups": n_groups,
        "views": list(selected_views),
        "max_features": args.max_features,
        "python": platform.python_version(),
        "scikit_learn": version("scikit-learn"),
        "trajectory_audit": version("trajectory-audit"),
    }
    if final_diagnostics is not None:
        run_metadata["final_answer_missing"] = final_diagnostics["missing"]

    output.mkdir(parents=True, exist_ok=True)
    paths = save_evaluation_artifacts(results, output)
    paths.update(
        {
            "summary": save_summary(summary, output / "summary.json"),
            "metadata": _save_json(output / "run_metadata.json", run_metadata),
            "groups": _save_json(output / "group_diagnostics.json", diagnostics),
            "assignments": _save_group_assignments(
                output / "group_assignments.csv", records, semantic_groups
            ),
            "report": write_markdown_report(
                output / "report.md",
                summary,
                run_metadata=run_metadata,
                view_stats=stats,
            ),
            "chart": write_macro_f1_svg(output / "macro_f1.svg", summary),
        }
    )
    if final_diagnostics is not None:
        paths.update(
            {
                "final_diagnostics_json": _save_json(
                    output / "final_answer_diagnostics.json", final_diagnostics
                ),
                "top_features": save_top_features_csv(
                    final_diagnostics["top_features"], output / "final_answer_top_features.csv"
                ),
                "final_diagnostics_report": write_final_answer_diagnostics(
                    output / "final_answer_diagnostics.md",
                    missing=final_diagnostics["missing"],
                    top_features=final_diagnostics["top_features"],
                    complete_only_summary=final_diagnostics["complete_only_summary"],
                    folds=args.folds,
                ),
            }
        )

    print("\nOut-of-fold Macro-F1", flush=True)
    print(f"{'split':<10} {'view':<20} {'macro_f1':>9} {'fnr':>9} {'auroc':>9}")
    for strategy, strategy_payload in summary["strategies"].items():
        for view, payload in strategy_payload["views"].items():
            metrics = payload["metrics"]
            print(
                f"{strategy:<10} {view:<20} {metrics['macro_f1']:>9.3f} "
                f"{metrics['false_negative_rate']:>9.3f} {metrics.get('roc_auc', float('nan')):>9.3f}"
            )
    print("\nArtifacts")
    for name, path in paths.items():
        print(f"  {name}: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trajectory-audit",
        description="Audit information shortcuts in agent-safety trajectory benchmarks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="download the pinned ATBench release")
    download.add_argument("--output", type=Path, default=DEFAULT_DATA_PATH)
    download.add_argument("--force", action="store_true")
    download.set_defaults(handler=_command_download)

    inspect = subparsers.add_parser("inspect", help="parse and summarize a trajectory file")
    inspect.add_argument("--input", type=Path, default=DEFAULT_DATA_PATH)
    inspect.add_argument(
        "--verify-atbench",
        action="store_true",
        help="also require the pinned official ATBench hash and 1,000-row shape",
    )
    inspect.set_defaults(handler=_command_inspect)

    run = subparsers.add_parser("run", help="run the complete partial-view TF-IDF audit")
    run.add_argument("--input", type=Path, default=DEFAULT_DATA_PATH)
    run.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_PATH)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--folds", type=int, default=5)
    run.add_argument("--groups", type=int, default=50)
    run.add_argument("--bootstrap-resamples", type=int, default=500)
    run.add_argument("--max-features", type=int, default=50_000)
    run.add_argument("--limit", type=int, default=None, help="stratified pilot subset")
    run.add_argument(
        "--views",
        nargs="+",
        choices=VIEW_NAMES,
        default=None,
        help="views to evaluate; defaults to all five",
    )
    run.set_defaults(handler=_command_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (DataFormatError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
