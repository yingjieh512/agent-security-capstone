"""Exercise live, version-pinned policy migrations against a local synthetic SMTP inbox.

Run from repository root with PYTHONPATH=src. This demo starts fresh temporary
databases and emits only schema names, versions and aggregate verification facts.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory

import mail_audit_workspace as workspace
from run_declaration_holdout import (
    ROOT, ROLES, LocalMailbox, check_freeze, commit_delivery, commit_grant, gold, grant_snapshot, init_ledger,
)
from run_solo_mail_audit import CAPS_PATH


def run_demo():
    check_freeze()
    policy_dir = ROOT / "examples/mail_audit"
    policies = {name: json.loads((policy_dir / f"{name}.json").read_text())
                for name in ("full_packet", "approved_subset", "count_limit")}
    caps = json.loads(CAPS_PATH.read_text())
    comp = secrets.token_bytes(32)
    keys = {role: secrets.token_bytes(32) for role in ROLES}
    grant = {"recipient": "desk@demo.invalid", "body": "Dispatch approval",
             "attachments": [("alpha.bin", b"A"), ("beta.bin", b"B")]}
    partial = dict(grant, body="Synthetic dispatch", attachments=[("alpha.bin", b"A")])
    count_only = dict(partial, attachments=[("different.bin", b"C")])
    outcomes = {}
    names_by_version = {}
    with TemporaryDirectory(prefix="mail-policy-demo-") as workdir:
        db = Path(workdir) / "audit.sqlite"
        with closing(sqlite3.connect(":memory:")) as ledger, LocalMailbox() as box:
            init_ledger(ledger)

            def activate(name, expected):
                result = workspace.activate(db, policies[name], caps, expect_version=expected)
                version = result["version"]
                if not result["feasible"] or version != expected + 1:
                    raise RuntimeError(f"Unexpected activation of {name}: {result}")
                names_by_version[version] = name
                return version

            def start(attempt, fact):
                snapshot = commit_grant(ledger, attempt, fact)
                return workspace.begin_attempt(db, attempt, snapshot, comp, keys["approval"])

            def submit(attempt, message, expected_version, expected_label):
                observed, mime = commit_delivery(box, attempt, message)
                pinned = workspace.finish_attempt(db, attempt, observed, comp, keys["delivery"])
                expected = gold(policies[names_by_version[expected_version]], grant_snapshot(ledger, attempt), mime)
                offline = workspace.audit_attempt(db, attempt, keys)
                if (pinned != expected_version or offline["version"] != pinned or
                        offline["decision"] != expected or expected != expected_label):
                    raise RuntimeError(f"Reference and signed receipts disagree on {attempt}")
                saved = workspace.read_attempt(db, attempt)
                outcomes[attempt] = {"version": pinned, "policy": names_by_version[pinned],
                                     "decision": offline["decision"], "persisted_mime_oracle": expected,
                                     "recorded_fields": {r: sorted(saved["records"][r]["fields"]) for r in ROLES}}

            first = activate("full_packet", 0)
            if start("across_the_change", grant) != first:
                raise AssertionError("Approval was not pinned to the initial policy")
            pending = workspace.audit_attempt(db, "across_the_change", keys)["decision"]
            second = activate("approved_subset", first)
            submit("across_the_change", partial, first, "unauthorized")
            start("after_the_change", grant)
            submit("after_the_change", partial, second, "authorized")

            limited = {r: list(fields) for r, fields in caps.items()}
            limited["delivery"].remove("attachment_names.raw")
            needs_names = {"all": [{"op": "eq", "field": "recipient"}, {"op": "subset", "field": "names"}]}
            rejected = workspace.activate(db, needs_names, limited, expect_version=second)
            after_rejection = workspace.status(db)["version"]
            if rejected["feasible"] or after_rejection != second:
                raise AssertionError("An uncheckable rule displaced the working revision")
            third = activate("count_limit", second)
            start("count_limited", grant)
            submit("count_limited", count_only, third, "authorized")
            fourth = activate("full_packet", third)
            start("rollback", grant)
            submit("rollback", partial, fourth, "unauthorized")
            same_revision = workspace.activate(db, policies["full_packet"], caps, expect_version=fourth)["version"]
            if same_revision != fourth or pending != "unknown":
                raise AssertionError("Idempotent activation or missing evidence check failed")

        # The mailbox and reference ledger are now closed. Only the minimized receipt
        # database and the source authentication keys are available to these checks.
        for attempt, entry in outcomes.items():
            historical = workspace.audit_attempt(db, attempt, keys)
            if historical["version"] != entry["version"] or historical["decision"] != entry["decision"]:
                raise AssertionError(f"Historical audit differs on {attempt}")
            entry["verified_after_mailbox_shutdown"] = True
        wrong_key = {**keys, "delivery": secrets.token_bytes(32)}
        wrong_key_decision = workspace.audit_attempt(db, "after_the_change", wrong_key)["decision"]
        if wrong_key_decision != "unknown":
            raise AssertionError("Wrong source authenticator was accepted")
    return {"smtp_acceptances": len(outcomes), "attempts": outcomes,
            "pending_before_smtp": pending, "infeasible_activation_refused": True,
            "version_after_refusal": after_rejection, "repeated_activation_version": same_revision,
            "wrong_delivery_key": wrong_key_decision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/mail_capstone/workspace_demo.json")
    args = parser.parse_args()
    result = run_demo()
    args.out.parent.mkdir(exist_ok=True, parents=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print("Attempt                 Revision   Signed verdict   Persisted MIME")
    for name, row in result["attempts"].items():
        print(f"{name:<24}{row['version']:<11}{row['decision']:<17}{row['persisted_mime_oracle']}")
    print(f"Historical checks passed after closing the mailbox. Evidence summary: {args.out}")


if __name__ == "__main__":
    main()
