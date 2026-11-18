"""Reproduce the single-operator policy migration experiment or its two-message demo."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3

import mail_policy_runtime as runtime
from mail_policy_search import compile_policy
from plan_mail_policy_change import plan_change
from run_declaration_holdout import (
    ROOT, ROLES, LocalMailbox, check_freeze, commit_delivery, commit_grant, counters,
    fact_template, gold, init_ledger, replay_witness, tally,
)

# Length-only templates from the pinned send_email and gog gmail send calls.
TEMPLATES = {"atbench:row718:call5": 16, "atbench:row600:call10": 810,
             "claw:row160:call5": 21, "claw:row224:call6": 1097}
FIXED = {r: ["recipient.tag", "body.raw", "attachment_bytes.item_tags", "attachment_names.raw",
             "attachment_sizes.list"] for r in ROLES}
CAPS_PATH = ROOT / "reports/policy_transfer/capabilities.json"


def policy_family():
    """All six attachment comparison combinations and the two registered controls."""
    comparisons = [(field, op) for field in ("items", "names", "sizes") for op in ("eq", "subset")]
    comparisons.extend([("body", "eq"), ("count", "le")])
    return {field + "_" + op: {"all": [{"op": "eq", "field": "recipient"}, {"op": op, "field": field}]}
            for field, op in comparisons}


def case_family():
    a, b = ("a.bin", "X"), ("b.bin", "YZ")
    base = (a, b, a)
    empty = ("empty.bin", "")
    cases = [
        ("equal", base, base),
        ("body_change", base, base),
        ("other_recipient", base, base),
        ("reordered", base, (b, a, a)),
        ("proper_selection", base, (a, b)),
        ("same_size_substitution", base, (("a.bin", "Q"), b, a)),
        ("different_size_substitution", base, (("a.bin", "QQQ"), b, a)),
        ("renamed", base, (("renamed.bin", "X"), b, a)),
        ("extra_copy", base, (*base, a)),
        ("multiplicity_change", base, (a, b, b)),
        ("crossed_names", base, (("b.bin", "X"), ("a.bin", "YZ"), a)),
        ("empty_selection", base, ()),
        ("extra_empty_file", (), (empty,)),
        ("no_grant", None, (a,)),
        ("both_empty", (), ()),
        ("equal_empty_file", (empty,), (empty,)),
    ]
    for name, granted, delivered in cases:
        approval = None if granted is None else {"recipient": "R0", "body": "B0", "attachments": granted}
        delivery = {"recipient": "R1" if name == "other_recipient" else "R0",
                    "body": "B1" if name == "body_change" else "B0", "attachments": delivered}
        yield name, approval, delivery


def expected_results(summary):
    return {k: summary[k] for k in ("correct", "unknown", "false_authorized", "false_unauthorized")}


def collect_scores(policies, schemas, comparison_key, keys):
    """Sign each approval before dispatch; use persisted raw MIME to score all candidate field sets."""
    profiles = {name: {"compiled": schemas[name], "fixed_common": FIXED,
                       **{old: schema for old, schema in schemas.items() if old != name}}
                for name in policies}
    stats = {name: {profile: counters() for profile in choices} for name, choices in profiles.items()}
    truth_counts = {name: Counter() for name in policies}
    by_case = {}
    accepted = 0
    with LocalMailbox() as box, closing(sqlite3.connect(":memory:")) as db:
        init_ledger(db)
        for template_idx, length in enumerate(TEMPLATES.values()):
            for case_idx, (case, approved, submitted) in enumerate(case_family()):
                attempt = f"solo-{template_idx}-{case_idx:02d}"
                grant = commit_grant(db, attempt, fact_template(approved, length))
                approvals = {}
                for name, policy in policies.items():
                    for profile, config in profiles[name].items():
                        approvals[name, profile] = runtime.issue(policy, config["approval"], "approval", attempt,
                                                                 grant, comparison_key, keys["approval"])
                observed, mime = commit_delivery(box, attempt, fact_template(submitted, length))
                accepted += 1
                for name, policy in policies.items():
                    truth = gold(policy, grant, mime)
                    truth_counts[name][truth] += 1
                    case_results = by_case.setdefault(case, {})
                    if case_results.setdefault(name, truth) != truth:
                        raise ValueError(f"Body length changed the truth for {name}/{case}")
                    for profile, config in profiles[name].items():
                        records = {"approval": approvals[name, profile],
                                   "delivery": runtime.issue(policy, config["delivery"], "delivery", attempt,
                                                             observed, comparison_key, keys["delivery"])}
                        actual = runtime.verify(policy, config, attempt, records, keys)
                        tally(stats[name][profile], actual, truth, records)
    return accepted, stats, truth_counts, by_case


def run():
    frozen = check_freeze()
    policies = policy_family()
    caps = json.loads(CAPS_PATH.read_text())
    schemas = {name: compile_policy(policy, caps)["selected"] for name, policy in policies.items()}
    if any(config is None for config in schemas.values()):
        raise ValueError("A registered rule is infeasible under the full menu")
    keys = {r: secrets.token_bytes(32) for r in ROLES}
    comparison_key = secrets.token_bytes(32)
    accepted, stats, truth_counts, by_case = collect_scores(policies, schemas, comparison_key, keys)
    changes = {}
    witnesses = {}
    for target, policy in policies.items():
        for previous, config in schemas.items():
            if target == previous:
                continue
            plan = plan_change(config, policy, caps)
            planned = {r: sorted((set(config[r]) - set(plan["retire"][r])) | set(plan["add"][r])) for r in ROLES}
            if planned != schemas[target]:
                raise ValueError("Applying a migration does not produce the measured target configuration")
            pair = plan["old_fields_witness"]
            witness_id, replay = None, None
            if pair:
                witness_id = next((k for k, p in witnesses.items() if p == pair), None)
                if witness_id is None:
                    witness_id = f"W{len(witnesses) + 1:02d}"
                    witnesses[witness_id] = pair
                # The same raw pair may justify different missing fields; verify each role configuration.
                replay = replay_witness(policy, config, pair, comparison_key, keys)
            changes[f"{previous}->{target}"] = {
                "action": plan["action"], "basis": plan["old_fields_basis"],
                "add": plan["add"], "retire": plan["retire"], "witness_id": witness_id, "smtp": replay,
                "using_previous_fields": expected_results(stats[target][previous]),
                "using_planned_fields": expected_results(stats[target]["compiled"]),
            }
    results = {name: {"declaration": policy, "fields": schemas[name], "truth": truth_counts[name],
                      "compiled": stats[name]["compiled"], "fixed_common": stats[name]["fixed_common"]}
               for name, policy in policies.items()}
    summary = {
        "policy_verdicts": accepted * len(policies),
        "migration_kinds": dict(Counter(change["action"] for change in changes.values())),
        "confirmed_migration_witnesses": sum(1 for change in changes.values()
                                             if change["smtp"] and change["smtp"]["reproduced"]),
        "witness_smtp_acceptances": sum(change["smtp"]["smtp_acceptances"] for change in changes.values()
                                        if change["smtp"]),
        "distinct_witness_pairs": len(witnesses),
    }
    for profile in ("fixed_common", "compiled"):
        profile_rows = [results[name][profile] for name in policies]
        summary[profile] = {key: sum(row[key] for row in profile_rows)
                            for key in ("correct", "false_authorized", "false_unauthorized", "unknown", "receipt_bytes")}
        summary[profile]["raw_bytes"] = {
            dimension: sum(row["raw_bytes"][dimension] for row in profile_rows)
            for dimension in ("recipient", "body", "names", "content")
        }
    return {"summary": summary, "freeze": frozen["prospective_tag"], "templates": TEMPLATES, "main_smtp_acceptances": accepted,
            "fixed_fields": FIXED, "case_labels_by_policy": by_case, "policies": results,
            "migrations": changes, "distinct_witness_world_pairs": witnesses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/solo_mail_audit/results.json")
    parser.add_argument("--demo", nargs=2, metavar=("FROM", "TO"), choices=tuple(policy_family()),
                        help="Plan a single registered policy change and replay its evidence gap")
    args = parser.parse_args()
    if args.demo:
        check_freeze()
        policies = policy_family()
        caps = json.loads(CAPS_PATH.read_text())
        previous, target = args.demo
        old = compile_policy(policies[previous], caps)["selected"]
        plan = plan_change(old, policies[target], caps)
        keys = {r: secrets.token_bytes(32) for r in ROLES}
        plan["smtp"] = replay_witness(policies[target], old, plan["old_fields_witness"], secrets.token_bytes(32), keys)
        print(json.dumps(plan, indent=2))
        return
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    print(f"{result['main_smtp_acceptances']} SMTP acceptances, {len(result['policies'])} rules, "
          f"{len(result['migrations'])} directed changes. Results in {args.out}")


if __name__ == "__main__":
    main()
