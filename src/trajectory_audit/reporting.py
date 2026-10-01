"""Aggregate cross-validation outputs and create lightweight audit reports."""

from __future__ import annotations

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.metrics import f1_score

from .baseline import bootstrap_confidence_interval, classification_metrics


def _strategy_name(split_name: str) -> str:
    return split_name.rsplit("_fold_", 1)[0]


def _paired_cluster_bootstrap_macro_f1(
    y_true: Sequence[int],
    first: Sequence[int],
    second: Sequence[int],
    groups: Sequence[str],
    *,
    n_resamples: int,
    seed: int,
) -> dict[str, Any]:
    """Bootstrap a paired Macro-F1 difference using identical group draws."""

    group_indices: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        group_indices[str(group)].append(index)
    group_keys = np.asarray(list(group_indices), dtype=object)
    true_array = np.asarray(y_true)
    first_array = np.asarray(first)
    second_array = np.asarray(second)
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(n_resamples):
        sampled = rng.choice(group_keys, size=len(group_keys), replace=True)
        indices = np.asarray(
            [index for group in sampled for index in group_indices[str(group)]],
            dtype=int,
        )
        estimates.append(
            float(
                f1_score(true_array[indices], first_array[indices], average="macro", zero_division=0)
                - f1_score(true_array[indices], second_array[indices], average="macro", zero_division=0)
            )
        )
    point = float(
        f1_score(true_array, first_array, average="macro", zero_division=0)
        - f1_score(true_array, second_array, average="macro", zero_division=0)
    )
    return {
        "metric": "macro_f1_difference",
        "estimate": point,
        "lower": float(np.quantile(estimates, 0.025)),
        "upper": float(np.quantile(estimates, 0.975)),
        "confidence": 0.95,
        "n_resamples": n_resamples,
        "sampling_units": "fixed_inferred_clusters",
        "seed": seed,
    }


