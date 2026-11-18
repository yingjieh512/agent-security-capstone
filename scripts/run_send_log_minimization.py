"""Score minimized receipts against an in-memory backend and measure their aggregate footprint.

Run from the repository root with PYTHONPATH=src. No recipient, message, comparison
tag, signature, or record containing those values is written to the output.
"""
from __future__ import annotations

import argparse
import hmac
from collections import Counter
import itertools
import json
from pathlib import Path
import secrets
import sqlite3
import uuid

from run_send_field_inventory import load_payloads
from trajectory_audit.send_log import Schema, compile_schema, issue, mac, verify, wire


POLICIES = ("recipient", "recipient_body")
ROLES = ("approval", "delivery")
PARTS = ("recipient", "body")
DEFAULT_OUTPUT = Path("outputs/send_log_minimization")


def declared_fields(parts, kind):
    return tuple(sorted(f"{role}.{part}.{kind}" for role in ROLES for part in parts))


def profiles(policy):
    compiled = compile_schema(policy)
    if not compiled["feasible"]:
        raise RuntimeError("Expected a certifying two-source schema")
    parts = PARTS if policy == "recipient_body" else PARTS[:1]
    separate = declared_fields(parts, "tag")
    minimum = declared_fields(("pair",), "tag") if policy == "recipient_body" else separate
    schemes = {
        "raw_full": Schema(policy, declared_fields(PARTS, "raw")),
        "raw_recipient": Schema(policy, declared_fields(PARTS[:1], "raw")),
        "stable_tag": Schema(policy, declared_fields(parts, "stable")),
        "separate_attempt_tags": Schema(policy, separate),
        "hand_minimum": Schema(policy, minimum),
        "synthesized": Schema(policy, tuple(compiled["fields"])),
    }
    if policy == "recipient_body":
        schemes["stable_pair_tag"] = Schema(policy, declared_fields(("pair",), "stable"))
    return schemes


class Backend:
    """Two independent tables, snapshot at dispatch and definitive backend terminal.

    No delivery means an explicitly finalized operation with a NULL recipient/body.
    A missing audit record is simulated later and never mutates either table.
    """
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        for name in ("approvals", "deliveries"):
            self.db.execute(f"CREATE TABLE {name}(attempt TEXT PRIMARY KEY, recipient TEXT, body TEXT)")

    def register(self, attempt, approval, delivery):
        for table, fact in (("approvals", approval), ("deliveries", delivery)):
            recipient, body = fact if fact is not None else (None, None)
            self.db.execute(f"INSERT INTO {table} VALUES (?,?,?)", (attempt, recipient, body))

    def source_fact(self, role, attempt):
        table = {"approval": "approvals", "delivery": "deliveries"}[role]
        row = self.db.execute(f"SELECT recipient,body FROM {table} WHERE attempt=?", (attempt,)).fetchone()
        if row is None:
            raise LookupError("No source record")
        return row if row[0] is not None else None

    def truth(self, policy, attempt):
        sql = """
            SELECT d.recipient IS NOT NULL AND NOT EXISTS(
                SELECT 1 FROM approvals a WHERE a.attempt=d.attempt
                AND a.recipient=d.recipient AND (?='recipient' OR a.body=d.body)
            ) FROM deliveries d WHERE d.attempt=?
        """
        row = self.db.execute(sql, (policy, attempt)).fetchone()
        if row is None:
            raise LookupError("Cannot score unfinalized attempt")
        return "violation" if row[0] else "within"


def score_reason(backend, attempt):
    # The exact failure reason uses recipient-first precedence when both fields differ.
    value = backend.db.execute("""
        SELECT CASE
            WHEN d.recipient IS NULL THEN 'within'
            WHEN a.recipient IS NULL THEN 'no_grant'
            WHEN a.recipient != d.recipient THEN 'wrong_recipient'
            WHEN a.body != d.body THEN 'wrong_body'
            ELSE 'within' END
        FROM deliveries d JOIN approvals a ON d.attempt=a.attempt WHERE d.attempt=?
    """, (attempt,)).fetchone()
    return value[0]


def record_result(table, verdict, truth):
    counts = table.setdefault("outcomes", Counter(cases=0, correct=0, unknown=0, false_clearance=0, false_accusation=0))
    counts["cases"] += 1
    if verdict == "unknown":
        counts["unknown"] += 1
    elif verdict == truth:
        counts["correct"] += 1
    elif verdict == "within":
        counts["false_clearance"] += 1
    elif verdict == "violation":
        counts["false_accusation"] += 1
    else:
        raise ValueError("Unknown verdict")


def add_footprint(observed, schema, records, identity):
    size = len(wire(records))
    observed["identity_slice_calls"] += 1
    observed["serialized_record_pair_bytes"] += size
    for field in schema.fields:
        _, part, kind = field.split(".")
        if kind == "raw":
            index = PARTS.index(part)
            observed[f"{part}_plaintext_value_bytes"] += len(identity[index].encode("utf-8"))


