"""Exercise the durable policy and send lifecycle across different SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
from threading import Barrier

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mail_audit_workspace as ws
from mail_policy_search import FIELDS


KEY = b"comparison-key-private"
KEYS = {"approval": b"grant-key-private", "delivery": b"mail-key-private"}
CAPS = {r: list(FIELDS) for r in KEYS}
RECIPIENT = {"op": "eq", "field": "recipient"}
ITEMS = {"op": "eq", "field": "items"}
NAMES = {"op": "eq", "field": "names"}
SUBSET = {"op": "subset", "field": "items"}
GRANT = {"recipient": "fiction@pilot.invalid", "body": "never store this mail body",
         "attachments": [("secret-name-a.bin", b"Attachment Alpha"), ("secret-name-b.bin", b"Attachment Beta")]}
DELIVERY = {**GRANT, "attachments": GRANT["attachments"][:1]}


def approve(db, attempt, grant=GRANT):
    return ws.begin_attempt(db, attempt, grant, KEY, KEYS["approval"])


def deliver(db, attempt, fact=DELIVERY):
    return ws.finish_attempt(db, attempt, fact, KEY, KEYS["delivery"])


def test_revisions_retries_and_historical_decisions(tmp_path):
    db = tmp_path / "evidence.sqlite"
    assert ws.status(db) == {"version": 0, "revision": None}
    assert not db.exists()
    assert ws.activate(db, ITEMS, CAPS, expect_version=0)["version"] == 1
    assert approve(db, "in-flight") == 1
    assert ws.audit_attempt(db, "in-flight", KEYS) == {"version": 1, "decision": "unknown"}
    swapped_order = {r: list(reversed(caps)) for r, caps in CAPS.items()}
    assert ws.activate(db, ITEMS, swapped_order) == {"activated": False, "feasible": True,
                                                      "version": 1, "plan": None}
    assert ws.activate(db, SUBSET, CAPS, expect_version=1)["version"] == 2
    assert approve(db, "in-flight") == 1  # retry must use the old revision
    assert deliver(db, "in-flight") == deliver(db, "in-flight") == 1
    assert ws.audit_attempt(db, "in-flight", KEYS) == {"version": 1, "decision": "unauthorized"}
    with pytest.raises(ws.Conflict):
        approve(db, "in-flight", DELIVERY)
    with pytest.raises(ws.Conflict):
        deliver(db, "in-flight", GRANT)
    assert approve(db, "new") == deliver(db, "new") == 2
    assert ws.audit_attempt(db, "new", KEYS) == {"version": 2, "decision": "authorized"}
    assert ws.activate(db, ITEMS, CAPS)["version"] == 3
    assert ws.revision(db, 3)["policy"] == ws.revision(db, 1)["policy"]
    assert ws.revision(db, 2)["policy"] == SUBSET
    assert ws.audit_attempt(db, "new", KEYS)["decision"] == "authorized"
    entry = ws.read_attempt(db, "new")
    assert entry["version"] == 2
    assert set(entry["records"]) == set(KEYS)
    for role in KEYS:
        assert set(entry["records"][role]["fields"]) == {"attachment_bytes.item_tags"}
    raw = db.read_bytes()
    for secret in (GRANT["recipient"].encode(), GRANT["body"].encode(), GRANT["attachments"][0][0].encode(),
                   GRANT["attachments"][0][1], KEY, *KEYS.values()):
        assert secret not in raw


def test_failed_deployment_does_not_change_current_state(tmp_path):
    db = tmp_path / "record.sqlite"
    assert ws.activate(db, RECIPIENT, CAPS)["activated"]
    limited = {**CAPS, "delivery": [f for f in FIELDS if f != "attachment_names.raw"]}
    result = ws.activate(db, NAMES, limited, expect_version=1)
    assert (result["activated"], result["feasible"], result["version"]) == (False, False, 1)
    assert result["plan"]["target_witness"] is not None
    with pytest.raises(ws.Conflict):
        ws.activate(db, NAMES, CAPS, expect_version=0)
    with pytest.raises(ValueError):
        ws.activate(db, NAMES, {"approval": ["typo"], "delivery": []})
    assert ws.revision(db, 2) is None and ws.status(db)["revision"]["policy"] == RECIPIENT
    assert approve(db, "good") == 1


def test_no_missing_record_can_be_invented_and_receipt_is_role_bound(tmp_path):
    db = tmp_path / "records.db"
    assert ws.audit_attempt(db, "absent", KEYS) == {"version": None, "decision": "unknown"}
    with pytest.raises(ValueError):
        approve(db, "uninitialized")
    ws.activate(db, RECIPIENT, CAPS)
    with pytest.raises(KeyError):
        deliver(db, "never-started")
    assert ws.read_attempt(db, "never-started") is None
    assert approve(db, "no-grant", None) == 1
    assert ws.audit_attempt(db, "no-grant", KEYS)["decision"] == "unknown"
    assert deliver(db, "no-grant") == 1
    assert ws.audit_attempt(db, "no-grant", KEYS)["decision"] == "unauthorized"
    assert approve(db, "no-delivery") == deliver(db, "no-delivery", None) == 1
    assert ws.read_attempt(db, "no-delivery")["records"]["delivery"]["present"] is False
    assert ws.audit_attempt(db, "no-delivery", KEYS)["decision"] == "unknown"
    approve(db, "signed")
    deliver(db, "signed")
    for wrong in ({}, {"approval": KEYS["delivery"], "delivery": KEYS["approval"]},
                  {"approval": b"wrong", "delivery": KEYS["delivery"]}):
        assert ws.audit_attempt(db, "signed", wrong)["decision"] == "unknown"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE attempts SET delivery=approval WHERE attempt='signed'")
    assert ws.audit_attempt(db, "signed", KEYS)["decision"] == "unknown"


def test_concurrent_activation_compare_and_set(tmp_path):
    db = tmp_path / "races.sqlite"
    ws.activate(db, ITEMS, CAPS)
    barrier = Barrier(2)
    def competing(policy):
        barrier.wait()
        try:
            return ws.activate(db, policy, CAPS, expect_version=1)["version"]
        except ws.Conflict:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(competing, [NAMES, SUBSET])) == {2, "stale"}
    assert ws.status(db)["version"] == 2 and ws.revision(db, 3) is None


def test_concurrent_terminals_are_immutable(tmp_path):
    db = tmp_path / "send-race.sqlite"
    ws.activate(db, ITEMS, CAPS)
    approve(db, "one")
    barrier = Barrier(2)
    def competing(fact):
        barrier.wait()
        try:
            return deliver(db, "one", fact)
        except ws.Conflict:
            return "conflicting"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(competing, [GRANT, DELIVERY])) == {1, "conflicting"}
    assert ws.audit_attempt(db, "one", KEYS)["decision"] in {"authorized", "unauthorized"}


def test_cli_activation_status_and_offline_audit(tmp_path):
    db = tmp_path / "cli.sqlite"
    caps = tmp_path / "caps.json"
    caps.write_text(json.dumps(CAPS))
    policy = tmp_path / "rule.json"
    policy.write_text(json.dumps(ITEMS))
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({r: k.hex() for r, k in KEYS.items()}))
    cmd = [sys.executable, str(SCRIPTS / "mail_audit_workspace.py")]
    def cli(command, *flags):
        return json.loads(subprocess.check_output([*cmd, command, "--db", str(db), *flags]))
    assert cli("activate", "--policy", str(policy), "--capabilities", str(caps), "--expect-version", "0")["activated"]
    assert cli("status", "--version", "1")["fields"] == ws.status(db)["revision"]["fields"]
    approve(db, "first")
    deliver(db, "first")
    assert cli("audit", "--attempt", "first", "--keys", str(keys)) == {"version": 1, "decision": "unauthorized"}


def test_mixed_comparison_scope_cannot_create_a_match(tmp_path):
    db = tmp_path / "scope.db"
    ws.activate(db, RECIPIENT, CAPS)
    approve(db, "test")
    ws.finish_attempt(db, "test", GRANT, b"rotated-comparison-key", KEYS["delivery"])
    assert ws.audit_attempt(db, "test", KEYS) == {"version": 1, "decision": "unknown"}


@pytest.mark.parametrize("corruption", ["different_policy", "malformed_receipt"])
def test_offline_audit_authenticates_policy_even_with_identical_fields(tmp_path, corruption):
    db = tmp_path / "substitution.db"
    ws.activate(db, RECIPIENT, CAPS)
    approve(db, "test")
    deliver(db, "test")
    assert ws.audit_attempt(db, "test", KEYS)["decision"] == "authorized"
    if corruption == "different_policy":
        equivalent_policy = {"all": [RECIPIENT]}
        wrong = ws.runtime.issue(equivalent_policy, ["recipient.tag"], "delivery",
                                 "test", GRANT, KEY, KEYS["delivery"])
        serialized = json.dumps(wrong)
    else:
        serialized = "{"
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE attempts SET delivery=? WHERE attempt='test'", (serialized,))
    assert ws.audit_attempt(db, "test", KEYS) == {"version": 1, "decision": "unknown"}
