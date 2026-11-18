"""Run the pre-specified attachment policy pilot on a local Mailpit inbox.

From the repository root: PYTHONPATH=src python scripts/run_attachment_holdout_pilot.py
"""
from __future__ import annotations

import argparse
from base64 import b64decode, b64encode
from collections import Counter
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys

from attachment_benchmark_shapes import load_templates
from attachment_mail_backend import LocalMailbox, VERSION as MAILPIT
from attachment_projection import ROLES, issue, verify, wire
from attachment_schema_check import run_search
from attachment_witness_replay import replay_witnesses
from trajectory_audit import send_log as frozen

ROOT = Path(__file__).resolve().parents[1]
HAND = ROOT / "scripts/attachment_hand_configs.json"
FROZEN_SHA = "8bb4aebe8d2ebb3657e0e7d9e4e505c0ee8994bbf2a96da0bd881f963a07a7a5"
HAND_SHA = "5ffecffab84f89548d605ce8904fd7d72f966c8bfb620a1bfd4b39f9b7c2c3c6"


@dataclass(frozen=True)
class Case:
    name: str
    granted: str | None
    sent: str
    allowed: bool
    wrong_recipient: bool = False
    other_header: bool = False
    rename: bool = False
    change_body: bool = False


CASES = [
    Case("exact", "A", "A", True),
    Case("proper_subset", "AB", "A", True),
    Case("same_metadata_substitution", "AB", "C", False),
    Case("rename", "A", "A", True, rename=True),
    Case("reorder", "AB", "BA", True),
    Case("duplicate_granted", "AA", "AA", True),
    Case("duplicate_excess", "AB", "AA", False),
    Case("wrong_multiplicity_same_total", "AAB", "ABB", False),
    Case("both_empty", "", "", True),
    Case("unused_grant", "AB", "", True),
    Case("wrong_recipient_empty", "", "", False, wrong_recipient=True),
    Case("explicit_no_grant", None, "A", False),
    Case("header_other_envelope_right", "A", "A", True, other_header=True),
    Case("header_right_envelope_other", "A", "A", False, wrong_recipient=True, other_header=True),
    Case("body_change", "A", "A", True, change_body=True),
    Case("zero_byte_attachment", "Z", "Z", True),
    Case("larger_subset", "AABCD", "DBA", True),
    Case("larger_wrong_subset", "AABCD", "DBB", False),
]


def freeze_check():
    source = Path(frozen.__file__)
    if hashlib.sha256(source.read_bytes()).hexdigest() != FROZEN_SHA:
        raise RuntimeError("Imported compiler differs from the frozen source")
    if hashlib.sha256(HAND.read_bytes()).hexdigest() != HAND_SHA:
        raise RuntimeError("Hand configuration differs from the pinned protocol")
    probe = subprocess.run([sys.executable, str(source), "--policy", "attachment_subset"],
                           capture_output=True, text=True, check=False)
    if probe.returncode != 2 or "invalid choice" not in probe.stderr or "attachment_subset" not in probe.stderr:
        raise RuntimeError(f"Unexpected native compiler response: {probe.stderr}")
    return {"commit": "1c5006f87490a1a9daf9b673762edd218859ae41", "compiler_sha256": FROZEN_SHA,
            "hand_sha256": HAND_SHA, "native_supported": False, "native_cli_exit": probe.returncode,
            "supported_policies": sorted(frozen.POLICIES)}


def init_ledger(db):
    db.executescript("""
        CREATE TABLE grants (attempt TEXT PRIMARY KEY, recipient TEXT, body TEXT);
        CREATE TABLE parts (attempt TEXT, ordinal INTEGER, name TEXT, content BLOB,
                            PRIMARY KEY(attempt, ordinal), FOREIGN KEY(attempt) REFERENCES grants(attempt));
    """)


def store_grant(db, attempt, recipient, body, files):
    with db:
        db.execute("INSERT INTO grants VALUES (?, ?, ?)", (attempt, recipient, body))
        db.executemany("INSERT INTO parts VALUES (?, ?, ?, ?)",
                       ((attempt, i, name, blob) for i, (name, blob) in enumerate(files)))


def grant_snapshot(db, attempt):
    row = db.execute("SELECT recipient, body FROM grants WHERE attempt=?", (attempt,)).fetchone()
    if row is None:
        raise ValueError("No authority snapshot for this attempt")
    if row[0] is None:
        return None
    parts = db.execute("SELECT name, content FROM parts WHERE attempt=? ORDER BY ordinal", (attempt,))
    return {"recipient": row[0], "body": row[1], "attachments": list(parts)}


