"""Plan evidence collection for future sends after a mail authorization rule changes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets

from mail_policy_search import FIELDS, ROLES, audit_config, compile_policy


def plan_change(current_fields, target_policy, capabilities):
    """Plan against the fields the two sources can actually emit under the new rule."""
    if not isinstance(current_fields, dict) or set(current_fields) != set(ROLES):
        raise ValueError("Current configuration must list both approval and delivery")
    for names in current_fields.values():
        if (not isinstance(names, (tuple, list)) or not all(isinstance(f, str) and f in FIELDS for f in names)
                or len(set(names)) != len(names)):
            raise ValueError("Invalid or duplicate field in current configuration")
    target = compile_policy(target_policy, capabilities)
    usable = {role: sorted(set(current_fields[role]) & set(capabilities[role])) for role in ROLES}
    audit = audit_config(target_policy, usable)
    result = {
        "current_fields": current_fields, "available_current_fields": usable,
        "old_fields_sufficient": audit["sufficient"], "old_fields_basis": audit["basis"],
        "old_fields_witness": audit["witness"], "target_feasible": target["feasible"],
        "target_fields": target["selected"], "target_basis": target["basis"],
        "target_witness": target.get("witness"), "finite_worlds": audit["domain"]["worlds"],
    }
    if target["selected"] is None:
        result.update(action="unavailable", add=None, retire=None)
        return result
    fields = target["selected"]
    add = {r: sorted(set(fields[r]) - set(current_fields[r])) for r in ROLES}
    retire = {r: sorted(set(current_fields[r]) - set(fields[r])) for r in ROLES}
    if not audit["sufficient"]:
        action = "replace_insufficient_fields"
    elif not any(add.values()) and any(retire.values()):
        action = "drop_surplus_fields"
    elif any(add.values()) or any(retire.values()):
        action = "switch_sufficient_projection"
    else:
        action = "keep_fields"
    result.update(action=action, add=add, retire=retire)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    old = parser.add_mutually_exclusive_group(required=True)
    old.add_argument("--from-policy", type=Path, help="Prior JSON declaration, using the compiled configuration")
    old.add_argument("--current-fields", type=Path, help="An existing approval/delivery field mapping")
    parser.add_argument("--to-policy", required=True, type=Path)
    parser.add_argument("--capabilities", required=True, type=Path)
    parser.add_argument("--replay", action="store_true", help="Verify any collision by sending synthetic local test mail")
    args = parser.parse_args()
    caps = json.loads(args.capabilities.read_text())
    target = json.loads(args.to_policy.read_text())
    if args.current_fields:
        current = json.loads(args.current_fields.read_text())
    else:
        current = compile_policy(json.loads(args.from_policy.read_text()), caps)["selected"]
        if current is None:
            parser.error("Prior policy is infeasible under this menu; supply the actual --current-fields")
    try:
        result = plan_change(current, target, caps)
    except ValueError as error:
        parser.error(str(error))
    if args.replay:
        from run_declaration_holdout import replay_witness
        if not result["target_feasible"]:
            schema, witness = caps, result["target_witness"]
        else:
            schema, witness = result["available_current_fields"], result["old_fields_witness"]
        result["local_replay"] = replay_witness(target, schema, witness, secrets.token_bytes(32),
                                                {r: secrets.token_bytes(32) for r in ROLES})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
