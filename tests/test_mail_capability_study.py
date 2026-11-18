"""Coverage and accounting regression tests for source capability deletions."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mail_policy_search import FIELDS, ROLES
from run_declaration_holdout import counters
from run_mail_capability_study import outcome_category, single_deletions, summarize


def both(*fields):
    return {r: list(fields) for r in ROLES}


def test_single_deletions_are_complete_and_source_local():
    full = both(*FIELDS)
    deletions = list(single_deletions(full))
    assert {(role, field) for role, field, _ in deletions} == {(r, f) for r in ROLES for f in FIELDS}
    assert len(deletions) == 20
    for role, field, cap in deletions:
        for source in ROLES:
            assert set(cap[source]) == (set(FIELDS) - {field} if source == role else set(FIELDS))
    assert full == both(*FIELDS)


@pytest.mark.parametrize(("control", "selected", "witness", "expected"), [
    (both("body.raw", "recipient.tag"), both("recipient.tag", "body.raw"), None, "unchanged"),
    (both("attachment_count"), both("attachment_sizes.list"), None, "fallback_without_new_raw"),
    (both("recipient.tag"), both("recipient.raw"), None, "fallback_with_new_raw"),
    ({"approval": ["recipient.raw"], "delivery": ["recipient.tag"]}, both("recipient.raw"), None,
     "fallback_with_new_raw"),
    (both("body.raw"), None, {"within": {}, "violation": {}}, "infeasible_with_collision"),
    (both("body.raw"), None, None, "infeasible_without_collision"),
])
def test_outcome_is_role_specific_and_requires_an_actual_collision(control, selected, witness, expected):
    assert outcome_category(control, selected, witness) == expected


def test_summary_distinguishes_copy_of_a_schema_from_an_extra_message_or_unavailable_profile():
    control = counters()
    control["correct"] = 2
    control["receipt_bytes"] = 200
    fallback = counters()
    fallback["correct"] = fallback["unknown"] = 1
    fallback["receipt_bytes"] = 180
    fallback["raw_bytes"]["names"] = 17
    schemas = {"control": {"measured": control}, "alternate1": {"measured": fallback}}
    results = {"one_policy": {
        "control": "control", "schemas": schemas, "single_deletions": {
            "s1": {"outcome": "unchanged", "schema": "control"},
            "s2": {"outcome": "fallback_with_new_raw", "schema": "alternate1"},
            "s3": {"outcome": "fallback_with_new_raw", "schema": "alternate1"},
            "s4": {"outcome": "infeasible_with_collision", "schema": None,
                   "witness_replay": {"smtp_acceptances": 2, "reproduced": True}},
        },
    }}
    total = summarize(results, 2, {"W01": {}})
    assert total["restricted_settings"] == 4
    assert total["restricted_feasible"] == 3
    assert total["restricted_feasible_setting_verdict_denominator"] == 6
    assert total["restricted_feasible_setting_verdicts"]["correct"] == 4
    assert total["restricted_feasible_setting_verdicts"]["unknown"] == 2
    assert total["control_policy_verdicts"]["correct"] == total["main_smtp_acceptances"] == 2
    assert total["witness_smtp_acceptances"] == 2 and total["confirmed_witness_replays"] == 1
    assert schemas["alternate1"]["delta_from_control"]["receipt_bytes"] == -20
    assert schemas["alternate1"]["delta_from_control"]["raw_bytes"]["names"] == 17
    with pytest.raises(ValueError, match="Missing or duplicated"):
        summarize(results, 3, {})


def test_archived_controls_and_deletion_grid_match_registered_study():
    study = Path(__file__).resolve().parents[1] / "reports" / "solo_mail_audit"
    result = json.loads((study / "capability_results.json").read_text())
    baseline = json.loads((study / "results.json").read_text())
    summary = result["summary"]
    assert set(result["policies"]) == set(baseline["policies"])
    assert summary["full_menu_controls"] == 8 and summary["restricted_settings"] == 160
    assert summary["main_smtp_acceptances"] == 64
    assert summary["restricted_feasible_setting_verdict_denominator"] == 64 * summary["restricted_feasible"]
    assert sum(summary["restricted_feasible_setting_verdicts"].values()) == 64 * summary["restricted_feasible"]
    cells = {f"{r}/{field}" for r in ROLES for field in FIELDS}
    for name, experiment in result["policies"].items():
        control = experiment["schemas"]["control"]
        assert control["fields"] == baseline["policies"][name]["fields"]
        assert control["measured"] == baseline["policies"][name]["compiled"]
        assert set(experiment["single_deletions"]) == cells
        for key, row in experiment["single_deletions"].items():
            role, field = key.split("/")
            if row["schema"] is not None:
                assert field not in experiment["schemas"][row["schema"]]["fields"][role]
            elif "witness" in row:
                assert row["witness"] in result["witnesses"]
                assert row["witness_replay"]["independent_truths"] == ["authorized", "unauthorized"]
                assert row["witness_replay"]["same_observation"]
