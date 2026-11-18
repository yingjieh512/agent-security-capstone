"""Versioned local mail evidence registry and offline auditor.

activate(db, policy, capabilities, expect_version=...) checks the proposed
migration and activates only feasible configurations. Version zero denotes an
empty registry. Reactivating an older declaration creates a new version.

begin_attempt(db, id, grant, comparison_key, approval_key) pins the active
revision and stores its authenticated projection. finish_attempt(db, id, fact,
comparison_key, delivery_key) uses that pinned revision. A fact is a source's
own snapshot or None for an explicit negative. Omitting finish leaves delivery
pending. Retries succeed only when the original projected receipt is reproduced.
Changes restricted to unrecorded values are intentionally indistinguishable.

audit_attempt(db, id, source_keys) checks persisted receipts with the pinned
declaration. Versions and attempt associations are trusted local SQLite state.
Keys are supplied by the caller and never written here. The signed receipt
binds the policy digest, selected fields, role and unique attempt ID.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3

import mail_policy_runtime as runtime
from mail_policy_search import FIELDS, ROLES
from plan_mail_policy_change import plan_change


APPLICATION_ID = 0x4D415531  # MAU1
REVISIONS = """CREATE TABLE revisions (
    version INTEGER PRIMARY KEY,
    policy TEXT NOT NULL,
    capabilities TEXT NOT NULL,
    fields TEXT NOT NULL
)"""
ATTEMPTS = """CREATE TABLE attempts (
    attempt TEXT PRIMARY KEY NOT NULL,
    version INTEGER NOT NULL REFERENCES revisions(version),
    approval TEXT NOT NULL,
    delivery TEXT
)"""


class Conflict(ValueError):
    """An update would overwrite an unexpected revision or existing receipt."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@contextmanager
def _database(path, *, write=False):
    path = Path(path)
    if str(path) == ":memory:":
        raise ValueError("Use a persistent SQLite file for a versioned workspace")
    if not write and not path.exists():
        yield None
        return
    location = str(path) if write else path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(location, uri=not write, timeout=30, isolation_level=None)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        application, = db.execute("PRAGMA application_id").fetchone()
        if application == 0 and not db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
            if not write:
                yield None
                return
            db.execute(REVISIONS)
            db.execute(ATTEMPTS)
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        elif application != APPLICATION_ID:
            raise ValueError("The SQLite file is not a mail audit registry")
        # Closing rolls back a transaction if validation or signing raises.
        yield db
        db.commit()


def _revision(db, version=None):
    if db is None:
        return None
    if version is None:
        row = db.execute("SELECT * FROM revisions ORDER BY version DESC LIMIT 1").fetchone()
    else:
        row = db.execute("SELECT * FROM revisions WHERE version=?", (version,)).fetchone()
    if row is None:
        return None
    return {"version": row[0], "policy": json.loads(row[1]),
            "capabilities": json.loads(row[2]), "fields": json.loads(row[3])}


def revision(db, version):
    """Retrieve a historical declaration and fields. Unknown revisions return None."""
    if type(version) is not int or version < 1:
        raise ValueError("A saved revision number must be a positive integer")
    with _database(db) as conn:
        return _revision(conn, version)


def status(db):
    with _database(db) as conn:
        active = _revision(conn)
        return {"version": active["version"] if active else 0, "revision": active}


def activate(db, policy, capabilities, *, expect_version=None):
    """Serialize local deployments and receipt writers in atomic transactions.

    The bounded compile runs under the writer lock so the checked predecessor and
    installed successor cannot diverge. An infeasible proposal returns its plan
    without adding a revision. A supplied stale precondition raises Conflict.
    """
    runtime.validate(policy)
    if expect_version is not None and (type(expect_version) is not int or expect_version < 0):
        raise ValueError("Expected version must be a nonnegative integer")
    if not isinstance(capabilities, dict) or set(capabilities) != set(ROLES):
        raise ValueError("Capabilities must declare approval and delivery")
    caps = {}
    for role in ROLES:
        names = capabilities[role]
        if (not isinstance(names, (list, tuple)) or not all(isinstance(f, str) and f in FIELDS for f in names)
                or len(names) != len(set(names))):
            raise ValueError("Unknown or duplicate source capability")
        caps[role] = sorted(names)
    with _database(db, write=True) as conn:
        old = _revision(conn)
        version = old["version"] if old else 0
        if expect_version is not None and expect_version != version:
            raise Conflict(f"Expected revision {expect_version}, current revision is {version}")
        if old and old["policy"] == policy and old["capabilities"] == caps:
            return {"activated": False, "feasible": True, "version": version, "plan": None}
        before = old["fields"] if old else {r: [] for r in ROLES}
        plan = plan_change(before, policy, caps)
        if not plan["target_feasible"]:
            return {"activated": False, "feasible": False, "version": version, "plan": plan}
        version += 1
        conn.execute("INSERT INTO revisions(version,policy,capabilities,fields) VALUES (?,?,?,?)",
                     (version, _json(policy), _json(caps), _json(plan["target_fields"])))
        return {"activated": True, "feasible": True, "version": version, "plan": plan}


