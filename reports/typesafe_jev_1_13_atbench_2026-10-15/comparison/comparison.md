# TypeSafe System One versus Jev Guard on ATBench

Dataset: ATBench test revision `de862a3d5363aa3928f70e2228b275135597226c`; SHA-256 `80c534b5f3517c872b528a2e6b64e34495206968edd184f4aed563d39f0cca09`. `unsafe` is positive.

Models: TypeSafe `jev-1.13.0` (pinned stable release) and Jev Guard `hubin/jev-guard-v3.2-2b`.

Compared 1,000 complete trajectories and 4,517 aligned checkpoints. Canonical state hashes matched for all 1,000 full inputs and 4,517 stepwise inputs. Actual submitted state hashes matched at 1,000/1,000 full inputs and 4,517/4,517 checkpoints.

TypeSafe uses its Noul `unsafe` probability with a fixed 0.5 threshold and an additional typed question. Jev Guard uses its native binary safety verdict. These are different decision protocols even when the trajectory state bytes match. The ATBench test labels were not used to choose either threshold.

TypeSafe used 2,955,536 full-run and 13,252,092 stepwise input tokens. At the [documented input price](https://docs.typesafe.ai/models) of $0.042 per million tokens (output tokens free), the estimated successful-request charges are $0.1241 and $0.5566, respectively.

TypeSafe used a shorter context-error fallback for 0 full inputs and 0 checkpoints.

## Complete trajectory

| Metric | Jev Guard | TypeSafe | TypeSafe − Jev |
|---|---:|---:|---:|
| Accuracy | 56.60% | 66.30% | +9.70% |
| Unsafe precision | 58.49% | 73.53% | +15.04% |
| Unsafe recall | 43.66% | 50.30% | +6.64% |
| Unsafe F1 | 50.00% | 59.74% | +9.74% |
| Balanced accuracy | 56.52% | 66.20% | +9.68% |
| TP | 217 | 250 | +33 |
| TN | 349 | 413 | +64 |
| FP | 154 | 90 | -64 |
| FN | 280 | 247 | -33 |

Predictions differed on 363/1,000 trajectories. TypeSafe alone was correct on 230; Jev Guard alone on 133.

## Final stepwise checkpoint

| Metric | Jev Guard | TypeSafe | TypeSafe − Jev |
|---|---:|---:|---:|
| Accuracy | 54.40% | 62.40% | +8.00% |
| Unsafe precision | 53.62% | 68.06% | +14.44% |
| Unsafe recall | 61.17% | 45.88% | -15.29% |
| Unsafe F1 | 57.14% | 54.81% | -2.34% |
| Balanced accuracy | 54.44% | 62.30% | +7.86% |
| TP | 304 | 228 | -76 |
| TN | 240 | 396 | +156 |
| FP | 263 | 107 | -156 |
| FN | 193 | 269 | +76 |

Final checkpoint predictions differed on 466/1,000 trajectories; all-checkpoint predictions differed on 2,095/4,517 checkpoints.

## Prediction changes as trajectories unfolded

| Measure | Jev Guard | TypeSafe |
|---|---:|---:|
| Ever predicted unsafe | 781 | 464 |
| Unsafe at first checkpoint | 379 | 86 |
| Median first unsafe fraction, among ever unsafe | 37.50% | 66.67% |
| Safe → unsafe changes | 552 | 437 |
| Unsafe → safe changes | 364 | 188 |
| Trajectories with any change | 561 | 422 |
| Gold unsafe, final miss after earlier alarm | 99 | 83 |

Both models raised an unsafe alarm on 381 trajectories; TypeSafe first alarmed earlier on 33, Jev Guard earlier on 241, and they tied on 107. Only TypeSafe alarmed on 83, only Jev Guard on 400, and neither on 136.

These are positions and changes in model judgments. ATBench supplies trajectory labels, not step-level gold labels or risk-onset times, so these counts do not measure detection delay or step-level accuracy.

## Source files

- Jev Guard full: [`predictions.jsonl`](../../jev_guard_v3_2_atbench_api_2026-10-09/predictions.jsonl)
- TypeSafe full: [`predictions.jsonl`](../full/predictions.jsonl)
- Jev Guard stepwise: [`step_predictions.jsonl`](../../jev_guard_v3_2_stepwise_api_2026-10-09/step_predictions.jsonl)
- TypeSafe stepwise: [`step_predictions_final.jsonl`](../stepwise/step_predictions_final.jsonl)
- Complete machine-readable comparison: [`comparison.json`](comparison.json)
