"""Measure identified recipient and message fields in the pinned send-call cohort.

From repository root: PYTHONPATH=src python scripts/run_send_field_inventory.py
No argument, user message, receipt, or digest of a sensitive value is exported.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from evidence_pilot_data import AT_PATH, CLAW_PATH, TARGET_FIELDS, data_manifest, load_cases
from trajectory_audit.data import load_records


BODY_FIELDS = {
    "send_email": ("text", "body", "html", "Mensjae"),
    "send_sms": ("message", "text", "msg", "sms", "sms_text"),
    "sendMessage": ("content",),
    "gog gmail send": ("body", "--body"),
}
CATEGORIES = ("primary_recipient", "copy_recipient", "body", "subject", "attachment_reference", "mixed_smsdata")
EXTRA_FIELDS = {
    "copy_recipient": ("cc", "bcc", "--cc", "--bcc"),
    "subject": ("subject", "--subject"),
    "attachment_reference": ("attachments", "--attachments", "file_path"),
    # Vendor describes this single opaque field as containing BOTH numbers and messages.
    # Count separately so neither main category receives a speculative length.
    "mixed_smsdata": ("smsdata",),
}


def raw_argument_maps(at_path, claw_path):
    """Transiently yield only candidate call arguments; use the cohort's original indexing."""
    for row_no, record in enumerate(load_records(at_path)):
        for index, event in enumerate(record.events):
            if event.kind == "tool_call" and event.name in ("send_email", "send_sms"):
                yield f"atbench:row{row_no}:call{index}", json.loads(event.arguments)

    for row_no, record in enumerate(json.loads(Path(claw_path).read_bytes())):
        index = 0
        for event in record["trajectory"]["events"]:
            if event["type"] != "message" or event["message"]["role"] != "assistant":
                continue
            for block in event["message"]["content"]:
                if block["type"] != "toolCall":
                    continue
                index += 1
                if block["name"] in ("sendMessage", "gog gmail send"):
                    yield f"claw:row{row_no}:call{index}", block["arguments"]


def field_size(value):
    """Logical unescaped UTF-8 value size, integer sizes use their decimal representation."""
    values = value if isinstance(value, list) else [value]
    if any(type(scalar) not in (str, int) for scalar in values):
        raise ValueError("Unsupported type in a measured argument field")
    return sum(len(str(s).encode("utf-8")) for s in values), len(values)


def load_payloads(at_path=AT_PATH, claw_path=CLAW_PATH):
    """Transient inputs for the local replay; callers must never serialize this list.

    The recipient is the conservative, trimmed single target from the cohort extractor.
    The body is the exact single plain-text argument (including HTML when so encoded).
    Unsupported/missing fields yield None. Payloads describe attempts, not their effects.
    """
    targets = {}
    def observe(*, row, target, **unused):
        targets[row["call_key"]] = target

    metadata = {r["call_key"]: r for r in load_cases(at_path, claw_path, observer=observe)}
    result = []
    for key, args in raw_argument_maps(at_path, claw_path):
        row = metadata[key]
        body = [args[name] for name in BODY_FIELDS[row["tool"]] if name in args]
        result.append({
            "call_key": key, "trajectory_id": row["trajectory_id"], "dataset": row["dataset"],
            "tool": row["tool"], "linkage": row["linkage"],
            "recipient": targets[key], "body": body[0] if len(body) == 1 and isinstance(body[0], str) else None,
        })
    return result


def collect(at_path=AT_PATH, claw_path=CLAW_PATH):
    """Return per-call metadata and length measurements only; validate the frozen cohort."""
    # Existing extractor verifies both input SHA-256 values and original call identity.
    metadata = {row["call_key"]: row for row in load_cases(at_path, claw_path)}
    seen = set()
    result = []
    for key, args in raw_argument_maps(at_path, claw_path):
        if key in seen:
            raise ValueError("Duplicate call in inventory")
        seen.add(key)
        row = metadata[key]
        tool = row["tool"]
        categories = {"primary_recipient": TARGET_FIELDS[tool], "body": BODY_FIELDS[tool], **EXTRA_FIELDS}
        measurements = {}
        for category, aliases in categories.items():
            fields = []
            for name in aliases:
                if name not in args:
                    continue
                value = args[name]
                size, count = field_size(value)
                fields.append((name, type(value).__name__, size, count))
            measurements[category] = fields
        result.append({"call_key": key, "trajectory_id": row["trajectory_id"], "dataset": row["dataset"],
                       "tool": tool, "single_target": row["single_target"], "linkage": row["linkage"],
                       "measurements": measurements})
    if seen != set(metadata):
        raise ValueError("Cohort identifiers differ between extractor and inventory")
    return result


def summarize(rows):
    metrics = {}
    for category in CATEGORIES:
        present = [row["measurements"][category] for row in rows]
        fields = [field for values in present for field in values]
        metrics[category] = {
            "calls_with_field": sum(bool(values) for values in present),
            "calls_with_nonempty_value": sum(any(bytes_ for _, _, bytes_, _ in values) for values in present),
            "field_occurrences": len(fields), "scalar_value_occurrences": sum(count for _, _, _, count in fields),
            "utf8_value_bytes": sum(bytes_ for _, _, bytes_, _ in fields),
            "json_type_counts": dict(Counter(kind for _, kind, _, _ in fields)),
            "alias_occurrences": dict(Counter(name for name, _, _, _ in fields)),
        }

    def sum_categories(categories):
        return {
            "calls_with_any_field": sum(any(row["measurements"][c] for c in categories) for row in rows),
            "field_occurrences": sum(metrics[c]["field_occurrences"] for c in categories),
            "utf8_value_bytes": sum(metrics[c]["utf8_value_bytes"] for c in categories),
        }

    return {
        "calls": len(rows), "trajectories": len({r["trajectory_id"] for r in rows}),
        "recognized_single_target": sum(r["single_target"] for r in rows),
        "binding": dict(Counter(r["linkage"] for r in rows)),
        "categories": metrics,
        "recipient_including_cc_bcc": sum_categories(("primary_recipient", "copy_recipient")),
        "recipient_and_body": sum_categories(("primary_recipient", "copy_recipient", "body")),
        "calls_with_both_recipient_and_body": sum(
            bool((r["measurements"]["primary_recipient"] or r["measurements"]["copy_recipient"])
                 and r["measurements"]["body"]) for r in rows
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/send_field_inventory"))
    args = parser.parse_args()
    rows = collect()
    by_tool = defaultdict(list)
    for row in rows:
        by_tool[row["tool"]].append(row)
    report = {
        "source": data_manifest(),
        "baseline": "Plaintext snapshot of recognized call argument values. Bytes exclude JSON wrapping, escaping, field names, response and user text, other argument fields, replication and compression.",
        "units": "Count each named field per call, including present empty strings; array members counted separately for scalar occurrences; no recipient identity deduplication.",
        "scope": "Forwarded message content in 'body' only. Subjects, attachment/path references and mixed smsdata are shown separately. Neither scope authorizations nor actual deliveries or trustworthy action times are inferred.",
        "all": summarize(rows),
        "single_target": summarize([r for r in rows if r["single_target"]]),
        "by_tool": {tool: summarize(group) for tool, group in sorted(by_tool.items())},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    for tool, summary in (("ALL", report["all"]), ("single_target", report["single_target"]), *report["by_tool"].items()):
        print(tool, summary["calls"], summary["recipient_including_cc_bcc"], summary["categories"]["body"])


if __name__ == "__main__":
    main()
