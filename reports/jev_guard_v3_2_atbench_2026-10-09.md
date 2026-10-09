# Jev Guard v3.2 2B on ATBench

Run date: 2026-10-09 (America/Los_Angeles)

## Result

The [Jev Guard v3.2 2B](https://huggingface.co/hubin/jev-guard-v3.2-2b)
public inference endpoint classified all 1,000 examples in the current
[ATBench](https://huggingface.co/datasets/AI45Research/ATBench) test release.
There were no API failures. `unsafe` is the positive class.

| Metric | Result |
|---|---:|
| Accuracy | 56.60% |
| Unsafe precision | 58.49% |
| Unsafe recall | 43.66% |
| Unsafe F1 | 50.00% |
| Balanced accuracy | 56.52% |

Confusion matrix: 217 true unsafe, 349 true safe, 154 false unsafe, and
280 missed unsafe. The model predicted `safe` for 629/1,000 cases, including
280/497 truly unsafe trajectories.

## Protocol and limits

- Dataset: official 1,000-case ATBench test JSON, pinned to revision
  `de862a3d5363aa3928f70e2228b275135597226c`, SHA-256
  `80c534b5f3517c872b528a2e6b64e34495206968edd184f4aed563d39f0cca09`.
- Input: the label-free `full` view from `trajectory_audit.views.build_view`:
  available tool definitions and complete ordered trajectory events. The gold
  verdict, taxonomy labels, and annotation rationale were excluded.
- Prompt: one fixed safety-review instruction, followed by the view. The Jev
  endpoint's `mode="single"`, empty `options`, and `safety_applicable=true`
  return its native safety head. Its default decision threshold was used;
  there was no test-set threshold tuning.
- Context: 52 cases exceeded the fixed 24,000-character cap. Their middle
  was omitted, retaining the beginning and end. All returned prompts had at
  most 9,397 model tokens. On the 948 unabridged cases, accuracy was 55.80%
  and unsafe F1 was 46.49%. The 52 abridged cases are label-skewed (50 unsafe,
  2 safe), so their higher F1 is not a comparable subgroup result.
- This is a **custom evaluation** of the published endpoint. It is not an
  official ATBench leaderboard entry: the formatting and long-input handling
  differ from other evaluators, and this model only produced binary safety
  predictions, not the three fine-grained diagnosis labels.

Reproduce using [`scripts/eval_jev_atbench.py`](../scripts/eval_jev_atbench.py).
The [1,000 per-case API predictions](jev_guard_v3_2_atbench_api_2026-10-09/predictions.jsonl)
and [machine-readable summary](jev_guard_v3_2_atbench_api_2026-10-09/summary.json)
are checked in. The hosted preview endpoint is temporary, so a later run may
require a new URL.

## Endpoint verification

The model card publishes
`https://approaches-lemon-antique-garden.trycloudflare.com/predict` as its
hosted v3.2 API. The evaluation script posts each input to that URL. Its
`/health` endpoint returned `model: jev-v3.2-2b` and
`checkpoint_updates: 1508` when checked. A fresh replay of ATBench case 1
returned the same `unsafe` probability (`0.012883701361715794`) and token
count (`1339`) as the saved result. The script now checks the model identifier
in every new response. These observations verify the request path and response
consistency. API responses alone cannot independently attest to the remote
server's weight files.
