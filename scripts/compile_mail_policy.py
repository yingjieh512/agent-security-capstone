"""Compile a JSON mail policy using only the capabilities offered by its two sources."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mail_policy_search import audit_config, compile_policy, repair_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--inspect-config", type=Path,
                        help="Audit an existing role-to-fields mapping, find additions and prune within it")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    capabilities = json.loads(args.capabilities.read_text())
    result = {"compiled": compile_policy(policy, capabilities)}
    if args.inspect_config:
        config = json.loads(args.inspect_config.read_text())
        result.update(audit=audit_config(policy, config), repair=repair_config(policy, config, capabilities),
                      prune=compile_policy(policy, config))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
