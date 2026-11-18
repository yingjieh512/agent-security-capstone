"""Checks for end-user JSON cases, including canonical binary parts and capability loss."""
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from attachment_mail_backend import CACHE
from run_mail_case import parse_fact, run

CASE = json.loads((ROOT / "examples/mail_audit/local_case.json").read_text())
CAPS = json.loads((ROOT / "reports/policy_transfer/capabilities.json").read_text())


def test_binary_part_is_decoded_and_synthetic_address_is_enforced():
    value = {**CASE["message"], "attachments": [{"name": "part", "content_b64": "AP8="}]}
    assert parse_fact(value)["attachments"] == [("part", b"\x00\xff")]
    with pytest.raises(ValueError, match="synthetic"):
        parse_fact({**value, "recipient": "someone@example.com"})
    with pytest.raises(ValueError):
        parse_fact({**value, "attachments": [{"name": "p", "content_b64": "@@"}]})


def test_infeasible_case_receives_no_messages():
    caps = {r: [f for f in fs if f != "body.raw"] for r, fs in CAPS.items()}
    result = run({**CASE, "policy_at_approval": {"op": "eq", "field": "body"}}, caps)
    assert result["status"] == "configuration_unavailable"
    assert result["smtp_acceptances"] == 0 and result["model_witness"]


@pytest.mark.skipif(os.environ.get("RUN_LOCAL_MAILPIT") != "1" or not (CACHE / "mailpit").exists(),
                    reason="uses the pinned local SMTP process")
def test_user_case_crossing_a_policy_boundary():
    row = run(CASE, CAPS)
    assert row["status"] == "audited" and row["smtp_acceptances"] == 1
    assert (row["approval_revision"], row["active_revision_at_delivery"]) == (1, 2)
    assert row["signed_verdict"] == row["persisted_mime_reference"] == "unauthorized"
    assert row["reference_if_evaluated_at_delivery_revision"] == "authorized"