def reference_verdict(db, attempt, persisted):
    """Use committed MIME and a separate SQL grouped count of approved blobs."""
    if persisted is None:
        raise ValueError("No committed message in the reference mailbox")
    recipient, = db.execute("SELECT recipient FROM grants WHERE attempt=?", (attempt,)).fetchone()
    limits = dict(db.execute("SELECT content, count(*) FROM parts WHERE attempt=? GROUP BY content", (attempt,)))
    for _, blob in persisted["attachments"]:
        limits[blob] = limits.get(blob, 0) - 1
    allowed = recipient == persisted["recipient"] and all(v >= 0 for v in limits.values())
    return "authorized" if allowed else "unauthorized"


def files(symbols, template, renamed=False):
    # Keep the nonempty payload lengths and filenames identical within each template.
    size = (32, 128, 512, 2048)[template]
    name = "renamed.bin" if renamed else "part.bin"
    return [(name, b"" if symbol == "Z" else symbol.encode() * size) for symbol in symbols]


def as_old_fact(fact):
    if fact is None:
        return None
    bag = sorted(b64encode(blob).decode("ascii") for _, blob in fact["attachments"])
    return fact["recipient"], json.dumps(bag, separators=(",", ":"))


def metrics():
    return {"correct": 0, "false_authorized": 0, "false_unauthorized": 0, "unknown": 0,
            "correct_authorized": 0, "correct_unauthorized": 0, "receipt_bytes": 0,
            "raw_logical_bytes": dict.fromkeys(("recipient", "body", "filename", "attachment"), 0)}


def score(row, prediction, truth):
    if prediction == truth:
        row["correct"] += 1
        row["correct_" + truth] += 1
    elif prediction == "unknown":
        row["unknown"] += 1
    elif prediction in ("authorized", "unauthorized"):
        row["false_" + prediction] += 1
    else:
        raise ValueError(f"Invalid label: {prediction}")


def footprint(row, records):
    raw = row["raw_logical_bytes"]
    for record in records.values():
        row["receipt_bytes"] += len(wire(record))
        f = record["fields"]
        raw["recipient"] += len((f.get("recipient.raw") or "").encode())
        raw["body"] += len((f.get("body.raw") or "").encode())
        raw["filename"] += sum(len(s.encode()) for s in f.get("attachment_names.raw") or [])
        raw["attachment"] += sum(len(b64decode(s, validate=True)) for s in f.get("attachment_content.raw") or [])


def check_faults(counts, config, attempt, records, keys, previous):
    edited = deepcopy(records)
    edited["delivery"]["fields"]["recipient.tag"] = "edited"
    variants = [
        ("no_approval", {"delivery": records["delivery"]}, keys),
        ("no_delivery", {"approval": records["approval"]}, keys),
        ("edited_projection", edited, keys),
        ("swapped_source_keys", records, {"approval": keys["delivery"], "delivery": keys["approval"]}),
    ]
    if previous is not None:
        variants.append(("cross_attempt_delivery", {"approval": records["approval"], "delivery": previous}, keys))
    for name, evidence, source_keys in variants:
        result = verify(config, attempt, evidence, None, source_keys)
        counts[name][result] += 1


