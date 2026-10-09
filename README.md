# Trajectory Audit

An executable MVP for testing whether an agent-safety benchmark can be predicted
without reading the full multi-step trajectory.

The pipeline uses the public
[ATBench](https://huggingface.co/datasets/AI45Research/ATBench) release and compares
five information views:

- full trajectory;
- user messages only;
- available tool schemas only;
- agent actions only;
- final answer only.

It evaluates a CPU TF-IDF/logistic-regression baseline with stratified random and
cluster-held-out cross-validation. ATBench does not publish template IDs, so these
are documented approximate TF-IDF task/tool clusters derived only from user
requests and tool names.

## Quick start

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/trajectory-audit download
.venv/bin/trajectory-audit run \
  --input data/raw/atbench/test.json \
  --output-dir outputs/atbench-mvp
```

The `run` command writes machine-readable metrics, per-example predictions, split
manifests, a Markdown report, an SVG comparison chart, top lexical features, and
a missing-final-answer ablation. Run tests with:

```bash
.venv/bin/pytest
```

## Capstone experiment suite

The complete two-column capstone paper and a command-by-command reproduction map
are in [`capstone/`](capstone/README.md). The paper combines the main ATBench
partial-view audit with risk-exposed-only analysis, ATBench/ATBench500 transfer,
and an external R-Judge replication.

The larger paper experiment grid is a separate CPU runner:

```bash
LOKY_MAX_CPU_COUNT=4 .venv/bin/python -m trajectory_audit.capstone_experiments \
  --input data/raw/atbench/test.json \
  --output-dir outputs/atbench-capstone
```

It adds event-boundary trajectory prefixes, `static_context` and
`user_plus_final` controls, fixed post-hoc cue masking, train-fold-only
top-coefficient token removal, feature-capacity and grouping sensitivity,
numeric structure-only prediction, and taxonomy-sliced metrics. The default grid
uses five folds, feature caps `{5k, 20k, 50k, all}`, cluster counts
`{25, 50, 75, 100}`, and cluster seeds `{7, 21, 42}`. Results are written as JSON
and CSV alongside a compact `experiment_summary.md`.

ATBench provides one official `test` split. This project fits diagnostic models
on new analysis splits of those 1,000 rows; its scores are benchmark-audit results,
not submissions to the official leaderboard.

The source dataset is Apache-2.0 licensed. Its annotation explanation (`reason`)
and taxonomy fields are excluded from every predictive view because they would
leak the gold label.

The code in this repository is MIT licensed. Downloaded ATBench data remains under
the dataset's Apache-2.0 license and is excluded from Git.

## Verified MVP result

The checked-in implementation was run on the complete 1,000-record release with
five folds, 50 label-free approximate task/tool clusters, and 500 cluster-bootstrap
resamples:

| View | Random Macro-F1 | Cluster-held-out Macro-F1 | Cluster-held-out unsafe FNR |
|---|---:|---:|---:|
| Full trajectory | 0.821 | 0.829 | 0.179 |
| User only | 0.684 | 0.681 | 0.280 |
| Tool schema only | 0.597 | 0.585 | 0.447 |
| Actions only | 0.651 | 0.658 | 0.376 |
| **Final answer only** | **0.874** | **0.880** | **0.044** |

All 26 trajectories without a terminal `Complete` answer are unsafe. After removing
those records, preserving the original cluster assignments, and rebuilding the
folds, final-answer-only Macro-F1 remains 0.871. This does not estimate the sentinel's
causal effect, but the other 974 answers still contain a strong signal. Safe final
answers contain refusal vocabulary, while unsafe answers often use tool completion
and confirmation vocabulary. This is not yet proof that ATBench is invalid or that
an LLM judge behaves the same way.

See [the concise result note](reports/atbench_mvp_results.md) and the generated
local reports in `outputs/atbench-mvp/`.

## Jev Guard public API evaluation

A separate evaluation sent all 1,000 ATBench test trajectories to the public
Jev Guard v3.2 2B inference API. It achieved 56.60% accuracy and 50.00% unsafe
F1 under the fixed safety-only prompt. This is a custom evaluation, not an
official leaderboard entry. See the [protocol and results](reports/jev_guard_v3_2_atbench_2026-10-09.md)
and [API evaluation script](scripts/eval_jev_atbench.py).

## Output files

- `report.md`: aggregate table, uncertainty intervals, and limitations;
- `macro_f1.svg`: comparison chart;
- `results.json`: fold-level metrics and manifests;
- `predictions.csv`: every out-of-fold prediction;
- `group_diagnostics.json` and `group_assignments.csv`: cluster audit trail;
- `final_answer_diagnostics.md`: missing-answer ablation and lexical cues.

## Package layout

- `data.py`, `views.py`: normalize trajectories and render five leakage-controlled views;
- `grouping.py`, `splits.py`: label-free clusters and group-disjoint folds;
- `baseline.py`: TF-IDF models, metrics, predictions, and bootstrap intervals;
- `diagnostics.py`, `reporting.py`: interpretation and artifacts;
- `cli.py`: reproducible `download`, `inspect`, and `run` commands.
