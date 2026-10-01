# When Does an Agent Safety Label Require the Full Trajectory

## A Partial View and Group Aware Audit of ATBench

**Document type:** Research Proposal  
**Proposed duration:** 10 weeks  
**Resources:** One researcher, standard CPU computing, and one Google Colab class GPU

## Abstract

Large language model agents can call tools, read files, browse websites, send messages, and take actions on a user’s behalf. Their safety therefore depends not only on the final response but also on what happened during execution. A **trajectory** is the chronological record of this process, including the user’s request, available tools, agent actions, tool results, and final answer. A **safety judge** is a model or classifier that reads this record and predicts whether the behavior was safe or unsafe.

This project asks whether high scores on trajectory safety benchmarks actually require judges to understand the full trajectory. Preliminary experiments on ATBench show that a simple classifier reading only the final answer achieves 0.880 Macro-F1, compared with 0.829 when it reads the complete trajectory. On R-Judge, the last agent action alone achieves 0.917, compared with 0.803 for the complete record. These are exploratory findings: they demonstrate strong local label signal, but do not prove data leakage, incorrect labels, or that trajectories are unnecessary in deployment.

The proposed work will test whether this pattern persists with a frozen compact safety model and with controlled counterfactual examples. In 120 source trajectories, the actions will remain unchanged while the final answer is rewritten in two ways: a meaning-preserving paraphrase and a version that conflicts with the actions actually taken. The resulting audit will clarify what benchmark scores measure and provide a reproducible reporting protocol for future agent safety evaluations.

> This project tests whether a benchmark score requires evidence from the full trajectory. It does not test whether full trajectories are useful in real deployments. A strong partial-view score is not a reason to discard process logs.

## Motivation

Traditional chatbots mainly produce text. A large language model, or LLM, agent can instead perform a sequence of operations: search a drive, open a document, call an external service, or send a message. Safety failures can therefore arise from relationships across several steps. An agent may receive permission to send a public document, encounter a malicious instruction inside a webpage, read a confidential file, and send it to an unauthorized recipient. Its final answer might simply say, “Task completed.”

A judge that labels this case unsafe after reading the entire record may have identified the unauthorized transfer. A judge that sees only “Task completed” and makes the same prediction has obtained the correct benchmark label without demonstrating that understanding.

A **benchmark** is a fixed collection of examples, reference labels, and scoring rules used to compare systems. Its safe or unsafe label is the **reference label**, sometimes called the gold label or ground truth. A high score shows that a model predicts these labels well; it does not automatically show why the predictions are correct.

This distinction concerns **construct validity**, meaning whether a test actually measures the capability it claims to measure. If a trajectory benchmark is intended to measure reasoning about permissions, data flow, and multi-step actions, then its score should ideally require evidence distributed across those steps. A **partial-view baseline** deliberately withholds most of the record. High partial-view performance indicates a possible **shortcut signal**: a feature correlated with the label that does not require the intended full reasoning process. Such a signal may be a genuine summary of the outcome rather than an error, but it narrows what the benchmark score can establish.

## Key Terms

| Term | Plain-language definition |
|---|---|
| LLM agent | A language-model system that can take multiple actions using search, email, database, or other tools. |
| Trajectory | The complete chronological record of a task, from the user request to the final answer. |
| Safety judge or guard | A model that labels a response or trajectory safe or unsafe. |
| Benchmark | A standardized “exam” containing examples, reference labels, and scoring rules. |
| Ground truth | The benchmark’s reference answer. ATBench labels are human reviewed, but they are still judgments made under a policy rather than infallible natural facts. |
| Partial view | A deliberately restricted part of a trajectory, such as only the user request, actions, or final answer. |
| Shortcut signal | A label-correlated clue that does not require the full reasoning the benchmark is intended to test. |
| Macro-F1 | The average of classification quality for the safe and unsafe classes. It ranges from 0 to 1 and is not simply percent correct. |
| Unsafe false-negative rate | The share of unsafe cases incorrectly predicted safe. Lower is better. |
| Safe false-positive rate | The share of safe cases incorrectly predicted unsafe. Lower is better. |
| Frozen model | A previously trained model whose parameters are not updated on ATBench. |
| Counterfactual pair | Two examples that keep the underlying actions fixed while changing one controlled feature, here the wording of the final answer. |

## Research Questions

1. How much ATBench label information can be recovered from the user request, tool description, actions, or final answer alone?
2. Does partial-view performance remain when similar tasks are kept together and held out from training?
3. Can missing answers, refusal words, text length, record structure, model capacity, or one grouping method explain the result?
4. Does the pattern persist with a frozen compact safety guard and with action-preserving counterfactual examples?