def run():
    pinned = freeze_check()
    templates = load_templates()
    search = run_search()
    manual = json.loads(HAND.read_text())["configs"]
    configs = {**manual, "synthesized": search["selected"],
               "recipient_and_count": {role: ["recipient.tag", "attachment_count"] for role in ROLES}}
    # Secondary sensitivity baseline; both sources expose only the raw inputs the policy uses.
    configs["policy_inputs_raw"] = {role: ["recipient.raw", "attachment_content.raw"] for role in ROLES}
    configs["expert_with_body_names"] = {
        role: manual["expert_minimal"][role] + ["body.raw", "attachment_names.raw"] for role in ROLES}
    for name, reduction in search["pruned_existing"].items():
        configs["pruned_" + name] = reduction["selected"]
    for name, suggestion in search["manual_minimum_additions"].items():
        if suggestion["cost"][-1]:
            extra = suggestion["optimal_additions"][0]
            configs["repaired_" + name] = {role: manual[name][role] + extra[role] for role in ROLES}
    comparison_key = secrets.token_bytes(32)
    keys = {role: secrets.token_bytes(32) for role in ROLES}
    profiles = {name: metrics() for name in configs}
    exact = frozen.Schema("recipient_body", tuple(frozen.compile_schema("recipient_body")["fields"]))
    old = {k: 0 for k in ("correct", "correct_authorized", "correct_unauthorized",
                          "false_authorized", "false_unauthorized", "unknown")}
    by_case = {}
    truth_counts = Counter()
    bytes_by_template = []
    faults = {key: Counter() for key in ("no_approval", "no_delivery", "edited_projection",
                                         "swapped_source_keys", "cross_attempt_delivery")}
    previous_delivery = None
    with closing(sqlite3.connect(":memory:")) as db, LocalMailbox() as mailbox:
        init_ledger(db)
        for i, template in enumerate(templates):
            template_bytes = Counter()
            bytes_by_template.append(template_bytes)
            for j, case in enumerate(CASES):
                attempt = f"send-{i:02}-{j:02}"
                target = f"approved{i}@pilot.invalid"
                other = f"other{i}@pilot.invalid"
                body = "p" * template["body_bytes"]
                store_grant(db, attempt, target if case.granted is not None else None,
                            body if case.granted is not None else None, files(case.granted or "", i))
                grant = grant_snapshot(db, attempt)
                approvals = {name: issue(config["approval"], "approval", attempt, grant, comparison_key, keys["approval"])
                             for name, config in configs.items()}
                sent_to = other if case.wrong_recipient else target
                header = (target if case.wrong_recipient else other) if case.other_header else sent_to
                sent_body = "q" * len(body) if case.change_body else body
                mailbox.submit(attempt, sent_to, files(case.sent, i, case.rename), sent_body, header_to=header)
                observed = mailbox.read(attempt)
                persisted = mailbox.oracle(attempt)
                if (not observed or not persisted or any(observed[k] != persisted[k] for k in
                        ("recipient", "attachments", "backend_id"))):
                    raise RuntimeError(f"REST and committed MIME disagree at {attempt}")
                truth = reference_verdict(db, attempt, persisted)
                if case.allowed != (truth == "authorized"):
                    raise RuntimeError(f"Fixture expectation differs from mailbox reference at {attempt}")
                truth_counts[truth] += 1
                predictions = {}
                for name, config in configs.items():
                    delivery = issue(config["delivery"], "delivery", attempt, observed, comparison_key, keys["delivery"])
                    records = {"approval": approvals[name], "delivery": delivery}
                    prediction = verify(config, attempt, records, None, keys)
                    predictions[name] = prediction
                    score(profiles[name], prediction, truth)
                    before = profiles[name]["receipt_bytes"]
                    footprint(profiles[name], records)
                    template_bytes[name] += profiles[name]["receipt_bytes"] - before
                    if name == "synthesized":
                        check_faults(faults, config, attempt, records, keys, previous_delivery)
                        previous_delivery = delivery
                old_records = [frozen.issue(exact, role, attempt, as_old_fact(fact), comparison_key, keys[role])
                               for role, fact in zip(ROLES, (grant, observed))]
                verdict = frozen.verify(exact, attempt, old_records, keys)
                predictions["v1_equality_proxy"] = {"within": "authorized", "violation": "unauthorized",
                                                     "unknown": "unknown"}[verdict]
                score(old, predictions["v1_equality_proxy"], truth)
                case_row = by_case.setdefault(case.name, {"truth": truth, "runs": 0, "predictions": {}})
                case_row["runs"] += 1
                for name, outcome in predictions.items():
                    case_row["predictions"].setdefault(name, Counter())[outcome] += 1
    checked = replay_witnesses(search, manual)
    return {"freeze": pinned, "mailpit": MAILPIT, "templates": templates, "scenario_families": len(CASES),
            "main_smtp_acceptances": sum(truth_counts.values()), "truth": truth_counts,
            "fixture_attachment_sizes_by_template": [32, 128, 512, 2048], "profiles": profiles,
            "receipt_bytes_by_template": bytes_by_template,
            "legacy_equality_proxy": old, "by_case": by_case, "faults": faults, "search": search,
            "witness_replay": checked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/attachment_holdout/summary.json")
    args = parser.parse_args()
    result = run()
    args.out.parent.mkdir(exist_ok=True, parents=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"{result['main_smtp_acceptances']} messages accepted; aggregate results in {args.out}")
    for name, row in result["profiles"].items():
        print(name, row["correct"], row["unknown"], row["false_authorized"], row["false_unauthorized"], row["receipt_bytes"])


if __name__ == "__main__":
    main()
