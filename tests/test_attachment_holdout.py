"""Regression tests for the held-out attachment policy and its evidence protocol."""
import base64
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from attachment_mail_backend import CACHE, LocalMailbox
from attachment_projection import issue, verify
from attachment_schema_check import run_search
from attachment_witness_replay import concrete_fact, visible_pattern
from run_attachment_holdout_pilot import freeze_check


ROLES = ("approval", "delivery")
ITEMS = "attachment_bytes.item_tags"
WHO = "recipient.tag"
CONFIG = {role: [WHO, ITEMS] for role in ROLES}
HAND = json.loads((SCRIPTS / "attachment_hand_configs.json").read_text())["configs"]
KEYS = {"approval": b"test approval source", "delivery": b"test mailbox source"}
COMPARISON = b"test scoped pseudonyms"
RECIPIENT = "private-user@holdout.invalid"


def mail(blobs=(), recipient=RECIPIENT, name="sensitive-name.bin"):
    return {"recipient": recipient, "attachments": [(name, b) for b in blobs],
            "body": "private body literal"}


def signed(config, grant, delivered, attempt="fixture"):
    return {r: issue(config[r], r, attempt, fact, COMPARISON, KEYS[r])
            for r, fact in zip(ROLES, (grant, delivered))}


@pytest.fixture(scope="module")
def search():
    return run_search()


def test_frozen_input_hashes_and_native_cli_rejection():
    # freeze_check hashes the imported implementation and invokes its native CLI.
    result = freeze_check()
    assert result["compiler_sha256"] == "8bb4aebe8d2ebb3657e0e7d9e4e505c0ee8994bbf2a96da0bd881f963a07a7a5"
    assert result["hand_sha256"] == "5ffecffab84f89548d605ce8904fd7d72f966c8bfb620a1bfd4b39f9b7c2c3c6"
    assert result["native_cli_exit"] == 2
    assert result["native_supported"] is False


def test_finite_search_selects_minimal_private_schema(search):
    assert (search["worlds"], search["configs_examined"]) == (400, 4096)
    assert search["minimum_field_count"] == 4
    assert search["selected_cost"] == [0, 0, 4]
    assert search["optimal_config_count"] == 1
    assert search["selected"] == CONFIG
    assert set(search["deletion_witnesses"]) == {f"{r}.{f}" for r in ROLES for f in CONFIG[r]}


@pytest.mark.parametrize("role,field", [(r, f) for r in ROLES for f in CONFIG[r]])
def test_each_field_deletion_yields_opposite_truth_with_identical_observations(search, role, field):
    witness = search["deletion_witnesses"][f"{role}.{field}"]
    reduced = deepcopy(CONFIG)
    reduced[role].remove(field)
    observations = []
    for side, expected in (("within", "authorized"), ("violation", "unauthorized")):
        grant, actual = (concrete_fact(witness[side][r]) for r in ROLES)
        allowed = Counter(blob for _, blob in grant["attachments"])
        excess = Counter(blob for _, blob in actual["attachments"]) - allowed
        assert (not excess and grant["recipient"] == actual["recipient"]) == (expected == "authorized")
        full = signed(CONFIG, grant, actual, side)
        assert verify(CONFIG, side, full, None, KEYS) == expected
        limited = signed(reduced, grant, actual, side)
        observations.append(visible_pattern(limited))
        assert verify(reduced, side, limited, None, KEYS) == "unknown"
    assert observations[0] == observations[1]


@pytest.mark.parametrize("name,approval,delivery", [
    ("expert_minimal", [], []), ("full_operational", [], []),
    ("metadata_only", [ITEMS], [ITEMS]), ("whole_bag", [ITEMS], [ITEMS]),
    ("missing_delivery_attachment", [], [ITEMS]), ("missing_delivery_recipient", [], [WHO]),
])
def test_minimal_repairs_identify_specific_source_and_field(search, name, approval, delivery):
    repair = search["manual_minimum_additions"][name]
    assert repair["cost"] == [0, 0, len(approval) + len(delivery)]
    assert repair["optimal_additions"] == [{"approval": approval, "delivery": delivery}]


@pytest.mark.parametrize("grant,actual,recipient,expected", [
    ([b"A", b"A", b"B"], [b"B", b"A"], RECIPIENT, "authorized"),
    ([b"A", b"A"], [b"A", b"A"], RECIPIENT, "authorized"),
    ([b"A", b"A", b"B"], [b"A", b"B", b"B"], RECIPIENT, "unauthorized"),
    ([b""], [b""], RECIPIENT, "authorized"),
    ([b"A"], [], RECIPIENT, "authorized"),
    ([], [b""], RECIPIENT, "unauthorized"),
    ([], [], "different@holdout.invalid", "unauthorized"),
    ([b"A"], [b"B"], RECIPIENT, "unauthorized"),
])
def test_subset_multiplicity_empty_bytes_and_bound_recipient(grant, actual, recipient, expected):
    records = signed(CONFIG, mail(grant), mail(actual, recipient, "renamed.dat"))
    assert verify(CONFIG, "fixture", records, None, KEYS) == expected


