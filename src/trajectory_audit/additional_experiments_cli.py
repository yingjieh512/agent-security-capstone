"""Standalone CLI for cross-release and risk-exposed capstone experiments."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .cross_release import (
    ATBENCH500_SPEC,
    ATBENCH_SPEC,
    ensure_release,
    run_cross_release,
    write_cross_release_outputs,
)
from .risk_exposed import run_risk_exposed_cv, write_risk_exposed_outputs


DEFAULT_ATBENCH = Path("data/raw/atbench/test.json")
DEFAULT_ATBENCH500 = Path("data/raw/atbench500/test.json")


def _cross_release(args: argparse.Namespace) -> int:
    ensure_release(args.atbench, ATBENCH_SPEC, download_missing=args.download_missing)
    ensure_release(
        args.atbench500, ATBENCH500_SPEC, download_missing=args.download_missing
    )
    result, predictions = run_cross_release(
        args.atbench,
        args.atbench500,
        max_features=args.max_features,
        seed=args.seed,
        threshold=0.5,
        ece_bins=args.ece_bins,
    )
    paths = write_cross_release_outputs(args.output_dir, result, predictions)
    for direction, payload in result["directions"].items():
        for view, view_payload in payload["views"].items():
            metrics = view_payload["metrics"]
            print(
                f"{direction:<28} {view:<18} "
                f"macro_f1={metrics['macro_f1']:.3f} "
                f"auroc={metrics['roc_auc']:.3f} "
                f"brier={metrics['brier_score']:.3f}"
            )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


def _risk_exposed(args: argparse.Namespace) -> int:
    ensure_release(args.atbench, ATBENCH_SPEC, download_missing=args.download_missing)
    results, bundle, assignments = run_risk_exposed_cv(
        args.atbench,
        folds=args.folds,
        requested_groups=args.groups,
        seed=args.seed,
        max_features=args.max_features,
        bootstrap_resamples=args.bootstrap_resamples,
    )
    paths = write_risk_exposed_outputs(
        args.output_dir, results, bundle, assignments
    )
    views = bundle["summary"]["strategies"]["group"]["views"]
    for view, payload in views.items():
        metrics = payload["metrics"]
        print(
            f"{view:<22} macro_f1={metrics['macro_f1']:.3f} "
            f"auroc={metrics['roc_auc']:.3f} "
            f"fnr={metrics['false_negative_rate']:.3f} "
            f"fpr={metrics['false_positive_rate']:.3f}"
        )
    for name, path in paths.items():
        print(f"{name}: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trajectory-audit-additions",
        description="Run standalone capstone transfer and subset experiments.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    cross = subparsers.add_parser(
        "cross-release",
        help="train on ATBench and ATBench500 in turn and test the other release",
    )
    cross.add_argument("--atbench", type=Path, default=DEFAULT_ATBENCH)
    cross.add_argument("--atbench500", type=Path, default=DEFAULT_ATBENCH500)
    cross.add_argument("--output-dir", type=Path, default=Path("outputs/cross-release"))
    cross.add_argument("--download-missing", action="store_true")
    cross.add_argument("--max-features", type=int, default=50_000)
    cross.add_argument("--seed", type=int, default=42)
    cross.add_argument("--ece-bins", type=int, default=10)
    cross.set_defaults(handler=_cross_release)

    risk = subparsers.add_parser(
        "risk-exposed",
        help="run grouped CV after removing ATBench rows marked benign",
    )
    risk.add_argument("--atbench", type=Path, default=DEFAULT_ATBENCH)
    risk.add_argument("--output-dir", type=Path, default=Path("outputs/risk-exposed"))
    risk.add_argument("--download-missing", action="store_true")
    risk.add_argument("--folds", type=int, default=5)
    risk.add_argument("--groups", type=int, default=50)
    risk.add_argument("--max-features", type=int, default=50_000)
    risk.add_argument("--bootstrap-resamples", type=int, default=500)
    risk.add_argument("--seed", type=int, default=42)
    risk.set_defaults(handler=_risk_exposed)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