def repeat_pairs(values):
    return sum(count * (count - 1) // 2 for count in values.values())


def witness_control(policy, attempt, facts, key):
    """Alternative trust model: a joint observer is entrusted with both local facts."""
    grant, delivery = facts["approval"], facts["delivery"]
    if policy == "recipient":
        cleared = delivery is None or (grant is not None and grant[0] == delivery[0])
    else:
        cleared = delivery is None or grant == delivery
    header = {"attempt": attempt, "role": "joint_witness", "v": 1,
              "policy": policy, "within": cleared}
    record = {**header, "mac": mac(key, header)}
    if record["attempt"] != attempt or record["policy"] != policy:
        raise AssertionError("Joint witness header mismatch")
    checked = {k: v for k, v in record.items() if k != "mac"}
    assert hmac.compare_digest(record["mac"], mac(key, checked))
    return ("within" if record["within"] else "violation"), len(wire([record]))


def run():
    inputs = load_payloads()
    payloads = [p for p in inputs if p["recipient"] is not None and p["body"] is not None]
    if len(payloads) != 80:
        raise ValueError("Unexpected identity slice: verify extractor or release")
    backend = Backend()
    comparison = secrets.token_bytes(32)
    keys = {role: secrets.token_bytes(32) for role in ROLES}
    schemas = {policy: profiles(policy) for policy in POLICIES}
    metrics = {policy: {name: {} for name in options} for policy, options in schemas.items()}
    stress = {policy: {} for policy in POLICIES}
    explain_schemas = {"synthesized": Schema("explain", tuple(compile_schema("explain")["fields"])),
                       "pair_only": Schema("explain", declared_fields(("pair",), "tag"))}
    explain = {name: {"fields": list(schema.fields), "counts": Counter(),
                      "truth_counts": Counter(), "identity_wire_bytes": 0}
               for name, schema in explain_schemas.items()}
    disagreement = Counter()
    link_values = {kind: {part: Counter() for part in PARTS} for kind in ("raw", "stable", "tag")}
    compound_values = {key: Counter() for key in ("raw", "stable", "tag")}
    joint_witness_key = secrets.token_bytes(32)
    witness = {policy: {} for policy in POLICIES}
    local_comparisons = {"separate_tags": Counter(), "pair_tags": Counter()}
    counts = Counter()
    for p in payloads:
        recipient, body = p["recipient"], p["body"]
        counts[p["tool"]] += 1
        # Alternates are algorithmically distinct test fixtures. No world is imputed
        # to describe the original user's approval or production delivery.
        recipients = (recipient, recipient + ".alternate")
        bodies = (body, body + "\n[alternate]")
        options = [None, *itertools.product(recipients, bodies)]
        for i, grant in enumerate(options):
            for j, delivery in enumerate(options):
                attempt = str(uuid.uuid5(uuid.NAMESPACE_URL, f"local-pilot:{p['call_key']}:{i}:{j}"))
                backend.register(attempt, grant, delivery)
                facts = {role: backend.source_fact(role, attempt) for role in ROLES}
                for policy, options_by_name in schemas.items():
                    truth = backend.truth(policy, attempt)
                    witness_verdict, witness_bytes = witness_control(policy, attempt, facts, joint_witness_key)
                    record_result(witness[policy], witness_verdict, truth)
                    if i == j == 1:
                        witness[policy]["identity_wire_bytes"] = witness[policy].get("identity_wire_bytes", 0) + witness_bytes
                    for name, schema in options_by_name.items():
                        records = [issue(schema, role, attempt, facts[role], comparison, keys[role])
                                   for role in ROLES]
                        result = verify(schema, attempt, records, keys)
                        sample = metrics[policy][name]
                        record_result(sample, result, truth)
                        if name != "raw_recipient" or policy == "recipient":
                            if result != truth:
                                raise AssertionError(f"Completely observed {policy}/{name} misverified")
                        if policy == "recipient_body" and i > 0 and j > 0:
                            if name == "separate_attempt_tags":
                                recipient_eq, body_eq = [
                                    records[0]["data"][f"approval.{part}.tag"] == records[1]["data"][f"delivery.{part}.tag"]
                                    for part in PARTS]
                                pattern = { (True, True): "both_equal", (True, False): "only_recipient_equal",
                                            (False, True): "only_body_equal", (False, False): "neither_equal"}[recipient_eq, body_eq]
                                local_comparisons["separate_tags"][pattern] += 1
                            if name == "synthesized":
                                eq = records[0]["data"]["approval.pair.tag"] == records[1]["data"]["delivery.pair.tag"]
                                local_comparisons["pair_tags"]["equal" if eq else "unequal"] += 1
                        if i == j == 1:  # identical approval/delivery of original-valued payload
                            actual_bytes = sample.setdefault("identity_footprint", Counter(
                                recipient_plaintext_value_bytes=0, body_plaintext_value_bytes=0))
                            add_footprint(actual_bytes, schema, records, (recipient, body))
                            if policy == "recipient_body" and name in ("raw_full", "stable_tag", "separate_attempt_tags"):
                                kind = {"raw_full": "raw", "stable_tag": "stable", "separate_attempt_tags": "tag"}[name]
                                for part in PARTS:
                                    v = records[1]["data"][f"delivery.{part}.{kind}"]
                                    link_values[kind][part][v] += 1
                            if policy == "recipient_body":
                                if name == "raw_full":
                                    compound_values["raw"][recipient, body] += 1
                                if name in ("stable_pair_tag", "synthesized"):
                                    kind = "stable" if name == "stable_pair_tag" else "tag"
                                    compound_values[kind][records[1]["data"][f"delivery.pair.{kind}"]] += 1
                        if name == "synthesized":
                            # All edits happen after issuance. Deliberate omission and
                            # cross-attempt replacement are distinct from terminal non-delivery.
                            other = issue(schema, "delivery", attempt + "-other", facts["delivery"],
                                          comparison, keys["delivery"])
                            with_stale = [records[0], other]
                            corrupt = dict(records[1])
                            mac = corrupt["mac"]
                            corrupt["mac"] = ("1" if mac[0] == "0" else "0") + mac[1:]
                            edited = {**records[1], "data": dict(records[1]["data"])}
                            field = next(iter(edited["data"]))
                            edited["data"][field] = None if edited["data"][field] is not None else "bogus"
                            conditions = {"changed_signed_field": [records[0], edited],
                                          "approval_missing": [records[1]],
                                          "delivery_missing": [records[0]],
                                          "both_missing": [],
                                          "wrong_attempt_receipt": with_stale,
                                          "bad_delivery_authenticator": [records[0], corrupt]}
                            for scenario, presented in conditions.items():
                                s = stress[policy].setdefault(scenario, {})
                                v = verify(schema, attempt, presented, keys)
                                record_result(s, v, truth)
                                if v not in ("unknown", truth):
                                    raise AssertionError(f"Unsound stress verdict in {scenario}")
                reason = score_reason(backend, attempt)
                for name, schema in explain_schemas.items():
                    rs = [issue(schema, role, attempt, facts[role], comparison, keys[role]) for role in ROLES]
                    decision = verify(schema, attempt, rs, keys)
                    if decision not in ("unknown", reason) or (name == "synthesized" and decision != reason):
                        raise AssertionError("Incorrect reason verdict")
                    detail = explain[name]
                    detail["counts"]["cases"] += 1
                    detail["counts"]["correct" if decision == reason else "unknown"] += 1
                    detail["truth_counts"][reason] += 1
                    if i == j == 1:
                        detail["identity_wire_bytes"] += len(wire(rs))
                weak = backend.truth("recipient", attempt)
                strong = backend.truth("recipient_body", attempt)
                if weak != strong:
                    disagreement["recipient_check_would_clear_payload_violation"] += 1
    links = {part: {kind: repeat_pairs(link_values[kind][part])
                    for kind in ("raw", "stable", "tag")} for part in PARTS}
    links["pair"] = {kind: repeat_pairs(vals) for kind, vals in compound_values.items()}
    for part in (*PARTS, "pair"):
        assert links[part]["raw"] == links[part]["stable"]
        assert links[part]["tag"] == 0
    return {
        "dataset": {"calls_eligible": len(payloads), "calls_scanned": len(inputs),
                    "eligible_trajectories": len({p["trajectory_id"] for p in payloads}),
                    "calls_by_tool": dict(counts)},
        "design": {"worlds_per_call": 25, "oracle": "Separate SQL equality checks over finalized dispatch snapshots and delivery states",
                   "footprint": "80 identity-matched scenarios only, both signed records as one compact JSON array, no whitespace/newline, no compression or key-store bytes",
                   "privacy": "Record-value plaintext bytes exclude common metadata and field names. Count cross-attempt equality pairs in delivery field on identity slice, once per original eligible call. Per-field repeat counts compare raw, stable, and separate attempt-scoped field encodings. Equal-value tags may reveal within-attempt equality; a keyholder can test guesses.",
                   "stress": "Malformed/missing source records injected after signing. Synthetic attempt-derived UUIDs and ephemeral per-run HMAC keys."},
        "schemas": {policy: {name: list(schema.fields) for name, schema in opts.items()}
                    for policy, opts in schemas.items()},
        "explanation_policy": explain,
        "complete": metrics, "stress": stress, "body_scope_mismatch": dict(disagreement),
        "cross_attempt_equal_field_pairs": links,
        "within_attempt_equality_visible_to_reader": local_comparisons,
        "joint_witness_different_trust_model": witness,
        "witness_scope": "A separately keyed joint observer is trusted to see both sources and compute the policy. Verification checks a policy- and attempt-bound 1-bit claim. This changes source independence and accountability.",

    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    out = parser.parse_args().output_dir
    results = run()
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
