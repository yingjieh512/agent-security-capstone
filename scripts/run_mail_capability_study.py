"""Compile and score eight frozen mail policies after single-source capability deletions.

Each run reuses one 64-message SMTP corpus. Identical configurations for the same
policy share measured receipts. Witnesses use separate SMTP sends for each
infeasible cell, even when its ordered pair of model worlds appeared elsewhere.
"""
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
from run_declaration_holdout import (ROOT, ROLES, LocalMailbox, check_freeze, commit_delivery,
                                     commit_grant, counters, fact_template, gold, init_ledger,
                                     replay_witness, tally)
from run_solo_mail_audit import CAPS_PATH, TEMPLATES, case_family, policy_family


CATEGORIES = ("unchanged", "fallback_without_new_raw", "fallback_with_new_raw",
              "infeasible_with_collision", "infeasible_without_collision")
VERDICTS = ("correct", "unknown", "false_authorized", "false_unauthorized")


def single_deletions(capabilities):
    for role in ROLES:
        for field in capabilities[role]:
            restricted = {r: list(capabilities[r]) for r in ROLES}
            restricted[role].remove(field)
            yield role, field, restricted


def outcome_category(control, selected, witness):
    if selected is None:
        return "infeasible_with_collision" if witness is not None else "infeasible_without_collision"
    if all(set(selected[r]) == set(control[r]) for r in ROLES):
        return "unchanged"
    added = {field for r in ROLES for field in set(selected[r]) - set(control[r])}
    if any(field.endswith(".raw") for field in added):
        return "fallback_with_new_raw"
    return "fallback_without_new_raw"


def compile_variants(policies, caps, comparison_key, keys):
    experiments = {}
    witnesses = {}
    for name, policy in policies.items():
        full = compile_policy(policy, caps)
        baseline = full["selected"]
        if baseline is None:
            raise ValueError(f"Full capabilities cannot implement registered policy {name}")
        schemas = {"control": {"fields": baseline}}
        omissions = {}
        for role, field, restricted in single_deletions(caps):
            plan = compile_policy(policy, restricted)
            config, witness = plan["selected"], plan["witness"]
            category = outcome_category(baseline, config, witness)
            row = {"outcome": category, "compiler_basis": plan["basis"], "schema": None}
            if config is not None:
                if any(set(config[r]) - set(restricted[r]) for r in ROLES):
                    raise ValueError("Compiler selected an unavailable source field")
                ref = next((ref for ref, item in schemas.items() if item["fields"] == config), None)
                if ref is None:
                    ref = f"alternate{len(schemas)}"
                    schemas[ref] = {"fields": config}
                row["schema"] = ref
            elif witness is not None:
                witness_id = next((ref for ref, pair in witnesses.items() if pair == witness), None)
                if witness_id is None:
                    witness_id = f"W{len(witnesses) + 1:02d}"
                    witnesses[witness_id] = witness
                row["witness"] = witness_id
                row["witness_replay"] = replay_witness(policy, restricted, witness, comparison_key, keys)
            else:
                row["full_menu_audit"] = plan["full_menu_audit"]
            omissions[f"{role}/{field}"] = row
        experiments[name] = {
            "policy": policy, "control_worlds_checked": full["runtime_worlds_checked"],
            "control": "control", "schemas": schemas, "single_deletions": omissions,
        }
    return experiments, witnesses


