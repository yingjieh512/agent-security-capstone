"""Run a user-supplied synthetic authorization case on an isolated local SMTP inbox.

Case JSON contains policy_at_approval, grant (object or null), message, and
optionally policy_before_delivery. Facts use single .invalid recipient, body
and attachments with name and either UTF-8 content or base64 content_b64.
Only the verdict, field names and revision IDs leave the temporary workspace.
"""
from __future__ import annotations

import argparse
from base64 import b64decode
from contextlib import closing
import json
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory

import mail_audit_workspace as workspace
from attachment_mail_backend import ADDRESS
from run_declaration_holdout import (
    ROLES, LocalMailbox, check_freeze, commit_grant, commit_delivery, gold, grant_snapshot, init_ledger,
)
from run_solo_mail_audit import CAPS_PATH


def parse_fact(value):
    if not isinstance(value, dict) or set(value) != {"recipient", "body", "attachments"}:
        raise ValueError("Expected recipient, body and attachments")
    if not isinstance(value["recipient"], str) or ADDRESS.fullmatch(value["recipient"]) is None:
        raise ValueError("A single synthetic .invalid recipient is required")
    if not isinstance(value["body"], str) or not isinstance(value["attachments"], list):
        raise ValueError("Expected text body and an attachment list")
    parts = []
    for item in value["attachments"]:
        if not isinstance(item, dict) or set(item) not in ({"name", "content"}, {"name", "content_b64"}):
            raise ValueError("An attachment needs name and exactly one of content, content_b64")
        if not isinstance(item["name"], str) or not item["name"] or any(c in item["name"] for c in "\r\n"):
            raise ValueError("Expected a nonempty single-line attachment name")
        payload = item.get("content", item.get("content_b64"))
        if not isinstance(payload, str):
            raise ValueError("The attachment value must be a string")
        data = payload.encode("utf-8") if "content" in item else b64decode(payload, validate=True)
        parts.append((item["name"], data))
    return {**value, "attachments": parts}


def run(case, caps):
    check_freeze()
    required = {"policy_at_approval", "grant", "message"}
    if not isinstance(case, dict) or not required <= set(case) or set(case) - required - {"policy_before_delivery"}:
        raise ValueError("Invalid case; see examples/mail_audit/local_case.json")
    policy = case["policy_at_approval"]
    grant = None if case["grant"] is None else parse_fact(case["grant"])
    message = parse_fact(case["message"])
    keys = {r: secrets.token_bytes(32) for r in ROLES}
    comp = secrets.token_bytes(32)
    with TemporaryDirectory(prefix="mail-audit-case-") as directory:
        db = Path(directory) / "audit.sqlite"
        initial = workspace.activate(db, policy, caps, expect_version=0)
        if not initial["feasible"]:
            return {"status": "configuration_unavailable", "smtp_acceptances": 0,
                    "reason": initial["plan"]["target_basis"], "model_witness": initial["plan"]["target_witness"]}
        with LocalMailbox() as mailbox, closing(sqlite3.connect(":memory:")) as ledger:
            init_ledger(ledger)
            snapshot = commit_grant(ledger, "case", grant)
            pinned = workspace.begin_attempt(db, "case", snapshot, comp, keys["approval"])
            changed = None
            if "policy_before_delivery" in case:
                changed = workspace.activate(db, case["policy_before_delivery"], caps, expect_version=pinned)
            active = workspace.status(db)
            received, stored_mime = commit_delivery(mailbox, "case", message)
            workspace.finish_attempt(db, "case", received, comp, keys["delivery"])
            reference = gold(policy, grant_snapshot(ledger, "case"), stored_mime)
            under_active = gold(active["revision"]["policy"], grant_snapshot(ledger, "case"), stored_mime)
        verified = workspace.audit_attempt(db, "case", keys)
        if verified["version"] != pinned:
            raise RuntimeError("Evidence registry returned an unexpected revision")
        outcome = "audited" if verified["decision"] == reference else "reference_disagreement"
        return {"status": outcome, "smtp_acceptances": 1, "approval_revision": pinned,
                "active_revision_at_delivery": active["version"],
                "intervening_policy_feasible": changed["feasible"] if changed else None,
                "signed_verdict": verified["decision"], "persisted_mime_reference": reference,
                "reference_if_evaluated_at_delivery_revision": under_active,
                "recorded_fields": workspace.revision(db, pinned)["fields"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("--capabilities", type=Path, default=CAPS_PATH)
    args = parser.parse_args()
    try:
        result = run(json.loads(args.case.read_text()), json.loads(args.capabilities.read_text()))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(json.dumps(result, indent=2))
    return int(result["status"] != "audited")


if __name__ == "__main__":
    raise SystemExit(main())