def test_three_valued_verdict_distinguishes_absent_evidence_from_signed_negative():
    no_grant = signed(CONFIG, None, mail())
    no_delivery = signed(CONFIG, mail(), None)
    assert verify(CONFIG, "fixture", no_grant, None, KEYS) == "unauthorized"
    assert verify(CONFIG, "fixture", no_delivery, None, KEYS) == "unknown"
    assert verify(CONFIG, "fixture", {"delivery": no_grant["delivery"]}, None, KEYS) == "unknown"
    assert verify(CONFIG, "fixture", {"approval": no_grant["approval"]}, None, KEYS) == "unknown"
    metadata = HAND["metadata_only"]
    for blob in (b"A", b"B"):
        incomplete = signed(metadata, mail([b"A", b"C"]), mail([blob]))
        assert verify(metadata, "fixture", incomplete, None, KEYS) == "unknown"


def test_scoped_tags_compare_within_attempt_without_raw_payloads():
    blob = b"distinct private attachment"
    content = mail([blob, blob])
    first, second = [signed(CONFIG, content, content, attempt) for attempt in ("one", "two")]
    encoded = base64.b64encode(blob).decode()
    sensitive = (RECIPIENT, content["body"], content["attachments"][0][0], blob.decode(), encoded)
    serialized = json.dumps(first)
    assert all(value not in serialized for value in sensitive)
    for r in ROLES:
        assert set(first[r]["fields"]) == {WHO, ITEMS}
        tags = first[r]["fields"][ITEMS]
        assert len(tags) == 2 and tags[0] == tags[1]
        assert first[r]["fields"][WHO] != second[r]["fields"][WHO]
        assert set(tags).isdisjoint(second[r]["fields"][ITEMS])
    assert first["approval"]["fields"] == first["delivery"]["fields"]
    assert first["approval"]["mac"] != first["delivery"]["mac"]
    raw = signed(HAND["full_operational"], content, content)
    assert all(value in json.dumps(raw) for value in (RECIPIENT, content["body"],
                                                       content["attachments"][0][0], encoded))


@pytest.mark.parametrize("role", ROLES)
def test_two_source_authenticators_bind_role_operation_policy_and_fields(role):
    other = next(r for r in ROLES if r != role)
    records = signed(CONFIG, mail(), mail())
    assert verify(CONFIG, "fixture", records, None, KEYS) == "authorized"
    assert verify(CONFIG, "fixture", {**records, role: records[other]}, None, KEYS) == "unknown"
    signed_by_other = issue(CONFIG[role], role, "fixture", mail(), COMPARISON, KEYS[other])
    assert verify(CONFIG, "fixture", {**records, role: signed_by_other}, None, KEYS) == "unknown"
    previous = signed(CONFIG, mail(), mail(), "previous")
    assert verify(CONFIG, "fixture", {**records, role: previous[role]}, None, KEYS) == "unknown"
    for key, value in (("policy", "another"), ("version", 2), ("present", False),
                       ("fields", {WHO: "edited", ITEMS: []})):
        invalid = {**records, role: {**records[role], key: value}}
        assert verify(CONFIG, "fixture", invalid, None, KEYS) == "unknown"


@pytest.mark.skipif(os.environ.get("RUN_LOCAL_MAILPIT") != "1" or not (CACHE / "mailpit").is_file(),
                    reason="Opt in with RUN_LOCAL_MAILPIT=1 and an installed local Mailpit binary")
def test_local_mailbox_recipient_and_committed_mime():
    actual = mail([b"\x00", b"\x00"])
    with LocalMailbox() as mailbox:
        queue_id = mailbox.submit("smtp-fixture", RECIPIENT, actual["attachments"], actual["body"],
                                  header_to="header-only@holdout.invalid")
        receipt, raw = mailbox.read("smtp-fixture"), mailbox.oracle("smtp-fixture")
    for fact in (receipt, raw):
        assert fact["backend_id"] == queue_id
        assert fact["recipient"] == RECIPIENT
        assert fact["attachments"] == actual["attachments"]
    records = signed(CONFIG, mail([b"\x00"]), receipt, "smtp-fixture")
    assert verify(CONFIG, "smtp-fixture", records, None, KEYS) == "unauthorized"


def test_pruning_respects_existing_source_capabilities(search):
    pruned = search["pruned_existing"]
    assert pruned["expert_minimal"]["selected"] == CONFIG
    assert pruned["expert_with_body_names"]["removed"] == {
        role: ["body.raw", "attachment_names.raw"] for role in ROLES
    }
    assert pruned["full_operational"]["selected"] == {
        role: ["recipient.raw", "attachment_content.raw"] for role in ROLES
    }
    assert all(row["optimal_config_count"] == 1 for row in pruned.values())
