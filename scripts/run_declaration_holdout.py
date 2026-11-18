"""Run the predeclared transfer test using only synthetic mail at a loopback SMTP service."""
from __future__ import annotations

import argparse
from base64 import b64decode
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys

import attachment_projection as prior
import mail_policy_runtime as runtime
from attachment_benchmark_shapes import load_templates
from attachment_mail_backend import LocalMailbox, VERSION
from mail_policy_search import audit_config, compile_policy, repair_config
from run_attachment_holdout_pilot import grant_snapshot, init_ledger, store_grant

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "reports/policy_transfer"
ROLES = ("approval", "delivery")
OLD_COMMIT = "596fc9251b99e8b47de1d4c5adaad4115d3038bf"
RAW_MEASURES = ("recipient", "body", "names", "content")


def load(path):
    return json.loads(path.read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_freeze():
    manifest = load(STUDY / "freeze.json")
    for path, expected in manifest["files"].items():
        if sha((ROOT / path).read_bytes()) != expected:
            raise ValueError(f"Frozen file changed: {path}")
    return manifest


def native_probe(policy_path, caps_path):
    # The old searcher's CLI may silently ignore argv. Test that rather than equating exit zero with support.
    command = [sys.executable, str(ROOT / "scripts/attachment_schema_check.py")]
    base = subprocess.run(command, check=True, capture_output=True).stdout
    supplied = subprocess.run(command + ["--policy", str(policy_path), "--capabilities", str(caps_path)],
                              capture_output=True)
    same = supplied.returncode == 0 and base == supplied.stdout
    if not same:
        raise RuntimeError("Unexpected prior-version behavior; inspect native output")
    return {"version": OLD_COMMIT, "argument_exit": supplied.returncode, "identical_to_no_arguments": same,
            "output_sha256": sha(base), "policy_supported": False, "selected_for_legacy_policy": json.loads(base)["selected"],
            "receipt_policy_id": prior.POLICY}


def fact_template(fact, body_size=None):
    if fact is None:
        return None
    recipient = fact["recipient"]
    # Synthetic witness addresses are already .invalid; author cases use symbolic identities.
    if "@" not in recipient:
        recipient = recipient.encode().hex() + "@pilot.invalid"
    body = fact["body"]
    if body_size is not None and body:
        # Preserve exact equality for the complete, finite set of synthetic body IDs.
        # Prefix the original instead of truncating it, so distinct bodies never collapse.
        body = body + "|" + "." * max(0, body_size - len(body.encode()) - 1)
    attachments = []
    for item in fact["attachments"]:
        name, content = (item["name"], item["content"]) if isinstance(item, dict) else item
        attachments.append((name, content.encode("utf-8")))
    return dict(recipient=recipient, body=body, attachments=attachments)


def smtp_body(body):
    # EmailMessage.set_content ends the plain text part in CRLF, even for an empty input.
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    return (text if text.endswith("\n") else text + "\n").replace("\n", "\r\n")


def gold(policy, grant, delivery):
    """Independent full-fact evaluator on committed MIME; uses no search or verifier projections."""
    if grant is None:
        return "unauthorized"

    def field(fact, name):
        if name in ("recipient", "body"):
            return fact[name]
        attachments = fact["attachments"]
        if name == "count":
            return len(attachments)
        if name == "items":
            return Counter(content for _, content in attachments)
        if name == "names":
            return Counter(filename for filename, _ in attachments)
        if name == "sizes":
            return Counter(len(content) for _, content in attachments)
        raise ValueError(name)

    def rule(expr):
        if "all" in expr:
            return all(rule(child) for child in expr["all"])
        if "any" in expr:
            return any(rule(child) for child in expr["any"])
        if "not" in expr:
            return not rule(expr["not"])
        lhs, rhs = field(delivery, expr["field"]), field(grant, expr["field"])
        if expr["op"] == "eq":
            return lhs == rhs
        if expr["op"] in ("subset", "le"):
            return lhs <= rhs
        raise ValueError(expr["op"])
    return "authorized" if rule(policy) else "unauthorized"


def transfer_cases():
    """A fixed five-factor design, independent of any challenge or search domain."""
    for mask in range(32):
        grant = dict(recipient="R0", body="B0", attachments=[["a.bin", "AB"], ["a.bin", "AB"],
                                                            ["b.bin", "X"], ["empty.bin", ""]])
        parts = [list(part) for part in grant["attachments"]]
        if mask & 4:
            parts.pop(1)
        if mask & 8:
            parts[0][0] = "renamed.bin"
        if mask & 16:
            # Change bytes and length together. Author cases can vary the two independently.
            parts[0][1] = "XYZ"
        delivery = dict(recipient="R1" if mask & 1 else "R0", body="B1" if mask & 2 else "B0",
                        attachments=parts[::-1])
        yield dict(id=f"factor-{mask:02}", approval=grant, delivery=delivery)


def counters():
    return dict(correct=0, false_authorized=0, false_unauthorized=0, unknown=0, receipt_bytes=0,
                raw_bytes={name: 0 for name in RAW_MEASURES})


def tally(row, actual, truth, records):
    key = "correct" if actual == truth else ("unknown" if actual == "unknown" else "false_" + actual)
    row[key] += 1
    for record in records.values():
        row["receipt_bytes"] += len(prior.wire(record))
        fields = record["fields"]
        row["raw_bytes"]["recipient"] += len((fields.get("recipient.raw") or "").encode())
        row["raw_bytes"]["body"] += len((fields.get("body.raw") or "").encode())
        row["raw_bytes"]["names"] += sum(len(s.encode()) for s in fields.get("attachment_names.raw") or [])
        row["raw_bytes"]["content"] += sum(len(b64decode(s, validate=True)) for s in fields.get("attachment_content.raw") or [])


def commit_grant(db, attempt, grant):
    store_grant(db, attempt, grant and grant["recipient"], grant and smtp_body(grant["body"]),
                grant["attachments"] if grant else ())
    return grant_snapshot(db, attempt)


def commit_delivery(box, attempt, delivery):
    box.submit(attempt, delivery["recipient"], delivery["attachments"], delivery["body"],
               header_to="display@pilot.invalid")
    observed, scorer = box.read(attempt), box.oracle(attempt)
    if not observed or not scorer or any(observed[k] != scorer[k] for k in ("recipient", "attachments", "body", "backend_id")):
        raise ValueError("REST evidence and independent persisted-MIME read disagree")
    return observed, scorer


def replay_case(db, box, attempt, case, body_size, policy, configs, legacy, secrets_, totals):
    comp, keys = secrets_
    grant = commit_grant(db, attempt, fact_template(case["approval"], body_size))
    approvals = {name: runtime.issue(policy, config["approval"], "approval", attempt, grant, comp, keys["approval"])
                 for name, config in configs.items() if config is not None}
    legacy_approval = prior.issue(legacy["approval"], "approval", attempt, grant, comp, keys["approval"])
    delivery, scored = commit_delivery(box, attempt, fact_template(case["delivery"], body_size))
    truth = gold(policy, grant_snapshot(db, attempt), scored)
    for name, config in configs.items():
        if config is None:
            tally(totals[name], "unknown", truth, {})
            continue
        evidence = runtime.issue(policy, config["delivery"], "delivery", attempt, delivery, comp, keys["delivery"])
        records = {"approval": approvals[name], "delivery": evidence}
        verdict = runtime.verify(policy, config, attempt, records, keys)
        tally(totals[name], verdict, truth, records)
    old_records = {"approval": legacy_approval,
                   "delivery": prior.issue(legacy["delivery"], "delivery", attempt, delivery, comp, keys["delivery"])}
    tally(totals["v2_forced_legacy_policy"], prior.verify(legacy, attempt, old_records, None, keys), truth, old_records)
    return truth


def observation(records):
    """Forget opaque token spellings, scope IDs, HMACs and attempt IDs. Preserve all readable fields."""
    payloads = [records[r]["fields"] for r in ROLES]
    signature = {}
    for name in sorted(set(payloads[0]) | set(payloads[1])):
        seen = [p[name] if name in p else None for p in payloads]
        if name in {"recipient.tag", "attachment_bytes.bag_tag", "attachment_bytes.item_tags"}:
            atoms = [x["value"] if x is not None else None for x in seen]
            if name == "attachment_bytes.item_tags":
                left, right = (Counter(xs or []) for xs in atoms)
                pattern = sorted((left[t], right[t]) for t in set(left) | set(right))
            else:
                pattern = atoms[0] == atoms[1] if all(x is not None for x in atoms) else None
            signature[name] = [[name in p for p in payloads], pattern]
        else:
            signature[name] = seen
    return signature


def replay_witness(policy, config, witness, comp, keys):
    if not witness:
        return {"available": False}
    observations, truths, decisions = [], [], []
    with LocalMailbox() as box, closing(sqlite3.connect(":memory:")) as db:
        init_ledger(db)
        for side in ("within", "violation"):
            world = witness[side]
            grant = commit_grant(db, side, fact_template(world["approval"]))
            approval_record = runtime.issue(policy, config["approval"], "approval", side, grant, comp, keys["approval"])
            observed, committed = commit_delivery(box, side, fact_template(world["delivery"]))
            records = {"approval": approval_record, "delivery":
                       runtime.issue(policy, config["delivery"], "delivery", side, observed, comp, keys["delivery"])}
            observations.append(observation(records))
            truths.append(gold(policy, grant_snapshot(db, side), committed))
            decisions.append(runtime.verify(policy, config, side, records, keys))
    return {"available": True, "smtp_acceptances": 2, "same_observation": observations[0] == observations[1],
            "independent_truths": truths, "verified_decisions": decisions,
            "reproduced": observations[0] == observations[1] and truths == ["authorized", "unauthorized"]}


def run(bundle):
    pinned = check_freeze()
    caps_path = STUDY / "capabilities.json"
    policy_path = bundle / "policy.json"
    policy, caps = load(policy_path), load(caps_path)
    native = native_probe(policy_path, caps_path)
    # Compile using a separate process before the benchmark runner reads any hand configuration or labels.
    output = subprocess.run([sys.executable, str(ROOT / "scripts/compile_mail_policy.py"), "--policy", str(policy_path),
                             "--capabilities", str(caps_path)], check=True, capture_output=True)
    compiled = json.loads(output.stdout)["compiled"]
    hand, cases = load(bundle / "hand.json"), load(bundle / "cases.json")
    for conf in hand.values():
        if set(conf) != set(ROLES) or any(len(conf[r]) != len(set(conf[r])) or set(conf[r]) - set(caps[r]) for r in ROLES):
            raise ValueError("Hand config has invalid capabilities")
    if (set(hand) != {"expert", "incomplete", "overcollected"} or not cases or
            len({case["id"] for case in cases}) != len(cases) or any(type(c["authorized"]) != bool for c in cases)):
        raise ValueError("Invalid challenge bundle")
    audit = audit_config(policy, hand["incomplete"])
    repaired = repair_config(policy, hand["incomplete"], caps)
    pruned = compile_policy(policy, hand["overcollected"])
    configs = {"auto": compiled["selected"], **hand,
               "repair": repaired["selected"], "prune": pruned["selected"], "v2_native": None}
    keys = {role: secrets.token_bytes(32) for role in ROLES}
    comp = secrets.token_bytes(32)
    witness = replay_witness(policy, hand["incomplete"], audit.get("witness"), comp, keys)
    templates = load_templates()
    cohorts = {}
    with LocalMailbox() as box, closing(sqlite3.connect(":memory:")) as db:
        init_ledger(db)
        schedule = {"author": [(case, t["body_bytes"]) for t in templates for case in cases],
                    "factorial": [(case, None) for case in transfer_cases()]}
        for name, scheduled in schedule.items():
            profiles = {k: counters() for k in [*configs, "v2_forced_legacy_policy"]}
            truth_counts = Counter()
            traces = {}
            for idx, (case, size) in enumerate(scheduled):
                attempt = f"{name}-{idx:04}"
                before = {profile: row["correct"] for profile, row in profiles.items()}
                label = replay_case(db, box, attempt, case, size, policy, configs, native["selected_for_legacy_policy"],
                                    (comp, keys), profiles)
                truth_counts[label] += 1
                trace = traces.setdefault(case["id"], {"truth": label, "correct_by_profile": Counter(), "n": 0})
                if "authorized" in case:
                    trace["author_label_matches_mime"] = case["authorized"] == (label == "authorized")
                if trace["truth"] != label:
                    raise ValueError("Template changed an authorization result")
                for profile, row in profiles.items():
                    trace["correct_by_profile"][profile] += row["correct"] - before[profile]
                trace["n"] += 1
            cohorts[name] = {"n": len(scheduled), "distinct_cases": len(traces), "truth": truth_counts,
                             "profiles": profiles, "case_results": traces}
    return {"frozen_files": pinned, "input_sha256": {n: sha((bundle/n).read_bytes()) for n in
            ("policy.json", "hand.json", "cases.json")}, "backend": VERSION, "native": native, "compiled": compiled,
            "audit_incomplete": audit, "repair": repaired, "prune": pruned, "configs": configs,
            "replayed_witness": witness, "templates": templates, "cohorts": cohorts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="Directory containing policy.json, hand.json and cases.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.bundle)
    args.out.parent.mkdir(exist_ok=True, parents=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for name, cohort in result["cohorts"].items():
        print(name, cohort["truth"], {k: (v["correct"], v["unknown"]) for k,v in cohort["profiles"].items()})


if __name__ == "__main__":
    main()