def _attempt_id(attempt):
    if not isinstance(attempt, str) or not attempt:
        raise ValueError("A nonempty attempt ID is required")


def _attempt_row(conn, attempt):
    if conn is None:
        return None
    return conn.execute("SELECT version,approval,delivery FROM attempts WHERE attempt=?", (attempt,)).fetchone()


def _write_receipt(db, attempt, role, fact, comparison_key, source_key):
    _attempt_id(attempt)
    if not all(isinstance(key, bytes) and key for key in (comparison_key, source_key)):
        raise ValueError("Supply nonempty comparison and source keys as bytes")
    with _database(db, write=True) as conn:
        row = _attempt_row(conn, attempt)
        if row is None and role == "delivery":
            raise KeyError("No pinned approval snapshot for this attempt")
        target = _revision(conn, row[0] if row else None)
        if target is None:
            raise ValueError("Activate a feasible rule before recording a send")
        record = _json(runtime.issue(target["policy"], target["fields"][role], role, attempt,
                                     fact, comparison_key, source_key))
        if row is None:
            conn.execute("INSERT INTO attempts(attempt,version,approval) VALUES (?,?,?)",
                         (attempt, target["version"], record))
        elif role == "delivery" and row[2] is None:
            conn.execute("UPDATE attempts SET delivery=? WHERE attempt=?", (record, attempt))
        elif record != row[1 if role == "approval" else 2]:
            raise Conflict(f"A different {role} receipt already exists for this attempt")
        return target["version"]


def begin_attempt(db, attempt, grant, comparison_key, approval_key):
    return _write_receipt(db, attempt, "approval", grant, comparison_key, approval_key)


def finish_attempt(db, attempt, delivery, comparison_key, delivery_key):
    return _write_receipt(db, attempt, "delivery", delivery, comparison_key, delivery_key)


def _records(row):
    records = {"approval": json.loads(row[1])}
    if row[2] is not None:
        records["delivery"] = json.loads(row[2])
    return records


def read_attempt(db, attempt):
    _attempt_id(attempt)
    with _database(db) as conn:
        row = _attempt_row(conn, attempt)
        return {"version": row[0], "records": _records(row)} if row else None


def audit_attempt(db, attempt, source_keys):
    """Read signed receipts and their pinned rule in one offline snapshot."""
    _attempt_id(attempt)
    with _database(db) as conn:
        row = _attempt_row(conn, attempt)
        if row is None:
            return {"version": None, "decision": "unknown"}
        result = {"version": row[0], "decision": "unknown"}
        if (not isinstance(source_keys, dict)
                or not all(isinstance(source_keys.get(r), bytes) and source_keys[r] for r in ROLES)
                or source_keys["approval"] == source_keys["delivery"]):
            return result
        try:
            records = _records(row)
        except (ValueError, TypeError):
            return result
        target = _revision(conn, row[0])
        result["decision"] = runtime.verify(target["policy"], target["fields"], attempt, records, source_keys)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("activate", help="Install a feasible configuration atomically")
    initialize.add_argument("--policy", required=True, type=Path)
    initialize.add_argument("--capabilities", required=True, type=Path)
    initialize.add_argument("--expect-version", type=int)
    show = commands.add_parser("status", help="Inspect current or historical configuration")
    show.add_argument("--version", type=int)
    audit = commands.add_parser("audit", help="Verify an attempt under its pinned configuration")
    audit.add_argument("--attempt", required=True)
    audit.add_argument("--keys", type=Path, required=True, help="Private JSON mapping approval/delivery to hex MAC keys")
    for sub in (initialize, show, audit):
        sub.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "activate":
            result = activate(args.db, json.loads(args.policy.read_text()), json.loads(args.capabilities.read_text()),
                              expect_version=args.expect_version)
        elif args.command == "status":
            result = status(args.db) if args.version is None else revision(args.db, args.version)
        else:
            supplied = json.loads(args.keys.read_text())
            keys = {r: bytes.fromhex(supplied[r]) for r in ROLES}
            result = audit_attempt(args.db, args.attempt, keys)
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(result is None or (args.command == "activate" and not result["feasible"]))


if __name__ == "__main__":
    raise SystemExit(main())