The completed CPU experiments provide exploratory answers to the first three questions. The fourth question is the main proposed work.

## Data and Method

ATBench contains 1,000 human-reviewed trajectories: 503 labeled safe and 497 unsafe. The analysis removes all answer-bearing fields, including the label, human rationale, risk source, failure mode, and real-world-harm description, before constructing model inputs.

ATBench provides only an official test split. The current audit therefore uses five-fold **cross-validation** rather than reporting an official leaderboard result. Cross-validation divides the data into five parts, repeatedly trains on four, and tests on the remaining part so that every record is predicted by a model that was not trained on that record.

To reduce the chance that closely related templates appear in both training and testing, the project clusters records using normalized user requests and tool names. Each cluster stays entirely within one fold. This **group-held-out split** is a reproducible proxy for task-family separation, not an official family split, because ATBench does not publish the original scenario identifiers.

Each trajectory is converted deterministically into five views:

| View | Information retained |
|---|---|
| Full | Tool descriptions and all events in chronological order |
| User-only | Messages written by the user |
| Tool-schema-only | Tool names, descriptions, and parameters |
| Actions-only | Agent actions and tool calls |
| Final-answer-only | The final explicit completion response |

The transparent baseline uses **TF-IDF**, which represents text through weighted word and phrase counts, followed by **logistic regression**, a simple linear classifier. This model is intentionally limited: it tests whether labels are accessible from surface text patterns, not whether a model performs full causal reasoning.

R-Judge provides an external comparison with 569 deduplicated records. Its 27 source files remain intact as evaluation groups. Because R-Judge does not mark a formal final answer, its last agent action is only a local-action proxy and not an exact equivalent of the ATBench final-answer view.

## Preliminary Exploratory Evidence

All values below use the primary group-held-out setting rather than an ordinary random split.

| Dataset and view | Macro-F1 | AUROC | Unsafe FNR | Safe FPR |
|---|---:|---:|---:|---:|
| ATBench full trajectory | 0.829 | 0.903 | 0.179 | 0.163 |
| ATBench final answer only | **0.880** | **0.938** | **0.044** | 0.193 |
| R-Judge full record | 0.803 | 0.902 | 0.080 | — |
| R-Judge last action | **0.917** | **0.969** | **0.053** | — |

**AUROC** measures how well the model ranks unsafe cases above safe cases across possible decision thresholds; 0.5 is approximately random and 1 is perfect ranking. A dash marks a value that was not included in the primary R-Judge report table. On ATBench, the final-minus-full Macro-F1 difference is +0.051. A 500-resample group bootstrap, a procedure that repeatedly resamples whole groups to estimate uncertainty, gives a conditional 95% interval of `[+0.011, +0.091]`.

Several completed checks suggest that the result is not caused by one trivial artifact:

- Removing the 26 records without a final completion leaves final-answer Macro-F1 at 0.871.
- Masking an exploratory dictionary of refusal, authorization, and completion phrases changes the score only from 0.880 to 0.877.
- Across 12 cluster counts and random settings, full performance ranges from 0.815 to 0.835 and final-answer performance from 0.870 to 0.880.
- A classifier using only record-structure features, such as event counts and role transitions, achieves 0.803 Macro-F1.
- On the 750 records involving an explicit risk source, final-answer-only reaches 0.940 and full reaches 0.831.

These findings show substantial local reference-label signal. They do **not** show that ATBench labels are wrong, that train-test leakage occurred, or that full trajectories lack real-world value. Final answers may faithfully summarize prior behavior, and the full records are about 53 times longer than final answers, which may disadvantage a sparse lexical model. Because the data and diagnostics have already been inspected, all current findings remain labeled preliminary and exploratory.

## Proposed Validation

### Frozen Compact Safety Model

