"""Out-of-trajectory evaluation of selective log-field reads on the pinned send-call cohort.

Estimate logical reads for a literal corroboration check. All three sources are local log
fields; the predicate neither verifies authorization nor measures external delivery.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import permutations
import json
from pathlib import Path
import re

import numpy as np
from evidence_pilot_data import data_manifest, load_cases

SOURCES = ("args", "user", "result")
ORDERS = tuple(permutations(SOURCES))
# A simple ASCII email grammar and a contiguous string of 10--15 digits. Preserve
# literal case and the '+' prefix. Unsupported spelling/format is out of scope.
EMAIL = re.compile(r"(?<![\w.+%@-])[a-zA-Z0-9_.%+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}(?![\w@-]|\.[\w-])", re.ASCII)
PHONE = re.compile(r"(?<![\w.+@-])\+?[0-9]{10,15}(?![\w@-]|\.[\w-])", re.ASCII)
# Post-hoc second grammar. All 28 sendMessage target strings use one of these
# two literal namespaces. A bare ID, unqualified name, and equivalent aliases
# do not match their qualified counterpart.
QUALIFIED_ID = re.compile(
    r"(?<![\w:/@.-])(?:channel|user):[A-Za-z0-9_][A-Za-z0-9_-]*(?![\w@-]|\.[\w-])",
    re.ASCII,
)
MIN_BRANCH = 4


def tokens(texts, grammar="contacts"):
    values = set()
    for text in texts:
        values.update(("email", m.group()) for m in EMAIL.finditer(text))
        # Skip any phone-looking substring inside an already recognized email.
        remainder = EMAIL.sub(" ", text)
        values.update(("digits", m.group()) for m in PHONE.finditer(remainder))
        if grammar == "qualified":
            values.update(("qualified", m.group()) for m in QUALIFIED_ID.finditer(text))
    return frozenset(values)


@dataclass
class Case:
    key: str
    trajectory: str
    tool: str
    fields: dict


def read_cases(grammar="contacts"):
    cases = []

    def observe(*, row, prior_user_texts, result_texts, primary_to_fields, **unused):
        fields = {name: tokens(parts, grammar) for name, parts in
                  zip(SOURCES, (primary_to_fields, prior_user_texts, result_texts))}
        cases.append(Case(row["call_key"], row["trajectory_id"], row["tool"], fields))

    load_cases(observer=observe)
    return cases


def execute(row, order):
    common = None
    for reads, source in enumerate(order, 1):
        value = row.fields[source]
        common = value if common is None else common & value
        if not common:
            return False, reads
    return True, len(order)


def fixed(rows, choices=ORDERS):
    return min(choices, key=lambda order: sum(execute(row, order)[1] for row in rows))


def signature(observed):
    # Only information from the already purchased field. Individual identifier
    # values cannot be used as features. Empty fields terminate before routing.
    return (min(len(observed), 2), tuple(sorted({kind for kind, _ in observed})))


def train_adaptive(rows):
    policies = []
    for first in SOURCES:
        choices = tuple(order for order in ORDERS if order[0] == first)
        fallback = fixed(rows, choices)
        branches = defaultdict(list)
        for row in rows:
            branches[signature(row.fields[first])].append(row)
        routes = {key: fixed(group, choices) for key, group in branches.items()
                  if key[0] and len(group) >= MIN_BRANCH}
        cost = sum(execute(row, routes.get(signature(row.fields[first]), fallback))[1]
                   for row in rows)
        policies.append((cost, fallback, routes))
    # SOURCES order breaks ties, identical to the fixed-policy search.
    return min(policies, key=lambda entry: entry[0])[1:]


def paired_interval(records):
    # Conditional on the fitted OOF predictions, resample whole trajectories.
    grouped = defaultdict(list)
    for row in records:
        grouped[row["trajectory"]].append(row["fixed_reads"] - row["adaptive_reads"])
    totals = np.array([sum(v) for v in grouped.values()])
    sizes = np.array([len(v) for v in grouped.values()])
    draw = np.random.default_rng(409).integers(0, len(totals), (5000, len(totals)))
    savings = totals[draw].sum(axis=1) / sizes[draw].sum(axis=1)
    return [float(v) for v in np.quantile(savings, [0.025, 0.975])]


def summarize(records):
    n = len(records)
    return {
        "calls": n, "trajectories": len({row["trajectory"] for row in records}),
        "corroborated": sum(row["full_reference"] for row in records),
        "full_reads": 3*n,
        **{k: sum(row[k] for row in records)
           for k in ("fixed_reads", "adaptive_reads", "oracle_fixed_reads", "clairvoyant_reads")},
        "paired_call_savings": dict(sorted(Counter(
            row["fixed_reads"]-row["adaptive_reads"] for row in records
        ).items())),
        "paired_mean_reads_saved_ci": paired_interval(records),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grammar", choices=("contacts", "qualified"), default="contacts",
                        help="Use primary ASCII contacts or the post-hoc superset adding channel:/user: IDs.")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is None:
        suffix = "_qualified" if args.grammar == "qualified" else ""
        args.output_dir = Path("outputs") / f"natural_recipient_queries{suffix}"
    cases = read_cases(args.grammar)
    groups = defaultdict(list)
    for case in cases:
        groups[case.tool].append(case)
    records = []
    per_tool = {}
    for tool, group in sorted(groups.items()):
        oracle = fixed(group)
        tool_records = []
        for row in group:
            train = [item for item in group if item.trajectory != row.trajectory]
            fixed_order = fixed(train)
            fallback, routes = train_adaptive(train)
            adaptive_order = routes.get(signature(row.fields[fallback[0]]), fallback)
            ref = bool(row.fields["args"] & row.fields["user"] & row.fields["result"])
            fixed_answer, fixed_reads = execute(row, fixed_order)
            adaptive_answer, adaptive_reads = execute(row, adaptive_order)
            oracle_answer, oracle_reads = execute(row, oracle)
            if not (ref == fixed_answer == adaptive_answer == oracle_answer):
                raise AssertionError("A query policy changed the observable predicate")
            tool_records.append({
                "call_key": row.key, "trajectory": row.trajectory, "tool": tool,
                "full_reference": ref, "fixed_reads": fixed_reads, "adaptive_reads": adaptive_reads,
                "oracle_fixed_reads": oracle_reads,
                "clairvoyant_reads": min(execute(row, order)[1] for order in ORDERS),
                "fixed_order": fixed_order,
                "adaptive_order": adaptive_order,
            })
        per_tool[tool] = {
            **summarize(tool_records), "hindsight_order": oracle,
            "recognized_any_by_source": {
                name: sum(bool(case.fields[name]) for case in group) for name in SOURCES
            },
        }
        records.extend(tool_records)
    summary = {
        "sources": data_manifest(), "overall": summarize(records), "per_tool": per_tool,
        "grammar": args.grammar,
        "predicate": "Nonempty intersection of recognized literals in primary target args, prior user messages and linked tool result text",
        "grammar_definition": ("Primary ASCII email and 10-15 digit strings with optional plus"
            if args.grammar == "contacts" else
            "Post-hoc sensitivity: primary grammar plus exact case-sensitive channel:ID and user:ID, where ID is ASCII alphanumeric/underscore/hyphen. "
            "Chosen after inspecting target namespace shapes, before running broad results. Identical extraction on each field; no alias resolution or removal of the prefix."),
        "cost": "One logical field open per source, irrespective of bytes. Stop immediately when intersection empty.",
        "reference": "Full inspection of three fields with same token grammar. Public log evidence only.",
        "split": "Leave all calls in held-out original trajectory out; policies fitted within tool",
        "oracles": "oracle_fixed_reads chooses one order per tool using the entire cohort; clairvoyant_reads chooses an order knowing every field of each call. Neither is deployable. The latter is a lower bound under the exact early-stop and three-field protocol.",
        "adaptive": f"Exhaustive first field, then type-set and cardinality (1 or 2+) routing; train-only, at least {MIN_BRANCH} training calls per branch, fallback fixed suffix otherwise.",
        "ci": "Paired trajectory-block bootstrap, 5000 draws, seed 409, fixed OOF predictions; inference conditional on chosen tools.",
        "limitations": "Email ASCII case-sensitive, phone-like contiguous digits 10-15 with optional plus (can match numeric IDs); no aliases, formatting normalization, cc/bcc, claims of consent, or authoritative receipt.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    (args.output_dir / "calls.jsonl").write_text(
        "".join(json.dumps(row)+"\n" for row in records)
    )
    print(json.dumps({"overall": summary["overall"], "per_tool": per_tool}, indent=2))


if __name__ == "__main__":
    main()
