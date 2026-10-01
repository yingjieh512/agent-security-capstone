# Capstone paper and reproduction guide

The paper is available as a compiled
[`trajectory_audit_capstone.pdf`](trajectory_audit_capstone.pdf) and as editable
[`trajectory_audit_capstone.tex`](trajectory_audit_capstone.tex) source. It follows
the two-column structure of the supplied sample capstone: problem and motivation,
related work, replication protocol, proposed audit, evaluation, threats to
validity, conclusion, and references.

## Reproduce the experiments

Create the environment once:

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev]'
```

Run the main ATBench experiment grid:

```bash
LOKY_MAX_CPU_COUNT=4 .venv/bin/trajectory-capstone \
  --input data/raw/atbench/test.json \
  --output-dir outputs/atbench-capstone
```

Run the risk-exposed subset and bidirectional release-transfer experiments:

```bash
LOKY_MAX_CPU_COUNT=4 .venv/bin/trajectory-audit-additions risk-exposed \
  --atbench data/raw/atbench/test.json \
  --output-dir outputs/risk-exposed

LOKY_MAX_CPU_COUNT=4 .venv/bin/trajectory-audit-additions cross-release \
  --atbench data/raw/atbench/test.json \
  --atbench500 data/raw/atbench500/test.json \
  --output-dir outputs/cross-release
```

Run the R-Judge external validation after placing the pinned official repository's
JSON files under `data/raw/rjudge/data/`:

```bash
LOKY_MAX_CPU_COUNT=4 .venv/bin/python scripts/run_rjudge_external.py \
  --data-dir data/raw/rjudge/data \
  --output-dir outputs/rjudge-external \
  --folds 5 --seed 42 --max-features 50000 --bootstrap-resamples 500
```

Validate the implementation:

```bash
LOKY_MAX_CPU_COUNT=4 .venv/bin/pytest -q
```

## Result map

| Paper evidence | Machine-readable source | Human-readable report |
|---|---|---|
| ATBench views, prefixes, cue removal, feature and cluster sensitivity | `outputs/atbench-capstone/capstone_results.json` | `outputs/atbench-capstone/experiment_summary.md` |
| Risk-exposed-only subset | `outputs/risk-exposed/risk_exposed_results.json` | `outputs/risk-exposed/risk_exposed_report.md` |
| ATBench ↔ ATBench500 transfer | `outputs/cross-release/cross_release_results.json` | `outputs/cross-release/cross_release_report.md` |
| R-Judge external validation | `outputs/rjudge-external/results.json` | `outputs/rjudge-external/report.md` |

ATBench is pinned to Hugging Face revision
`de862a3d5363aa3928f70e2228b275135597226c`; the main file SHA-256 is
`80c534b5f3517c872b528a2e6b64e34495206968edd184f4aed563d39f0cca09`.
ATBench500's SHA-256 is
`031285443c6b8ca64fc117bd995a4b4490c340467136506763aeed1b23c8f34c`.
The R-Judge experiment uses repository commit
`83ce301da3ad50dd8b397e772863f5411c3d3dc2` and records the upstream version
ambiguity in its report.

The scores are diagnostic out-of-fold analyses of public records. They are not
official leaderboard submissions. In particular, R-Judge has no final-answer
marker, so its `last_action_only` view is a last-action proxy rather than a terminal
answer.