def measure_shared_corpus(policies, comparison_key, keys):
    for experiment in policies.values():
        experiment["corpus_truth"] = Counter()
        for schema in experiment["schemas"].values():
            schema["measured"] = counters()
    accepted = 0
    with LocalMailbox() as box, closing(sqlite3.connect(":memory:")) as db:
        init_ledger(db)
        for template_index, length in enumerate(TEMPLATES.values()):
            for index, (_, approved, submitted) in enumerate(case_family()):
                # Reusing the solo experiment's attempt lengths also makes wire bytes comparable.
                attempt = f"solo-{template_index}-{index:02d}"
                grant = commit_grant(db, attempt, fact_template(approved, length))
                approvals = {}
                for name, experiment in policies.items():
                    for ref, schema in experiment["schemas"].items():
                        approvals[name, ref] = runtime.issue(experiment["policy"], schema["fields"]["approval"],
                                                             "approval", attempt, grant, comparison_key, keys["approval"])
                observed, mime = commit_delivery(box, attempt, fact_template(submitted, length))
                accepted += 1
                for name, experiment in policies.items():
                    policy = experiment["policy"]
                    truth = gold(policy, grant, mime)
                    experiment["corpus_truth"][truth] += 1
                    for ref, schema in experiment["schemas"].items():
                        fields = schema["fields"]
                        delivery = runtime.issue(policy, fields["delivery"], "delivery", attempt, observed,
                                                 comparison_key, keys["delivery"])
                        records = {"approval": approvals[name, ref], "delivery": delivery}
                        actual = runtime.verify(policy, fields, attempt, records, keys)
                        tally(schema["measured"], actual, truth, records)
    return accepted


def summarize(policies, accepted, witnesses):
    outcomes = Counter()
    restricted_verdicts = Counter()
    control_verdicts = Counter()
    replay_mails = 0
    confirmed = 0
    schemas_scored = 0
    for experiment in policies.values():
        schemas = experiment["schemas"]
        control = schemas[experiment["control"]]["measured"]
        schemas_scored += len(schemas)
        control_verdicts.update({k: control[k] for k in VERDICTS})
        for schema in schemas.values():
            measured = schema["measured"]
            if sum(measured[k] for k in VERDICTS) != accepted:
                raise ValueError("Missing or duplicated corpus decisions")
            schema["delta_from_control"] = {
                "receipt_bytes": measured["receipt_bytes"] - control["receipt_bytes"],
                "raw_bytes": {k: v - control["raw_bytes"][k] for k, v in measured["raw_bytes"].items()},
            }
        for row in experiment["single_deletions"].values():
            outcomes[row["outcome"]] += 1
            if row["schema"] is not None:
                measured = schemas[row["schema"]]["measured"]
                restricted_verdicts.update({k: measured[k] for k in VERDICTS})
            if "witness_replay" in row:
                replay = row["witness_replay"]
                replay_mails += replay["smtp_acceptances"]
                confirmed += int(replay["reproduced"])
    feasible = sum(outcomes[k] for k in CATEGORIES[:3])
    return {
        "full_menu_controls": len(policies), "restricted_settings": sum(outcomes.values()),
        "restricted_feasible": feasible, "restricted_outcomes": {k: outcomes[k] for k in CATEGORIES},
        "main_smtp_acceptances": accepted, "distinct_policy_schema_combinations_scored": schemas_scored,
        "control_policy_verdicts": dict(control_verdicts),
        "restricted_feasible_setting_verdicts": dict(restricted_verdicts),
        "restricted_feasible_setting_verdict_denominator": feasible * accepted,
        "distinct_witness_world_pairs": len(witnesses), "confirmed_witness_replays": confirmed,
        "witness_smtp_acceptances": replay_mails,
    }


def run():
    manifest = check_freeze()
    policies = policy_family()
    capabilities = json.loads(CAPS_PATH.read_text())
    comparison_key = secrets.token_bytes(32)
    keys = {role: secrets.token_bytes(32) for role in ROLES}
    experiments, witnesses = compile_variants(policies, capabilities, comparison_key, keys)
    accepted = measure_shared_corpus(experiments, comparison_key, keys)
    return {
        "freeze": manifest["prospective_tag"], "full_capabilities": capabilities, "templates": TEMPLATES,
        "units": {
            "omission": "Role/field key removes just that field on that role from full_capabilities.",
            "scores": "Per policy, each same selected schema reuses its measured row on the same corpus.",
            "unsupported": "No generated receipts or footprint assigned to an infeasible schema.",
            "delta": "Selected schema minus the same policy's full-capability control, across the 64 messages.",
            "witness": "Deduplicated ordered (authorized world, unauthorized world) with literal fixture values.",
        },
        "summary": summarize(experiments, accepted, witnesses), "policies": experiments, "witnesses": witnesses,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/solo_mail_audit/capability_results.json")
    args = parser.parse_args()
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
