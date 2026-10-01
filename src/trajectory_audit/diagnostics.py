"""Post-hoc diagnostics for interpreting partial-view shortcut signals."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


_MARKUP_LINE = re.compile(r"^\[[^\n]*\]\s*$", re.MULTILINE)


def strip_view_markup(text: str) -> str:
    """Remove renderer headers before interpreting lexical coefficients."""

    return "\n".join(
        line for line in _MARKUP_LINE.sub("", text).splitlines() if line.strip()
    )


def top_tfidf_features(
    texts: Sequence[str],
    labels: Sequence[int],
    *,
    top_k: int = 25,
    max_features: int = 20_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Fit a descriptive full-data model and return largest signed coefficients.

    This model is for vocabulary diagnosis only.  Its training-set coefficients
    are not a held-out estimate and must not be reported as predictive performance.
    """

    if len(texts) != len(labels) or len(texts) < 2:
        raise ValueError("texts and labels must have equal length of at least two")
    if set(labels) != {0, 1}:
        raise ValueError("top_tfidf_features requires binary 0/1 labels")
    cleaned = [strip_view_markup(text) or "[EMPTY]" for text in texts]
    min_df = 3 if len(texts) >= 30 else 1
    vectorizer = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=min_df,
        max_features=max_features,
        sublinear_tf=True,
        stop_words="english",
        strip_accents="unicode",
    )
    matrix = vectorizer.fit_transform(cleaned)
    model = LogisticRegression(
        class_weight="balanced",
        max_iter=1_000,
        random_state=seed,
        solver="liblinear",
    )
    model.fit(matrix, labels)
    terms = vectorizer.get_feature_names_out()
    coefficients = model.coef_[0]

    def rows(indices: Sequence[int], direction: str) -> list[dict[str, Any]]:
        return [
            {
                "direction": direction,
                "term": str(terms[index]),
                "coefficient": float(coefficients[index]),
                "document_frequency": int(matrix[:, index].getnnz()),
            }
            for index in indices
        ]

    unsafe_indices = coefficients.argsort()[::-1][:top_k]
    safe_indices = coefficients.argsort()[:top_k]
    return {
        "fit_scope": "all_records_descriptive_only",
        "n": len(texts),
        "vocabulary_size": int(len(terms)),
        "unsafe_associated": rows(unsafe_indices, "unsafe"),
        "safe_associated": rows(safe_indices, "safe"),
    }


def missing_by_label(texts: Sequence[str], labels: Sequence[int]) -> dict[str, Any]:
    if len(texts) != len(labels):
        raise ValueError("texts and labels must have the same length")
    missing_labels = [
        label for text, label in zip(texts, labels) if text.rstrip().endswith("<NONE>")
    ]
    return {
        "total": len(missing_labels),
        "safe": missing_labels.count(0),
        "unsafe": missing_labels.count(1),
    }


def save_top_features_csv(payload: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = list(payload.get("unsafe_associated", [])) + list(
        payload.get("safe_associated", [])
    )
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["direction", "term", "coefficient", "document_frequency"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return target


def write_final_answer_diagnostics(
    path: str | Path,
    *,
    missing: Mapping[str, Any],
    top_features: Mapping[str, Any],
    complete_only_summary: Mapping[str, Any],
    folds: int = 5,
) -> Path:
    lines = [
        "# Final-answer-only 诊断",
        "",
        "该文件检查 `final_answer_only` 的高分是否完全由缺失终止回答造成，并列出",
        "与标签相关的描述性词项。词项模型在全部样本上拟合，仅用于解释，不是 held-out 分数。",
        "",
        "## 缺失情况",
        "",
        f"- 没有 `Complete` 回答：{missing['total']} 条",
        f"- 其中 safe：{missing['safe']}；unsafe：{missing['unsafe']}",
        "",
        f"## 删除缺失样本后的 {folds} 折结果",
        "",
        "| 切分 | N | Macro-F1 | AUROC | Unsafe recall | FNR |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for strategy, payload in complete_only_summary.get("strategies", {}).items():
        metrics = payload["views"]["final_answer_only"]["metrics"]
        recall = metrics["per_class"]["1"]["recall"]
        lines.append(
            f"| {strategy} | {metrics['n']} | {metrics['macro_f1']:.3f} | "
            f"{metrics['roc_auc']:.3f} | {recall:.3f} | {metrics['false_negative_rate']:.3f} |"
        )
    if complete_only_summary.get("skipped"):
        lines.append(
            f"| skipped | — | — | — | — | — |  \n\n原因：{complete_only_summary['skipped']}"
        )
    lines.extend(
        [
            "",
            "删除这些样本后会改变数据、folds 和训练集；这里沿用原始 cluster 分配，仍不能据此估计 `<NONE>` 的因果贡献。",
            "如果重新分折和训练后的分数仍接近主结果，只能说明带回答的样本仍保留大部分信号。",
            "",
            "## 与 unsafe 相关的词项",
            "",
            "| 词项 | 系数 | 文档频率 |",
            "|---|---:|---:|",
        ]
    )
    for row in top_features.get("unsafe_associated", []):
        lines.append(
            f"| `{row['term']}` | {row['coefficient']:.3f} | {row['document_frequency']} |"
        )
    lines.extend(
        [
            "",
            "## 与 safe 相关的词项",
            "",
            "| 词项 | 系数 | 文档频率 |",
            "|---|---:|---:|",
        ]
    )
    for row in top_features.get("safe_associated", []):
        lines.append(
            f"| `{row['term']}` | {row['coefficient']:.3f} | {row['document_frequency']} |"
        )
    lines.extend(
        [
            "",
            "这些系数只能说明词项和标签相关。它们可能来自安全拒绝、动作结果、生成模板或",
            "任务本身，不能单独证明 annotation leakage。",
        ]
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


__all__ = [
    "missing_by_label",
    "save_top_features_csv",
    "strip_view_markup",
    "top_tfidf_features",
    "write_final_answer_diagnostics",
]
