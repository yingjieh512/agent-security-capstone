# Trajectory Audit

## Single-operator capstone · Mail authorization audit

When a mail agent's authorization policy changes, can the approval service and the receiving mailbox still produce enough evidence to audit the next send? The system compiles a policy and two source capability declarations into collection rules. It reports fields to add or retire, produces replayable examples of missing evidence, and pins each send to the version in effect at approval. A local Mailpit backend provides real SMTP delivery. The study covers 56 directed policy changes and 160 single-field capability losses. The Chinese [one-page faculty proposal](capstone/solo_mail_audit_proposal_zh.pdf) and [final report](capstone/solo_mail_audit_final_zh.pdf) describe the research contribution and limits.

With Python 3.10+ on macOS or Linux, run the following from the repository root. The first command provisions Mailpit v1.34.0 and checks three experiments against their archived results. The second runs an editable case that spans a policy change.

```sh
python3 scripts/reproduce_mail_capstone.py
PYTHONPATH=src:scripts python3 scripts/run_mail_case.py examples/mail_audit/local_case.json
```

For a portable source, report and results bundle, run `python3 scripts/package_mail_capstone.py`. It writes `outputs/mail_capstone/solo-mail-audit.zip`. The [final experiment protocol](reports/solo_mail_audit/final_protocol.md) records the acceptance criteria and the [Chinese project report](reports/solo_mail_audit/final_report.md) explains the measurements.

## Earlier benchmark experiments

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

The code in this repository is MIT licensed. ATBench data remains under the
dataset's Apache-2.0 license. The canonical download under `data/raw/` is ignored
by Git; the archived experiment outputs include derived ATBench rows and prompts.

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

A [stepwise API follow-up](reports/jev_guard_v3_2_stepwise_atbench_2026-10-09.md)
replays each trajectory as cumulative prefixes after agent actions. It records
the first unsafe judgment and every safe/unsafe prediction change across 4,517
checkpoints, with [reproduction code](scripts/eval_jev_stepwise.py). ATBench
provides only whole-trajectory labels, so these are model-prediction timelines
rather than step-level accuracy measurements.

## Adversarial ATBench-style Jev Guard trajectories

The [adversarial trajectory report](reports/jev_guard_adversarial_atbench_results_2026-10-15.md)
documents a paired audit of Jev Guard v3.2 2B's complete-trajectory safety head.
Each of 100 previously detected unsafe ATBench trajectories has an unchanged
`clean` view, a length-matched neutral tool-result note, and a forged final safety
summary inside the same lower-trust tool result. On this frozen cohort, the safety
head marked 0/100 clean, 5/100 neutral, and 64/100 adversarial views as safe.
The attack increased false negatives by 59 percentage points versus the neutral
control (parent bootstrap 95% CI: 49–69 points). This measures the safety head,
not the native permission gate or end-to-end agent execution.

The [constructor](scripts/construct_jev_adversarial.py) writes ATBench-style raw
rows plus exact model prompts and reversible edit manifests. The
[paired evaluator](scripts/eval_jev_adversarial_pairs.py) records individual API
responses, completeness, and paired bootstrap estimates. The fixed source IDs
and paired statistics are mirrored in the [compact audit copy](reports/jev_adversarial_evidence_2026-10-16/README.md).
The complete [archived `outputs/` snapshot](outputs/) contains generated states,
edit manifests, per-request responses, development runs, and full ATBench replays.
Although `.gitignore` matches `outputs/`, its existing 68 files were explicitly
added to this repository. Future generated files remain ignored unless added
explicitly. Original ATBench text includes credential-shaped strings; the actual
TypeSafe API key is absent from the archive.

## TypeSafe System One API evaluation

The [TypeSafe replay script](scripts/eval_typesafe_atbench.py) runs the same
1,000 full-trajectory states and 4,517 stepwise checkpoint states through the
version-pinned `jev-1.13.0` Decision Model. It sends a fixed binary Noul safety
question, records the unsafe probability, and uses a prespecified 0.5 threshold.
The original state text, 24,000-character middle omission, and checkpoint
boundaries are reused exactly. TypeSafe's additional typed question and Jev
Guard's native safety head are different decision protocols.

```bash
python scripts/eval_typesafe_atbench.py --experiment both --dry-run
python scripts/eval_typesafe_atbench.py --experiment both --api-key-stdin
```

The key prompt hides input and does not write the key to a file. Alternatively,
set `TYPESAFE_API_KEY` in the environment and omit `--api-key-stdin`. Runs resume
completed predictions and reject incompatible saved model, question, or state
hashes. The completed run, paired comparison, and interpretation are in the
[TypeSafe ATBench report](reports/typesafe_jev_1_13_atbench_2026-10-15.md).

The [official TypeSafe Jev adversarial replay](reports/typesafe_jev_adversarial_atbench_2026-10-16.md)
uses the same 100 ATBench parent trajectories and exact 300 clean, neutral, and
adversarial state texts as the Jev Guard audit. On this selected cohort, the
attack increased unsafe false negatives over the neutral control by 14 percentage
points for pinned `jev-1.13.0` and 13 points for pinned `jev-1.14.0`; Jev Guard's
increase was 59 points. TypeSafe uses the existing Noul safety question and a
fixed 0.5 threshold, so the comparison describes these judge configurations.
The [TypeSafe paired evaluator](scripts/eval_typesafe_adversarial_pairs.py) and
[cross-judge analysis](scripts/compare_jev_adversarial_judges.py) preserve
per-state responses and paired uncertainty estimates. The [published cross-judge
comparison](reports/jev_adversarial_evidence_2026-10-16/cross_judge/comparison.json)
and its paired evidence are mirrored in the compact audit copy; the [full
outputs](outputs/) are also available in the repository.

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

## Cross-tool evidence acquisition pilot

The [ATBench and Claw pilot](reports/atbench_claw_cross_tool_query_pilot_2026-11-18.md) compares adaptive queries with the best fixed order per tool at equal correct coverage. It includes results for 91 logged calls, a separate controlled replay with independent scoring tables, and reproduction commands.

## Policy-specific send audit records

The [minimum send-log pilot](reports/atbench_claw_minimum_send_log_2026-11-18.md) compiles a policy and source capabilities into authenticated, attempt-bound records. It compares the privacy footprint of two-source receipts across ATBench and Claw send arguments, gives counterexamples when a field is missing, and checks decisions against a local backend.

The [held-out attachment authorization pilot](reports/attachment_holdout/README.md) freezes that compiler and tests it against a separate Mailpit SMTP backend. It records where the frozen compiler fails, runs an external field search against an independently hand-written configuration, and replays the resulting evidence gaps in the mailbox.

The [independent policy transfer pilot](reports/policy_transfer/README.md) compares the original attachment system with a declaration-based compiler frozen before a blind proxy submitted a new rule. Both the hand-written configuration and the generated one are verified on the same persisted SMTP messages.
