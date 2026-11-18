"""Regression checks for a migration's deployment delta and capability bounds."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mail_policy_search import FIELDS, ROLES
from plan_mail_policy_change import plan_change
from run_solo_mail_audit import case_family, policy_family


def two_roles(*fields):
    return {r: list(fields) for r in ROLES}


def test_changing_content_comparison_returns_executable_delta_and_witness():
    before = two_roles("recipient.tag", "attachment_bytes.bag_tag")
    plan = plan_change(before, policy_family()["items_subset"], two_roles(*FIELDS))
    assert plan["action"] == "replace_insufficient_fields"
    assert set(plan["old_fields_witness"]) == {"within", "violation"}
    for r in ROLES:
        updated = (set(before[r]) - set(plan["retire"][r])) | set(plan["add"][r])
        assert updated == set(plan["target_fields"][r]) == {"recipient.tag", "attachment_bytes.item_tags"}


def test_disappearing_capability_is_not_used_to_authorize():
    old = two_roles("recipient.tag", "attachment_names.raw")
    caps = two_roles(*FIELDS)
    caps["delivery"].remove("attachment_names.raw")
    result = plan_change(old, policy_family()["names_eq"], caps)
    assert not result["target_feasible"] and not result["old_fields_sufficient"]
    assert result["target_witness"] and result["target_fields"] is None
    assert "attachment_names.raw" not in result["available_current_fields"]["delivery"]


def test_fixed_registration_and_rejected_current_field():
    assert len(policy_family()) == 8
    assert len({case[0] for case in case_family()}) == 16
    with pytest.raises(ValueError, match="Invalid or duplicate"):
        plan_change(two_roles("recipent.tag"), policy_family()["items_eq"], two_roles(*FIELDS))