The primary model will be [Qwen3Guard-Gen-0.6B](https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B), with approximately 600 million learned parameters. [StepGuard-4B](https://huggingface.co/ninty-seven/StepGuard) may be added if memory and runtime permit. “Frozen” means that neither model will be trained or fine-tuned on ATBench.

A development pilot of at most 50 records will fix the prompt, truncation rule, decoding settings, and output parser; those records will then be excluded from the main guard result. All views will use the same settings. The analysis will record input token counts, truncation, parsing failures, latency, and peak GPU memory. A token is a small unit of text used by the model, and the **context window** is the maximum number of tokens it can read at once.

The main comparison is final-answer-only versus full. The provisional practical criterion is that final-answer performance no more than 0.03 Macro-F1 below full represents comparable label recoverability. The actual difference and uncertainty interval will be reported regardless of whether this criterion is met.

### Action Preserving Counterfactuals

The project will select 120 ATBench source trajectories, ideally 60 safe and 60 unsafe. Every tool call, parameter, result, and event order will remain unchanged. Each source will receive two rewritten final answers:

1. **Meaning-preserving rewrite:** changes style, length, politeness, or wording while preserving the actors, objects, permissions, actions, and outcome.
2. **Action-report conflict rewrite:** minimizes, exaggerates, or incorrectly describes the action that actually occurred.

Each source therefore forms a three-version set: the original and two rewrites. This produces 360 text versions and 240 original-to-rewrite paired comparisons. Reference judgments will follow a written action-based rule centered on what the agent did and whether it was authorized. Every rewrite will document the exact change and receive a delayed blind re-review by the researcher.

The main outcomes are verdict-flip rate, change in risk score, and the difference between full and final-only accuracy when the final report conflicts with the trace. Meaning-preserving and conflict rewrites will be analyzed separately.

### External Replication and Error Analysis

The same frozen guard will be evaluated on R-Judge using full, actions-only, and last-action-only views. Approximately 80–100 errors will then be manually categorized, including cases where full is correct and final is wrong, the reverse pattern, unsafe false negatives, safe false positives, counterfactual flips, and output-parsing failures.

## Evaluation and Limitations

Macro-F1 is the primary metric. The project will also report AUROC, unsafe FNR, safe FPR, balanced accuracy, parsing failures, token counts, latency, and peak memory. **Balanced accuracy** is the average recall of the safe and unsafe classes. Paired or group-level bootstrap intervals will quantify uncertainty without treating related examples as independent.

The main limitations are that ATBench has no untouched public confirmation set; proxy clusters cannot recover hidden task-family identifiers; long trajectories may be truncated or represented less effectively; human rewrites may differ from natural model outputs; one compact guard cannot represent all model families; and static public benchmarks cannot estimate real-world incident rates.

The project analyzes public static records only. It will not execute tool calls, connect real email or payment accounts, or create a new operational attack chain.

## Ten Week Plan

| Weeks | Main work |
|---|---|
| 1–2 | Freeze data, views, prompts, metrics, and analysis plan; complete the guard pilot. |
| 3–4 | Run frozen-model experiments on ATBench and R-Judge. |
| 5–6 | Construct, blind-review, and evaluate 120 counterfactual three-version sets. |
| 7–8 | Complete statistical analysis and review 80–100 representative errors. |
| 9–10 | Package code, Colab notebook, paper, audit checklist, and presentation. |

## Expected Contributions and Deliverables

The conceptual contribution is to separate three questions: whether a model can predict benchmark labels, whether it understands the multi-step process, and whether it can detect hazards in deployment. This project directly studies the first, provides diagnostic evidence about the second, and does not treat benchmark performance as a guarantee of the third.

The project will deliver:

1. A capstone paper that separates preliminary findings from the new validation study.
2. Reproducible CPU and Colab-compatible code and a demonstration notebook.
3. A documented set of 120 action-preserving counterfactual three-version groups.
4. Per-example predictions, grouping records, and uncertainty analyses.
5. A reporting checklist for future trajectory-safety benchmarks.

Success does not require final-answer-only to outperform full. If the frozen guard genuinely benefits from the complete trace or remains stable under controlled rewrites, that result will narrow the preliminary finding and provide stronger evidence for ATBench’s trajectory-level validity.

## References

1. Li et al. [ATBench: A Diverse and Realistic Trajectory Benchmark for Long-Horizon Agent Safety](https://arxiv.org/abs/2604.02022), 2026.
2. Yuan et al. [R-Judge: Benchmarking Safety Risk Awareness for LLM Agents](https://aclanthology.org/2024.findings-emnlp.79/), 2024.
3. Luo et al. [AgentAuditor: Human-Level Safety and Security Evaluation for LLM Agents](https://arxiv.org/abs/2506.00641), 2025.
4. Chen et al. [TraceSafe: A Systematic Assessment of LLM Guardrails on Multi-Step Tool-Calling Trajectories](https://arxiv.org/abs/2604.07223), 2026.
5. Mohammadi. [trajectory-judge: What Outcome-Only LLM Judges Miss on Agent Trajectories](https://arxiv.org/abs/2609.00038), 2026.
6. Gururangan et al. [Annotation Artifacts in Natural Language Inference Data](https://aclanthology.org/N18-2017/), 2018.
7. Poliak et al. [Hypothesis Only Baselines in Natural Language Inference](https://aclanthology.org/S18-2023/), 2018.
8. Feng et al. [Misleading Failures of Partial-Input Baselines](https://aclanthology.org/P19-1551/), 2019.