def aggregate_cross_validation(
    results: Mapping[str, Any],
    *,
    semantic_groups: Sequence[str] | None = None,
    bootstrap_resamples: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    """Aggregate out-of-fold predictions once per record, strategy, and view."""

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    fold_metrics: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for split_name, split in results.get("splits", {}).items():
        strategy = _strategy_name(str(split_name))
        for view, payload in split.get("views", {}).items():
            buckets[(strategy, str(view))].extend(payload.get("predictions", []))
            fold_metrics[(strategy, str(view))].append(payload.get("metrics", {}))

    summary: dict[str, Any] = {
        "schema_version": 1,
        "bootstrap_resamples": bootstrap_resamples,
        "strategies": {},
    }
    expected_records = int(results.get("dataset", {}).get("labelled_records", 0))
    prepared_predictions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for (strategy, view), predictions in sorted(buckets.items()):
        predictions = sorted(predictions, key=lambda row: int(row["record_index"]))
        indices = [int(row["record_index"]) for row in predictions]
        if len(indices) != len(set(indices)):
            raise ValueError(f"duplicate out-of-fold predictions for {strategy}/{view}")
        if expected_records and len(indices) != expected_records:
            raise ValueError(
                f"incomplete out-of-fold coverage for {strategy}/{view}: "
                f"expected {expected_records}, found {len(indices)}"
            )
        prepared_predictions[(strategy, view)] = predictions
        y_true = [row["y_true"] for row in predictions]
        y_pred = [row["y_pred"] for row in predictions]
        scores = [row.get("positive_score") for row in predictions]
        score_values = None if any(value is None for value in scores) else scores
        metrics = classification_metrics(y_true, y_pred, scores=score_values)

        if semantic_groups is not None:
            groups = [semantic_groups[index] for index in indices]
        else:
            groups = [str(row.get("group", index)) for index, row in zip(indices, predictions)]

        confidence_intervals: dict[str, Any] = {}
        if bootstrap_resamples:
            for metric in ("macro_f1", "accuracy", "false_negative_rate"):
                confidence_intervals[metric] = bootstrap_confidence_interval(
                    y_true,
                    y_pred,
                    metric=metric,
                    scores=score_values,
                    groups=groups,
                    n_resamples=bootstrap_resamples,
                    seed=seed,
                )

        per_fold = fold_metrics[(strategy, view)]
        fold_summary = {}
        for metric in ("macro_f1", "accuracy", "roc_auc", "false_negative_rate"):
            values = [float(item[metric]) for item in per_fold if item.get(metric) is not None]
            if values:
                fold_summary[metric] = {
                    "mean": statistics.fmean(values),
                    "standard_deviation": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "folds": len(values),
                }
        summary["strategies"].setdefault(strategy, {"views": {}})["views"][view] = {
            "metrics": metrics,
            "confidence_intervals": confidence_intervals,
            "fold_summary": fold_summary,
            "records": len(predictions),
        }

    for strategy_payload in summary["strategies"].values():
        views = strategy_payload["views"]
        full_score = views.get("full", {}).get("metrics", {}).get("macro_f1")
        for view_payload in views.values():
            score = view_payload["metrics"].get("macro_f1")
            view_payload["macro_f1_retention_vs_full"] = (
                score / full_score if score is not None and full_score else None
            )
    if bootstrap_resamples:
        for strategy, strategy_payload in summary["strategies"].items():
            full_rows = prepared_predictions.get((strategy, "full"))
            final_rows = prepared_predictions.get((strategy, "final_answer_only"))
            if not full_rows or not final_rows:
                continue
            full_by_index = {int(row["record_index"]): row for row in full_rows}
            final_by_index = {int(row["record_index"]): row for row in final_rows}
            if set(full_by_index) != set(final_by_index):
                raise ValueError(f"full/final coverage differs for {strategy}")
            ordered_indices = sorted(full_by_index)
            y_true = [int(full_by_index[index]["y_true"]) for index in ordered_indices]
            if any(
                int(final_by_index[index]["y_true"]) != truth
                for index, truth in zip(ordered_indices, y_true)
            ):
                raise ValueError(f"full/final labels differ for {strategy}")
            groups = (
                [semantic_groups[index] for index in ordered_indices]
                if semantic_groups is not None
                else [str(full_by_index[index]["group"]) for index in ordered_indices]
            )
            strategy_payload["paired_differences"] = {
                "final_answer_only_minus_full": _paired_cluster_bootstrap_macro_f1(
                    y_true,
                    [int(final_by_index[index]["y_pred"]) for index in ordered_indices],
                    [int(full_by_index[index]["y_pred"]) for index in ordered_indices],
                    groups,
                    n_resamples=bootstrap_resamples,
                    seed=seed,
                )
            }
    return summary


def view_length_statistics(view_texts: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Describe representation sizes and explicit missing-view sentinels."""

    output: dict[str, Any] = {}
    for view, texts in view_texts.items():
        lengths = [len(text) for text in texts]
        output[view] = {
            "n": len(lengths),
            "mean_characters": statistics.fmean(lengths) if lengths else 0.0,
            "median_characters": statistics.median(lengths) if lengths else 0.0,
            "min_characters": min(lengths, default=0),
            "max_characters": max(lengths, default=0),
            "explicit_missing": sum(text.rstrip().endswith("<NONE>") for text in texts),
        }
    return output


def _interval_text(payload: Mapping[str, Any], metric: str) -> str:
    interval = payload.get("confidence_intervals", {}).get(metric)
    if not interval:
        return ""
    return f" [{interval['lower']:.3f}, {interval['upper']:.3f}]"


def write_markdown_report(
    path: str | Path,
    summary: Mapping[str, Any],
    *,
    run_metadata: Mapping[str, Any],
    view_stats: Mapping[str, Any],
) -> Path:
    """Write a self-contained Chinese report for the MVP run."""

    lines = [
        "# ATBench 局部视图审计：MVP 结果",
        "",
        "本报告比较同一个 TF-IDF／Logistic Regression 分类器在五种信息视图上的表现。",
        "这些分数来自 ATBench 官方 `test` 数据上的自定义交叉验证，属于 benchmark audit，",
        "不是官方 leaderboard test score。",
        "",
        "## 运行设置",
        "",
        f"- 样本数：{run_metadata['records']}（safe {run_metadata['safe']}／unsafe {run_metadata['unsafe']}）",
        f"- 随机种子：{run_metadata['seed']}；交叉验证：{run_metadata['folds']} folds",
        f"- 近似任务组：{run_metadata['semantic_groups']} 个；分组只使用用户请求和工具名，不使用标签",
        f"- 输入文件 SHA-256：`{run_metadata['input_sha256']}`",
        f"- Bootstrap：按近似任务组重采样 {summary.get('bootstrap_resamples', 0)} 次",
        "",
        "## 主结果",
        "",
        "| 切分 | 视图 | Macro-F1（条件式 95% cluster-bootstrap CI） | AUROC | Unsafe recall | FNR | 相对 full |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for strategy, strategy_payload in summary.get("strategies", {}).items():
        for view, payload in strategy_payload.get("views", {}).items():
            metrics = payload["metrics"]
            recall = metrics.get("per_class", {}).get("1", {}).get("recall")
            retention = payload.get("macro_f1_retention_vs_full")
            lines.append(
                "| {strategy} | {view} | {f1:.3f}{ci} | {auc} | {recall} | {fnr} | {retention} |".format(
                    strategy=strategy,
                    view=view,
                    f1=metrics["macro_f1"],
                    ci=_interval_text(payload, "macro_f1"),
                    auc=(f"{metrics['roc_auc']:.3f}" if metrics.get("roc_auc") is not None else "—"),
                    recall=(f"{recall:.3f}" if recall is not None else "—"),
                    fnr=(
                        f"{metrics['false_negative_rate']:.3f}"
                        if metrics.get("false_negative_rate") is not None
                        else "—"
                    ),
                    retention=(f"{retention:.1%}" if retention is not None else "—"),
                )
            )

    lines.extend(
        [
            "",
            f"`random` 是普通 stratified {run_metadata['folds']}-fold；`group` 是 TF-IDF 聚类得到的近似任务／工具簇",
            f"held-out {run_metadata['folds']}-fold。它只能降低相似请求或工具模式同时进入训练和测试的风险。",
            "",
            "## Final answer 与 full 的配对差值",
            "",
            "| 切分 | Δ Macro-F1（final − full） | 条件式 95% cluster-bootstrap CI |",
            "|---|---:|---:|",
        ]
    )
    for strategy, strategy_payload in summary.get("strategies", {}).items():
        difference = strategy_payload.get("paired_differences", {}).get(
            "final_answer_only_minus_full"
        )
        if difference:
            lines.append(
                f"| {strategy} | {difference['estimate']:+.3f} | "
                f"[{difference['lower']:+.3f}, {difference['upper']:+.3f}] |"
            )
    lines.extend(
        [
            "",
            "该区间在每次重采样中使用同一批近似 cluster，直接比较两种视图。",
            "",
            "## 初步解释",
            "",
        ]
    )
    for strategy, strategy_payload in summary.get("strategies", {}).items():
        views = strategy_payload.get("views", {})
        full = views.get("full", {}).get("metrics", {}).get("macro_f1")
        partial = [
            (view, payload.get("metrics", {}).get("macro_f1"))
            for view, payload in views.items()
            if view != "full"
        ]
        partial = [(view, score) for view, score in partial if score is not None]
        if full is not None and partial:
            best_view, best_score = max(partial, key=lambda pair: pair[1])
            relation = best_score / full if full else 0.0
            lines.append(
                f"- **{strategy}：**最强局部视图是 `{best_view}`（Macro-F1 {best_score:.3f}），"
                f"相当于 full 的 {relation:.1%}。"
            )
    lines.extend(
        [
            "",
            "局部视图达到或超过 full 说明标签中存在不依赖完整跨步轨迹的强信号；",
            "它不自动证明数据集无效，也不证明某个具体词就是泄漏来源。下一步需要查看",
            "高置信错误、每个 risk category 的结果，并加入冻结的小型 safety judge 复核。",
            "",
            "## 视图规模",
            "",
            "| 视图 | 平均字符数 | 中位字符数 | 显式缺失 |",
            "|---|---:|---:|---:|",
        ]
    )
    for view, stats in view_stats.items():
        lines.append(
            f"| {view} | {stats['mean_characters']:.0f} | {stats['median_characters']:.0f} | {stats['explicit_missing']} |"
        )
    lines.extend(
        [
            "",
            "## 关键限制",
            "",
            "- ATBench 没有公开原始 scenario/template ID；这里的 group 是可复现的无监督近似，",
            "  不能声称恢复了生成时的真实配对关系。",
            "- 官方构造过程从共同 scenario skeleton 生成 safe/unsafe variants；pair ID 未发布，",
            "  因而近似聚类不能排除真实配对仍然跨 fold。",
            "- TF-IDF 基线测量词汇与短语信号，不测真正的长程推理能力。",
            "- 所有视图共用 50,000 个词项和同一正则化强度；full 平均约 14.6k 字符，",
            "  final answer 约 278 字符。词表截断和 TF-IDF 归一化可能稀释 full 中的局部信号，",
            "  因而 final > full 不能解释成完整轨迹本身没有价值。",
            "- 聚类在全部输入上无监督拟合，但完全不读取安全标签；预测模型仍严格在每折训练集拟合。",
            "- 置信区间对固定聚类与固定 OOF predictions 做组级重采样，不包含重新聚类、",
            "  重新分折或分析选择的不确定性；还需要 untouched confirmatory data。",
            "- `reason`、`risk_source`、`failure_mode`、`real_world_harm` 均未进入任何预测视图。",
            "",
            "逐样本结果见 `predictions.csv`，完整折信息和混淆矩阵见 `results.json`。",
        ]
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def write_macro_f1_svg(path: str | Path, summary: Mapping[str, Any]) -> Path:
    """Write a dependency-free grouped bar chart of out-of-fold Macro-F1."""

    strategies = list(summary.get("strategies", {}))
    view_order = [
        "full",
        "user_only",
        "tool_schema_only",
        "action_only",
        "final_answer_only",
    ]
    available = {
        view
        for payload in summary.get("strategies", {}).values()
        for view in payload.get("views", {})
    }
    views = [view for view in view_order if view in available]
    width, height = 980, 120 + 72 * len(views)
    left, right, top, bottom = 230, 50, 55, 45
    plot_width = width - left - right
    colors = ["#2563eb", "#f97316", "#16a34a", "#9333ea"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#172033}.title{font-size:20px;font-weight:650}.label{font-size:14px}.tick{font-size:12px;fill:#526071}.value{font-size:12px;font-weight:600}</style>',
        '<text class="title" x="24" y="30">ATBench partial-view audit — out-of-fold Macro-F1</text>',
    ]
    for tick in range(0, 11, 2):
        score = tick / 10
        x = left + score * plot_width
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height-bottom}" stroke="#e5e7eb"/>')
        parts.append(f'<text class="tick" x="{x:.1f}" y="{height-18}" text-anchor="middle">{score:.1f}</text>')

    bar_height = 18
    for row, view in enumerate(views):
        center_y = top + 26 + row * 72
        parts.append(f'<text class="label" x="{left-12}" y="{center_y+5}" text-anchor="end">{escape(view)}</text>')
        for offset, strategy in enumerate(strategies):
            payload = summary["strategies"][strategy]["views"].get(view)
            if not payload:
                continue
            score = float(payload["metrics"]["macro_f1"])
            y = center_y - (len(strategies) * bar_height) / 2 + offset * bar_height
            bar_width = score * plot_width
            color = colors[offset % len(colors)]
            parts.append(f'<rect x="{left}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height-3}" rx="2" fill="{color}"/>')
            parts.append(f'<text class="value" x="{left+bar_width+6:.1f}" y="{y+12:.1f}">{score:.3f}</text>')

    legend_x = width - right - 170
    for index, strategy in enumerate(strategies):
        y = 22 + index * 20
        color = colors[index % len(colors)]
        parts.append(f'<rect x="{legend_x}" y="{y-11}" width="12" height="12" rx="2" fill="{color}"/>')
        parts.append(f'<text class="tick" x="{legend_x+18}" y="{y}">{escape(strategy)}</text>')
    parts.append("</svg>")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return target


def save_summary(summary: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "aggregate_cross_validation",
    "save_summary",
    "view_length_statistics",
    "write_macro_f1_svg",
    "write_markdown_report",
]
