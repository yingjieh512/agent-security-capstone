"""Remove one capability from each role in turn and replay any impossibility witness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets

from mail_policy_search import compile_policy
from run_declaration_holdout import ROLES, check_freeze, replay_witness


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--capabilities", required=True, type=Path)
    parser.add_argument("--field", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    check_freeze()
    policy = json.loads(args.policy.read_text())
    caps = json.loads(args.capabilities.read_text())
    rows = {}
    for role in ROLES:
        limited = {r: list(caps[r]) for r in ROLES}
        limited[role].remove(args.field)
        search = compile_policy(policy, limited)
        keys = {r: secrets.token_bytes(32) for r in ROLES}
        replay = replay_witness(policy, limited, search["witness"], secrets.token_bytes(32), keys)
        rows[role] = {"capabilities": limited, "compiled": search, "smtp": replay}
    args.out.parent.mkdir(exist_ok=True, parents=True)
    args.out.write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
