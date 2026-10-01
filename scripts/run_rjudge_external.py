#!/usr/bin/env python3
"""Run a CPU-only external partial-view audit on public R-Judge data."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.metrics import f1_score

from trajectory_audit.baseline import (
    classification_metrics,
    evaluate_tfidf_cross_validation,
    save_evaluation_artifacts,
)
from trajectory_audit.reporting import (
    aggregate_cross_validation,
    save_summary,
    view_length_statistics,
)
from trajectory_audit.rjudge import (
    RJUDGE_VIEW_NAMES,
    build_rjudge_views,
    corpus_diagnostics,
    load_rjudge_directory,
)


REPOSITORY_URL = "https://github.com/Lordog/R-Judge"
REPOSITORY_COMMIT = "83ce301da3ad50dd8b397e772863f5411c3d3dc2"
PAPER_URL = "https://aclanthology.org/2024.findings-emnlp.79/"
OFFICIAL_SITE_URL = "https://rjudgebench.github.io/"
ACL_ATTACHMENT_URL = (
    "https://aclanthology.org/attachments/2024.findings-emnlp.79.data.zip"
)
ACL_ATTACHMENT_SHA256 = (
    "2f15b1b2b45279b0c4e509114f77fad3cec14c61b5553c3b565a119addd115a8"
)


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _oof_rows(results: Mapping[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for split_name, split in results["splits"].items():
        strategy = split_name.rsplit("_fold_", 1)[0]
        for view, payload in split["views"].items():
            buckets[(strategy, view)].extend(payload["predictions"])
    for key in buckets:
        buckets[key].sort(key=lambda row: int(row["record_index"]))
    return buckets


def paired_macro_f1_differences(
    results: Mapping[str, Any],
    *,
    groups: Sequence[str],
    first_view: str = "last_action_only",
    second_view: str = "full",
    resamples: int,
    seed: int,
) -> dict[str, Any]:
    """Fixed-prediction, source-group bootstrap of paired view differences."""

    buckets = _oof_rows(results)
    output: dict[str, Any] = {}
    for strategy in sorted({key[0] for key in buckets}):
        first = buckets[(strategy, first_view)]
        second = buckets[(strategy, second_view)]
        first_by_index = {int(row["record_index"]): row for row in first}
        second_by_index = {int(row["record_index"]): row for row in second}
        if set(first_by_index) != set(second_by_index):
            raise ValueError(f"paired view coverage differs for {strategy}")
        indices = sorted(first_by_index)
        truth = np.asarray([first_by_index[i]["y_true"] for i in indices], dtype=int)
        pred_first = np.asarray([first_by_index[i]["y_pred"] for i in indices], dtype=int)
        pred_second = np.asarray([second_by_index[i]["y_pred"] for i in indices], dtype=int)

        group_to_positions: dict[str, list[int]] = defaultdict(list)
        for position, record_index in enumerate(indices):
            group_to_positions[str(groups[record_index])].append(position)
        group_keys = np.asarray(sorted(group_to_positions), dtype=object)
        rng = np.random.default_rng(seed)
        estimates = []
        for _ in range(resamples):
            sampled = rng.choice(group_keys, size=len(group_keys), replace=True)
            positions = np.asarray(
                [position for group in sampled for position in group_to_positions[str(group)]],
                dtype=int,
            )
            estimates.append(
                float(
                    f1_score(
                        truth[positions],
                        pred_first[positions],
                        labels=[0, 1],
                        average="macro",
                        zero_division=0,
                    )
                    - f1_score(
                        truth[positions],
                        pred_second[positions],
                        labels=[0, 1],
                        average="macro",
                        zero_division=0,
                    )
                )
            )
        point = float(
            f1_score(truth, pred_first, labels=[0, 1], average="macro", zero_division=0)
            - f1_score(truth, pred_second, labels=[0, 1], average="macro", zero_division=0)
        )
        output[strategy] = {
            "comparison": f"{first_view}_minus_{second_view}",
            "estimate": point,
            "lower": float(np.quantile(estimates, 0.025)),
            "upper": float(np.quantile(estimates, 0.975)),
            "confidence": 0.95,
            "n_resamples": resamples,
            "sampling_units": "fixed_source_files",
            "seed": seed,
        }
    return output


def subgroup_metrics(
    results: Mapping[str, Any],
    records: Sequence[Any],
) -> dict[str, Any]:
    """Compute descriptive OOF metrics by attack origin and application category."""

    output: dict[str, Any] = {}
    for (strategy, view), rows in sorted(_oof_rows(results).items()):
        for field in ("attack_type", "category"):
            field_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                index = int(row["record_index"])
                field_groups[str(records[index].metadata[field])].append(row)
            for value, selected in sorted(field_groups.items()):
                y_true = [row["y_true"] for row in selected]
                y_pred = [row["y_pred"] for row in selected]
                scores = [row.get("positive_score") for row in selected]
                score_values = None if any(score is None for score in scores) else scores
                output.setdefault(strategy, {}).setdefault(view, {}).setdefault(field, {})[
                    value
                ] = classification_metrics(
                    y_true,
                    y_pred,
                    scores=score_values,
                    positive_label=1,
                )
    return output


def _fingerprint(file_hashes: Mapping[str, str]) -> str:
    body = "\n".join(f"{path} {digest}" for path, digest in sorted(file_hashes.items()))
    return sha256(body.encode("utf-8")).hexdigest()


def write_svg(path: Path, summary: Mapping[str, Any]) -> Path:
    strategies = list(summary["strategies"])
    views = [view for view in RJUDGE_VIEW_NAMES if view in summary["strategies"][strategies[0]]["views"]]
    width, height = 980, 120 + 76 * len(views)
    left, right, top, bottom = 220, 55, 55, 45
    plot_width = width - left - right
    colors = ["#2563eb", "#ea580c"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#172033}.title{font-size:20px;font-weight:650}.label{font-size:14px}.tick{font-size:12px;fill:#526071}.value{font-size:12px;font-weight:600}</style>',
        '<text class="title" x="24" y="30">R-Judge external validation — out-of-fold Macro-F1</text>',
    ]
    for tick in range(0, 11, 2):
        score = tick / 10
        x = left + score * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height-bottom}" stroke="#e5e7eb"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{height-18}" text-anchor="middle">{score:.1f}</text>')
    bar_height = 19
    for row_index, view in enumerate(views):
        center = top + 28 + row_index * 76
        parts.append(f'<text class="label" x="{left-12}" y="{center+5}" text-anchor="end">{escape(view)}</text>')
        for strategy_index, strategy in enumerate(strategies):
            score = float(summary["strategies"][strategy]["views"][view]["metrics"]["macro_f1"])
            y = center - len(strategies) * bar_height / 2 + strategy_index * bar_height
            bar_width = score * plot_width
            color = colors[strategy_index % len(colors)]
            parts.append(f'<rect x="{left}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height-3}" rx="2" fill="{color}"/>')
            parts.append(f'<text class="value" x="{left+bar_width+6:.1f}" y="{y+12:.1f}">{score:.3f}</text>')
    legend_x = width - right - 155
    for index, strategy in enumerate(strategies):
        y = 22 + index * 20
        parts.append(f'<rect x="{legend_x}" y="{y-11}" width="12" height="12" rx="2" fill="{colors[index]}"/>')
        parts.append(f'<text class="tick" x="{legend_x+18}" y="{y}">{escape(strategy)}</text>')
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def write_report(
    path: Path,
    *,
    diagnostics: Mapping[str, Any],
    summary: Mapping[str, Any],
    paired: Mapping[str, Any],
    subgroups: Mapping[str, Any],
    metadata: Mapping[str, Any],
    view_stats: Mapping[str, Any],
) -> Path:
    lines = [
        "# R-Judge 外部验证：局部轨迹视图审计",
        "",
        "该实验把 ATBench 上的低成本 TF-IDF／Logistic Regression 审计协议迁移到 R-Judge，",
        "用于检验‘不读取完整轨迹也能预测安全标签’是否只出现在一个数据集。",
        "",
        "## 数据与许可",
        "",
        f"- 官方仓库：[{REPOSITORY_URL}]({REPOSITORY_URL})，固定 commit `{REPOSITORY_COMMIT}`。",
        f"- 论文与权威附件入口：[{PAPER_URL}]({PAPER_URL})。",
        f"- 官方项目站：[{OFFICIAL_SITE_URL}]({OFFICIAL_SITE_URL}) 声明数据为 **CC BY-NC-SA**，但未注明版本；",
        "  当前 GitHub commit 根目录没有 `LICENSE` 文件，因此使用时应保留出处并按非商业、相同方式共享解释。",
        f"- 当前仓库含 {diagnostics['raw_rows']} 行；删去两个完全相同的官方 judge 输入",
        f"  （`profile + contents`，后出现的 ID {diagnostics['duplicate_input_ids_removed']}）后为 {diagnostics['deduplicated_rows']} 条，",
        "  与论文所报 569 条一致。",
        f"- ACL 附件 SHA-256 `{ACL_ATTACHMENT_SHA256}` 实际只有 564 条且没有 `attack_type`；",
        "  本实验使用较新的固定 GitHub commit，并显式记录版本差异。",
        "",
        "## 实验设置",
        "",
        f"- 标签：0=safe，1=unsafe；去重后 safe {diagnostics['label_counts']['0']}／unsafe {diagnostics['label_counts']['1']}。",
        f"- {metadata['folds']}-fold OOF；random 为分层随机折，group 为 27 个 source JSON file 完全隔离的分组折。",
        f"- 模型：word unigram+bigram TF-IDF（最多 {metadata['max_features']:,} features）+ balanced Logistic Regression。",
        f"- 固定 source-file cluster bootstrap {metadata['bootstrap_resamples']} 次；随机种子 {metadata['seed']}。",
        "- `risk_description`、`attack_type`、category、source filename 与标签均不进入文本视图。",
        "",
        "## 视图定义",
        "",
        "- `full`：profile、user、agent thought、agent action、environment 的完整顺序记录。",
        "- `user_only`：仅用户消息。",
        "- `action_only`：所有 agent action；不含 thought 或 environment。",
        "- `last_action_only`：最后一个 agent action。R-Judge 没有 terminal/final-answer 标记，因此这里只能称为最后动作代理。",
        "",
        "## 主结果",
        "",
        "| 切分 | 视图 | Macro-F1（95% source-cluster bootstrap CI） | AUROC | Unsafe recall | FNR |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for strategy, strategy_payload in summary["strategies"].items():
        for view in RJUDGE_VIEW_NAMES:
            payload = strategy_payload["views"][view]
            metrics = payload["metrics"]
            ci = payload["confidence_intervals"]["macro_f1"]
            recall = metrics["per_class"]["1"]["recall"]
            lines.append(
                f"| {strategy} | {view} | {metrics['macro_f1']:.3f} "
                f"[{ci['lower']:.3f}, {ci['upper']:.3f}] | "
                f"{metrics.get('roc_auc', float('nan')):.3f} | {recall:.3f} | "
                f"{metrics['false_negative_rate']:.3f} |"
            )
    lines.extend(
        [
            "",
            "## 最后动作与完整轨迹的配对差值",
            "",
            "| 切分 | Δ Macro-F1（last action − full） | 95% source-cluster bootstrap CI |",
            "|---|---:|---:|",
        ]
    )
    for strategy, payload in paired.items():
        lines.append(
            f"| {strategy} | {payload['estimate']:+.3f} | "
            f"[{payload['lower']:+.3f}, {payload['upper']:+.3f}] |"
        )

    lines.extend(
        [
            "",
            "## 按风险来源拆分（group OOF，描述性）",
            "",
            "| 视图 | 来源 | n | Macro-F1 | AUROC | Unsafe FNR |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for view in RJUDGE_VIEW_NAMES:
        for origin, metrics in subgroups["group"][view]["attack_type"].items():
            auc = metrics.get("roc_auc")
            fnr = metrics.get("false_negative_rate")
            lines.append(
                f"| {view} | {origin} | {metrics['n']} | {metrics['macro_f1']:.3f} | "
                f"{auc:.3f} | {fnr:.3f} |"
            )

    group_views = summary["strategies"]["group"]["views"]
    full = group_views["full"]["metrics"]["macro_f1"]
    best_partial_name, best_partial = max(
        (
            (name, group_views[name]["metrics"]["macro_f1"])
            for name in RJUDGE_VIEW_NAMES
            if name != "full"
        ),
        key=lambda item: item[1],
    )
    lines.extend(
        [
            "",
            "## 解释",
            "",
            f"在较严格的 source-file-held-out 设置中，full 的 Macro-F1 为 {full:.3f}，",
            f"最强局部视图 `{best_partial_name}` 为 {best_partial:.3f}。",
            "局部动作信号在 injection 子集上尤其强，而 unintended 子集明显更难。",
            "结果说明跨数据集仍存在可由局部文本捕捉的安全标签信号；具体强度应结合上表和分组折评估，",
            "不能把随机折结果当作跨场景泛化能力。",
            "",
            "## 视图规模",
            "",
            "| 视图 | 平均字符数 | 中位字符数 | 显式缺失 |",
            "|---|---:|---:|---:|",
        ]
    )
    for view in RJUDGE_VIEW_NAMES:
        stats = view_stats[view]
        lines.append(
            f"| {view} | {stats['mean_characters']:.0f} | "
            f"{stats['median_characters']:.0f} | {stats['explicit_missing']} |"
        )
    lines.extend(
        [
            "",
            "## 限制",
            "",
            "- R-Judge 没有正式 train/test split；这些分数是对公开全集的探索性 OOF 审计，不是官方 leaderboard 分数。",
            "- source filename 是可复现但粗粒度的 domain proxy；一个文件内部仍可能包含多个任务模板。",
            "- `last_action_only` 不是 final answer。它可能是工具调用、界面动作、拒绝回复或自然语言回答。",
            "- TF-IDF 测量词汇／短语可预测性，不测真正的安全推理，也不能单独证明 annotation leakage。",
            "- random folds 可能共享近似模板；group folds 才是主要外部验证结果。",
            "- 置信区间条件于固定 folds、固定 source groups 和固定 OOF predictions，不含模型／分析选择不确定性。",
            "- 官方项目站、论文附件与当前仓库的行数和字段存在版本漂移；所有结论只适用于这里固定的 commit。",
            "",
            "逐样本预测见 `predictions.csv`，完整折信息见 `results.json`，攻击来源与应用类别描述性结果见 `subgroup_metrics.json`。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw/rjudge/data"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/rjudge-external"))
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-features", type=int, default=50_000)
    parser.add_argument("--bootstrap-resamples", type=int, default=500)
    parser.add_argument(
        "--keep-duplicate-inputs",
        action="store_true",
        help="Keep the two repeated official judge inputs in the current repository.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    loaded = load_rjudge_directory(
        args.data_dir,
        deduplicate_inputs=not args.keep_duplicate_inputs,
    )
    diagnostics = corpus_diagnostics(loaded)
    records = list(loaded.records)
    rendered = [build_rjudge_views(record) for record in records]
    view_texts = {
        view: [record_views[view] for record_views in rendered]
        for view in RJUDGE_VIEW_NAMES
    }
    source_groups = [str(record.metadata["source_file"]) for record in records]

    results = evaluate_tfidf_cross_validation(
        records,
        n_splits=args.folds,
        split_strategies=("random", "group"),
        group_values=source_groups,
        view_names=RJUDGE_VIEW_NAMES,
        view_texts=view_texts,
        seed=args.seed,
        positive_label=1,
        max_features=args.max_features,
        ngram_range=(1, 2),
        class_weight="balanced",
        bootstrap_resamples=0,
    )
    summary = aggregate_cross_validation(
        results,
        semantic_groups=source_groups,
        bootstrap_resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    paired = paired_macro_f1_differences(
        results,
        groups=source_groups,
        resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    subgroups = subgroup_metrics(results, records)
    lengths = view_length_statistics(view_texts)
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(args.data_dir),
        "output_dir": str(args.output_dir),
        "repository_url": REPOSITORY_URL,
        "repository_commit": REPOSITORY_COMMIT,
        "paper_url": PAPER_URL,
        "official_site_url": OFFICIAL_SITE_URL,
        "license_statement": "CC BY-NC-SA (version unspecified on official site; repository has no LICENSE file)",
        "acl_attachment_url": ACL_ATTACHMENT_URL,
        "acl_attachment_sha256": ACL_ATTACHMENT_SHA256,
        "acl_attachment_rows": 564,
        "file_manifest_sha256": _fingerprint(loaded.file_sha256),
        "folds": args.folds,
        "seed": args.seed,
        "max_features": args.max_features,
        "bootstrap_resamples": args.bootstrap_resamples,
        "deduplicate_official_inputs": not args.keep_duplicate_inputs,
        "group_definition": "relative source JSON filename",
        "view_names": list(RJUDGE_VIEW_NAMES),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    save_evaluation_artifacts(results, args.output_dir)
    save_summary(summary, args.output_dir / "summary.json")
    _write_json(args.output_dir / "paired_differences.json", paired)
    _write_json(args.output_dir / "subgroup_metrics.json", subgroups)
    _write_json(args.output_dir / "corpus_diagnostics.json", diagnostics)
    _write_json(args.output_dir / "view_statistics.json", lengths)
    _write_json(args.output_dir / "run_metadata.json", metadata)
    write_svg(args.output_dir / "macro_f1.svg", summary)
    write_report(
        args.output_dir / "report.md",
        diagnostics=diagnostics,
        summary=summary,
        paired=paired,
        subgroups=subgroups,
        metadata=metadata,
        view_stats=lengths,
    )

    for strategy, payload in summary["strategies"].items():
        for view in RJUDGE_VIEW_NAMES:
            metrics = payload["views"][view]["metrics"]
            print(
                f"{strategy:6} {view:16} "
                f"Macro-F1={metrics['macro_f1']:.3f} "
                f"AUROC={metrics.get('roc_auc', float('nan')):.3f} "
                f"FNR={metrics['false_negative_rate']:.3f}"
            )
    print(f"wrote {args.output_dir}")


if __name__ == "__main__":
    main()
